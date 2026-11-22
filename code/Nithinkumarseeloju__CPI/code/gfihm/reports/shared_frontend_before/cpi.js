'use strict';
let requestVersion=0,motion=null,searchVersion=0,lastJob=null,pairOffset=0,displayedPoseSource='experimental';
async function api(url,body){let r=await fetch(url,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});let d=await r.json();if(!r.ok)throw Error(typeof d.detail==='string'?d.detail:JSON.stringify(d.detail));return d;}
function clearResult(){window.clearBioemu?.();lastJob=null;requestVersion++;loadToken++;stop();motion=null;metadata=null;ligand=null;pocket=null;protein=null;viewer.removeAllModels();viewer.removeAllShapes();viewer.removeAllSurfaces();viewer.removeAllLabels();viewer.render();currentPose=100;contactShapes=[];el('atoms').textContent='?';el('residues').textContent='?';el('quality').textContent='';el('assignedList').replaceChildren();el('assignedStatus').textContent='';el('position').disabled=true;el('reset').disabled=true;el('retry').hidden=true;el('jobError').hidden=true;el('contactList').replaceChildren();el('scoreResult').textContent='Ready for the new query.';el('poseSource').textContent='';el('measurement').textContent='';el('queryStatus').textContent='';el('play').disabled=true;el('replay').disabled=true;el('export').removeAttribute('href');el('download').removeAttribute('href');el('complexTitle').textContent='No pose selected';el('sceneTitle').textContent='Choose a compound and protein';el('affinity').textContent='';}
async function searchPairs(){const v=requestVersion,sv=++searchVersion;try{const found=await api(`/api/pairs?dataset=${el('dataset').value}&q=${encodeURIComponent(el('pairSearch').value)}&matched=${el('matchedOnly').checked}&offset=${pairOffset}`);if(v!==requestVersion||sv!==searchVersion)return;el('pairSelect').replaceChildren(new Option('Choose a pair',''));for(const p of found)el('pairSelect').add(new Option(`${p.pose_available?'[3D match] ':''}${p.id.slice(0,10)} | ${p.smiles.slice(0,90)} | ${p.sequence_preview}`,p.id));el('queryStatus').textContent=`${found.length} pairs shown (up to 50). Uncheck the filter to search all pairs.`;}catch(e){el('queryStatus').textContent=e.message;}}
el('searchPairs').onclick=()=>{pairOffset=0;searchPairs();};el('matchedOnly').onchange=()=>{pairOffset=0;searchPairs();};el('nextPairs').onclick=()=>{pairOffset+=50;searchPairs();};el('previousPairs').onclick=()=>{pairOffset=Math.max(0,pairOffset-50);searchPairs();};
el('dataset').onchange=()=>{pairOffset=0;clearResult();el('smiles').value='';el('sequence').value='';searchPairs();};
el('pairSelect').onchange=async()=>{clearResult();const v=requestVersion,id=el('pairSelect').value;if(!id)return;const p=await api(`/api/pairs/${id}?dataset=${el('dataset').value}`);if(v!==requestVersion)return;el('smiles').value=p.smiles;el('sequence').value=p.sequence;el('measurement').textContent='Source CSV measurement(s): '+p.measurements.map(x=>`${x.original_score} (row ${x.row_id})`).join(', ');};
el('smiles').oninput=clearResult;el('sequence').oninput=clearResult;el('method').onchange=clearResult;
pose=function(value){if(!ligand||!motion?.available)return;value=Number(value);if(!Number.isFinite(value))return;value=Math.max(0,Math.min(100,value));currentPose=value;
 const u=value/100*(motion.offsets.length-1),j=Math.min(motion.offsets.length-2,Math.floor(u)),w=u-j,off=motion.offsets[j].map((x,k)=>x*(1-w)+motion.offsets[j+1][k]*w);
 ligand.selectedAtoms({}).forEach((a,k)=>{a.x=original[k][0]+off[0];a.y=original[k][1]+off[1];a.z=original[k][2]+off[2];});ligand.setStyle({},ligandStyle);drawContacts();viewer.render();el('sceneTitle').textContent=value===100?(displayedPoseSource==='docked'?'Predicted docking pose':'Experimental final pose'):'Illustrative approach';};
