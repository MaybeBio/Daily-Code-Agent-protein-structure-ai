"""Bounded, run-scoped scientific evidence retrieval for research design."""

from __future__ import annotations

import contextvars
import fcntl
import hashlib
import json
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler
from xml.etree import ElementTree as ET

BASES = {
    "pubmed": "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/",
    "chembl": "https://www.ebi.ac.uk/chembl/api/data/",
    "bindingdb": "https://www.bindingdb.org/rest/",
    "string": "https://version-12-5.string-db.org/api/",
}
OPS = {
    "pubmed_search": "pubmed",
    "pubmed_abstract": "pubmed",
    "chembl_target": "chembl",
    "bindingdb_target": "bindingdb",
    "string_protein": "string",
}
CURRENT = contextvars.ContextVar("evidence_session", default=None)
DESIGN_REFERENCE = contextvars.ContextVar("design_evidence_reference", default=None)
MAX_RESPONSE = 5_000_000


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def load_config():
    p = os.getenv("DRUGEVOLVE_EVIDENCE_CONFIG", "").strip()
    if not p:
        return {"enabled": False}
    cfg = json.loads(Path(p).read_text(encoding="utf8"))
    if not isinstance(cfg, dict) or not isinstance(cfg.get("sources", {}), dict):
        raise ValueError("Invalid evidence configuration")
    if set(cfg.get("sources", {})) - set(BASES):
        raise ValueError("Unknown evidence source")
    if not isinstance(cfg.get("enabled", False), bool):
        raise ValueError("enabled must be boolean")
    for name, entry in cfg.get("sources", {}).items():
        if not isinstance(entry, dict) or not isinstance(
            entry.get("enabled", False), bool
        ):
            raise ValueError(f"{name}.enabled must be boolean")
    if cfg.get("enabled") and not any(
        v.get("enabled") for v in cfg.get("sources", {}).values()
    ):
        raise ValueError("At least one evidence source must be enabled")
    if not isinstance(cfg.get("ncbi_email", ""), str):
        raise ValueError("ncbi_email must be a string")
    if (
        type(cfg.get("string_species", 9606)) is not int
        or cfg.get("string_species", 9606) <= 0
    ):
        raise ValueError("Invalid string_species")
    if (
        type(cfg.get("bindingdb_cutoff_nm", 10)) not in (int, float)
        or not 0 < cfg.get("bindingdb_cutoff_nm", 10) <= 100000
    ):
        raise ValueError("Invalid bindingdb_cutoff_nm")
    if cfg.get("failure_policy", "continue") not in ("continue", "stop"):
        raise ValueError("Invalid failure policy")
    for key in ("max_queries", "max_records"):
        if type(cfg.get(key, 5)) is not int or not 1 <= cfg.get(key, 5) <= 30:
            raise ValueError("Invalid " + key)
    return cfg


def _append(path, item):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf8") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")


def _text(node):
    return " ".join("".join(node.itertext()).split()) if node is not None else ""


