"""Lossless source-row catalog and conservative experimental-pose matching."""
import csv,json,sqlite3,hashlib,re,zipfile,collections,time
import io
from pathlib import Path
from rdkit import Chem,RDLogger
from rdkit.Chem.MolStandardize import rdMolStandardize
from preprocess import ROOT,parse_protein
DB=ROOT/'processed/cpi.sqlite'
class Connection(sqlite3.Connection):
 """Commit/rollback a context and release its file handle on Windows."""
 def __exit__(self,*exc):
  try:return super().__exit__(*exc)
  finally:self.close()

def connect():
 c=sqlite3.connect(DB,timeout=60,factory=Connection);c.row_factory=sqlite3.Row;return c
def normalize(smiles,sequence):
 from docking.inputs import clean_sequence
 seq=clean_sequence(sequence)
 mol=Chem.MolFromSmiles(smiles.strip())
 if mol is None or mol.GetNumHeavyAtoms()==0:raise ValueError('The compound text is not valid SMILES. Check brackets and atom names.')
 can=Chem.MolToSmiles(mol);key=hashlib.sha256((can+'|'+seq).encode()).hexdigest()
 neutral=Chem.MolToSmiles(rdMolStandardize.Uncharger().uncharge(mol))
 return key,can,seq,neutral
def init():
 DB.parent.mkdir(parents=True, exist_ok=True)
 c=connect();c.executescript('''PRAGMA journal_mode=WAL;
 CREATE TABLE IF NOT EXISTS pairs(id TEXT PRIMARY KEY,smiles TEXT,sequence TEXT,ligand_key TEXT);
 CREATE INDEX IF NOT EXISTS ligand ON pairs(ligand_key);
 CREATE TABLE IF NOT EXISTS measurements(dataset TEXT,row_id INTEGER,pair_id TEXT,original_smiles TEXT,original_sequence TEXT,original_score TEXT,status TEXT,PRIMARY KEY(dataset,row_id));
 CREATE INDEX IF NOT EXISTS pair_measurements ON measurements(pair_id,dataset);
 CREATE TABLE IF NOT EXISTS matches(pair_id TEXT,pdb_id TEXT,chain TEXT,query_start INTEGER,query_end INTEGER,identity REAL,query_coverage REAL,chain_coverage REAL,method TEXT,PRIMARY KEY(pair_id,pdb_id,chain));
 CREATE TABLE IF NOT EXISTS scanned(pdb_id TEXT PRIMARY KEY);
 CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,pair_id TEXT,status TEXT,result TEXT,error TEXT);
 CREATE TABLE IF NOT EXISTS job_methods(job_id TEXT PRIMARY KEY,method TEXT);
 CREATE TABLE IF NOT EXISTS scores(dataset TEXT,pair_id TEXT,checkpoint TEXT,result TEXT,PRIMARY KEY(dataset,pair_id,checkpoint));
 CREATE TABLE IF NOT EXISTS receptors(pdb_id TEXT,chain TEXT,sequence TEXT,PRIMARY KEY(pdb_id,chain));
 CREATE TABLE IF NOT EXISTS receptor_scanned(pdb_id TEXT PRIMARY KEY);
 CREATE TABLE IF NOT EXISTS receptor_index_state(key TEXT PRIMARY KEY,value TEXT);
 ''');c.commit();return c

def find_receptor(sequence):
 """Match the protein independently of the requested compound.

 The known reference ligand defines the docking box, never the new pose.
 Recheck the candidate chain with Biopython before returning it.
 """
 from Bio.PDB import PDBParser
 from preprocess import AA
 with connect() as c:
  candidates=[dict(r) for r in c.execute('SELECT * FROM receptors WHERE instr(?,sequence)>0 ORDER BY length(sequence) DESC,pdb_id,chain',(sequence,))]
 if not candidates:return None
 with zipfile.ZipFile(ROOT/'P-L.zip') as archive:
  for candidate in candidates:
   meta=json.loads((ROOT/f"processed/pdbbind/complexes/{candidate['pdb_id']}/metadata.json").read_text())
   structure=PDBParser(QUIET=True).get_structure(candidate['pdb_id'],io.StringIO(archive.read(meta['protein_archive_path']).decode()))
   chain=next(structure.get_models())[candidate['chain']]
   observed=''.join(AA.get(r.resname,'X') for r in chain if r.id[0]==' ' or r.resname in AA)
   if observed!=candidate['sequence'] or candidate['chain'] not in {a['chain'] for a in meta['pocket_atom_metadata']}:continue
   pos=sequence.find(observed)
   return dict(pdb_id=candidate['pdb_id'],chain=candidate['chain'],query_start=pos+1,query_end=pos+len(observed),identity=1.,query_coverage=len(observed)/len(sequence),chain_coverage=1.,method='Protein-only lookup: exact contacting chain/domain, independently verified with Biopython; reference ligand defines known docking pocket')
 return None

