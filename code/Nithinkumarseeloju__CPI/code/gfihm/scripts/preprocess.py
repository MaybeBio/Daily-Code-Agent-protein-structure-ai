"""Reproducible local preprocessing. Never executes files from input archives."""
from __future__ import annotations
import argparse, collections, csv, hashlib, io, json, math, re, sys, tarfile, time, zipfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import numpy as np
from scipy.spatial import cKDTree
from rdkit import Chem, RDLogger, rdBase
from rdkit.Chem import rdPartialCharges

ROOT = Path(__file__).resolve().parents[1]
AA = dict(zip('ALA ARG ASN ASP CYS GLN GLU GLY HIS ILE LEU LYS MET PHE PRO SER THR TRP TYR VAL'.split(), 'ARNDCQEGHILKMFPSTWYV'))
AA.update(MSE='M', SEC='U', PYL='O', HYP='P', HID='H', HIE='H', HIP='H', CYX='C', ASH='D', GLH='E', LYN='K')
ELEMENTS = {Chem.GetPeriodicTable().GetElementSymbol(i).upper(): i for i in range(1,119)}
UNITS = {'M':1., 'mM':1e-3, 'uM':1e-6, 'nM':1e-9, 'pM':1e-12, 'fM':1e-15}
FEATURES = ['atomic_number','formal_charge','formal_charge_known','gasteiger_charge','gasteiger_charge_known','aromatic','aromatic_known','hybridization_rdkit_enum','hybridization_known','is_ligand']

def dump(path, obj):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, allow_nan=False), encoding='utf-8')

def write_csv(path, rows, fields=None):
    path=Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    if fields is None: fields=list(dict.fromkeys(k for row in rows for k in row))
    with path.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)

def digest(text): return hashlib.sha256(text.encode()).hexdigest()

def load_index():
    with tarfile.open(ROOT/'P-L.tar.gz') as t:
        raw=t.extractfile('index/INDEX_general_PL.2020R1.lst').read()
        readme=t.extractfile('index/README').read()
    out=ROOT/'processed'/'source_index'; out.mkdir(parents=True,exist_ok=True)
    (out/'INDEX_general_PL.2020R1.lst').write_bytes(raw)
    (out/'README.txt').write_bytes(readme)
    records={}
    for lineno,line in enumerate(raw.decode().splitlines(),1):
        if not line or line.startswith('#'): continue
        left,_,note=line.partition('//'); parts=left.split()
        if len(parts)!=4: raise ValueError(f'Index line {lineno}: unexpected columns: {line}')
        pdb,resolution,year,affinity=parts
        if not re.fullmatch(r'[a-zA-Z0-9]{4}',pdb): raise ValueError(f'Unsafe PDB ID: {pdb}')
        if pdb in records: raise ValueError(f'Duplicate PDB ID in index: {pdb}')
        m=re.fullmatch(r'(Kd|Ki|IC50)(<=|>=|=|<|>|~)([0-9.eE+-]+)([munpf]?M)',affinity)
        rec=dict(pdb_id=pdb,resolution=resolution,release_year=int(year),affinity_raw=affinity,index_note=note.strip(),index_line=lineno)
        if m:
            kind,op,value,unit=m.groups(); molar=float(value)*UNITS[unit]
            if molar<=0 or not math.isfinite(molar): raise ValueError(f'Invalid affinity: {line}')
            rec.update(affinity_type=kind,affinity_operator=op,affinity_molar=molar,p_affinity=-math.log10(molar),p_affinity_operator={'<':'>','>':'<','<=':'>=','>=':'<=','=':'=','~':'~'}[op])
        else: rec['label_error']='UNPARSEABLE_AFFINITY'
        records[pdb]=rec
    return records

