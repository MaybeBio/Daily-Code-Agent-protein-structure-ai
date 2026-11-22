"""PLIP contacts for the explicitly selected ligand; source coordinates unchanged."""
import json,threading,zipfile,hashlib
from pathlib import Path
from rdkit import Chem
from preprocess import ROOT
from docking_stages import timed
LOCK=threading.Lock()
@timed("contacts")
def analyze(folder):
 folder=Path(folder);cache=folder/'interaction_analysis.json'
 
 with LOCK:
  
  from plip.structure.preparation import PDBComplex
  from plip.exchange.report import BindingSiteReport
  from plip.basic import config
  from openbabel import pybel
  # This Windows wheel lacks the InChI output plugin. Supply only that writer
  # through RDKit; Open Babel/PLIP still perform their own contact calculations.
  meta=json.loads((folder/'metadata.json').read_text())
  if (folder/'protein.pdb').exists():protein=(folder/'protein.pdb').read_text()
  else:
   with zipfile.ZipFile(ROOT/'P-L.zip') as z:protein=z.read(meta['protein_archive_path']).decode()
  ligand=Chem.SDMolSupplier(str(folder/'ligand.sdf'),removeHs=True)[0]
  signature=hashlib.sha256(b'plip-v4'+protein.encode()+(folder/'ligand.sdf').read_bytes()).hexdigest()
  if cache.is_file():
   saved=json.loads(cache.read_text())
   if saved.get('input_sha256')==signature:return saved
  tag='Q'+hashlib.sha256(Chem.MolToSmiles(ligand).encode()).hexdigest()[:2].upper()
  pdb_ligand=ligand
  for atom in pdb_ligand.GetAtoms():
   info=Chem.AtomPDBResidueInfo();info.SetName(f'{atom.GetSymbol()}{atom.GetIdx()+1:03d}'[-4:]);info.SetResidueName(tag);info.SetResidueNumber(9999);info.SetChainId('Z');info.SetIsHeteroAtom(True);atom.SetMonomerInfo(info)
  records=[l for l in protein.splitlines() if l.startswith(('ATOM  ','HETATM','TER   '))]
  if any(l[17:27]==f'{tag} Z9999 ' for l in records):raise ValueError('Selected-ligand residue ID would collide with the receptor.')
  # Regenerate serial IDs consistently, including ligand CONECT bond records.
  serial=0
  for i,line in enumerate(records):
   if line.startswith("TER"):
    records[i]="TER"
   else:
    serial+=1
    records[i]=line[:6]+f"{serial:5d}"+line[11:]
  maximum=serial;liglines=Chem.MolToPDBBlock(pdb_ligand).splitlines()
  for l in liglines:
   if l.startswith(('ATOM','HETATM')):records.append(l[:6]+f'{int(l[6:11])+maximum:5d}'+l[11:])
   elif l.startswith('CONECT'):records.append('CONECT'+''.join(f'{int(l[i:i+5])+maximum:5d}' for i in range(6,len(l),5) if l[i:i+5].strip()))
  path=folder/'selected_complex.pdb';path.write_text('\n'.join(records)+'\nEND\n')
  config.OUTPUTFOLDER=str(folder/'plip');config.NOHYDRO=False
  # Preserve the authoritative SDF topology when PLIP reads the PDB complex.
  # PDB readers otherwise infer ligand bond orders a second time from distances.
  from plip.structure import preparation
  from unittest.mock import patch
  import math
  original_reader=preparation.read_pdb
  def read_with_ligand_topology(*args,**kwargs):
   complex_mol,fmt=original_reader(*args,**kwargs)
   ob=pybel.ob
   target=complex_mol.OBMol
   ref=pybel.readstring('mol',Chem.MolToMolBlock(ligand)).OBMol
   ids=[]
   for atom in ob.OBMolAtomIter(target):
    res=atom.GetResidue()
    if res and res.GetName()==tag and res.GetChain()=='Z' and res.GetNum()==9999:
     ids.append(atom.GetIdx())
   if len(ids)!=ref.NumAtoms():raise ValueError("PLIP input ligand atom count differs from the docked SDF.")
   group=set(ids)
   for bond in list(ob.OBMolBondIter(target)):
    a,b=bond.GetBeginAtomIdx(),bond.GetEndAtomIdx()
    if a in group or b in group:target.DeleteBond(bond)
   for idx,source in zip(ids,ob.OBMolAtomIter(ref)):
    atom=target.GetAtom(idx)
    if atom.GetAtomicNum()!=source.GetAtomicNum() or math.dist((atom.GetX(),atom.GetY(),atom.GetZ()),(source.GetX(),source.GetY(),source.GetZ()))>.002:
     raise ValueError("PLIP atom mapping differs from the docked SDF.")
    atom.SetFormalCharge(source.GetFormalCharge());atom.SetImplicitHCount(source.GetImplicitHCount())
    atom.SetAromatic(source.IsAromatic())
   for bond in ob.OBMolBondIter(ref):
    a,b=ids[bond.GetBeginAtomIdx()-1],ids[bond.GetEndAtomIdx()-1]
    target.AddBond(a,b,bond.GetBondOrder())
    target.GetBond(a,b).SetAromatic(bond.IsAromatic())
   target.SetChainsPerceived(True)
   return complex_mol,fmt
  model=PDBComplex();model.output_path=config.OUTPUTFOLDER
  with patch.object(preparation,'read_pdb',read_with_ligand_topology):
   model.load_pdb(str(path))
  chosen=[l for l in model.ligands if l.hetid==tag and l.chain=='Z' and l.position==9999]
  if len(chosen)!=1:raise ValueError('PLIP could not uniquely identify the selected ligand.')
  # The selected SDF carries authoritative bond orders. PLIP's Windows wheel
  # lacks the InChI writer, so supply the identifier on this ligand instance.
  molecule=chosen[0].mol
  perceived=Chem.MolFromMolBlock(molecule.write("mol"),removeHs=True)
  if perceived is None or not (perceived.GetNumHeavyAtoms()==ligand.GetNumHeavyAtoms() and
      Chem.MolToSmiles(perceived,isomericSmiles=False)==Chem.MolToSmiles(ligand,isomericSmiles=False)):
   raise ValueError("PLIP ligand bond orders or connectivity differ from the docked SDF.")
  if 'inchikey' not in pybel.outformats:
   write=molecule.write
   molecule.write=lambda format='smi', *args, **kwargs: Chem.MolToInchiKey(ligand) if format=='inchikey' else write(format,*args,**kwargs)
  model.characterize_complex(chosen[0]);site=model.interaction_sets[f'{tag}:Z:9999'];report=BindingSiteReport(site);contacts=[]
  for prefix,label in (('hydrophobic','hydrophobic contact'),('hbond','hydrogen bond'),('saltbridge','salt bridge'),('pistacking','pi stacking'),('pication','pi-cation interaction'),('halogen','halogen bond'),('waterbridge','water bridge'),('metal','metal complex')):
   for values in getattr(report,prefix+'_info'):
    r=dict(zip(getattr(report,prefix+'_features'),values))
    contacts.append(dict(type=label,residue=f"{r['RESCHAIN']}:{r['RESTYPE']}{r['RESNR']}",chain=r['RESCHAIN'],residue_number=r['RESNR'],distance=float(next(r[k] for k in ('DIST','DIST_D-A','DIST_A-W','CENTDIST') if k in r)),ligand_position=list(r.get('LIGCOO',r.get('METALCOO',[]))),protein_position=list(r.get('PROTCOO',r.get('TARGETCOO',[]))),details=r))
  residues={(l[21].strip(),l[17:20].strip(),int(l[22:26])) for l in records if l.startswith(("ATOM","HETATM"))}
  if any((c["chain"].strip(),c["details"]["RESTYPE"],int(c["residue_number"])) not in residues for c in contacts):
   raise ValueError("PLIP contact residue does not exist in the supplied receptor.")
  result=dict(input_sha256=signature,method='PLIP 3.0.1; Open Babel 3.1.1; calculated contacts with PLIP chemical/geometry rules and added hydrogens',selected_ligand=f'{tag}:Z:9999 in generated selected_complex.pdb',contacts=contacts,note='Assignments depend on protonation and structural quality. Unclassified geometric contacts remain separately available; no affinity is inferred.')
  cache.write_text(json.dumps(result,indent=2));return result
if __name__=='__main__':
 import sys
 print(json.dumps(analyze(ROOT/'processed/pdbbind/complexes'/(sys.argv[1] if len(sys.argv)>1 else '2ity')),indent=2))