def find_receptor_homolog(sequence):
 """Find an experimental template only when its alignment and pocket are conservative."""
 from Bio.Align import PairwiseAligner,substitution_matrices
 from Bio.PDB import PDBParser
 from preprocess import AA
 sequence=sequence.upper()
 if not 100<=len(sequence)<=5000:return None
 matrix=substitution_matrices.load('BLOSUM62')
 alphabet=set(matrix.alphabet)
 alignment_sequence=''.join(aa if aa in alphabet else 'X' for aa in sequence)
 kmer_size=8
 kmers={sequence[i:i+kmer_size] for i in range(len(sequence)-kmer_size+1) if set(sequence[i:i+kmer_size])<=set('ACDEFGHIKLMNPQRSTVWY')}
 if not kmers:return None
 minimum_length=int(len(sequence)*.60)
 maximum_length=int(len(sequence)/.95)+1
 with connect() as c:
  candidates=[dict(r) for r in c.execute('SELECT * FROM receptors WHERE length(sequence) BETWEEN ? AND ?',(minimum_length,maximum_length))]
 aligned=[]
 aligner=PairwiseAligner()
 aligner.mode='local';aligner.substitution_matrix=matrix;aligner.open_gap_score=-10;aligner.extend_gap_score=-0.5
 for candidate in candidates:
  subject=candidate['sequence']
  if not any(kmer in subject for kmer in kmers):continue
  result=aligner.align(alignment_sequence,subject)[0]
  query_positions=[];subject_positions=[];coordinates=result.coordinates
  for i in range(coordinates.shape[1]-1):
   q0,q1=coordinates[0,i],coordinates[0,i+1];s0,s1=coordinates[1,i],coordinates[1,i+1]
   if q1>q0 and s1>s0:
    for offset in range(min(q1-q0,s1-s0)):
     query_positions.append(int(q0+offset));subject_positions.append(int(s0+offset))
  length=len(query_positions)
  if not length:continue
  identity=float(sum(sequence[q]==subject[s] and sequence[q] in 'ACDEFGHIKLMNPQRSTVWY' for q,s in zip(query_positions,subject_positions))/length)
  query_coverage=float(length/len(sequence));chain_coverage=float(length/len(subject))
  if identity<.90 or query_coverage<.60 or chain_coverage<.95:continue
  candidate.update(identity=identity,query_coverage=query_coverage,chain_coverage=chain_coverage,
                   query_start=int(min(query_positions)+1),query_end=int(max(query_positions)+1),
                   aligned_positions=dict(zip(subject_positions,query_positions)))
  aligned.append(candidate)
 if not aligned:return None
 resolutions={}
 with (ROOT/'processed/pdbbind/manifest.csv').open(newline='') as f:
  for row in csv.DictReader(f):
   try:resolutions[row['pdb_id']]=float(row['resolution'])
   except (KeyError,ValueError):continue
 aligned.sort(key=lambda c:(-c['identity'],-c['query_coverage'],-c['chain_coverage'],
                            resolutions.get(c['pdb_id'],float('inf')),c['pdb_id'],c['chain']))
 parser=PDBParser(QUIET=True)
 with zipfile.ZipFile(ROOT/'P-L.zip') as archive:
  for candidate in aligned:
   reference_folder=ROOT/'processed/pdbbind/complexes'/candidate['pdb_id']
   metadata_path=reference_folder/'metadata.json'
   if not metadata_path.is_file():continue
   metadata=json.loads(metadata_path.read_text())
   protein=archive.read(metadata['protein_archive_path']).decode()
   structure=parser.get_structure(candidate['pdb_id'],io.StringIO(protein))
   chain=next(structure.get_models())[candidate['chain']]
   residues=[r for r in chain if r.id[0]==' ' or r.resname in AA]
   observed=''.join(AA.get(r.resname,'X') for r in residues)
   if observed!=candidate['sequence']:continue
   residue_positions={(str(r.id[1]),r.id[2].strip()):i for i,r in enumerate(residues)}
   pocket_keys={(str(int(a['resid'])),(a.get('icode') or '').strip())
                for a in metadata['pocket_atom_metadata'] if a['chain']==candidate['chain']}
   pocket_subject_positions=[residue_positions.get(key) for key in pocket_keys]
   if not pocket_subject_positions or any(pos is None for pos in pocket_subject_positions):continue
   mapping=candidate.pop('aligned_positions')
   if any(pos not in mapping or sequence[mapping[pos]]!=observed[pos] for pos in pocket_subject_positions):continue
   candidate['pocket_identity']=1.0
   candidate['pocket_residues']=len(pocket_subject_positions)
   candidate['method']='PDBbind experimental homolog template; local BLOSUM62 alignment with >=90% identity, >=60% query coverage and >=95% chain coverage; all contacting pocket residues match the query sequence'
   candidate.pop('sequence',None)
   return candidate
 return None

