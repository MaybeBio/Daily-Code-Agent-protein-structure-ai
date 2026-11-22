"""Exercise the public score, job and artifact endpoints on the running local app."""
import argparse
import json
import math
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from rdkit import Chem
from try_one import ROOT, SMILES

FKBP = "MGVQVETISPGDGRTFPKRGQTCVVHYTGMLEDGKKFDSSRDRNKPFKFVLGKQEVIRGWEEGVAQMSVGQRAKLTISPDYAYGATGHPGIIPPNATLIFDVELLKLE"
UBIQUITIN = "MQIFVKTLTGKTITLEVEPSDTIENVKAKIQDKEGIPPDQQRLIFAGKQLEDGRTLSDYNIQKESTLHLVLRLRGG"


def request(url, data=None, raw=False):
    req = Request(url, data=json.dumps(data).encode() if data else None, headers={"Content-Type":"application/json"})
    with urlopen(req, timeout=180) as response:
        return response.read() if raw else json.load(response)


def check(base, name, smiles, sequence, invalid, rebuild):
    start = time.perf_counter()
    row = dict(name=name, smiles=smiles, valid=not invalid, passed=False)
    payload = dict(dataset="davis", smiles=smiles, sequence=sequence, no_cache=rebuild)
    if invalid:
        reasons = []
        for endpoint in ("predict", "jobs"):
            try:
                request(f"{base}/api/{endpoint}", payload)
            except HTTPError as error:
                reasons.append(f"{endpoint} {error.code} {error.read().decode()}")
                if error.code not in (400, 422):
                    raise
        row.update(passed=len(reasons)==2, error=" | ".join(reasons))
    else:
        score = request(base+"/api/predict", payload)
        row.update(score=score["score"], unit=score["score_label"], score_seconds=time.perf_counter()-start)
        job_start = time.perf_counter()
        jid = request(base+"/api/jobs", payload)["id"]
        row.update(job_id=jid)
        while True:
            state = request(base+"/api/jobs/"+jid)
            if state["status"] not in ("running", "queued"):
                break
            time.sleep(1)
        result = state["result"]
        row.update(timings=result.get("timings", []), job_seconds=time.perf_counter()-job_start)
        if state["status"] == "completed":
            dock = result["docking"]
            sdf = request(result["artifact_base"]+"/ligand.sdf", raw=True)
            mol = Chem.MolFromMolBlock(sdf.decode().split("$$$$")[0])
            query = Chem.MolFromSmiles(smiles)
            pose = bool(mol and mol.GetConformer().Is3D() and
                        mol.GetNumHeavyAtoms()==query.GetNumHeavyAtoms() and mol.HasSubstructMatch(query,useChirality=True)
                        and all(math.isfinite(v) for p in mol.GetConformer().GetPositions() for v in p))
            receptor = request(result["artifact_base"]+"/protein.pdb", raw=True)
            metadata = request(result["artifact_base"]+"/metadata.json")
            analysis = metadata.get("interaction_analysis")
            contacts = result.get("contacts")
            verified_contacts = isinstance(contacts, list) and analysis and analysis["contacts"] == contacts
            row.update(passed=bool(pose and math.isfinite(score["score"]) and b"ATOM  " in receptor and verified_contacts),
                       pose=pose, contacts=len(contacts) if isinstance(contacts, list) else None,
                       route=dock["protein_source"], cache_hit=dock["receptor_cache_hit"],
                       vina=dock["selected_vina_score_kcal_mol"])
            if not verified_contacts:
                row.update(stage="contacts", error=result.get("warnings") or "PLIP contacts could not be verified.")
        else:
            row.update(stage=result.get("stage"), error=result.get("detail"))
    row["seconds"] = round(time.perf_counter()-start, 2)
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", action="append", type=int)
    parser.add_argument("--no-cache", action="store_true")
    args = parser.parse_args()
    seq = json.loads((ROOT/".runtime/check_pair.json").read_text())["sequence"]
    cases = [
        ("Erlotinib / EGFR", SMILES, seq, False),
        ("Benzoic acid / FKBP12 (FASTA)", "O=C(O)c1ccccc1", ">FKBP12\n"+FKBP, False),
        ("Aspirin / FKBP12 (lowercase and line break)", "CC(=O)Oc1ccccc1C(=O)O", FKBP[:52].lower()+"\n"+FKBP[52:].lower(), False),
        ("Gefitinib / EGFR (1210 residues)", "COc1cc2ncnc(Nc3ccc(F)c(Cl)c3)c2cc1OCCCN1CCOCC1", seq, False),
        ("Ethanol / FKBP12", "CCO", FKBP, False),
        ("Invalid SMILES", "not a molecule", FKBP, True),
        ("Invalid sequence", "CCO", "MKKF123XYZ", True),
        ("Adenine / ubiquitin", "Nc1ncnc2[nH]cnc12", UBIQUITIN, False),
    ]
    base = json.loads((ROOT/".runtime/local_servers.json").read_text())["app_url"]
    print("Case | Result | Wall seconds | Receptor or error", flush=True)
    passed = True
    for number, case in enumerate(cases, 1):
        if args.case and number not in args.case:
            continue
        start = time.perf_counter()
        try:
            row = check(base, *case, args.no_cache)
        except (OSError, ValueError, KeyError) as exc:
            row = dict(name=case[0], valid=not case[3], passed=False, stage="test_client",
                       error=str(exc), seconds=round(time.perf_counter()-start, 2))
        (ROOT/f".runtime/case-{number}.json").write_text(json.dumps(row, indent=2))
        print(f"{number}. {case[0]} | {'PASS' if row['passed'] else 'FAIL'} | {row['seconds']} | {row.get('route') or row.get('error')}", flush=True)
        passed &= row["passed"]
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
