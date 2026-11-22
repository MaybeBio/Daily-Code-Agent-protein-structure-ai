"""Exercise BioEmu transport and browser with labelled synthetic fixtures only.

No BioEmu inference is claimed. Temporary imported results never touch production storage.
"""
import copy
import io
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
from types import SimpleNamespace
from unittest.mock import patch
import sys

import uvicorn
from playwright.sync_api import sync_playwright
from rdkit import Chem
import cpi_bioemu2 as bio
import bioemu2_worker
from cpi_app import app


def fixture(request):
    atoms, bonds = [], []
    for mol, role, chain in [(Chem.MolFromSequence(request['sequence']), 'protein', 'A'),
                            (Chem.MolFromSmiles(request['smiles']), 'ligand', 'L')]:
        offset = len(atoms)
        for atom in mol.GetAtoms():
            info = atom.GetPDBResidueInfo()
            atoms.append(dict(elem=atom.GetSymbol(), atom=info.GetName().strip() if info else atom.GetSymbol()+str(atom.GetIdx()+1),
                              resn=info.GetResidueName().strip() if info else 'LIG',
                              resi=info.GetResidueNumber() if info else len(request['sequence'])+1,
                              chain=chain, role=role))
        bonds.extend([[b.GetBeginAtomIdx()+offset, b.GetEndAtomIdx()+offset] for b in mol.GetBonds()])
    frames = [[[float(i), float(j if a['role']=='ligand' else j/3), 0.0] for i,a in enumerate(atoms)] for j in range(3)]
    return dict(schema='cpi-bioemu2-result-v1',pair_id=request['pair_id'],smiles=request['smiles'],sequence=request['sequence'],
                source='BioEmu-2',kind='trajectory',units='angstrom',time_units='ns',times_ns=[0,1,2],atoms=atoms,bonds=bonds,frames=frames,
                physicality=dict(checked=True,passed=[True,False,True],reasons=['','synthetic test failure','']),
                settings=dict(test_fixture=True),environment=dict(test_fixture='Synthetic transport test; not model inference'))


def archive(data, request, extra=None):
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('result.json',json.dumps(data));z.writestr('request.json',json.dumps(request))
        for name in ('system.yaml','topology.cif','samples.xtc','physicality.json'):
            z.writestr(name,'SYNTHETIC TRANSPORT TEST ONLY')
        if extra:z.writestr(extra,'not allowed')
    return stream.getvalue()


def verify_worker(tmp, request, data):
    """Contract checks with explicit fake GPU/model APIs, never inference."""
    import numpy as np
    chains=[object(),object()];residues={};atoms=[]
    for i,a in enumerate(data['atoms']):
        key=(a['chain'],a['resi'])
        residue=residues.setdefault(key,SimpleNamespace(index=a['resi']-1,name=a['resn'],chain=chains[0 if a['chain']=='A' else 1]))
        atoms.append(SimpleNamespace(index=i,name=a['atom'],element=SimpleNamespace(symbol=a['elem']),residue=residue))
    topology=SimpleNamespace(atoms=atoms,chains=chains,bonds=[(atoms[a],atoms[b]) for a,b in data['bonds']])
    class Trajectory:
        def __init__(self,n):
            self.xyz=np.asarray(data['frames'][:n])/10;self.time=np.asarray(data['times_ns'][:n])*1000
            self.topology=topology
    calls=[]
    def load_system(path):
        system=json.loads(path.read_text(encoding='utf-8'))
        assert system['entities'][0]['sequence']==request['sequence']
        assert system['entities'][1]['smiles']==request['smiles']
        return system,None
    def predict(system,**kwargs):
        assert kwargs['num_samples']==1 and kwargs['batch_size']==1
        calls.append('predict');kwargs['output_dir'].mkdir();return Trajectory(1)
    def simulate(system,**kwargs):
        assert kwargs['num_trajectory_steps']==2 and kwargs['lag_time_ns']==1
        calls.append('simulate');return [Trajectory(3)]
    def checks(trajectory,**kwargs):
        return SimpleNamespace(checked=True,passed=[True]*len(trajectory.xyz),reasons=['']*len(trajectory.xyz))
    def save(trajectory,path,**kwargs):
        path.mkdir()
        for name in ('topology.cif','samples.xtc','physicality.json'):(path/name).write_text('TEST ONLY')
    fake=SimpleNamespace(load_system_and_contacts=load_system,load_model=lambda:object(),predict_structure=predict,
                         simulate_trajectory=simulate,check_physicality=checks,save_frames=save)
    gpu=SimpleNamespace(__version__='TEST ONLY',cuda=SimpleNamespace(is_available=lambda:True,get_device_name=lambda n:'FAKE GPU FOR CONTRACT TEST'))
    request_path=Path(tmp)/'request.json';request_path.write_text(json.dumps(request),encoding='utf-8')
    for steps in (0,2):
        output=Path(tmp)/f'worker-{steps}'
        with patch.dict(sys.modules,{'bioemu2':fake,'torch':gpu}),patch.object(bioemu2_worker.platform,'system',return_value='Linux'),patch.object(bioemu2_worker.importlib.metadata,'version',return_value='TEST ONLY'),patch.object(sys,'argv',['worker','--request',str(request_path),'--out',str(output),'--steps',str(steps)]):
            bioemu2_worker.main()
        exported=json.loads((output/'result.json').read_text(encoding='utf-8'))
        np.testing.assert_allclose(exported['frames'],data['frames'][:steps+1],atol=0.000005,rtol=0)
        assert exported['times_ns']==data['times_ns'][:steps+1]
        assert exported['kind']==('pose' if steps==0 else 'trajectory')
        bio.validate_result(exported,request['pair_id'])
        assert (output/'cpi_bioemu2_result.zip').is_file()
    assert calls==['predict','predict','simulate']


