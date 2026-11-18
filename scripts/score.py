import argparse, os, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import common, agent, gh  # noqa: E402
from scripts.agent import load_prompts  # noqa: E402

# 每完成这么多个仓库就落盘一次:步骤被 timeout-minutes 杀掉时,已完成的结果不会丢。
SAVE_EVERY = 50
_now = time.monotonic

def _score_one(row, client, prompts, model, fetch, fetch_tree, breaker=None):
    text = common.repo_text(row, fetch, fetch_tree)
    if not text:
        return {"score": 0, "one_liner": "无 README/描述/目录树,跳过"}
    return agent.score_repo(client, model, prompts, text, breaker=breaker)

def run(cfg, date, client=None, fetch=None, fetch_tree=None):
    fetch = fetch or gh.fetch_readme
    fetch_tree = fetch_tree or gh.fetch_tree
    cand_path = common.data_dir("candidates", f"{date}.json")
    candidates = common.load_json(cand_path) if os.path.exists(cand_path) else []
    llm_cfg = cfg.get("llm", {}) or {}
    out_path = common.data_dir("scored", f"{date}.json")
    if not bool(llm_cfg.get("enabled", True)):
        # noagent 降级:不打分,score=None、one_liner 用描述兜底(供站点搜索摘要)。
        out = [{**row, "score": None,
                "one_liner": (row.get("description") or "").strip()}
               for row in candidates]
        common.dump_json(out_path, out)
        return out
    client = client if client is not None else agent.make_client()
    prompts = load_prompts(os.path.join(common.ROOT, "prompts.yaml"))
    model = agent.model_name()

    # 墙钟预算:到点后剩余仓库直接标记,保证步骤在 timeout-minutes 前自己结束并落盘。
    max_seconds = float(llm_cfg.get("max_seconds", 0) or 0)
    deadline = _now() + max_seconds if max_seconds > 0 else None
    breaker = agent.CircuitBreaker(int(llm_cfg.get(
        "connect_fail_limit", agent.DEFAULT_CONNECT_FAIL_LIMIT)))

    out = [{**row, "score": None, "one_liner": "[llm pending]"} for row in candidates]
    done, lock = 0, threading.Lock()

    def work(i, row):
        nonlocal done
        if deadline is not None and _now() >= deadline:
            res = {"score": None, "one_liner": "[llm budget exhausted]"}
        else:
            try:
                breaker.check()         # 熔断后连 README 都不用抓
                res = _score_one(row, client, prompts, model, fetch, fetch_tree,
                                 breaker=breaker)
            except agent.LLMUnavailable:
                res = {"score": None, "one_liner": "[llm unavailable]"}
            except Exception as e:
                # 只留一行原因:并发下每个失败都打会让日志爆炸,但完全吞掉又没法判断
                # 是限流、超时、模型名错还是 base_url 写错(describe_error 带底层 cause)。
                print(f"[score failed] {row.get('full_name')}: "
                      f"{agent.describe_error(e)[:200]}", flush=True)
                res = {"score": None, "one_liner": "[llm failed]"}
        with lock:
            out[i] = {**row, **res}
            done += 1
            if done % 100 == 0 or done == len(candidates):
                print(f"[score] {done}/{len(candidates)}", flush=True)
            if done % SAVE_EVERY == 0:
                common.dump_json(out_path, out)

    with ThreadPoolExecutor(max_workers=int(llm_cfg.get("concurrency", 8))) as ex:
        futures = [ex.submit(work, i, row) for i, row in enumerate(candidates)]
        for f in futures:
            f.result()                   # work 内部已兜底,这里只传递真正的程序错误
    common.dump_json(out_path, out)
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.path.join(common.ROOT, "config.yaml"))
    a = ap.parse_args()
    cfg = common.load_config(a.config)
    print(len(run(cfg, common.today())))

if __name__ == "__main__":
    main()