def parse_protein(text):
    """First model; choose highest occupancy altloc; heavy amino-acid atoms only."""
    chosen={}; warnings=collections.Counter(); model_seen=False
    for line in text.splitlines():
        tag=line[:6].strip()
        if tag=='MODEL':
            if model_seen: break
            model_seen=True
        if tag=='ENDMDL': break
        if tag not in ('ATOM','HETATM'): continue
        if len(line)<54: raise ValueError('PROTEIN_TRUNCATED_ATOM_LINE')
        res=line[17:20].strip()
        if res in ('HOH','WAT','DOD'): warnings['waters_omitted']+=1; continue
        if tag=='HETATM' and res not in AA: warnings['nonprotein_heteroatoms_omitted']+=1; continue
        name=line[12:16].strip(); elem=line[76:78].strip().upper()
        if not elem:
            elem=re.sub('[0-9]','',name)[0].upper(); warnings['elements_inferred_from_atom_name']+=1
        if elem in ('H','D'): continue
        if elem not in ELEMENTS: raise ValueError('UNKNOWN_PROTEIN_ELEMENT:'+elem)
        xyz=[float(line[a:b]) for a,b in ((30,38),(38,46),(46,54))]
        if not all(math.isfinite(v) for v in xyz): raise ValueError('NONFINITE_PROTEIN_COORDINATES')
        occ=float(line[54:60].strip() or '0'); alt=line[16:17]
        key=(line[21:22],line[22:26],line[26:27],name)
        charge=line[78:80].strip(); q=0; known=0
        if re.fullmatch(r'[0-9][+-]',charge): q=int(charge[0])*(1 if charge[1]=='+' else -1); known=1
        atom=dict(xyz=xyz,z=ELEMENTS[elem],resname=res,chain=key[0],resid=key[1].strip(),icode=key[2].strip(),name=name,line=line,formal_charge=q,formal_charge_known=known)
        rank=(occ,alt==' ',alt=='A')
        if key in chosen: warnings['alternate_or_duplicate_atoms_removed']+=1
        if key not in chosen or rank>chosen[key][0]: chosen[key]=(rank,atom)
    atoms=[v[1] for v in chosen.values()]
    if len(atoms)<3: raise ValueError('PROTEIN_HAS_TOO_FEW_ATOMS')
    chains=collections.defaultdict(list); seen=set()
    for a in atoms:
        key=(a['chain'],a['resid'],a['icode'])
        if key not in seen:
            seen.add(key); chains[a['chain']].append(AA.get(a['resname'],'X'))
    seqs=sorted(set(''.join(v) for v in chains.values()))
    return atoms,seqs,dict(warnings)

def init_worker(archive, output):
    global ZIP, OUT
    ZIP=zipfile.ZipFile(archive); OUT=Path(output)
    RDLogger.DisableLog('rdApp.*')