def resolve_pair(pair_id):
 """Resolve manual queries using the same strict ligand+chain criteria."""
 from Bio.PDB import PDBParser
 from preprocess import AA
 with connect() as c:
  existing=c.execute('SELECT 1 FROM matches WHERE pair_id=? LIMIT 1',(pair_id,)).fetchone()
  if existing:return
  if c.execute('SELECT 1 FROM measurements WHERE pair_id=? LIMIT 1',(pair_id,)).fetchone() and c.execute('SELECT count(*) FROM scanned').fetchone()[0]>=19037:return
  pair=c.execute('SELECT * FROM pairs WHERE id=?',(pair_id,)).fetchone()
 if not pair:return
 lookup_path=ROOT/'processed/ligand_structure_lookup.json'
 if lookup_path.exists():lookup=json.loads(lookup_path.read_text())
 else:
  lookup=collections.defaultdict(list)
  with (ROOT/'processed/pdbbind/manifest.csv').open(newline='') as f:
   for r in csv.DictReader(f):
    if r['status']!='accepted':continue
    mol=Chem.MolFromSmiles(r['canonical_smiles']);lk=Chem.MolToSmiles(rdMolStandardize.Uncharger().uncharge(mol))
    lookup[lk].append([r['pdb_id'],r['protein_archive_path']])
  temporary=lookup_path.with_suffix('.tmp.json');temporary.write_text(json.dumps(lookup));temporary.replace(lookup_path)
 with zipfile.ZipFile(ROOT/'P-L.zip') as z,connect() as c:
  for pdb,path in lookup.get(pair['ligand_key'],[]):
   meta=json.loads((ROOT/f'processed/pdbbind/complexes/{pdb}/metadata.json').read_text());contact_chains={a['chain'] for a in meta['pocket_atom_metadata']}
   structure=PDBParser(QUIET=True).get_structure(pdb,io.StringIO(z.read(path).decode()))
   for chain in next(structure.get_models()):
    if chain.id not in contact_chains:continue
    seq=''.join(AA.get(r.resname,'X') for r in chain if r.id[0]==' ' or r.resname in AA)
    if len(seq)<50 or 'X' in seq:continue
    pos=pair['sequence'].find(seq)
    if pos>=0:c.execute('INSERT OR IGNORE INTO matches VALUES (?,?,?,?,?,?,?,?,?)',(pair_id,pdb,chain.id,pos+1,pos+len(seq),1.,len(seq)/len(pair['sequence']),1.,'RDKit stereo connectivity after charge normalization + exact Biopython chain/domain sequence; chain participates in pocket'))
  c.commit()
