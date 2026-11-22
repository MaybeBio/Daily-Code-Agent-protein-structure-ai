"""Private-LAN docking API used by the affinity frontend."""
import os
from typing import Literal
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from cpi_app import Query, complexes, job, job_status, pose_artifact

app = FastAPI(title="Perceiver CPI docking")
origins = os.environ.get("CPI_FRONTEND_ORIGINS", "http://127.0.0.1:8000,http://localhost:8000").split(",")
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET","POST"], allow_headers=["Content-Type"])

class DockQuery(Query):
    method: Literal["dock"] = "dock"

@app.post("/api/jobs")
def submit(query: DockQuery):
    return job(query)

@app.get("/api/jobs/{jid}")
def status(jid: str, request: Request):
    data = job_status(jid)
    result = data.get("result") or {}
    if result.get("artifact_base"):
        base = os.environ.get("CPI_DOCKING_PUBLIC_URL", str(request.base_url)).rstrip("/")
        result["artifact_base"] = f"{base}/api/jobs/{jid}/files"
    return data

app.get("/api/jobs/{jid}/files/{file}")(pose_artifact)
app.get("/api/complexes")(complexes)