def decode(op, body, limit):
    if op == "pubmed_abstract":
        if b"<!ENTITY" in body.upper():
            raise ValueError("XML entities are not accepted")
        root = ET.fromstring(body)
        out = []
        for article in root.findall(".//PubmedArticle")[:limit]:
            med = article.find("./MedlineCitation")
            pmid = _text(med.find("./PMID"))
            texts = []
            for x in med.findall(".//Abstract/AbstractText"):
                value = _text(x)
                if value:
                    texts.append(
                        (x.get("Label", "") + ": " if x.get("Label") else "") + value
                    )
            abstract = "\n".join(texts)
            out.append(
                {
                    "source_id": pmid,
                    "title": _text(med.find(".//ArticleTitle")),
                    "abstract": abstract,
                    "abstract_status": "available" if abstract else "unavailable",
                    "url": "https://pubmed.ncbi.nlm.nih.gov/" + pmid + "/",
                }
            )
        return out
    obj = json.loads(body)
    if op == "pubmed_search":
        result = obj.get("esearchresult", {})
        return [
            {
                "source_id": x,
                "url": "https://pubmed.ncbi.nlm.nih.gov/" + x + "/",
                "abstract_status": "not_fetched",
            }
            for x in result.get("idlist", [])[:limit]
        ]
    if op == "chembl_target":
        values = obj.get("targets", [obj] if obj.get("target_chembl_id") else [])
        return [
            {
                "source_id": v.get("target_chembl_id", ""),
                "name": v.get("pref_name", ""),
                "organism": v.get("organism", ""),
                "target_type": v.get("target_type", ""),
                "components": [
                    {
                        "accession": c.get("accession", ""),
                        "description": c.get("component_description", ""),
                    }
                    for c in v.get("target_components", [])
                ],
                "url": "https://www.ebi.ac.uk/chembl/target_report_card/"
                + v.get("target_chembl_id", "")
                + "/",
            }
            for v in values[:limit]
        ]
    if op == "bindingdb_target":
        val = obj.get("getLindsByUniprotsResponse", {}).get("affinities", [])
        return [
            {
                "source_id": str(v.get("monomerid", "")),
                "target": v.get("query", ""),
                "smiles": v.get("smile", ""),
                "affinity_type": v.get("affinity_type", ""),
                "affinity_nM": v.get("affinity", ""),
                "pmid": v.get("pmid", ""),
                "doi": v.get("doi", ""),
            }
            for v in val[:limit]
        ]
    if op == "string_protein":
        return [
            {
                "source_id": v.get("stringId", ""),
                "query": v.get("queryItem", ""),
                "name": v.get("preferredName", ""),
                "species": v.get("ncbiTaxonId"),
                "annotation": v.get("annotation", ""),
            }
            for v in obj[:limit]
        ]
    raise ValueError("Unknown operation")


