"""Local docking service. Run from the main project with the provided launcher."""
import json
import os
import re
import tempfile
import threading
import traceback
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from docking_stages import start_trace, Stage
from cpi_data import ROOT, connect, init, normalize
from cpi_sequence_docking import predict_and_dock
from cpi_contacts import analyze
from cpi_job_errors import classify_failure, failure_detail
from cpi_motion import plan, heavy_coordinates
from rdkit import Chem
import numpy as np

app = FastAPI(title="Local CPI docking")
app.add_middleware(CORSMiddleware, allow_origins=[os.getenv("PERCEIVER_APP_URL","http://127.0.0.1:8000"), os.getenv("PERCEIVER_APP_URL","http://127.0.0.1:8000").replace("127.0.0.1","localhost")],allow_methods=["GET","POST"],allow_headers=["Content-Type"])
pool = ThreadPoolExecutor(max_workers=2)
guard = threading.Lock()
with init() as db:
    interrupted = dict(pose_available=False, stage="interrupted",
                       detail="Docking service restarted during this job. Submit the pair again.")
    db.execute("UPDATE jobs SET status='failed', result=?, error=? WHERE status IN ('queued','running')",
               (json.dumps(interrupted), interrupted["detail"]))

class Query(BaseModel):
    dataset: str = "davis"
    smiles: str
    sequence: str
    method: str = "dock"
    no_cache: bool = False

def execute(jid, smiles, sequence, no_cache):
    with connect() as db:
        db.execute("UPDATE jobs SET status='running' WHERE id=?", (jid,))
    parent = ROOT / "processed/predicted" / jid
    timings = start_trace()
    try:
        parent.mkdir(parents=True, exist_ok=True)
        folder = Path(tempfile.mkdtemp(prefix="run-", dir=parent))
        docking = predict_and_dock(smiles, sequence, folder, force_rebuild=no_cache)
        result = dict(pose_available=True, docking=docking, route=docking["protein_source"],
                      directory=folder.name, artifact_base=f"/api/jobs/{jid}/files")
        warnings = []
        try:
            result["contacts"] = analyze(folder)["contacts"]
        except Exception as exc:
            warnings.append(dict(stage="contacts", detail=str(exc), traceback=traceback.format_exc()))
            result["contacts"] = None
        try:
            with Stage("motion"):
                ligand = Chem.SDMolSupplier(str(folder / "ligand.sdf"))[0]
                result["motion"] = plan(np.asarray(ligand.GetConformer().GetPositions()),
                                        heavy_coordinates((folder / "protein.pdb").read_text()))
        except Exception as exc:
            warnings.append(dict(stage="motion", detail=str(exc), traceback=traceback.format_exc()))
            result["motion"] = dict(available=False)
        result["warnings"] = warnings
        state, error = "completed", None
    except Exception as exc:
        error = traceback.format_exc()
        stage = getattr(exc, "docking_stage", None) or classify_failure(error)
        result = dict(pose_available=False,stage=stage,detail=failure_detail(stage)+" "+error.strip().splitlines()[-1])
        state = "failed"
    result["timings"] = timings
    with connect() as db:
        db.execute("UPDATE jobs SET status=?,result=?,error=? WHERE id=?",(state,json.dumps(result),error,jid))

@app.get("/api/complexes")
def health():
    return []

@app.post("/api/jobs")
def submit(q: Query):
    try:
        jid,smiles,sequence,key=normalize(q.smiles,q.sequence)
    except ValueError as error:
        raise HTTPException(400,str(error))
    with guard, connect() as db:
        previous=db.execute("SELECT status FROM jobs WHERE id=?",(jid,)).fetchone()
        if not previous or previous["status"]=="failed" or (q.no_cache and previous["status"] not in ("queued","running")):
            db.execute("INSERT OR REPLACE INTO jobs VALUES (?,?,?,?,?)",(jid,jid,"queued",None,None))
            db.commit()
            pool.submit(execute,jid,smiles,sequence,q.no_cache)
    return {"id":jid}

@app.get("/api/jobs/{jid}")
def status(jid: str, request: Request):
    with connect() as db:
        row=db.execute("SELECT * FROM jobs WHERE id=?",(jid,)).fetchone()
    if row is None: raise HTTPException(404,"Job not found.")
    result=dict(row)
    result["result"]=json.loads(result["result"]) if result["result"] else None
    if result["result"] and result["result"].get("artifact_base"):
        result["result"]["artifact_base"]=str(request.base_url).rstrip("/")+result["result"]["artifact_base"]
    if result["status"]=="failed":
        result.update(stage=result["result"]["stage"],detail=result["result"]["detail"])
    return result

@app.get("/api/jobs/{jid}/files/{name}")
def artifact(jid: str, name: str):
    if not re.fullmatch("[0-9a-f]{64}",jid) or name not in ("protein.pdb","pocket.pdb","ligand.sdf","metadata.json","graph.npz"):
        raise HTTPException(404)
    with connect() as db:
        row = db.execute("SELECT status, result FROM jobs WHERE id=?", (jid,)).fetchone()
    if not row or row["status"] != "completed":
        raise HTTPException(404, "Pose files are available after a successful docking run.")
    record = json.loads(row["result"])
    folder = ROOT / "processed/predicted" / jid / record.get("directory", "")
    if not (folder/name).is_file(): raise HTTPException(404)
    if name=="metadata.json":
        result=json.loads((folder/name).read_text())
        analysis = folder / "interaction_analysis.json"
        result["interaction_analysis"] = json.loads(analysis.read_text()) if analysis.is_file() else None
        return result
    return FileResponse(folder/name, filename=name)
