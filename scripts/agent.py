import json, os, random, threading, time
import yaml
from openai import OpenAI, APIConnectionError, APIStatusError

DEFAULT_MODEL = "deepseek-chat"

# 连续这么多次连接层失败就判定端点不可达并熔断:
# 不熔断时每个仓库要白等 5 次退避(4+8+16+32=60s),500 个仓库就是 80 分钟,
# 正是 daily 撞满 timeout-minutes 的直接原因。12 次 ≈ 并发 8 下 2 轮,足以跳过瞬时抖动。
DEFAULT_CONNECT_FAIL_LIMIT = 12


class LLMUnavailable(RuntimeError):
    """端点连续连接失败后主动熔断,剩余仓库直接跳过。"""


class CircuitBreaker:
    """线程安全的连续失败计数器:打开后 check() 立即抛错,不再发请求。"""

    def __init__(self, limit: int = DEFAULT_CONNECT_FAIL_LIMIT):
        self.limit = int(limit)
        self._lock = threading.Lock()
        self.failures = 0
        self.opened = False

    def check(self) -> None:
        if self.opened:
            raise LLMUnavailable("LLM 连续连接失败,已熔断")

    def success(self) -> None:
        with self._lock:
            self.failures = 0
            self.opened = False

    def failure(self) -> None:
        with self._lock:
            self.failures += 1
            if self.limit > 0 and self.failures >= self.limit:
                self.opened = True


def describe_error(err: Exception) -> str:
    """带底层原因的错误描述:APIConnectionError 本身只有 "Connection error.",
    看不到是 DNS、TLS 还是 base_url 本身不是合法 URL。"""
    text = f"{type(err).__name__}: {err}"
    cause = err.__cause__
    if cause is not None:
        text += f" (cause: {type(cause).__name__}: {str(cause)[:160]})"
    return text

# 单次请求超时。不传 timeout 时 openai SDK 默认 600s 且自带 2 次自动重试:
# 一个卡住的请求最坏能占 30 分钟,并发里几个一起卡,整步就会静默跑满 timeout-minutes。
# 这里压到 90s 并关掉 SDK 重试,退避统一交给 _retry_json。
REQUEST_TIMEOUT_SECONDS = 90

def load_prompts(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def make_client() -> OpenAI:
    # secret 末尾的空格/换行会让 httpx 抛 "Illegal header value",再被包装成
    # APIConnectionError("Connection error.")——看起来像网络故障,实际一个 strip 就修好。
    return OpenAI(base_url=os.environ["LLM_BASE_URL"].strip(),
                  api_key=os.environ["LLM_API_KEY"].strip(),
                  timeout=REQUEST_TIMEOUT_SECONDS, max_retries=0)

def model_name() -> str:
    return os.environ.get("LLM_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL

# 4xx 是客户端错误(key 错/model 名错/请求格式错),再试也一样,立即放弃;
# 429 限流、408 超时、5xx 服务端错都是瞬时,留给重试。
def _is_permanent(err) -> bool:
    return (isinstance(err, APIStatusError)
            and 400 <= err.status_code < 500
            and err.status_code not in (408, 429))

def _retry_json(client, model, msgs, parse, attempts=5, breaker=None):
    """JSON 模式调 LLM:指数退避重试,叠加 jitter 打散高并发下的惊群。

    429/5xx 仍按 5 次退避重试;连接层错误(APIConnectionError,含超时)不重试——
    端点不可达时重试只会让每个仓库白等 60s,改由 breaker 全局熔断。
    """
    for attempt in range(attempts):
        if breaker is not None:
            breaker.check()
        try:
            r = client.chat.completions.create(model=model, messages=msgs, temperature=0.0,
                                               response_format={"type": "json_object"})
            result = parse(json.loads(r.choices[0].message.content))
            if breaker is not None:
                breaker.success()
            return result
        except Exception as e:      # 网络/限流/解析
            if _is_permanent(e):
                raise
            if isinstance(e, APIConnectionError):
                if breaker is not None:
                    breaker.failure()
                raise               # 单仓库不再退避重试,交给全局熔断
            if attempt == attempts - 1:
                raise
            time.sleep(2 ** (attempt + 2) + random.random())

def score_repo(client, model, prompts, readme, breaker=None) -> dict:
    p = prompts["score"]
    msgs = [{"role": "system", "content": p["system"]},
            {"role": "user", "content": p["user"].format(readme=readme[:10000])}]
    return _retry_json(client, model, msgs,
                       lambda obj: {"score": int(obj["score"]),
                                    "one_liner": str(obj.get("one_liner", ""))},
                       breaker=breaker)

def build_code_card(client, model, prompts, readme, breaker=None) -> dict:
    p = prompts["code_card"]
    msgs = [{"role": "system", "content": p["system"]},
            {"role": "user", "content": p["user"].format(readme=readme)}]
    return _retry_json(client, model, msgs,
                       lambda obj: {"card": str(obj.get("card", ""))}, breaker=breaker)