def process_complex(task):
    pdb,paths,rec=task; rec=dict(rec); warnings=[]; exclusions=[]
    rec.update(status='excluded',graph_path='',training_eligible=False)
    try:
        required=['protein.pdb','ligand.sdf','ligand.mol2','pocket.pdb']
        missing=[k for k in required if k not in paths]
        if missing: raise ValueError('MISSING_FILES:'+','.join(missing))
        # Reading all four also verifies their ZIP CRC checksums.
        data={k:ZIP.read(paths[k]).decode('utf-8',errors='replace') for k in required}
        rec['protein_archive_path']=paths['protein.pdb']
        prot,seqs,pwarnings=parse_protein(data['protein.pdb'])
        rec['protein_chain_hashes']=';'.join(digest(s) for s in seqs)
        rec['protein_chain_lengths']=';'.join(str(len(s)) for s in seqs)
        rec['protein_parse_counts']=json.dumps(pwarnings,sort_keys=True)
        if pwarnings.get('nonprotein_heteroatoms_omitted'): warnings.append('COFACTORS_OR_IONS_OMITTED_FROM_GRAPH')
        try: parse_protein(data['pocket.pdb'])
        except Exception: warnings.append('SUPPLIED_POCKET_INVALID_RECOMPUTED_FROM_PROTEIN')
        mol=Chem.MolFromMolBlock(data['ligand.sdf'].split('$$$$')[0],sanitize=True,removeHs=True,strictParsing=True)
        ligand_source='sdf'
        if mol is None:
            mol=Chem.MolFromMol2Block(data['ligand.mol2'],sanitize=True,removeHs=True)
            ligand_source='mol2'
            if mol is not None: warnings.append('SDF_INVALID_USED_MOL2')
        if mol is None: raise ValueError('LIGAND_CHEMISTRY_INVALID_IN_SDF_AND_MOL2')
        mol=Chem.RemoveHs(mol)
        if mol.GetNumAtoms()<3 or mol.GetNumConformers()==0: raise ValueError('LIGAND_HAS_TOO_FEW_ATOMS_OR_NO_COORDINATES')
        ligxyz=np.asarray(mol.GetConformer().GetPositions(),dtype=np.float64)
        if not np.isfinite(ligxyz).all() or np.max(np.ptp(ligxyz,axis=0))<0.1: raise ValueError('INVALID_LIGAND_COORDINATES')
        if np.any(np.asarray([np.linalg.norm(ligxyz[b.GetBeginAtomIdx()]-ligxyz[b.GetEndAtomIdx()]) for b in mol.GetBonds()])>3.5):
            exclusions.append('IMPLAUSIBLE_LIGAND_BOND_LENGTH')
        if len(Chem.GetMolFrags(mol))>1: exclusions.append('DISCONNECTED_LIGAND')
        charges=[]
        try:
            charged=Chem.AddHs(mol)
            rdPartialCharges.ComputeGasteigerCharges(charged,throwOnParamFailure=True)
            charges=[float(charged.GetAtomWithIdx(i).GetProp('_GasteigerCharge')) for i in range(mol.GetNumAtoms())]
            if not all(math.isfinite(v) for v in charges): raise ValueError('nonfinite charge')
        except Exception:
            charges=None; warnings.append('LIGAND_PARTIAL_CHARGE_UNAVAILABLE_MASKED')
        protxyz=np.asarray([a['xyz'] for a in prot])
        nearest,_=cKDTree(ligxyz).query(protxyz,k=1)
        min_dist=float(nearest.min())
        if min_dist>6: raise ValueError('NO_PROTEIN_POCKET_WITHIN_6_ANGSTROM')
        if min_dist<1.0: exclusions.append('SEVERE_PROTEIN_LIGAND_CLASH')
        residue_keys={(a['chain'],a['resid'],a['icode']) for a,d in zip(prot,nearest) if d<=6.0}
        pocket=[a for a in prot if (a['chain'],a['resid'],a['icode']) in residue_keys]
        pocketxyz=np.asarray([a['xyz'] for a in pocket])
        xyz=np.concatenate([ligxyz,pocketxyz]).astype(np.float32)
        feats=[]
        for i,a in enumerate(mol.GetAtoms()):
            feats.append([a.GetAtomicNum(),a.GetFormalCharge(),1,charges[i] if charges is not None else 0,int(charges is not None),int(a.GetIsAromatic()),1,int(a.GetHybridization()),1,1])
        for a in pocket: feats.append([a['z'],a['formal_charge'],a['formal_charge_known'],0,0,0,0,0,0,0])
        pairs=cKDTree(xyz).query_pairs(4.5,output_type='ndarray')
        edges=np.concatenate([pairs,pairs[:,::-1]],axis=0).T.astype(np.int32)
        distances=np.linalg.norm(xyz[edges[0]]-xyz[edges[1]],axis=1).astype(np.float32)
        nlig=mol.GetNumAtoms()
        kinds=np.where((edges[0]<nlig)&(edges[1]<nlig),0,np.where((edges[0]>=nlig)&(edges[1]>=nlig),1,2)).astype(np.int8)
        bonds=[]; bondfeatures=[]
        for b in mol.GetBonds():
            i,j=b.GetBeginAtomIdx(),b.GetEndAtomIdx()
            for u,v in ((i,j),(j,i)):
                bonds.append((u,v)); bondfeatures.append([b.GetBondTypeAsDouble(),b.GetIsAromatic(),b.GetIsConjugated(),b.IsInRing()])
        contacts=[]
        for li,js in enumerate(cKDTree(ligxyz).query_ball_tree(cKDTree(pocketxyz),4.0)):
            for pi in js:
                a=pocket[pi]; d=float(np.linalg.norm(ligxyz[li]-pocketxyz[pi]))
                contacts.append(dict(ligand_atom=li,pocket_atom=pi,node_index=nlig+pi,distance=round(d,3),residue=f"{a['chain']}:{a['resname']}{a['resid']}{a['icode']}",protein_atom=a['name']))
        if not contacts: warnings.append('NO_CONTACTS_WITHIN_4_ANGSTROM')
        if rec.get('affinity_operator')!='=': exclusions.append('CENSORED_OR_UNPARSEABLE_AFFINITY')
        if 'covalent' in rec.get('index_note','').lower(): exclusions.append('INDEX_FLAGS_COVALENT_COMPLEX')
        if 'incomplete' in rec.get('index_note','').lower(): exclusions.append('INDEX_FLAGS_INCOMPLETE_STRUCTURE')
        dest=OUT/'complexes'/pdb; dest.mkdir(parents=True,exist_ok=True)
        np.savez_compressed(dest/'graph.npz',positions=xyz,node_features=np.asarray(feats,dtype=np.float32),edge_index=edges,edge_distance=distances,edge_kind=kinds,ligand_bond_index=np.asarray(bonds,dtype=np.int32).reshape(-1,2).T,ligand_bond_features=np.asarray(bondfeatures,dtype=np.float32).reshape(-1,4),ligand_atom_count=np.int32(nlig),p_affinity=np.float32(rec.get('p_affinity',np.nan)))
        (dest/'ligand.sdf').write_text(Chem.MolToMolBlock(mol)+'\n$$$$\n',encoding='utf-8')
        # Atom ordering matches pocket graph nodes. Altloc characters are cleared.
        (dest/'pocket.pdb').write_text('\n'.join(a['line'][:16]+' '+a['line'][17:] for a in pocket)+'\nEND\n',encoding='utf-8')
        rec.update(status='accepted' if not exclusions else 'visualization_only',training_eligible=not exclusions,ligand_source=ligand_source,canonical_smiles=Chem.MolToSmiles(mol),ligand_atoms=nlig,protein_atoms=len(prot),pocket_atoms=len(pocket),pocket_residues=len(residue_keys),spatial_directed_edges=edges.shape[1],minimum_protein_ligand_distance=round(min_dist,4),contact_pairs=len(contacts),graph_path=f'processed/pdbbind/complexes/{pdb}/graph.npz')
        meta=dict(rec,node_feature_names=FEATURES,pocket_atom_metadata=[{k:v for k,v in a.items() if k not in ('line','xyz')} for a in pocket],contacts=sorted(contacts,key=lambda x:x['distance']),warnings=warnings,exclusion_reasons=exclusions)
        dump(dest/'metadata.json',meta)
    except Exception as exc:
        exclusions.append(str(exc)); rec['error_type']=type(exc).__name__
    rec['warnings']=';'.join(warnings); rec['exclusion_reasons']=';'.join(exclusions)
    return rec