function play(restart=false){if(!motion?.available)return;if(anim){stop();return;}if(restart||currentPose>=100){el('position').value=0;pose(0);viewer.zoomTo({model:[pocket,ligand]});viewer.render();}let previous=performance.now();el('play').textContent='Pause';const tick=now=>{const next=Math.min(100,currentPose+Math.max(0,Math.min(now-previous,100))/80*Number(el('speed').value));previous=now;el('position').value=next;pose(next);if(next<100)anim=requestAnimationFrame(tick);else stop();};anim=requestAnimationFrame(tick);}
el('play').onclick=()=>play();el('replay').onclick=()=>{stop();play(true);};
el('predict').onclick=async()=>{
 clearResult();const v=requestVersion,q={dataset:el('dataset').value,smiles:el('smiles').value,sequence:el('sequence').value,method:el('method').value};el('queryStatus').textContent='Calculating the score and checking for a verified structure…';
 api('/api/predict',q).then(d=>{if(v!==requestVersion)return;el('scoreResult').textContent=`${d.score_label}: ${d.score.toFixed(5)}`;if(d.reference_verification&&!d.reference_verification.numerically_reproduced)el('scoreResult').textContent+=` (weights verified; historical batch difference up to ${d.reference_verification.batch_max_error.toPrecision(2)})`;el('measurement').textContent='Source CSV measurements: '+(d.source_measurements.map(x=>x.original_score).join(', ')||'none for this query')+(d.truncated?` | Model uses the first ${d.sequence_limit} encoded tokens; this input has ${d.sequence_tokens}.`:'');}).catch(e=>{if(v===requestVersion)el('scoreResult').textContent=e.message;});
 try{const job=await api('/api/jobs',q);if(v!==requestVersion)return;lastJob=job.id;while(v===requestVersion){const d=await api(`/api/jobs/${job.id}`);if(v!==requestVersion)return;if(d.status==='completed'){
    const result=d.result;displayedPoseSource=result.artifact_base?'docked':'experimental';motion=result.motion;el('pdb').value=result.pdb_id;const loaded=await loadComplex({base:result.artifact_base});if(v!==requestVersion)return;if(!loaded)throw Error('The pose files could not be displayed.');
    el('poseSource').textContent=`${result.route}: ${result.pdb_id.toUpperCase()}, chain ${result.match.chain}; sequence positions ${result.match.query_start}–${result.match.query_end}; 100% identity over the displayed chain, ${(result.match.query_coverage*100).toFixed(1)}% of your full sequence. Protonation is normalized for ligand matching; stereochemistry is preserved.`;
    el('queryStatus').textContent=motion.reason;el('quality').textContent=result.artifact_base?'Computed docking result; confidence is not calibrated.':'Experimental coordinates of the matched chain/domain.';el('play').disabled=!motion.available;el('replay').disabled=!motion.available;el('export').href=result.artifact_base?`/api/export/pose/${job.id}`:`/api/export/${result.pdb_id}`;el('position').disabled=!motion.available;el('reset').disabled=false;showAssignedContacts();
    currentPose=100;el('position').value=100;drawContacts();viewer.render();el('sceneTitle').textContent=result.artifact_base?'Predicted docking pose':'Experimental final pose';
    [...el('contactList').children].forEach(row=>{row.style.cursor='pointer';row.onclick=()=>{const c=metadata.contacts.find(c=>c.residue===row.firstChild.textContent),a=pocket.selectedAtoms({})[c.pocket_atom];pocket.setStyle({chain:a.chain,resi:a.resi},{sphere:{radius:.3,color:'#ff99ef'}},true);viewer.render();};});return;
   }if(d.status==='unsupported'||d.status==='failed'){el('queryStatus').textContent=d.result?.message||'The structure job failed. Open the technical error for details, then retry when the problem is fixed.';el('retry').hidden=false;el('jobError').hidden=d.status==='unsupported';el('jobError').href=`/api/jobs/${job.id}/error`;return;}
   el('queryStatus').textContent=`3D job ${d.status}. The score is calculated separately.`;await new Promise(r=>setTimeout(r,700));}
 }catch(e){if(v===requestVersion)el('queryStatus').textContent=e.message;}
};
(async()=>{
 viewer=$3Dmol.createViewer(el('molecule'),{backgroundColor:'#101927',antialias:true});viewer.setProjection('orthographic');
 rows=await api('/api/complexes');el('pdbInventoryStatus').textContent=rows.length.toLocaleString()+' processed complexes available.';for(const r of rows)el('pdbInventory').append(new Option(r.affinity_raw,r.pdb_id));refreshCoverage();el('full').checked=true;clearResult();status('Select a dataset pair to show its own matched structure.');
 const params=new URLSearchParams(location.search),dataset=params.get('dataset'),pair=params.get('pair');
 if(['davis','kiba','metz'].includes(dataset))el('dataset').value=dataset;
 if(pair&&/^[a-f0-9]{64}$/.test(pair))el('pairSearch').value=pair;
 await searchPairs();window.addEventListener('resize',()=>viewer.resize());
 if(pair&&/^[a-f0-9]{64}$/.test(pair)){
  const detail=await api(`/api/pairs/${pair}?dataset=${el('dataset').value}`);
  if(![...el('pairSelect').options].some(o=>o.value===pair))el('pairSelect').add(new Option('Saved manual query '+pair.slice(0,10),pair));
  el('pairSelect').value=pair;el('smiles').value=detail.smiles;el('sequence').value=detail.sequence;
  const method=params.get('method');if(['experimental','dock','redock'].includes(method))el('method').value=method;
  await el('predict').onclick();
 }
})().catch(e=>status(e.message));

