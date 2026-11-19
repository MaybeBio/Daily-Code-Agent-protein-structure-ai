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

# 全局限速:所有线程共享同一个最小间隔。服务商实测限额约 10 次/分钟,
# 取 7.5s/次(8 次/分钟)留余量。
# 注意:真正的吞吐由这里封顶,并发数只决定「同时等待的线程数」。
# 因此不要把 concurrency 调很低(请求通常 5~15s,太少线程喂不满 8 次/分钟);
# 用 LLM_MIN_INTERVAL 可以覆盖间隔(秒),设为 0 关闭限速。
MIN_REQUEST_INTERVAL_SECONDS = 7.5
_rate_lock = threading.Lock()
_next_slot = 0.0

def _rate_limit():
    """全局限速:按最小间隔给每次请求排一个时间槽,并发再高也不会同时打满限额。"""
    interval = float(os.environ.get("LLM_MIN_INTERVAL", MIN_REQUEST_INTERVAL_SECONDS))
    if interval <= 0:
        return
    global _next_slot
    with _rate_lock:
        now = time.monotonic()
        wait = max(0.0, _next_slot - now)
        _next_slot = max(now, _next_slot) + interval
    if wait > 0:
        time.sleep(wait)

def _retry_after(err):
    """429 响应里的 Retry-After(秒);没有就返回 None。"""
    headers = getattr(getattr(err, "response", None), "headers", None)
    raw = headers.get("retry-after") if headers else None
    try:
        return max(0.0, float(raw)) if raw is not None else None
    except (TypeError, ValueError):
        return None

# 4xx 是客户端错误(key 错/model 名错/请求格式错),再试也一样,立即放弃;
# 429 限流、408 超时、5xx 服务端错都是瞬时,留给重试。
def _is_permanent(err) -> bool:
    return (isinstance(err, APIStatusError)
            and 400 <= err.status_code < 500
            and err.status_code not in (408, 429))

def _retry_json(client, model, msgs, parse, attempts=8, breaker=None):
    """JSON 模式调 LLM:全局限速 + 指数退避,429 优先遵循 Retry-After。

    连接层错误(APIConnectionError,含超时)每个仓库最多试 3 次,再交给 breaker 熔断;
    429/5xx 按 attempts(默认 8)退避重试。
    """
    conn_attempts = min(3, attempts)
    conn_fail = 0
    for attempt in range(attempts):
        if breaker is not None:
            breaker.check()
        try:
            _rate_limit()
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
                conn_fail += 1
                if conn_fail >= conn_attempts or attempt == attempts - 1:
                    if breaker is not None:
                        breaker.failure()
                    raise
                time.sleep(min(2 ** conn_fail, 30) + random.random())
                continue
            if attempt == attempts - 1:
                raise
            delay = _retry_after(e)
            if delay is None:
                delay = min(2 ** (attempt + 2), 60) + random.random()
            time.sleep(delay)

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
