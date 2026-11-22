#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Remove held-out complexes from the pre-training corpus (sequence-level filter).

Criterion
---------
A pre-training sequence is one BFS token string delimited by
``<|im_start|>`` ... ``<|im_end|>``; tokens are gene symbols.  For a held-out
reference complex with member set K (|K| = L >= --min-subunits), a sequence
*contains* K as a contiguous run when some window ``toks[w:w+L]`` satisfies
``set(window) == K``: all L members sit in L adjacent positions and no
non-member sits between them.  Order inside the window is free.  A sequence
that matches this condition for at least one held-out complex is dropped.

Why this filter exists
----------------------
The pre-training corpus is produced by unsupervised graph partitioning of the
complete PPI network and is therefore blind to the held-out split: a base
subgraph can reassemble a held-out complex even though the complex itself was
never used as a training label.  Three filters act together on the held-out
partition:

* base subgraph level - Jaccard < 0.30 against every held-out complex;
  1,176 of 25,353 base subgraphs failed and were dropped together with all
  of their noisy copies.
* fine-tuning pool level - Jaccard < 0.50 per noise-injected variant;
  7,152 of 497,816 were removed.
* sequence level - this script.  Contiguous runs are what an autoregressive
  model can memorise verbatim, so any sequence reproducing a held-out complex
  as an adjacent block is removed outright.  Superset containment (members
  scattered through the sequence) is *not* removed.

Reference values (7:3 revision corpus, 1,152 held-out complexes of which 710
have L >= 3): 18,979,562 sequences scanned, 9,262 dropped (0.0488%),
18,970,300 kept.

Output layout
-------------
Surviving sequences are re-emitted in groups of --group (default 8), the same
layout ``GraphTransform_BFS_Pretrain.py`` writes, so
``04_pretraining/Dataset.py`` keeps reading one record per training sample.

Usage
-----
python Filter_Heldout_Contiguous.py \
    --corpus pretrain_data/pretrain_combined.json \
    --heldout data/split_7-3/Complex_Test.pkl \
    --token-map data/token_id_gene.pkl \
    --min-subunits 3 \
    --out pretrain_data/pretrain_combined_filtered.json \
    --report pretrain_data/filter_report.json

