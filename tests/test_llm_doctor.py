from scripts import llm_doctor


def test_redact_strips_userinfo_and_query():
    assert llm_doctor.redact(
        "https://user:pw@api.example.com/v1?key=sk-secret") == "https://api.example.com/v1"


def test_parse_base_rejects_non_url():
    ok, detail = llm_doctor.parse_base("sk-secret-123")
    assert ok is False
    assert "http" in detail.lower()
    assert "sk-secret-123" not in detail          # 诊断日志绝不能再泄露疑似密钥


def test_parse_base_accepts_https():
    ok, detail = llm_doctor.parse_base("https://api.example.com/v1")
    assert ok is True
    assert detail == "https://api.example.com/v1"


def test_diagnose_flags_bad_url_without_leaking_value():
    report = llm_doctor.diagnose({"LLM_BASE_URL": "sk-secret-123",
                                  "LLM_API_KEY": "k"})
    text = "\n".join(f"{r['check']}: {r['detail']}" for r in report)
    assert "sk-secret-123" not in text
    assert next(r for r in report if r["check"] == "base_url")["ok"] is False


def test_diagnose_reports_dns_failure_without_crashing(monkeypatch):
    def boom(*a, **k):
        raise OSError("name resolution failed")
    monkeypatch.setattr(llm_doctor.socket, "getaddrinfo", boom)
    report = llm_doctor.diagnose({"LLM_BASE_URL": "https://api.example.com/v1",
                                  "LLM_API_KEY": "k"})
    dns = next(r for r in report if r["check"] == "dns")
    assert dns["ok"] is False
    assert "resolution failed" in dns["detail"]


def test_diagnose_notes_404_path_hint(monkeypatch):
    """404 说明主机可达但路径可能写错(base_url 通常应以 /v1 结尾)。"""
    import urllib.error

    class Sock:
        def close(self): pass

    def fake_urlopen(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)

    monkeypatch.setattr(llm_doctor.socket, "getaddrinfo",
                        lambda *a, **k: [(2, 1, 6, "", ("1.2.3.4", 443))])
    monkeypatch.setattr(llm_doctor.socket, "create_connection", lambda *a, **k: Sock())
    monkeypatch.setattr(llm_doctor.urllib.request, "urlopen", fake_urlopen)
    report = llm_doctor.diagnose({"LLM_BASE_URL": "https://api.example.com/v1",
                                  "LLM_API_KEY": "k"})
    http = next(r for r in report if r["check"] == "http")
    assert "404" in http["detail"]
    assert "path" in http["detail"]


def test_diagnose_warns_on_api_key_whitespace():
    """本次事故:secret 末尾空格 → h11 LocalProtocolError: Illegal header value。"""
    report = llm_doctor.diagnose({"LLM_BASE_URL": "sk-abc", "LLM_API_KEY": "sk-test \n"})
    key = next(r for r in report if r["check"] == "api_key")
    assert "whitespace" in key["detail"].lower()


def test_main_returns_nonzero_on_failure(monkeypatch, capsys):
    monkeypatch.setattr(llm_doctor, "diagnose",
                        lambda env=None: [{"check": "base_url", "ok": False,
                                           "detail": "bad"}])
    assert llm_doctor.main() == 1
    assert "FAIL" in capsys.readouterr().out