def build():
 RDLogger.DisableLog('rdApp.*');c=init();cache={}
 for dataset in ('davis','kiba','metz'):
  existing={r[0] for r in c.execute('SELECT row_id FROM measurements WHERE dataset=?',(dataset,))}
  with (ROOT/f'{dataset}.csv').open(newline='',encoding='utf-8-sig') as f:
   for rowid,r in enumerate(csv.DictReader(f),2):
    if rowid in existing:continue
    s,q,y=r['compound_iso_smiles'],r['target_sequence'],r['affinity']
    try:
     k,can,seq,lk=normalize(s,q);c.execute('INSERT OR IGNORE INTO pairs VALUES (?,?,?,?)',(k,can,seq,lk));status='valid'
    except Exception as e:k=None;status=str(e)
    c.execute('INSERT INTO measurements VALUES (?,?,?,?,?,?,?)',(dataset,rowid,k,s,q,y,status))
  c.commit();print(dataset,'rows indexed',flush=True)
 c.close()
def match():
 RDLogger.DisableLog('rdApp.*');c=init();bylig=collections.defaultdict(list)
 for r in c.execute('SELECT * FROM pairs'):bylig[r['ligand_key']].append(dict(r))
 done={r[0] for r in c.execute('SELECT pdb_id FROM scanned')};t=time.time()
 with zipfile.ZipFile(ROOT/'P-L.zip') as z, (ROOT/'processed/pdbbind/manifest.csv').open(newline='') as f:
  for i,r in enumerate(csv.DictReader(f)):
   pdb=r['pdb_id']
   if pdb in done:continue
   if r['status']=='accepted':
    mol=Chem.MolFromSmiles(r['canonical_smiles']);lk=Chem.MolToSmiles(rdMolStandardize.Uncharger().uncharge(mol))
    candidates=bylig.get(lk,[])
    if candidates:
     atoms,_,_=parse_protein(z.read(r['protein_archive_path']).decode());chains=collections.defaultdict(list);seen=set()
     meta=json.loads((ROOT/f'processed/pdbbind/complexes/{pdb}/metadata.json').read_text());pocket_chains={a['chain'] for a in meta['pocket_atom_metadata']}
     from preprocess import AA
     for a in atoms:
      rk=(a['chain'],a['resid'],a['icode'])
      if rk not in seen:chains[a['chain']].append(AA.get(a['resname'],'X'));seen.add(rk)
     for chain,aa in chains.items():
      if chain not in pocket_chains:continue
      seq=''.join(aa)
      if len(seq)<50 or 'X' in seq:continue
      for p in candidates:
       pos=p['sequence'].find(seq)
       if pos>=0:
        c.execute('INSERT OR IGNORE INTO matches VALUES (?,?,?,?,?,?,?,?,?)',(p['id'],pdb,chain,pos+1,pos+len(seq),1.,len(seq)/len(p['sequence']),1.,'Exact stereo connectivity after charge normalization; exact contiguous observed chain/domain'))
   c.execute('INSERT OR IGNORE INTO scanned VALUES (?)',(pdb,))
   if i%500==0:c.commit();print('scanned',i,'matches',c.execute('SELECT count(*) FROM matches').fetchone()[0],flush=True)
 c.commit();coverage={}
 for ds in ('davis','kiba','metz'):
  coverage[ds]=dict(source_rows=c.execute('SELECT count(*) FROM measurements WHERE dataset=?',(ds,)).fetchone()[0],valid_pairs=c.execute('SELECT count(DISTINCT pair_id) FROM measurements WHERE dataset=?',(ds,)).fetchone()[0],pose_matched_pairs=c.execute('SELECT count(DISTINCT m.pair_id) FROM measurements m JOIN matches x ON x.pair_id=m.pair_id WHERE dataset=?',(ds,)).fetchone()[0])
 (ROOT/'reports/pair_coverage.json').write_text(json.dumps(dict(datasets=coverage,matching_seconds=time.time()-t,policy='Conservative exact chain/domain matches only. Unmatched does not mean no complex exists.'),indent=2));print(coverage);c.close()
if __name__=='__main__':build();match()
