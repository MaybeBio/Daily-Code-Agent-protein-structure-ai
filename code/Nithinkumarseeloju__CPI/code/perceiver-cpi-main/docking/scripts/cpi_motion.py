"""Rigid illustrative paths, with conservative continuous collision checks."""
import json,time,zipfile
import numpy as np
from scipy.spatial import cKDTree
from preprocess import ROOT

def directions(n):
 i=np.arange(n);z=1-2*(i+.5)/n;t=i*np.pi*(3-np.sqrt(5))
 return np.column_stack([np.sqrt(1-z*z)*np.cos(t),np.sqrt(1-z*z)*np.sin(t),z])

def heavy_coordinates(raw):
 xyz=[]
 for line in raw.splitlines():
  if line.startswith('ENDMDL'):break
  if line[:6].strip() not in ('ATOM','HETATM'):continue
  element=line[76:78].strip() or line[12:16].strip().lstrip('0123456789')[:1]
  if element in ('H','D'):continue
  try:xyz.append([float(line[30:38]),float(line[38:46]),float(line[46:54])])
  except ValueError:pass
 return np.asarray(xyz)

def plan(lig,xyz):
 tree=cKDTree(xyz);threshold=1.4;step=.45
 def segment(a,b):
  distance=np.linalg.norm(b-a);n=max(2,int(np.ceil(distance/step))+1)
  points=np.linspace(a,b,n);d=tree.query((lig[None,:,:]+points[:,None,:]).reshape(-1,3))[0]
  # Distance to a fixed obstacle is 1-Lipschitz. Subtracting half the sample
  # spacing provides a lower bound for every point between sampled frames.
  lower=float(d.min())-distance/(n-1)/2
  return lower>=threshold,lower
 center=lig.mean(0);length=float(np.max(np.linalg.norm(xyz-center,axis=1))+np.max(np.linalg.norm(lig-center,axis=1))+8)
 zero=np.zeros(3);found=None;ds=directions(96)
 # Prefer an outward direction near the pocket centroid first.
 near=xyz[tree.query_ball_point(center,12)]
 if len(near):
  outward=center-near.mean(0)
  if np.linalg.norm(outward)>.01:ds=np.vstack([outward/np.linalg.norm(outward),ds])
 for v in ds:
  outside=v*length;okay,clearance=segment(outside,zero)
  if okay:found=([outside,zero],clearance,'straight');break
 if not found:
  for v in ds[:48]:
   waypoint=v*5.;okay,end_clearance=segment(waypoint,zero)
   if not okay:continue
   for w in directions(32):
    outside=w*length;okay,clearance=segment(outside,waypoint)
    if okay:found=([outside,waypoint,zero],min(clearance,end_clearance),'two-segment');break
   if found:break
 result=dict(available=bool(found),distance_threshold=threshold,method='Rigid translation; 96 sphere directions plus up to 48 x 32 bent candidates; <=0.45 A checks with Lipschitz clearance bound for all intermediate translations. Includes all protein-file heavy atoms, waters and cofactors. This is geometric illustration, not a physical path.')
 if found:
  points,clearance,kind=found;offsets=[]
  for a,b in zip(points,points[1:]):offsets.extend(np.linspace(a,b,max(2,int(np.ceil(np.linalg.norm(b-a)/step))+1))[:-1].tolist())
  offsets.append([0.,0.,0.]);result.update(offsets=offsets,path_kind=kind,minimum_continuous_distance_lower_bound=clearance,reason='The final pose is shown below. The approach is animated for explanation.')
 else:result['reason']='You can view the final pose. We could not draw a checked approach through this pocket without crossing the protein.'
 return result

def approach(pdb):
 folder=ROOT/'processed/pdbbind/complexes'/pdb;cache=folder/'approach_v2.json'
 if cache.exists():return json.loads(cache.read_text())
 started=time.time();meta=json.loads((folder/'metadata.json').read_text())
 with zipfile.ZipFile(ROOT/'P-L.zip') as z:raw=z.read(meta['protein_archive_path']).decode()
 xyz=heavy_coordinates(raw)
 with np.load(folder/'graph.npz') as g:lig=g['positions'][:int(g['ligand_atom_count'])].astype(float)
 result=plan(lig,np.asarray(xyz));result.update(seconds=time.time()-started,version=2)
 cache.write_text(json.dumps(result));return result