def assign_structure_splits(records):
    eligible=[r for r in records if r['training_eligible']]
    parent={r['pdb_id']:r['pdb_id'] for r in eligible}
    def find(x):
        while parent[x]!=x: parent[x]=parent[parent[x]]; x=parent[x]
        return x
    def union(a,b):
        a,b=find(a),find(b)
        if a!=b: parent[max(a,b)]=min(a,b)
    seen={}
    for r in eligible:
        for h in r['protein_chain_hashes'].split(';'):
            if h in seen: union(r['pdb_id'],seen[h])
            else: seen[h]=r['pdb_id']
    groups=collections.defaultdict(list)
    for r in eligible: groups[find(r['pdb_id'])].append(r)
    counts=dict(train=0,val=0,test=0); targets=dict(train=.8*len(eligible),val=.1*len(eligible),test=.1*len(eligible))
    for key,group in sorted(groups.items(),key=lambda kv:(-len(kv[1]),digest(kv[0]+'seed42'))):
        split=max(counts,key=lambda s:(targets[s]-counts[s])/max(targets[s],1))
        for r in group: r['split']=split; r['protein_group']=key
        counts[split]+=len(group)
    fields=['pdb_id','graph_path','p_affinity','affinity_type','affinity_raw','protein_group','split']
    for split in counts:
        write_csv(ROOT/'processed'/'pdbbind'/f'{split}.csv',[{k:r[k] for k in fields} for r in eligible if r['split']==split],fields)
    overlaps={}
    for key in ['pdb_id','canonical_smiles','protein_chain_hashes']:
        sets={s:{v for r in eligible if r['split']==s for v in (r[key].split(';') if key=='protein_chain_hashes' else [r[key]])} for s in counts}
        overlaps[key]={f'{a}-{b}':len(sets[a]&sets[b]) for a,b in [('train','val'),('train','test'),('val','test')]}
    assert all(v==0 for v in overlaps['pdb_id'].values())
    assert all(v==0 for v in overlaps['protein_chain_hashes'].values())
    return dict(counts=counts,protein_groups=len(groups),largest_protein_group=max(map(len,groups.values()),default=0),overlap=overlaps,policy='Group any complexes sharing an exact observed protein chain sequence; seed 42 tie-break. Similar but nonidentical proteins and ligands can cross splits. Not a homology/scaffold-disjoint benchmark.')