el('retry').onclick=async()=>{if(!lastJob)return;try{await api(`/api/jobs/${lastJob}/retry`,{});el('predict').click();}catch(e){el('queryStatus').textContent=e.message;}};
function showAssignedContacts(){
 el('assignedList').replaceChildren();const a=metadata?.interaction_analysis;
 el('assignedStatus').textContent=a?'PLIP calculated contacts; dependent on protonation.':'Assigned contact types unavailable for this structure. Nearby contacts above are distance measurements only.';
 for(const c of a?.contacts||[]){const row=document.createElement('div');row.className='contact';row.textContent=`${c.residue} | ${c.type} | ${c.distance.toFixed(2)} Angstrom`;row.onclick=()=>{pocket.setStyle({chain:c.chain,resi:Number(c.residue_number)},{sphere:{radius:.3,color:'#ff99ef'}},true);viewer.render();};el('assignedList').append(row);}
}
const drawGeometricContacts=drawContacts;
drawContacts=function(){drawGeometricContacts();if(currentPose!==100||!el('contacts').checked)return;
 for(const c of metadata?.interaction_analysis?.contacts||[]){const p=c.protein_position,l=c.ligand_position;contactShapes.push(viewer.addLine({start:{x:p[0],y:p[1],z:p[2]},end:{x:l[0],y:l[1],z:l[2]},color:c.type==='hydrogen bond'?'#a3e99b':c.type==='salt bridge'?'#e9a4f9':'#f4b45f',dashed:true,linewidth:2}));}
};

const baseStyleProtein=styleProtein;
styleProtein=function(){baseStyleProtein();if(!protein||!ligand)return;
 const nearby=protein.selectedAtoms({hetflag:true}).filter(a=>!['H','D'].includes(a.elem)&&original.some(p=>Math.hypot(a.x-p[0],a.y-p[1],a.z-p[2])<=6)).map(a=>a.serial);
 if(el('context').checked&&nearby.length)protein.setStyle({serial:nearby},{sphere:{radius:.25,color:'#b5c5dd'}},true);
 viewer.render();
};
el('context').onchange=styleProtein;
const playback=document.createElement('div');playback.className='playback';
const speedLabel=el('speed').parentElement,rangeLabel=el('position').previousElementSibling,notice=el('position').nextElementSibling;
playback.append(speedLabel,el('play'),el('replay'),rangeLabel,el('position'),notice);
document.querySelector('.scene').insertBefore(playback,document.querySelector('.legend'));
document.querySelector('.badge').textContent='LOCAL CPI PROJECT';

