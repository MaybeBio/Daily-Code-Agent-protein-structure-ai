"""Export exact CPI inputs and validate/import remote BioEmu2 results."""
from collections import Counter
import hashlib
import io
import json
from pathlib import Path
import re
import tempfile
import zipfile

import numpy as np
from Bio.SeqUtils import seq1
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from rdkit import Chem
from cpi_data import ROOT, normalize

STORE = ROOT / 'processed/bioemu2'
MAX_UPLOAD = 100 * 1024 * 1024
router = APIRouter(prefix='/api/bioemu2')


class PairInput(BaseModel):
    smiles: str = Field(max_length=10000)
    sequence: str = Field(max_length=20000)


def pair_input(q):
    try:
        key, smiles, sequence, _ = normalize(q.smiles, q.sequence)
        if any(c not in 'ACDEFGHIKLMNPQRSTVWY' for c in sequence):
            raise ValueError('BioEmu export needs the 20 standard protein letters. Replace unknown or modified residues using a verified sequence.')
        return dict(schema='cpi-bioemu2-request-v1', pair_id=key, smiles=smiles, sequence=sequence)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


def check_id(value):
    if not re.fullmatch('[a-f0-9]{64}', value):
        raise HTTPException(400, 'Invalid result or pair ID.')
    return value


@router.post('/request')
def export_request(q: PairInput):
    data = pair_input(q)
    folder = STORE / 'requests'
    folder.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(data, indent=2)
    path = folder / (data['pair_id'] + '.json')
    path.write_text(raw, encoding='utf-8')
    system = dict(entities=[dict(entity_type='protein', asym_ids=['A'], sequence=data['sequence'], mods=[]),
                            dict(entity_type='ligand', asym_ids=['L'], smiles=data['smiles'])],
                  bonds=[], asym_id_to_author_id={})
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('request.json', raw)
        z.writestr('pair.yaml', json.dumps(system, indent=2))
        z.write(ROOT / 'scripts/bioemu2_worker.py', 'bioemu2_worker.py')
        z.write(ROOT / 'BIOEMU2.md', 'README.md')
    return Response(output.getvalue(), media_type='application/zip', headers={
        'Content-Disposition': f'attachment; filename="bioemu2_{data["pair_id"][:12]}_input.zip"'})


