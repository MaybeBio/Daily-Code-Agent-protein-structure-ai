"""Local-only molecular viewer. Run from any directory; Ctrl+C stops it."""
import argparse, csv, json, mimetypes, re, zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT=Path(__file__).resolve().parents[1]

class Handler(BaseHTTPRequestHandler):
    def send(self,data,kind='application/json',status=200):
        if not isinstance(data,bytes): data=data.encode('utf-8')
        self.send_response(status); self.send_header('Content-Type',kind)
        self.send_header('Content-Length',str(len(data))); self.send_header('X-Content-Type-Options','nosniff')
        self.end_headers(); self.wfile.write(data)

    def do_GET(self):
        path=urlparse(self.path).path
        try:
            if path=='/api/complexes':
                manifest=ROOT/'processed/pdbbind/manifest.csv'
                with manifest.open(encoding='utf-8',newline='') as f:
                    rows=[{k:r.get(k,'') for k in ('pdb_id','status','affinity_raw','affinity_type','p_affinity','split','exclusion_reasons')} for r in csv.DictReader(f) if r['graph_path'] and r['status']!='excluded']
                self.send(json.dumps(rows)); return
            if path=='/api/summary':
                data={p.stem:json.loads(p.read_text()) for p in (ROOT/'reports').glob('*summary.json')}
                self.send(json.dumps(data)); return
            match=re.fullmatch(r'/api/complex/([A-Za-z0-9]{4})/(metadata.json|pocket.pdb|ligand.sdf|protein.pdb|graph.npz)',path)
            if match:
                pdb,file=match.groups(); folder=ROOT/'processed/pdbbind/complexes'/pdb
                if file=='protein.pdb':
                    meta=json.loads((folder/'metadata.json').read_text())
                    with zipfile.ZipFile(ROOT/'P-L.zip') as z: raw=z.read(meta['protein_archive_path'])
                else: raw=(folder/file).read_bytes()
                self.send(raw,'application/json' if file.endswith('.json') else 'application/octet-stream' if file.endswith('.npz') else 'text/plain'); return
            files={'/':'index.html','/app.js':'app.js','/style.css':'style.css','/vendor/3Dmol-min.js':'vendor/3Dmol-min.js'}
            if path in files:
                file=ROOT/'viewer'/files[path]
                self.send(file.read_bytes(),mimetypes.guess_type(str(file))[0] or 'application/octet-stream'); return
            self.send(json.dumps({'error':'File not found.'}),status=404)
        except FileNotFoundError:
            self.send(json.dumps({'error':'This processed file is missing. Complete preprocessing first.'}),status=404)
        except Exception as e:
            self.send(json.dumps({'error':f'Cannot read this structure: {type(e).__name__}: {e}'}),status=500)

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--port',type=int,default=8765); args=p.parse_args()
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    print(f'Protein Pocket Explorer: http://127.0.0.1:{args.port}',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