def process_structures(workers,limit,resume=False):
    if resume and limit: raise ValueError('--resume cannot be combined with --limit; this protects the full manifest.')
    index=load_index()
    with zipfile.ZipFile(ROOT/'P-L.zip') as z:
        grouped=collections.defaultdict(dict)
        for n in z.namelist():
            m=re.search(r'/([A-Za-z0-9]{4})/\1_(protein\.pdb|ligand\.sdf|ligand\.mol2|pocket\.pdb)$',n)
            if m:
                pdb,kind=m.groups()
                if kind in grouped[pdb]: raise ValueError(f'Duplicate structure file {pdb} {kind}')
                grouped[pdb][kind]=n
        embedded={}
        for n in z.namelist():
            if n.endswith('.csv'):
                rows=list(csv.DictReader(io.StringIO(z.read(n).decode())))
                embedded[n]=dict(rows=len(rows),columns=list(rows[0]) if rows else [],used_for_structure_labels=False,reason='No PDB ID; authoritative index is used instead.')
    ids=sorted(set(grouped)|set(index)); ids=ids[:limit] if limit else ids
    tasks=[(p,grouped.get(p,{}),index.get(p,dict(pdb_id=p,label_error='MISSING_INDEX_LABEL'))) for p in ids]
    out=ROOT/'processed'/'pdbbind'; out.mkdir(parents=True,exist_ok=True)
    # Validate archive identity before reusing completed records. Hashing is
    # streamed, so a multi-GB archive is never loaded into memory.
    signature={}
    for name in ('P-L.zip','P-L.tar.gz'):
        with (ROOT/name).open('rb') as source: signature[name]=hashlib.file_digest(source,'sha256').hexdigest()
    signature['graph_schema']=1
    signature_path=out/'resume_sources.json'; journal=out/'manifest.jsonl'
    records=[]; start=time.time()
    if resume and journal.exists():
        if signature_path.exists(): previous=json.loads(signature_path.read_text())
        else:
            provenance=json.loads((ROOT/'reports/input_provenance.json').read_text())
            previous={Path(p['path']).name:p['sha256'] for p in provenance if Path(p['path']).name in ('P-L.zip','P-L.tar.gz')}
            previous['graph_schema']=1
        if previous!=signature: raise ValueError('The source archives changed. Run without --resume to rebuild their graphs.')
        lines=journal.read_text(encoding='utf-8').splitlines(); cached={}
        for line_number,line in enumerate(lines):
            try: rec=json.loads(line)
            except json.JSONDecodeError:
                if line_number==len(lines)-1: break  # interrupted last write
                raise
            folder=out/'complexes'/rec['pdb_id']
            if rec['status']=='excluded' or all((folder/name).is_file() and (folder/name).stat().st_size for name in ('graph.npz','metadata.json','pocket.pdb','ligand.sdf')):
                cached[rec['pdb_id']]=rec
        records=[cached[p] for p in ids if p in cached]
        tasks=[task for task in tasks if task[0] not in cached]
        print(f'Resume: reusing {len(records)} complexes; processing {len(tasks)} missing or unfinished complexes.',flush=True)
    dump(signature_path,signature)
    if resume and not tasks and (ROOT/'reports/pdbbind_summary.json').exists():
        previous_report=json.loads((ROOT/'reports/pdbbind_summary.json').read_text())
        if previous_report.get('processed')==len(ids) and (out/'manifest.csv').exists():
            return previous_report
    # Atomically replace a possibly interrupted journal with complete records.
    temporary=journal.with_suffix('.tmp')
    temporary.write_text(''.join(json.dumps(r,allow_nan=False)+'\n' for r in records),encoding='utf-8')
    temporary.replace(journal)
    with ProcessPoolExecutor(max_workers=workers,initializer=init_worker,initargs=(str(ROOT/'P-L.zip'),str(out))) as pool:
        with journal.open('a',encoding='utf-8') as f:
            for i,rec in enumerate(pool.map(process_complex,tasks,chunksize=16),1):
                records.append(rec); f.write(json.dumps(rec,allow_nan=False)+'\n')
                if i%250==0 or i==len(tasks):
                    f.flush(); print(f'PDBbind {i}/{len(tasks)}; {time.time()-start:.0f}s; statuses={dict(collections.Counter(r["status"] for r in records))}',flush=True)
    records.sort(key=lambda r:r['pdb_id'])
    split_report=assign_structure_splits(records)
    write_csv(out/'manifest.csv',records)
    write_csv(out/'excluded.csv',[r for r in records if r['status']!='accepted'])
    report=dict(index_records=len(index),structure_complexes=len(grouped),processed=len(records),status_counts=dict(collections.Counter(r['status'] for r in records)),affinity_types=dict(collections.Counter(r.get('affinity_type','missing') for r in records)),exclusions=dict(collections.Counter(reason for r in records for reason in r['exclusion_reasons'].split(';') if reason)),warnings=dict(collections.Counter(reason for r in records for reason in r['warnings'].split(';') if reason)),structure_ids_missing_index=sorted(set(grouped)-set(index)),index_ids_missing_structures=sorted(set(index)-set(grouped)),embedded_csv=embedded,splits=split_report,seconds=round(time.time()-start,1))
    dump(ROOT/'reports'/'pdbbind_summary.json',report)
    return report