def validate_result(data, expected_pair):
    if not isinstance(data, dict) or data.get('schema') != 'cpi-bioemu2-result-v1':
        raise ValueError('This is not a CPI BioEmu-2 result. Use the supplied worker to create the result ZIP.')
    if data.get('pair_id') != expected_pair:
        raise ValueError('This result belongs to a different protein or compound. Select the original pair before importing it.')
    canonical = pair_input(PairInput(smiles=data['smiles'], sequence=data['sequence']))
    if canonical['pair_id'] != expected_pair:
        raise ValueError('The sequence or compound does not match the result ID.')
    if data.get('units') != 'angstrom' or data.get('time_units') != 'ns' or data.get('source') != 'BioEmu-2':
        raise ValueError('The coordinate units or model label are missing or unsupported.')
    atoms = data['atoms']
    if not isinstance(atoms, list) or not 2 <= len(atoms) <= 50000:
        raise ValueError('The atom list is empty or too large for this viewer (maximum 50,000 atoms).')
    frames = np.asarray(data['frames'], dtype=float)
    if frames.ndim != 3 or frames.shape[1:] != (len(atoms), 3) or not 1 <= len(frames) <= 101:
        raise ValueError('Some animation frames have missing atoms or coordinates; maximum 101 frames.')
    if not np.isfinite(frames).all() or np.max(np.abs(frames)) > 1e6:
        raise ValueError('The result contains invalid XYZ positions.')
    times = np.asarray(data['times_ns'], dtype=float)
    if times.shape != (len(frames),) or not np.isfinite(times).all() or times[0] != 0:
        raise ValueError('The frame times are missing or invalid.')
    if len(frames) > 1 and (data.get('kind') != 'trajectory' or not (np.diff(times) > 0).all()):
        raise ValueError('These frames are not marked as successive time steps. Unordered samples cannot be played as motion.')
    if len(frames) == 1 and data.get('kind') != 'pose':
        raise ValueError('A single frame must be labelled as a predicted pose.')
    residues = {}
    ligand_elements = Counter()
    ca_counts = Counter()
    allowed_elements = {Chem.GetPeriodicTable().GetElementSymbol(i) for i in range(2, 119)}
    for atom in atoms:
        if atom.get('elem') not in allowed_elements or atom.get('role') not in ('protein', 'ligand'):
            raise ValueError('Unknown atom element or protein/compound label.')
        if not isinstance(atom.get('resi'), int) or atom['resi'] < 1:
            raise ValueError('A residue number is missing or invalid.')
        if any(not isinstance(atom.get(k), str) or len(atom[k]) > 12 for k in ('atom', 'resn', 'chain')):
            raise ValueError('An atom label is missing or too long.')
        if atom['role'] == 'protein':
            if atom['chain'] != 'A':
                raise ValueError('Expected protein chain A.')
            previous = residues.setdefault(atom['resi'], atom['resn'])
            if previous != atom['resn']:
                raise ValueError('One protein residue has conflicting names.')
            if atom['atom'] == 'CA':
                ca_counts[atom['resi']] += 1
        else:
            if atom['chain'] != 'L':
                raise ValueError('Expected compound chain L.')
            ligand_elements[atom['elem']] += 1
    sequence = ''.join(seq1(residues[i]) for i in sorted(residues))
    if sequence != canonical['sequence'] or any(ca_counts[i] != 1 for i in residues):
        raise ValueError('The protein atoms do not contain the complete requested sequence. Truncated or different proteins are rejected.')
    mol = Chem.RemoveHs(Chem.MolFromSmiles(canonical['smiles']))
    if ligand_elements != Counter(a.GetSymbol() for a in mol.GetAtoms()):
        raise ValueError('The compound atom counts do not match your SMILES. Import the result for the correct compound.')
    edges = set()
    for bond in data['bonds']:
        if not isinstance(bond, list) or len(bond) != 2 or any(type(i) is not int or not 0 <= i < len(atoms) for i in bond) or bond[0] == bond[1]:
            raise ValueError('A bond points to a missing atom.')
        edge = tuple(sorted(bond))
        if edge in edges:
            raise ValueError('The bond list contains duplicates.')
        edges.add(edge)
        if atoms[bond[0]]['role'] != atoms[bond[1]]['role']:
            raise ValueError('This input has no covalent protein-compound bond, but the result contains one.')
    ligand_indices = [i for i, atom in enumerate(atoms) if atom['role'] == 'ligand']
    remap = {idx: j for j, idx in enumerate(ligand_indices)}
    ligand_graph = Chem.RWMol()
    for idx in ligand_indices:
        ligand_graph.AddAtom(Chem.Atom(atoms[idx]['elem']))
    for a, b in edges:
        if a in remap and b in remap:
            ligand_graph.AddBond(remap[a], remap[b], Chem.BondType.SINGLE)
    parameters = Chem.AdjustQueryParameters.NoAdjustments()
    parameters.makeBondsGeneric = True
    query = Chem.RWMol(Chem.AdjustQueryProperties(mol, parameters))
    # The preview exports connectivity, without aromatic/bond-order annotations.
    # Match element-labelled topology without imposing absent aromatic flags.
    for atom in mol.GetAtoms():
        query.ReplaceAtom(atom.GetIdx(), Chem.AtomFromSmarts(f'[#' + str(atom.GetAtomicNum()) + ']'))
    if ligand_graph.GetNumBonds() != mol.GetNumBonds() or not ligand_graph.GetMol().HasSubstructMatch(query.GetMol()):
        raise ValueError('The compound bond connections do not match your SMILES.')
    physicality = data['physicality']
    if type(physicality.get('checked')) is not bool or len(physicality['passed']) != len(frames) or len(physicality['reasons']) != len(frames):
        raise ValueError('The geometry-check report does not cover every frame.')
    if any(type(p) is not bool for p in physicality['passed']) or any(not isinstance(r, str) for r in physicality['reasons']):
        raise ValueError('Invalid geometry-check results.')
    # Return only the documented fields; ignore unrelated data in imported JSON.
    return {key: data[key] for key in ('schema', 'pair_id', 'smiles', 'sequence', 'source', 'kind',
            'units', 'time_units', 'times_ns', 'atoms', 'bonds', 'frames', 'physicality', 'settings', 'environment')}