def run():
    checks=[]
    original_store=bio.STORE
    with tempfile.TemporaryDirectory(prefix='bioemu-test-',dir=bio.ROOT/'reports') as tmp:
        bio.STORE=Path(tmp)/'storage'
        listener=socket.socket();listener.bind(('127.0.0.1',0))
        port=listener.getsockname()[1]
        server=uvicorn.Server(uvicorn.Config(app,log_level='error',lifespan='off'))
        thread=threading.Thread(target=server.run,kwargs={'sockets':[listener]},daemon=True);thread.start()
        base=f'http://127.0.0.1:{port}'
        def call(path, value=None, raw=None):
            body=json.dumps(value).encode() if value is not None else raw
            req=urllib.request.Request(base+path,data=body,headers={'Content-Type':'application/json' if value is not None else 'application/zip'})
            try:
                with urllib.request.urlopen(req,timeout=30) as r:return r.status,r.read()
            except urllib.error.HTTPError as e:return e.code,e.read()
        try:
            for _ in range(100):
                if server.started:break
                time.sleep(.05)
            assert server.started
            q=dict(smiles='CCO',sequence='AC')
            status,body=call('/api/bioemu2/request',q);assert status==200,body
            with zipfile.ZipFile(io.BytesIO(body)) as z:
                request=json.loads(z.read('request.json'))
                system=json.loads(z.read('pair.yaml'))
                assert system['entities'][0]['sequence']=='AC' and system['entities'][1]['smiles']=='CCO'
                compile(z.read('bioemu2_worker.py'),'exported_worker','exec')
                assert 'Linux' in z.read('README.md').decode()
            checks.append('Export contains exact pair, runnable worker syntax, and GPU setup guide')
            pair=request['pair_id'];data=fixture(request)
            verify_worker(tmp,request,data)
            checks.append('Worker contract with mocked GPU APIs: pose then successive rollout, Angstrom/time conversion, complete output ZIP; no real inference')
            for smiles in ('c1ccccc1','Cn1c(=O)c2c(ncn2C)n(C)c1=O','C[C@H](O)C(=O)O.[Na+]'):
                other=bio.pair_input(bio.PairInput(smiles=smiles,sequence='AC'))
                bio.validate_result(fixture(other),other['pair_id'])
            checks.append('Aromatic, chiral and disconnected compounds retain supported connectivity')
            route='/api/bioemu2/import/'+pair
            status,body=call(route,raw=archive(data,request));assert status==200,body
            result_id=json.loads(body)['result_id']
            status,body=call(route,raw=archive(data,request));assert status==200,body
            assert json.loads(body)['result_id']==result_id
            status,body=call('/api/bioemu2/results',q);assert json.loads(body)['results']==[result_id]
            status,body=call(f'/api/bioemu2/result/{pair}/{result_id}/result.json')
            assert json.loads(body)['frames']==data['frames']
            checks.append('Import, repeat import, saved-result lookup, and exact coordinate roundtrip')
            bad_cases=[]
            wrong=copy.deepcopy(data);wrong['pair_id']='0'*64;bad_cases.append(wrong)
            wrong=copy.deepcopy(data);wrong['frames'][0][0][0]=float('nan');bad_cases.append(wrong)
            wrong=copy.deepcopy(data);wrong['times_ns']=[0,2,1];bad_cases.append(wrong)
            wrong=copy.deepcopy(data);wrong['atoms'][0]['resn']='GLY';bad_cases.append(wrong)
            wrong=copy.deepcopy(data);wrong['bonds']=[b for b in wrong['bonds'] if b[0] < len(wrong['atoms'])-3];bad_cases.append(wrong)
            wrong=copy.deepcopy(data);wrong['physicality']['passed']=[True];bad_cases.append(wrong)
            wrong=copy.deepcopy(data);wrong['kind']='ensemble';bad_cases.append(wrong)
            for wrong in bad_cases:
                status,body=call(route,raw=archive(wrong,request));assert status==400,(status,body)
            status,body=call(route,raw=archive(data,request,'../escape.txt'));assert status==400
            status,body=call(route,raw=b'broken zip');assert status==400
            checks.append('Rejected wrong pair, NaN, unordered samples, changed protein, missing ligand bond, missing checks, unsafe ZIP, and damaged ZIP')
            with sync_playwright() as p:
                browser=p.chromium.launch(executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe',headless=True,args=['--enable-unsafe-swiftshader'])
                page=browser.new_page(viewport={'width':1440,'height':1000});errors=[]
                page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(base,wait_until='networkidle')
                page.fill('#smiles','CCO');page.fill('#sequence','AC')
                page.locator('#bioemuPanel summary').click();page.click('#bioemuLoad')
                page.wait_for_function("document.getElementById('bioemuFrameInfo').textContent.includes('Frame 1 of 3')")
                assert page.locator('#bioemuMolecule canvas').count()>0
                page.click('#bioemuPlay')
                page.wait_for_function("document.getElementById('bioemuFrameInfo').textContent.includes('Frame 2 of 3')")
                page.click('#bioemuPlay');assert 'FAILED' in page.locator('#bioemuGeometry').inner_text()
                page.locator('#bioemuFrame').evaluate("e=>{e.value='2';e.dispatchEvent(new Event('input'));}")
                assert '2.000 ns' in page.locator('#bioemuFrameInfo').inner_text()
                page.reload(wait_until='networkidle');page.fill('#smiles','CCO');page.fill('#sequence','AC')
                page.locator('#bioemuPanel').evaluate('e=>e.open=true');page.click('#bioemuLoad')
                page.wait_for_function("!document.getElementById('bioemuScene').hidden")
                page.fill('#sequence','ACA');assert page.locator('#bioemuScene').is_hidden()
                page.click('#bioemuLoad');page.wait_for_function("document.getElementById('bioemuStatus').textContent.includes('No BioEmu result')")
                page.fill('#sequence','AC')
                page.set_input_files('#bioemuImport',{'name':'wrong.zip','mimeType':'application/zip','buffer':archive(bad_cases[0],request)})
                page.wait_for_function("document.getElementById('bioemuStatus').textContent.includes('different protein')")
                assert page.locator('#bioemuScene').is_hidden()
                page.set_input_files('#bioemuImport',{'name':'result.zip','mimeType':'application/zip','buffer':archive(data,request)})
                page.wait_for_function("!document.getElementById('bioemuScene').hidden")
                page.set_viewport_size({'width':390,'height':844})
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+2')
                assert not errors,errors
                browser.close()
            checks.append('Browser: 3D canvas, play/pause/scrub, failed-geometry label, reload, stale-input clearing, wrong-pair rejection, import, mobile layout; no page errors')
        finally:
            server.should_exit=True;thread.join(timeout=10);listener.close();bio.STORE=original_store
    report=dict(status='PASS',checks=checks,gpu_inference='NOT RUN: remote Linux GPU not configured',
                fixture='Synthetic fixtures were used only in temporary test storage; no model predictions fabricated or published')
    (bio.ROOT/'reports/bioemu2_validation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':run()