let coverageRequest=0;
async function refreshCoverage(){
 const token=++coverageRequest;el('coverageStatus').textContent='Reading current results...';
 try{
  const data=await api('/api/results');if(token!==coverageRequest)return;
  const counts=data.pdbbind.status_counts;
  el('pdbCounts').textContent=`PDBbind: ${data.pdbbind.processed.toLocaleString()} complexes checked; ${counts.accepted.toLocaleString()} accepted for the prepared training pool; ${counts.visualization_only.toLocaleString()} view-only; ${counts.excluded.toLocaleString()} excluded.`;
  const body=el('coverageTable').querySelector('tbody');body.replaceChildren();
  for(const [dataset,d] of Object.entries(data.datasets)){
   const row=document.createElement('tr');
   for(const value of [dataset==='kiba'?'KIBA':dataset[0].toUpperCase()+dataset.slice(1),d.source_rows,d.valid_pairs,d.valid_pairs-d.score_not_precomputed,d.pose_ready_pairs,d.animation_ready_pairs]){
    const cell=document.createElement('td');cell.textContent=typeof value==='number'?value.toLocaleString():value;cell.style.padding='8px 12px 8px 0';row.append(cell);
   }
   body.append(row);
  }
  el('coverageStatus').textContent=`Counts read from the current database. Protein-only docking index: ${data.receptor_structures_indexed.toLocaleString()} of ${counts.accepted.toLocaleString()} eligible structures. Uncomputed scores and missing poses are not counted as ready.`;
 }catch(e){if(token===coverageRequest)el('coverageStatus').textContent='Could not read current counts: '+e.message;}
}
el('refreshCoverage').onclick=refreshCoverage;
el('preprocessingResults').ontoggle=()=>{if(el('preprocessingResults').open)refreshCoverage();};

el('browseStructure').onclick=async()=>{
 clearResult();const version=requestVersion;const id=el('browsePdb').value.trim().toLowerCase();
 el('smiles').value='';el('sequence').value='';el('pairSelect').value='';
 el('scoreResult').textContent='PDBbind structure viewer: no dataset model score requested.';
 try{
  if(!rows.some(r=>r.pdb_id===id))throw Error('This PDB ID is unavailable. Choose an ID from the list. The excluded structures have no valid output graph.');
  displayedPoseSource='experimental';el('pdb').value=id;motion=null;
  const loaded=await loadComplex();if(version!==requestVersion)return;if(!loaded)throw Error('The structure files could not be displayed.');
  el('poseSource').textContent=`Experimental PDBbind complex ${id.toUpperCase()}. Not linked to a CSV query in this view.`;
  el('sceneTitle').textContent='Experimental final pose';currentPose=100;el('position').value=100;
  el('export').href=`/api/export/${id}`;el('reset').disabled=false;showAssignedContacts();drawContacts();
  for(const row of el('contactList').children){row.style.cursor='pointer';row.onclick=()=>{
   const c=metadata.contacts.find(c=>c.residue===row.firstChild.textContent),atom=pocket.selectedAtoms({})[c.pocket_atom];
   pocket.setStyle({chain:atom.chain,resi:atom.resi},{sphere:{radius:.3,color:'#ff99ef'}},true);viewer.render();
  };}
  while(version===requestVersion){
   const result=await api(`/api/pdbbind/${id}/motion`);if(version!==requestVersion)return;
   if(result.status==='completed'){
    motion=result.motion;el('play').disabled=!motion.available;el('replay').disabled=!motion.available;el('position').disabled=!motion.available;
    el('queryStatus').textContent=motion.reason;return;
   }
   if(result.status==='failed'){el('queryStatus').textContent=result.message;return;}
   el('queryStatus').textContent='Final pose ready. Checking an illustrative approach while you inspect the pocket...';
   await new Promise(resolve=>setTimeout(resolve,700));
  }
 }catch(e){if(version===requestVersion)el('queryStatus').textContent=e.message;}
};