@router.post('/import/{pair_id}')
async def import_result(pair_id: str, request: Request):
    check_id(pair_id)
    if not (STORE / 'requests' / (pair_id + '.json')).is_file():
        raise HTTPException(400, 'Download the input package for this pair first, then import its completed result.')
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_UPLOAD:
            raise HTTPException(413, 'This ZIP is over 100 MB. Generate fewer motion steps for the site preview.')
    try:
        with zipfile.ZipFile(io.BytesIO(body)) as z:
            infos = z.infolist()
            names = [i.filename for i in infos]
            allowed = {'result.json', 'request.json', 'system.yaml', 'topology.cif', 'samples.xtc', 'physicality.json'}
            if set(names) != allowed or len(names) != len(allowed):
                raise ValueError('The ZIP must be the cpi_bioemu2_result.zip made by the worker, with no renamed or extra files.')
            if sum(i.file_size for i in infos) > 200 * 1024 * 1024:
                raise ValueError('The uncompressed result is over 200 MB. Use fewer motion steps.')
            data = validate_result(json.loads(z.read('result.json')), pair_id)
            original = json.loads(z.read('request.json'))
            if original != json.loads((STORE / 'requests' / (pair_id + '.json')).read_text(encoding='utf-8')):
                raise ValueError('The original request in this ZIP does not match the exported pair.')
            if z.testzip() is not None:
                raise ValueError('The ZIP is damaged. Download it again from the GPU machine.')
        digest = hashlib.sha256(body).hexdigest()
        parent = STORE / 'results' / pair_id
        parent.mkdir(parents=True, exist_ok=True)
        folder = parent / digest
        if not folder.exists():
            with tempfile.TemporaryDirectory(prefix='import-', dir=parent) as staging:
                stage = Path(staging)
                (stage / 'result.json').write_text(json.dumps(data, allow_nan=False), encoding='utf-8')
                (stage / 'result.zip').write_bytes(body)
                # Immutable content-addressed files avoid overwriting prior runs.
                try:
                    stage.rename(folder)
                except FileExistsError:
                    pass
        return dict(pair_id=pair_id, result_id=digest, frames=len(data['frames']))
    except (ValueError, KeyError, TypeError, zipfile.BadZipFile, RuntimeError) as exc:
        raise HTTPException(400, 'Cannot import this result: ' + str(exc)) from exc


@router.post('/results')
def list_results(q: PairInput):
    pair = pair_input(q)
    parent = STORE / 'results' / pair['pair_id']
    results = sorted(parent.glob('*/result.json'), key=lambda p: p.stat().st_mtime, reverse=True)
    return dict(pair_id=pair['pair_id'], results=[p.parent.name for p in results])


@router.get('/result/{pair_id}/{result_id}/{filename}')
def result_file(pair_id: str, result_id: str, filename: str):
    folder = STORE / 'results' / check_id(pair_id) / check_id(result_id)
    if filename not in ('result.json', 'result.zip') or not (folder / filename).is_file():
        raise HTTPException(404, 'This BioEmu result was not found.')
    return FileResponse(folder / filename, filename=filename if filename.endswith('.zip') else None)
