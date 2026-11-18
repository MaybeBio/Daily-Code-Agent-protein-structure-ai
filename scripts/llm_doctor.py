"""LLM 端点诊断:在 Actions 里跑一次,定位 APIConnectionError 的真实原因。

只打印脱敏后的地址(去掉 userinfo/query)、DNS/TCP/HTTP 结果和错误原因,
绝不打印 LLM_API_KEY 的值。
"""
import os
import socket
import sys
import urllib.error
import urllib.request
from urllib.parse import urlsplit


def redact(url: str) -> str:
    """scheme://host[:port]/path —— 去掉可能带密钥的 userinfo 和 query。"""
    try:
        p = urlsplit((url or "").strip())
        host = p.hostname or ""
        if p.port:
            host = f"{host}:{p.port}"
    except Exception:
        return "<unparseable>"
    if not p.scheme and not host:
        return "<empty>"
    return f"{p.scheme}://{host}{p.path or ''}"


def parse_base(base: str) -> tuple[bool, str]:
    """判断 LLM_BASE_URL 是否是合法的 http(s) 绝对地址。

    常见事故:把 API key 误填进 LLM_BASE_URL、漏了 https://、或值里带换行。
    这些都会让 openai SDK 抛 APIConnectionError("Connection error."),看不出原因。
    """
    base = (base or "").strip()
    if not base:
        return False, "LLM_BASE_URL is empty"
    try:
        p = urlsplit(base)
    except Exception as e:
        return False, f"unparseable URL: {type(e).__name__}"
    if p.scheme not in ("http", "https"):
        return False, f"scheme is {p.scheme!r}, expected http/https (value redacted)"
    if not p.hostname:
        return False, "missing host"
    if any(c.isspace() for c in base):
        return False, "value contains whitespace/newline (value redacted)"
    return True, redact(base)


def _cause_text(err: Exception) -> str:
    text = f"{type(err).__name__}: {err}"
    cause = err.__cause__
    if cause is not None:
        text += f" (cause: {type(cause).__name__}: {str(cause)[:200]})"
    return text


def diagnose(env: dict | None = None) -> list[dict]:
    env = os.environ if env is None else env
    base = (env.get("LLM_BASE_URL") or "").strip()
    ok, detail = parse_base(base)
    report = [{"check": "base_url", "ok": ok, "detail": detail}]

    key = env.get("LLM_API_KEY") or ""
    if not key:
        detail = "missing"
    elif key != key.strip():
        # 实测事故:末尾空格/换行 → h11 LocalProtocolError: Illegal header value,
        # 被 openai SDK 包装成 APIConnectionError,看起来像网络不通。
        detail = f"set (len={len(key)}) but has leading/trailing whitespace"
    else:
        detail = f"set (len={len(key)})"
    report.append({"check": "api_key", "ok": bool(key), "detail": detail})
    report.append({"check": "model",
                   "ok": True,
                   "detail": (env.get("LLM_MODEL") or "").strip() or "deepseek-chat (default)"})
    if not ok:
        return report

    p = urlsplit(base)
    host = p.hostname
    port = p.port or (443 if p.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        report.append({"check": "dns", "ok": True,
                       "detail": f"{host} -> {infos[0][4][0]}"})
    except Exception as e:
        report.append({"check": "dns", "ok": False, "detail": _cause_text(e)})
        return report

    try:
        sock = socket.create_connection((host, port), timeout=5)
        sock.close()
        report.append({"check": "tcp", "ok": True, "detail": f"{host}:{port} connected"})
    except Exception as e:
        report.append({"check": "tcp", "ok": False, "detail": _cause_text(e)})
        return report

    # 用标准库而不是 httpx:Actions 里 openai 依赖的是 httpx2,没有 httpx 模块。
    url = base.rstrip("/") + "/models"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key.strip()}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            status = r.status
    except urllib.error.HTTPError as e:
        status = e.code                      # 401/404 也证明主机可达
    except Exception as e:
        report.append({"check": "http", "ok": False, "detail": _cause_text(e)})
        return report
    detail = f"GET {redact(url)} -> {status}"
    if status == 404:
        detail += " (host reachable; check base_url path, usually ends with /v1)"
    report.append({"check": "http", "ok": status < 500, "detail": detail})
    return report


def main() -> int:
    report = diagnose()
    for item in report:
        print(f"[{'ok' if item['ok'] else 'FAIL'}] {item['check']}: {item['detail']}")
    return 0 if all(item["ok"] for item in report) else 1


if __name__ == "__main__":
    sys.exit(main())