class EvidenceSession:
    def __init__(self, run_dir, config):
        self.cfg = config
        self.id = uuid.uuid4().hex
        self.root = Path(run_dir) / "cognition" / "external" / self.id
        self.count = 0
        self.records = {}
        self.errors = []
        self.lock = threading.RLock()

    def query(self, op, query):
        with self.lock:
            return self._query(op, query)

    def _query(self, op, query):
        source = OPS.get(op)
        request_id = uuid.uuid4().hex
        info = {
            "request_id": request_id,
            "source": source,
            "operation": op,
            "query": query[:500],
            "time": datetime.now(timezone.utc).isoformat(),
        }
        try:
            if (
                not self.cfg.get("enabled")
                or not source
                or not self.cfg.get("sources", {}).get(source, {}).get("enabled")
            ):
                raise ValueError("source_disabled")
            self.count += 1
            if self.count > self.cfg.get("max_queries", 8):
                raise ValueError("query_budget_exhausted")
            if not query or len(query) > 500:
                raise ValueError("invalid_query")
            limit = self.cfg.get("max_records", 5)
            params = {}
            if op == "pubmed_search":
                path = "esearch.fcgi"
                params = {
                    "db": "pubmed",
                    "term": query,
                    "retmode": "json",
                    "retmax": str(limit),
                    "tool": "DrugEvolve",
                }
            elif op == "pubmed_abstract":
                if not re.fullmatch(r"\d+(,\d+){0,4}", query):
                    raise ValueError("expected PMID or comma-separated PMIDs")
                path = "efetch.fcgi"
                params = {
                    "db": "pubmed",
                    "id": query,
                    "retmode": "xml",
                    "tool": "DrugEvolve",
                }
            elif op == "chembl_target":
                if not re.fullmatch(r"CHEMBL\d+", query, re.I):
                    raise ValueError("expected ChEMBL target ID")
                path = "target/" + query.upper() + ".json"
            elif op == "bindingdb_target":
                if not re.fullmatch(r"[A-Za-z0-9]{6,10}", query):
                    raise ValueError("expected UniProt accession")
                path = "getLigandsByUniprots"
                params = {
                    "uniprot": query,
                    "cutoff": str(self.cfg.get("bindingdb_cutoff_nm", 10)),
                    "response": "application/json",
                }
            else:
                if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", query):
                    raise ValueError("expected protein identifier")
                path = "json/get_string_ids"
                params = {
                    "identifiers": query,
                    "species": str(self.cfg.get("string_species", 9606)),
                    "caller_identity": "DrugEvolveResearch",
                }
            if source == "pubmed" and self.cfg.get("ncbi_email"):
                params["email"] = self.cfg["ncbi_email"]
            url = BASES[source] + path + ("?" + urlencode(params) if params else "")
            raw = self._fetch(url, source, info)
            if len(raw) > MAX_RESPONSE:
                raise ValueError("response_too_large")
            records = decode(op, raw, limit)
            info.update(
                status="ok",
                record_count=len(records),
                sha256=hashlib.sha256(raw).hexdigest(),
            )
            result = []
            for rec in records:
                eid = (
                    source
                    + ":"
                    + op
                    + ":"
                    + str(rec.get("source_id", ""))
                    + ":"
                    + uuid.uuid4().hex[:8]
                )
                entry = {
                    "evidence_id": eid,
                    "source": source,
                    "operation": op,
                    "retrieved_at": info["time"],
                    "request_id": request_id,
                    "content": rec,
                }
                self.records[eid] = entry
                _append(self.root / "evidence.jsonl", entry)
                result.append(entry)
            return {
                "status": "ok",
                "request_id": request_id,
                "evidence": result,
                "count": len(result),
            }
        except (
            ValueError,
            KeyError,
            AttributeError,
            IndexError,
            ET.ParseError,
            HTTPError,
            URLError,
            OSError,
            TypeError,
        ) as e:
            info.update(
                status="error",
                error=str(e)[:250] if isinstance(e, ValueError) else type(e).__name__,
            )
            self.errors.append(info["error"])
            return {"status": "error", "request_id": request_id, "error": info["error"]}
        finally:
            _append(self.root / "requests.jsonl", info)

    def _fetch(self, url, source, info):
        # Cooperate across evidence sessions within this run directory.
        lock_dir = self.root.parent / ".rate_limits"
        lock_dir.mkdir(parents=True, exist_ok=True)
        last_error = None
        for attempt in range(3):
            info["attempts"] = attempt + 1
            with (lock_dir / (source + ".lock")).open("a+") as handle:
                fcntl.flock(handle, fcntl.LOCK_EX)
                handle.seek(0)
                try:
                    last = float(handle.read() or "0")
                except ValueError:
                    last = 0
                delay = 1.1 - (time.time() - last)
                if delay > 0:
                    time.sleep(delay)
                handle.seek(0)
                handle.truncate()
                handle.write(str(time.time()))
                handle.flush()
                fcntl.flock(handle, fcntl.LOCK_UN)
            try:
                with build_opener(NoRedirect()).open(
                    Request(
                        url,
                        headers={
                            "User-Agent": "DrugEvolve-Evidence/0.1",
                            "Accept": "application/json, application/xml, text/xml",
                        },
                    ),
                    timeout=20,
                ) as response:
                    info["http_status"] = response.status
                    return response.read(MAX_RESPONSE + 1)
            except HTTPError as exc:
                info["http_status"] = exc.code
                if exc.code != 429 and not 500 <= exc.code < 600:
                    raise
                last_error = exc
            except (URLError, TimeoutError, ConnectionError) as exc:
                last_error = exc
            if attempt < 2:
                time.sleep(min(2**attempt, 4))
        raise last_error

    def validate_and_save(self, candidate, citations):
        if self.cfg.get("failure_policy", "continue") == "stop" and self.errors:
            raise ValueError("Evidence query failed: " + self.errors[0])
        for c in citations:
            if c["evidence_id"] not in self.records:
                raise ValueError("Unknown evidence ID: " + c["evidence_id"])
            record = self.records[c["evidence_id"]]
            if record["source"] == "pubmed" and record["operation"] == "pubmed_search":
                raise ValueError("PubMed search IDs do not establish abstract content")
            if (
                record["source"] == "pubmed"
                and record["content"].get("abstract_status") == "unavailable"
            ):
                raise ValueError("Missing abstract cannot support a citation")
        _append(
            self.root / "usage.jsonl", {"candidate": candidate, "citations": citations}
        )
