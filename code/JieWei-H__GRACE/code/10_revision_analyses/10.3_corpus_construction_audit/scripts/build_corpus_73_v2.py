#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Streaming builder for the 7:3 leakage-controlled pre-training corpus.

Loading the archived 4 GB noisy-subgraph pickles exceeds the 80 GB container
limit, so the noise is regenerated on the fly instead: each worker takes one
base subgraph, produces its noisy copies with the same size-weighted schedule
as the original pipeline, drops the copies that reach Jaccard >= 0.3 with a
held-out complex, and returns BFS strings. Memory stays flat.

Output: /root/LLM73/pretrain_data/pretrain_73_part*.json + merged file.
"""
import json
import multiprocessing as mp
import os
import pickle
import sys
import time

sys.modules["__main__"].TokenIDGene = type("TokenIDGene", (), {})
sys.path.insert(0, "/root/GraphModuleGenerate")
sys.path.insert(0, "/root/LLM/Model-Heltout/Dataset")

SRC = "/root/LLM/Model-Heltout/Dataset"
OUT = os.environ.get("OUT_DIR", "/root/LLM73/pretrain_data")
TEST_SETS = "/root/gpu_runs/test_complex_idsets_73.pkl"
THRESH = 0.3
TARGET_TOTAL = 10000000      # per batch, as in the archived pipeline
NPROC = int(os.environ.get("NPROC", "60"))
FLUSH_EVERY = 600000
GROUP = 8

os.makedirs(OUT, exist_ok=True)

_G = {}


def log(m):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), m), flush=True)


def init_worker(ppi_path, tok_path, tests_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "gm2", "/root/GraphModuleGenerate/2.ALL_Complex_Generate_multi.py")
    # importing the script would run its __main__ block; read classes instead
    src = open("/root/GraphModuleGenerate/2.ALL_Complex_Generate_multi.py",
               encoding="utf-8").read()
    src = src.split('if __name__ == "__main__":')[0]
    ns = {"__name__": "gm2"}
    exec(compile(src, "gm2", "exec"), ns)
    _G["SubgraphGenerator"] = ns["SubgraphGenerator"]

    import GraphTransform_BFS_Pretrain as G
    ppi = pickle.load(open(ppi_path, "rb"))
    tok = pickle.load(open(tok_path, "rb"))
    _G["builder"] = G.TrainingDataBuilder(G.GraphFeatureProcessor(ppi),
                                          G.GraphSequenceGenerator(tok))
    _G["gen"] = _G["SubgraphGenerator"](ppi)
    tests = [frozenset(int(n) for n in s) for s in pickle.load(open(tests_path, "rb"))]
    _G["tests"] = [t for t in tests if t]
    inv = {}
    for i, t in enumerate(_G["tests"]):
        for n in t:
            inv.setdefault(n, []).append(i)
    _G["inv"] = inv


def is_leak(nodes):
    inv = _G["inv"]
    cand = set()
    for n in nodes:
        c = inv.get(n)
        if c:
            cand.update(c)
    if not cand:
        return False
    ln = len(nodes)
    tests = _G["tests"]
    for ci in cand:
        t = tests[ci]
        inter = len(nodes & t)
        if inter and inter / float(ln + len(t) - inter) >= THRESH:
            return True
    return False


def work(task):
    idx, sub, noise_level, num_copies = task
    gen = _G["gen"]
    builder = _G["builder"]
    out, dropped, tiny = [], 0, 0
    for j in range(num_copies):
        try:
            ng = gen.add_noise_to_subgraph(sub, noise_level)
        except Exception:
            continue
        nodes = frozenset(int(n) for n in ng.nodes())
        if len(nodes) < 2:
            tiny += 1
            continue
        if is_leak(nodes):
            dropped += 1
            continue
        txt = builder.encode_subgraph(ng, core_node_percent=0.2, random_seed=idx * 1000 + j)
        if txt:
            out.append("<|im_start|>%s<|im_end|>" % txt)
    return idx, out, dropped, tiny


def main():
    log("loading base subgraphs and PPI")
    ppi_path = os.path.join(SRC, "Graph_init/graph.pkl")
    tok_path = os.path.join(SRC, "Graph_init/token_id_gene.pkl")
    subs = pickle.load(open(os.path.join(SRC, "Graph_init/all_subgraphs.pkl"), "rb"))
    n_smoke = int(os.environ.get("SMOKE_N", "0"))
    target = TARGET_TOTAL
    if n_smoke:
        subs = subs[:n_smoke]
        target = int(os.environ.get("SMOKE_TARGET", "20000"))
    log("base subgraphs %d, target copies %d" % (len(subs), target))

    init_worker(ppi_path, tok_path, TEST_SETS)
    sizes = [s.number_of_nodes() for s in subs]
    weights = [1.0 / max(1, s ** 0.5) for s in sizes]
    tw = sum(weights)
    weights = [w / tw for w in weights]
    copies = [max(1, int(w * target)) for w in weights]
    tasks = []
    base_leak = 0
    for i, s in enumerate(subs):
        nodes = frozenset(int(n) for n in s.nodes())
        if is_leak(nodes):
            base_leak += 1
            continue
        nl = 1.0 * (10 / max(1, sizes[i])) ** 0.5
        tasks.append((i, s, nl, copies[i]))
    log("base-level filter: %d of %d base subgraphs share Jaccard >= %.1f with a held-out "
        "complex and are excluded together with all their noisy copies (%.1f%%)"
        % (base_leak, len(subs), THRESH, 100.0 * base_leak / max(1, len(subs))))
    log("planned noisy copies (one batch): %d across %d base subgraphs"
        % (sum(copies), len(tasks)))

    written, total, dropped_total, tiny_total = [], 0, 0, 0
    fragments, k = [], 0
    t0 = time.time()
    with mp.Pool(processes=NPROC, initializer=init_worker,
                 initargs=(ppi_path, tok_path, TEST_SETS)) as pool:
        for n_done, (idx, out, dropped, tiny) in enumerate(
                pool.imap_unordered(work, tasks, chunksize=1), 1):
            fragments.extend(out)
            total += len(out)
            dropped_total += dropped
            tiny_total += tiny
            if len(fragments) >= FLUSH_EVERY:
                chunks = [{"text": " ".join(fragments[j:j + GROUP])}
                          for j in range(0, len(fragments), GROUP)]
                path = os.path.join(OUT, "pretrain_73_part%03d.json" % k)
                json.dump(chunks, open(path, "w"))
                written.append(path)
                log("chunk %d written: kept=%d leak=%d tiny=%d  base %d/%d  %.0fs"
                    % (k, total, dropped_total, tiny_total, n_done, len(tasks), time.time() - t0))
                fragments, k = [], k + 1
            if n_done % 2000 == 0:
                log("progress %d/%d base subgraphs, kept=%d dropped=%d %.0fs"
                    % (n_done, len(tasks), total, dropped_total, time.time() - t0))
    if fragments:
        chunks = [{"text": " ".join(fragments[j:j + GROUP])}
                  for j in range(0, len(fragments), GROUP)]
        path = os.path.join(OUT, "pretrain_73_part%03d.json" % k)
        json.dump(chunks, open(path, "w"))
        written.append(path)

    log("generation done: kept=%d leak_dropped=%d (%.1f%%) tiny=%d in %.0fs"
        % (total, dropped_total, 100.0 * dropped_total / max(1, total + dropped_total),
           tiny_total, time.time() - t0))

    merged = os.path.join(OUT, "pretrain_combined_73.json")
    with open(merged, "w") as out:
        out.write("[")
        first = True
        for p in written:
            for item in json.load(open(p)):
                if not first:
                    out.write(",")
                out.write(json.dumps(item))
                first = False
        out.write("]")
    log("merged -> %s (%.2f GB)" % (merged, os.path.getsize(merged) / 1e9))
    log("DONE corpus73")


if __name__ == "__main__":
    main()