Add --dry-run to count only (no output file, no disk cost).
"""
import argparse
import json
import os
import pickle
import re
import sys
import time
from collections import Counter

BLOCK_RE = re.compile(r'<\|im_start\|>([^<]*)<\|im_end\|>')


def _unpickle_shim():
    """Pickles produced by the training pipeline reference __main__.TokenIDGene."""
    mod = sys.modules.get("__main__")
    if mod is not None and not hasattr(mod, "TokenIDGene"):
        mod.TokenIDGene = type("TokenIDGene", (), {})


def load_pickle(path):
    _unpickle_shim()
    with open(path, "rb") as fh:
        return pickle.load(fh)


def as_member_set(obj):
    """Complexes arrive either as networkx graphs or as plain node collections."""
    if hasattr(obj, "nodes"):
        return frozenset(obj.nodes())
    if isinstance(obj, (set, frozenset, list, tuple)):
        return frozenset(obj)
    raise TypeError("cannot read a member set from %r" % type(obj))


def load_heldout(path, token_map, min_subunits):
    raw = load_pickle(path)
    if isinstance(raw, dict):
        raw = list(raw.values())
    sets = []
    for c in raw:
        s = as_member_set(c)
        if s:
            sets.append(s)
    if token_map is not None:
        if hasattr(token_map, "id_to_gene"):
            id_to_gene = token_map.id_to_gene
        elif isinstance(token_map, dict):
            id_to_gene = token_map.get("id_to_gene", token_map)
        else:
            raise TypeError("token map must be a dict or expose .id_to_gene, got %r"
                            % type(token_map))
        sets = [frozenset(id_to_gene[n] for n in s if n in id_to_gene) for s in sets]
    total = len(sets)
    sets = [s for s in sets if len(s) >= min_subunits]
    return sets, total


def build_inverse(sets):
    inv = {}
    for i, s in enumerate(sets):
        for g in s:
            inv.setdefault(g, []).append(i)
    return inv


def has_contig(toks, ks, L):
    """True when some window of length L has exactly the member set ks."""
    n = len(toks)
    if L > n:
        return False
    win = Counter(toks[:L])
    if len(win) == L and set(win) == ks:
        return True
    for w in range(1, n - L + 1):
        out = toks[w - 1]
        inn = toks[w + L - 1]
        win[out] -= 1
        if win[out] == 0:
            del win[out]
        win[inn] += 1
        if len(win) == L and set(win) == ks:
            return True
    return False


def is_leak(toks, gs, inv, sets):
    cand = set()
    for g in toks:
        c = inv.get(g)
        if c:
            cand.update(c)
    ngs = len(gs)
    for i in cand:
        ks = sets[i]
        L = len(ks)
        if L > ngs or not ks <= gs:
            continue
        if has_contig(toks, ks, L):
            return True
    return False


def iter_blocks(path, chunk_bytes):
    """Stream (block_text) out of a JSON corpus without loading it whole."""
    carry = ""
    with open(path, "r", encoding="utf-8", newline="") as fh:
        while True:
            buf = fh.read(chunk_bytes)
            if not buf:
                text = carry
                carry = ""
            else:
                text = carry + buf
                cut = text.rfind("<|im_start|>")
                if cut > 0:
                    carry = text[cut:]
                    text = text[:cut]
                else:
                    carry = ""
            for seq in BLOCK_RE.findall(text):
                yield seq
            if not buf:
                break


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--corpus", required=True, help="pre-training corpus JSON array")
    ap.add_argument("--heldout", required=True, help="pickle of held-out complexes")
    ap.add_argument("--token-map", default=None, help="token_id_gene.pkl (id_to_gene)")
    ap.add_argument("--min-subunits", type=int, default=3,
                    help="ignore held-out complexes with fewer members (default 3)")
    ap.add_argument("--out", default=None, help="filtered corpus (omit with --dry-run)")
    ap.add_argument("--report", default=None, help="JSON report path")
    ap.add_argument("--group", type=int, default=8,
                    help="sequences per JSON record (default 8)")
    ap.add_argument("--chunk-mb", type=int, default=64)
    ap.add_argument("--dry-run", action="store_true", help="count only, write nothing")
    args = ap.parse_args()

    if not args.dry_run and not args.out:
        ap.error("--out is required unless --dry-run is given")

    token_map = load_pickle(args.token_map) if args.token_map else None
    sets, total_heldout = load_heldout(args.heldout, token_map, args.min_subunits)
    print("held-out complexes: %d total, %d with >= %d subunits"
          % (total_heldout, len(sets), args.min_subunits), flush=True)
    if not sets:
        raise SystemExit("no held-out complex passed the subunit threshold")
    inv = build_inverse(sets)

    out_fh = None
    if not args.dry_run:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        out_fh = open(args.out, "w", encoding="utf-8", newline="")
        out_fh.write("[")

    n_in = n_drop = n_keep = n_rec = 0
    buf = []
    first_rec = True
    t0 = time.time()

    for seq in iter_blocks(args.corpus, args.chunk_mb * 1024 * 1024):
        n_in += 1
        toks = seq.split()
        gs = set(toks)
        if is_leak(toks, gs, inv, sets):
            n_drop += 1
        else:
            n_keep += 1
            if out_fh is not None:
                buf.append("<|im_start|>%s<|im_end|>" % seq)
                if len(buf) >= args.group:
                    if not first_rec:
                        out_fh.write(",")
                    out_fh.write(json.dumps({"text": " ".join(buf)}, ensure_ascii=False))
                    first_rec = False
                    n_rec += 1
                    buf = []
        if n_in % 2000000 == 0:
            print("  scanned %d  dropped %d  %.0fs"
                  % (n_in, n_drop, time.time() - t0), flush=True)

    if out_fh is not None:
        if buf:
            if not first_rec:
                out_fh.write(",")
            out_fh.write(json.dumps({"text": " ".join(buf)}, ensure_ascii=False))
            n_rec += 1
        out_fh.write("]")
        out_fh.close()

    elapsed = time.time() - t0
    report = {
        "corpus": os.path.abspath(args.corpus),
        "heldout_file": os.path.abspath(args.heldout),
        "heldout_complexes_total": total_heldout,
        "heldout_complexes_used": len(sets),
        "min_subunits": args.min_subunits,
        "criterion": "sequence contains a held-out complex as a contiguous run "
                     "(window of length L whose token set equals the member set)",
        "sequences_in": n_in,
        "sequences_dropped": n_drop,
        "sequences_kept": n_keep,
        "dropped_fraction": round(100.0 * n_drop / n_in, 4) if n_in else None,
        "records_written": n_rec,
        "group": args.group,
        "dry_run": bool(args.dry_run),
        "elapsed_sec": round(elapsed, 1),
    }
    print(json.dumps(report, indent=2), flush=True)
    if args.report:
        with open(args.report, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)
            fh.write("\n")


if __name__ == "__main__":
    main()