def process_tables():
    RDLogger.DisableLog('rdApp.*'); summaries={}; global_pairs=collections.defaultdict(dict); cache={}
    for name in ('davis','kiba','metz'):
        groups=collections.defaultdict(list); excluded=[]; total=0
        with (ROOT/f'{name}.csv').open(newline='',encoding='utf-8-sig') as f:
            for rownum,row in enumerate(csv.DictReader(f),2):
                total+=1; smiles=row.get('compound_iso_smiles','').strip(); seq=row.get('target_sequence','').strip().upper()
                try:
                    value=float(row['affinity'])
                    if not math.isfinite(value): raise ValueError('AFFINITY_IS_NOT_A_FINITE_NUMBER')
                    if not seq or re.search('[^ACDEFGHIKLMNPQRSTVWYBXZJUO]',seq): raise ValueError('INVALID_PROTEIN_SEQUENCE')
                    if smiles not in cache:
                        mol=Chem.MolFromSmiles(smiles)
                        cache[smiles]=Chem.MolToSmiles(mol) if mol is not None and mol.GetNumAtoms()>0 else None
                    canonical=cache[smiles]
                    if not canonical: raise ValueError('INVALID_COMPOUND_SMILES')
                    key=digest(canonical+'|'+seq)
                    bucket=int(key[:16],16)%10000; split='train' if bucket<8000 else 'val' if bucket<9000 else 'test'
                    groups[key].append(dict(pair_id=key,smiles=canonical,sequence=seq,label=value,source_row=rownum,split=split))
                except Exception as e: excluded.append(dict(source_row=rownum,reason=str(e)))
        accepted=[]; duplicates=0; conflicts=0
        for key,rows in groups.items():
            if len({r['label'] for r in rows})>1:
                conflicts+=1
                excluded.extend(dict(source_row=r['source_row'],reason='SAME_PAIR_HAS_DIFFERENT_LABELS') for r in rows)
            else:
                accepted.append(rows[0]); duplicates+=len(rows)-1
                excluded.extend(dict(source_row=r['source_row'],reason='EXACT_DUPLICATE_REMOVED') for r in rows[1:])
                global_pairs[key][name]=rows[0]['split']
        out=ROOT/'processed'/name
        for split in ('train','val','test'): write_csv(out/f'{split}.csv',[r for r in accepted if r['split']==split],['pair_id','smiles','sequence','label','source_row','split'])
        write_csv(out/'excluded_rows.csv',excluded,['source_row','reason'])
        summary=dict(input_rows=total,accepted_unique_pairs=len(accepted),excluded_rows=len(excluded),duplicate_rows=duplicates,conflicting_pairs=conflicts,unique_ligands=len({r['smiles'] for r in accepted}),unique_sequences=len({r['sequence'] for r in accepted}),label_min=min((r['label'] for r in accepted),default=None),label_max=max((r['label'] for r in accepted),default=None),splits=dict(collections.Counter(r['split'] for r in accepted)),coordinates_available=False,label_handling='Original numeric scores preserved. Source CSV does not specify units or transformations; do not combine scores across datasets.',split_policy='SHA256 canonical isomeric SMILES + exact sequence; same pair always goes to the same split across all three datasets. Not cold-target or cold-ligand.')
        overlap={}
        for field in ('pair_id','smiles','sequence'):
            sets={s:{r[field] for r in accepted if r['split']==s} for s in ('train','val','test')}
            overlap[field]={f'{a}-{b}':len(sets[a]&sets[b]) for a,b in [('train','val'),('train','test'),('val','test')]}
        assert all(v==0 for v in overlap['pair_id'].values())
        summary['overlap']=overlap; summaries[name]=summary
        dump(out/'summary.json',summary); print(name,summary['input_rows'],summary['accepted_unique_pairs'],flush=True)
    cross={f'{a}-{b}':sum(a in v and b in v for v in global_pairs.values()) for a,b in [('davis','kiba'),('davis','metz'),('kiba','metz')]}
    violations=sum(len(set(v.values()))>1 for v in global_pairs.values())
    assert violations==0
    dump(ROOT/'reports'/'table_summary.json',dict(datasets=summaries,cross_dataset_exact_pair_overlap=cross,cross_dataset_pair_split_conflicts=violations))
    return summaries

