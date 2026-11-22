"""Native Windows Vina + Meeko. Known-pocket docking with explicit provenance."""
import json,re,subprocess,sys,time,zipfile,hashlib
from pathlib import Path
import numpy as np
from rdkit import Chem
from rdkit.Chem import AllChem,rdMolAlign
from rdkit.Chem.MolStandardize import rdMolStandardize
from scipy.spatial import cKDTree
from preprocess import ROOT,parse_protein

def run(args,folder,name,timeout=600):
 result=subprocess.run([str(a) for a in args],capture_output=True,text=True,timeout=timeout,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
 (folder/f'{name}.log').write_text(result.stdout+'\n'+result.stderr,encoding='utf-8')
 if result.returncode:raise RuntimeError(f'{name} failed. See {folder.name}/{name}.log: '+result.stderr[-500:])
 return result.stdout

def _meeko_rejected_residues(log_text):
 return sorted(set(re.findall(r"No template matched for residue_key='([^']+)'",log_text)))

def _rejected_residues_in_box(residue_atoms,center,box):
 center=np.asarray(center,dtype=float);half_box=np.asarray(box,dtype=float)/2
 return sorted(residue for residue,coordinates in residue_atoms.items()
               if np.any(np.all(np.abs(np.asarray(coordinates,dtype=float)-center)<=half_box,axis=1)))

def _pose_matches_query(query,pose):
 if query.GetNumAtoms()!=pose.GetNumAtoms() or query.GetNumBonds()!=pose.GetNumBonds():
  return False
 if Chem.MolToSmiles(query,isomericSmiles=False)!=Chem.MolToSmiles(pose,isomericSmiles=False):
  return False
 return pose.HasSubstructMatch(query,useChirality=True)

def dock(smiles,pdb,folder):
 from meeko import MoleculePreparation,PDBQTWriterLegacy
 start=time.time();folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
 reference_folder=ROOT/'processed/pdbbind/complexes'/pdb
 meta=json.loads((reference_folder/'metadata.json').read_text())
 with zipfile.ZipFile(ROOT/'P-L.zip') as z:raw_protein=z.read(meta['protein_archive_path']).decode()
 protein_atoms,_,preparation_warnings=parse_protein(raw_protein)
 protein_lines=[];previous_chain=None
 for atom in protein_atoms:
  if not atom['line'].startswith('ATOM  '):continue
  if previous_chain is not None and atom['chain']!=previous_chain:protein_lines.append('TER')
  line=atom['line'];protein_lines.append(line[:16]+' '+line[17:]);previous_chain=atom['chain']
 protein='\n'.join(protein_lines+['TER','END'])+'\n'
 (folder/'protein.pdb').write_text(protein)
 # Keep one highest-occupancy conformer per atom; no reference ligand enters the receptor.
 (folder/'receptor_input.pdb').write_text(protein)
 receptor=folder/'receptor.pdbqt'
 if not receptor.exists():run([sys.executable,'-m','meeko.cli.mk_prepare_receptor','--read_pdb',folder/'receptor_input.pdb','-o',folder/'receptor','-p'],folder,'receptor_preparation')
 query=Chem.MolFromSmiles(smiles)
 if query is None:raise ValueError('Invalid compound text.')
 if len(Chem.GetMolFrags(query))!=1:raise ValueError('Docking currently requires one connected compound; separate salts need explicit preparation.')
 molecule=Chem.AddHs(query);params=AllChem.ETKDGv3();params.randomSeed=42
 if AllChem.EmbedMolecule(molecule,params)!=0:raise ValueError('Could not generate a valid 3D starting shape for this compound.')
 if AllChem.MMFFHasAllMoleculeParams(molecule):AllChem.MMFFOptimizeMolecule(molecule,maxIters=500)
 setup=MoleculePreparation().prepare(molecule)[0]
 pdbqt,okay,reason=PDBQTWriterLegacy.write_string(setup)
 if not okay:raise ValueError(reason)
 (folder/'ligand_input.pdbqt').write_text(pdbqt)
 reference=Chem.SDMolSupplier(str(reference_folder/'ligand.sdf'),removeHs=True)[0]
 refxyz=np.asarray(reference.GetConformer().GetPositions());center=refxyz.mean(0);box=np.maximum(np.ptp(refxyz,axis=0)+12,22)
 if np.any(box>40):raise ValueError('Reference pocket needs a box larger than this small-molecule workflow supports.')
 args=[ROOT/'tools/vina.exe','--receptor',receptor,'--ligand',folder/'ligand_input.pdbqt','--out',folder/'docked.pdbqt','--cpu','2','--seed','42','--exhaustiveness','8','--num_modes','5']
 for key,val in zip(('center_x','center_y','center_z'),center):args.extend(['--'+key,str(val)])
 for key,val in zip(('size_x','size_y','size_z'),box):args.extend(['--'+key,str(val)])
 run(args,folder,'vina',timeout=900)
 run([sys.executable,'-m','meeko.cli.mk_export',folder/'docked.pdbqt','-s',folder/'ranked_poses.sdf'],folder,'pose_export')
 ranked=[Chem.RemoveHs(m) for m in Chem.SDMolSupplier(str(folder/'ranked_poses.sdf'),removeHs=False) if m is not None]
 if not ranked:raise ValueError('Docking output contained no readable poses.')
 # Meeko restores bond orders and atom identity using its stored input mapping.
 selected=None;checks=[]
 atoms,_,_=parse_protein(protein);protxyz=np.asarray([a['xyz'] for a in atoms]);tree=cKDTree(protxyz)
 for rank,mol in enumerate(ranked,1):
  xyz=np.asarray(mol.GetConformer().GetPositions());same=_pose_matches_query(query,mol)
  lengths=[np.linalg.norm(xyz[b.GetBeginAtomIdx()]-xyz[b.GetEndAtomIdx()]) for b in mol.GetBonds()]
  minimum=float(tree.query(xyz)[0].min());valid=same and np.isfinite(xyz).all() and min(lengths,default=0)>.7 and max(lengths,default=10)<3.0 and 1.0<=minimum<=4.0
  checks.append(dict(rank=rank,canonical_connectivity_and_stereo_match=same,minimum_protein_distance=minimum,accepted=bool(valid)))
  if valid and selected is None:selected=(rank,mol,xyz)
 if selected is None:raise ValueError('All docked poses failed chemistry, bond-length or pocket-placement checks.')
 rank,mol,xyz=selected
 # Preserve the saved stereo labels, and reject a changed chiral geometry.
 geometric=Chem.Mol(mol);Chem.AssignAtomChiralTagsFromStructure(geometric,replaceExistingTags=True)
 for a,b in zip(mol.GetAtoms(),geometric.GetAtoms()):
  if a.GetChiralTag()!=Chem.ChiralType.CHI_UNSPECIFIED and a.GetChiralTag()!=b.GetChiralTag():raise ValueError('Docking changed a specified stereocenter; pose rejected.')
 (folder/'ligand.sdf').write_text(Chem.MolToMolBlock(mol)+'\n$$$$\n')
 nearest=cKDTree(xyz).query(protxyz)[0]
 residues={(a['chain'],a['resid'],a['icode']) for a,d in zip(atoms,nearest) if d<=6}
 pocket=[a for a in atoms if (a['chain'],a['resid'],a['icode']) in residues];pocketxyz=np.asarray([a['xyz'] for a in pocket])
 (folder/'pocket.pdb').write_text('\n'.join(a['line'][:16]+' '+a['line'][17:] for a in pocket)+'\nEND\n')
 contacts=[]
 for i,js in enumerate(cKDTree(xyz).query_ball_tree(cKDTree(pocketxyz),4)):
  for j in js:
   a=pocket[j];contacts.append(dict(ligand_atom=i,pocket_atom=j,residue=f"{a['chain']}:{a['resname']}{a['resid']}{a['icode']}",protein_atom=a['name'],distance=round(float(np.linalg.norm(xyz[i]-pocketxyz[j])),3)))
 contacts.sort(key=lambda c:c['distance'])
 np.savez_compressed(folder/'graph.npz',positions=np.concatenate([xyz,pocketxyz]),ligand_atom_count=len(xyz))
 output=dict(pdb_id=pdb,pose_source='AutoDock Vina predicted pose',training_eligible=False,exclusion_reasons=['PREDICTED_POSE'],ligand_atoms=len(xyz),pocket_atoms=len(pocket),pocket_residues=len(residues),contacts=contacts,protein_archive_path=meta['protein_archive_path'],affinity_raw='Docked pose; no experimental affinity assigned',affinity_type='',p_affinity=None,p_affinity_operator='',canonical_smiles=Chem.MolToSmiles(mol),pocket_atom_metadata=[{k:v for k,v in a.items() if k not in ('line','xyz')} for a in pocket])
 (folder/'metadata.json').write_text(json.dumps(output,indent=2))
 neutral=lambda m:Chem.MolToSmiles(rdMolStandardize.Uncharger().uncharge(m))
 rmsd=None
 if neutral(reference)==neutral(query):
  # Same receptor coordinates; CalcRMS does NOT align away pose error.
  refn=rdMolStandardize.Uncharger().uncharge(reference);predn=rdMolStandardize.Uncharger().uncharge(mol)
  rmsd=float(rdMolAlign.CalcRMS(predn,refn,maxMatches=10000))
 result=dict(source='AutoDock Vina 1.2.7 + Meeko',receptor_pdb=pdb,selected_rank=rank,ranked_pose_checks=checks,box_center=center.tolist(),box_size=box.tolist(),pocket_source='Known reference ligand site; ligand removed from receptor. Not blind docking.',preparation='Meeko residue templates; one highest-occupancy alternate location per atom. Waters, metals and separate cofactors removed for this limited preparation; not suitable for sites requiring them without specialist preparation.',preparation_warnings=preparation_warnings,conformer_seed=42,vina_seed=42,exhaustiveness=8,cpu=2,seconds=time.time()-start,reference_rmsd_angstrom=rmsd,rmsd_method='Symmetry-aware heavy-atom CalcRMS in the unchanged receptor frame, no ligand realignment; n=1 known-pocket redocking when reference matches.',graph_schema='Pose coordinate arrays only; not the PDBbind training graph schema.',confidence='No calibrated confidence. Docking rank/energy is not the trained CPI score.')
 (folder/'docking.json').write_text(json.dumps(result,indent=2));return result

def dock_generated(smiles,protein_path,sites,folder):
 from meeko import MoleculePreparation,PDBQTWriterLegacy
 start=time.time();folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
 if not sites:raise ValueError('P2Rank did not provide any candidate pockets.')
 raw_protein=Path(protein_path).read_text(encoding='utf-8')
 protein_atoms,_,warnings=parse_protein(raw_protein)
 if not protein_atoms:raise ValueError('The predicted protein contains no usable amino-acid atoms.')
 lines=[];previous_chain=None
 for atom in protein_atoms:
  if not atom['line'].startswith('ATOM  '):continue
  if previous_chain is not None and atom['chain']!=previous_chain:lines.append('TER')
  lines.append(atom['line'][:16]+' '+atom['line'][17:]);previous_chain=atom['chain']
 protein='\n'.join(lines+['TER','END'])+'\n'
 (folder/'protein.pdb').write_text(protein,encoding='utf-8')
 (folder/'receptor_input.pdb').write_text(protein,encoding='utf-8')
 receptor=folder/'receptor.pdbqt'
 if not receptor.exists():
  run([sys.executable,'-m','meeko.cli.mk_prepare_receptor','--read_pdb',folder/'receptor_input.pdb','-o',folder/'receptor','-p','--delete_bad_res'],folder,'receptor_preparation')
 query=Chem.MolFromSmiles(smiles)
 if query is None:raise ValueError('Invalid compound text.')
 if len(Chem.GetMolFrags(query))!=1:raise ValueError('Docking currently requires one connected compound; separate salts need explicit preparation.')
 molecule=Chem.AddHs(query);params=AllChem.ETKDGv3();params.randomSeed=42
 if AllChem.EmbedMolecule(molecule,params)!=0:raise ValueError('Could not generate a valid 3D starting shape for this compound.')
 if AllChem.MMFFHasAllMoleculeParams(molecule):AllChem.MMFFOptimizeMolecule(molecule,maxIters=500)
 setup=MoleculePreparation().prepare(molecule)[0]
 pdbqt,okay,reason=PDBQTWriterLegacy.write_string(setup)
 if not okay:raise ValueError(reason)
 (folder/'ligand_input.pdbqt').write_text(pdbqt,encoding='utf-8')
 ligand_xyz=np.asarray(molecule.GetConformer().GetPositions())
 box=np.maximum(np.ptp(ligand_xyz,axis=0)+12,22)
 if np.any(box>40):raise ValueError('The compound needs a docking box larger than this workflow supports.')
 atoms,_,_=parse_protein(protein)
 protein_xyz=np.asarray([atom['xyz'] for atom in atoms])
 preparation_log=folder/'receptor_preparation.log'
 rejected_residues=_meeko_rejected_residues(preparation_log.read_text(encoding='utf-8',errors='replace')) if preparation_log.is_file() else []
 preparation_warnings=list(warnings)
 if rejected_residues:
  preparation_warnings.append('Meeko omitted residues with unmatched templates: '+', '.join(rejected_residues)+'. Docking pockets whose boxes overlap those residues are skipped.')
 rejected_residue_atoms={}
 for atom in atoms:
  key=f"{atom['chain']}:{atom['resid']}{atom['icode']}"
  if key in rejected_residues:rejected_residue_atoms.setdefault(key,[]).append(atom['xyz'])
 tree=cKDTree(protein_xyz)
 site_results=[];best=None
 for site in sites:
  center=np.asarray(site['center'],dtype=float)
  if center.shape!=(3,) or not np.isfinite(center).all():continue
  rank=int(site['rank']);site_folder=folder/'site_runs'/f'pocket_{rank}'
  site_folder.mkdir(parents=True,exist_ok=True)
  overlapping_residues=_rejected_residues_in_box(rejected_residue_atoms,center,box)
  if overlapping_residues:
   site_results.append(dict(rank=rank,p2rank_score=site['score'],p2rank_probability=site['probability'],status='skipped_receptor_template_mismatch',skipped_residues=overlapping_residues))
   continue
  output=site_folder/'docked.pdbqt'
  args=[ROOT/'tools/vina.exe','--receptor',receptor,'--ligand',folder/'ligand_input.pdbqt','--out',output,'--cpu','2','--seed','42','--exhaustiveness','8','--num_modes','5']
  for key,value in zip(('center_x','center_y','center_z'),center):args.extend(['--'+key,str(value)])
  for key,value in zip(('size_x','size_y','size_z'),box):args.extend(['--'+key,str(value)])
  run(args,site_folder,'vina',timeout=900)
  scores=[]
  for line in output.read_text(encoding='utf-8').splitlines():
   if line.startswith('REMARK VINA RESULT:'):
    try:scores.append(float(line.split()[3]))
    except (IndexError,ValueError):pass
  if not scores:
   site_results.append(dict(rank=rank,p2rank_score=site['score'],p2rank_probability=site['probability'],status='no_vina_scores'))
   continue
  sdf=site_folder/'ranked_poses.sdf'
  run([sys.executable,'-m','meeko.cli.mk_export',output,'-s',sdf],site_folder,'pose_export')
  ranked=[Chem.RemoveHs(mol) for mol in Chem.SDMolSupplier(str(sdf),removeHs=False) if mol is not None]
  checks=[];selected=None
  for pose_rank,mol in enumerate(ranked,1):
   xyz=np.asarray(mol.GetConformer().GetPositions())
   same=_pose_matches_query(query,mol)
   lengths=[np.linalg.norm(xyz[b.GetBeginAtomIdx()]-xyz[b.GetEndAtomIdx()]) for b in mol.GetBonds()]
   minimum=float(tree.query(xyz)[0].min())
   valid=same and np.isfinite(xyz).all() and min(lengths,default=0)>.7 and max(lengths,default=10)<3.0 and 1.0<=minimum<=4.0
   checks.append(dict(rank=pose_rank,canonical_connectivity_and_stereo_match=same,minimum_protein_distance=minimum,accepted=bool(valid)))
   if valid:
    selected=(pose_rank,mol,xyz,scores[min(pose_rank-1,len(scores)-1)])
    break
  if selected is None:
   site_results.append(dict(rank=rank,p2rank_score=site['score'],p2rank_probability=site['probability'],status='no_valid_pose',pose_checks=checks))
   continue
  pose_rank,mol,xyz,energy=selected
  entry=dict(rank=rank,p2rank_score=site['score'],p2rank_probability=site['probability'],vina_score_kcal_mol=energy,status='docked',selected_pose_rank=pose_rank,pose_checks=checks)
  site_results.append(entry)
  if best is None or (energy,-site['probability'],rank)<(best[0],-best[1]['probability'],best[1]['rank']):
   best=(energy,site,pose_rank,mol,xyz,checks)
 if best is None:raise ValueError('Vina found no chemically valid pose in the top P2Rank pockets.')
 energy,selected_site,selected_rank,mol,xyz,checks=best
 geometric=Chem.Mol(mol);Chem.AssignAtomChiralTagsFromStructure(geometric,replaceExistingTags=True)
 for expected,observed in zip(mol.GetAtoms(),geometric.GetAtoms()):
  if expected.GetChiralTag()!=Chem.ChiralType.CHI_UNSPECIFIED and expected.GetChiralTag()!=observed.GetChiralTag():
   raise ValueError('Docking changed a specified stereocenter; pose rejected.')
 (folder/'ligand.sdf').write_text(Chem.MolToMolBlock(mol)+'\n$$$$\n',encoding='utf-8')
 nearest=cKDTree(xyz).query(protein_xyz)[0]
 residues={(atom['chain'],atom['resid'],atom['icode']) for atom,distance in zip(atoms,nearest) if distance<=6}
 pocket=[atom for atom in atoms if (atom['chain'],atom['resid'],atom['icode']) in residues]
 pocket_xyz=np.asarray([atom['xyz'] for atom in pocket])
 (folder/'pocket.pdb').write_text('\n'.join(atom['line'][:16]+' '+atom['line'][17:] for atom in pocket)+'\nEND\n',encoding='utf-8')
 contacts=[]
 for i,neighbors in enumerate(cKDTree(xyz).query_ball_tree(cKDTree(pocket_xyz),4)):
  for j in neighbors:
   atom=pocket[j]
   contacts.append(dict(ligand_atom=i,pocket_atom=j,residue=f"{atom['chain']}:{atom['resname']}{atom['resid']}{atom['icode']}",protein_atom=atom['name'],distance=round(float(np.linalg.norm(xyz[i]-pocket_xyz[j])),3)))
 contacts.sort(key=lambda contact:contact['distance'])
 np.savez_compressed(folder/'graph.npz',positions=np.concatenate([xyz,pocket_xyz]),ligand_atom_count=len(xyz))
 ranked_sites=sorted(site_results,key=lambda item:(item.get('vina_score_kcal_mol',float('inf')),-(item['p2rank_probability'] or 0),item['rank']))
 for overall_rank,item in enumerate(ranked_sites,1):item['overall_rank']=overall_rank
 metadata=dict(pdb_id='sequence',display_name='ESMFold predicted structure',pose_source='AutoDock Vina predicted pose after ESMFold sequence folding and P2Rank blind pocket search',training_eligible=False,exclusion_reasons=['PREDICTED_POSE','PREDICTED_PROTEIN'],ligand_atoms=len(xyz),pocket_atoms=len(pocket),pocket_residues=len(residues),contacts=contacts,affinity_raw=f'Vina score {energy:.2f} kcal/mol; not an experimental affinity',affinity_type='',p_affinity=None,p_affinity_operator='',canonical_smiles=Chem.MolToSmiles(mol),pocket_atom_metadata=[{key:value for key,value in atom.items() if key not in ('line','xyz')} for atom in pocket],selected_pocket_rank=selected_site['rank'],pocket_candidates=ranked_sites,preparation_warnings=preparation_warnings)
 (folder/'metadata.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
 result=dict(source='AutoDock Vina 1.2.7 + Meeko',protein_source='ESMFold sequence prediction',pocket_source='P2Rank blind pocket prediction',selected_pocket_rank=selected_site['rank'],selected_pocket_probability=selected_site['probability'],selected_pocket_p2rank_score=selected_site['score'],selected_rank=selected_rank,selected_vina_score_kcal_mol=energy,pocket_candidates=ranked_sites,ranked_pose_checks=checks,box_center=selected_site['center'],box_size=box.tolist(),preparation='Meeko residue templates; unmatched residues are omitted and overlapping pocket boxes are skipped. Highest-occupancy alternate location per atom. Predicted structure and static receptor; no waters, metals or separate cofactors.',preparation_warnings=preparation_warnings,conformer_seed=42,vina_seed=42,exhaustiveness=8,cpu=2,seconds=time.time()-start,confidence='ESMFold pLDDT estimates structure confidence only; P2Rank probability estimates pocket likelihood; Vina score is not calibrated binding affinity.')
 (folder/'docking.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
 return result

if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser();p.add_argument('--pdb',default='2ity');p.add_argument('--smiles');args=p.parse_args()
 meta=json.loads((ROOT/f'processed/pdbbind/complexes/{args.pdb}/metadata.json').read_text())
 print(json.dumps(dock(args.smiles or meta['canonical_smiles'],args.pdb,ROOT/'processed/docking_demo'/args.pdb),indent=2))