def main():
    p=argparse.ArgumentParser(); p.add_argument('--mode',choices=['all','tables','structures'],default='all'); p.add_argument('--workers',type=int,default=4); p.add_argument('--limit',type=int)
    p.add_argument('--resume',action='store_true',help='Reuse finished PDBbind graphs after checking source archive SHA256; retry missing outputs.')
    args=p.parse_args()
    if args.mode in ('all','tables'):
        process_tables()
        from prepare_2d_ligands import main as prepare_2d_ligands
        prepare_2d_ligands()
    if args.mode in ('all','structures'): process_structures(args.workers,args.limit,args.resume)
    dump(ROOT/'reports'/'schema.json',dict(schema_version=1,coordinates='Angstrom; original common crystal coordinate frame; heavy atoms only; ligand nodes first, pocket nodes second',pocket='All atoms of amino acid residues having a heavy atom within 6 A of any ligand heavy atom',spatial_edges='Directed neighbor edges <=4.5 A, no self edges; these are distance connections, not chemical bonds',edge_kind={'0':'ligand-ligand','1':'protein-protein','2':'protein-ligand'},node_feature_names=FEATURES,ligand_bond_features=['bond_order','aromatic','conjugated','in_ring'],charges='Ligand formal charges from sanitized RDKit; Gasteiger estimated with explicit H then heavy atom charges retained. Protein formal charge only when explicit in PDB; all protein partial charges unknown. Unknown values zero-filled with mask=0; never interpret as neutral.',protein_bonds='No protein covalent topology or bond orders assigned; only spatial edges. Force-field preparation needed for MD.',affinity='p_affinity = -log10(value in mol/L); Kd, Ki and IC50 remain distinct types. Bound operators reverse on log conversion. Only exact values enter ordinary regression splits.',versions=dict(python=sys.version,rdkit=rdBase.rdkitVersion,numpy=np.__version__),model_compatibility='Generic NPZ 3D graph schema. The recovered CPI checkpoints consume 2D ligand features and protein sequences, not these XYZ graphs.'))

if __name__=='__main__': main()
