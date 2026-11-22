"""Build the AlphaFold pretraining set.

Run from the repo root, in the background:
    nohup python scripts/download_alphafold.py --n 50000 > results/alphafold_download.log 2>&1 &

Steps:
  1. Download Swiss-Prot as one fasta (93 MB). The UniProt REST stream endpoint returns
     the same accessions at about 50 rows a second, which would take over an hour, and it
     gives no sequences.
  2. Keep entries of 30 to 256 residues.
  3. Remove anything resembling a MegaScale protein, before downloading, so no structure
     is fetched that we would have to throw away.
  4. Sample n of what is left and fetch each AlphaFold model, parsing it straight to
     backbone coordinates and discarding the text.

Resumable: shards of 2,000 are written as it goes, and a second run skips what is there.
"""
import argparse
import gzip
import random
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import torch

from pobj.data.pretrain_set import (mmseqs_similar, parse_alphafold, write_fasta,
                                    write_megascale_fasta)

RAW = Path("data/raw/alphafold")
PROCESSED = Path("data/processed")
SHARDS = PROCESSED / "alphafold"

SWISSPROT_URL = ("https://ftp.ebi.ac.uk/pub/databases/uniprot/current_release/"
                 "knowledgebase/complete/uniprot_sprot.fasta.gz")
FILE_URL = "https://alphafold.ebi.ac.uk/files/AF-{acc}-F1-model_v6.pdb"
USER_AGENT = "pobj-research/0.1"          # the files endpoint returns 403 without one


class RateLimiter:
    """Hold the whole process to a fixed number of requests per second.

    AlphaFold DB rate limits well below what it can serve: 24 workers were blocked within
    a thousand requests, and even 6 tripped it afterwards. Capping the rate explicitly is
    more reliable than guessing a worker count, and it is the polite way to use a shared
    public service.
    """

    def __init__(self, per_second):
        self.interval = 1.0 / per_second if per_second else 0.0
        self.lock = threading.Lock()
        self.next_slot = 0.0

    def wait(self):
        if not self.interval:
            return
        with self.lock:
            now = time.monotonic()
            self.next_slot = max(now, self.next_slot) + self.interval
            delay = self.next_slot - now
        if delay > 0:
            time.sleep(delay)


limiter = RateLimiter(0)


def fetch(url, timeout=30):
    limiter.wait()
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode()


def swissprot(min_len, max_len):
    """-> {accession: sequence} within the length range."""
    archive = RAW / "uniprot_sprot.fasta.gz"
    if not archive.exists():
        print(f"downloading Swiss-Prot ({SWISSPROT_URL})", flush=True)
        archive.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(SWISSPROT_URL, archive)

    sequences, acc, chunks = {}, None, []
    with gzip.open(archive, "rt") as f:
        for line in f:
            if line.startswith(">"):
                if acc and min_len <= sum(map(len, chunks)) <= max_len:
                    sequences[acc] = "".join(chunks)
                acc, chunks = line.split("|")[1], []
            else:
                chunks.append(line.strip())
    if acc and min_len <= sum(map(len, chunks)) <= max_len:
        sequences[acc] = "".join(chunks)
    return sequences


# A 404 is a final answer: AlphaFold has no model for that accession. These are not, so
# an accession skipped for one of them is tried again on the next run.
RETRYABLE = {"http_429", "server_error", "network_error"}


def already_done():
    done, kept = set(), 0
    for shard in SHARDS.glob("shard_*.pt"):
        blob = torch.load(shard, weights_only=False)
        for entry in blob["skipped"]:
            acc, reason = entry if isinstance(entry, tuple) else (entry, None)
            if reason not in RETRYABLE:
                done.add(acc)
        done |= {r["acc"] for r in blob["structures"]}
        kept += len(blob["structures"])
    return done, kept


def download_one(acc, min_plddt, min_len, max_len):
    """-> (record, None) if usable, else (None, why it was skipped).

    Over half of Swiss-Prot accessions have no model in AlphaFold DB, so a 404 is an
    ordinary answer and must not be retried. Retrying those was costing three seconds of
    sleep each and held the whole download to a tenth of the achievable rate.
    """
    for attempt in range(4):
        try:
            text = fetch(FILE_URL.format(acc=acc))
            break
        except urllib.error.HTTPError as error:
            if error.code == 429:                        # rate limited: wait, then retry
                if attempt == 3:
                    return None, "http_429"
                wait = float(error.headers.get("Retry-After") or 5 * (attempt + 1) ** 2)
                time.sleep(min(wait, 60))
            elif error.code < 500:                       # 404 and friends: a final answer
                return None, f"http_{error.code}"
            elif attempt == 3:
                return None, "server_error"
            else:
                time.sleep(2 ** attempt)
        except Exception:
            if attempt == 3:
                return None, "network_error"
            time.sleep(2 ** attempt)

    seq, coords, plddt = parse_alphafold(text)
    if coords is None:
        return None, "unparseable"
    if not (min_len <= len(seq) <= max_len):
        return None, "bad_length"
    if plddt < min_plddt:
        return None, "low_plddt"
    return {"acc": acc, "seq": seq, "coords": coords, "plddt": plddt}, None


def candidate_accessions(args):
    """Length-filtered, leakage-filtered, in a fixed shuffled order."""
    cache = PROCESSED / "alphafold_candidates.txt"
    if cache.exists():
        return cache.read_text().split()

    sequences = swissprot(args.min_len, args.max_len)
    print(f"{len(sequences):,} Swiss-Prot entries of {args.min_len}-{args.max_len} residues",
          flush=True)

    query_fa = PROCESSED / "swissprot_filtered.fasta"
    target_fa = PROCESSED / "megascale.fasta"
    write_fasta(query_fa, sequences)
    n_targets = write_megascale_fasta(target_fa)
    print(f"searching against {n_targets} MegaScale proteins with mmseqs", flush=True)

    removed, close = mmseqs_similar(query_fa, target_fa,
                                    PROCESSED / "swissprot_vs_megascale.m8",
                                    PROCESSED / "mmseqs_tmp")
    print(f"removing {len(removed):,} similar entries "
          f"({len(close):,} of them at 30% identity or more)", flush=True)

    kept = sorted(set(sequences) - removed)
    random.Random(args.seed).shuffle(kept)
    cache.write_text("\n".join(kept) + "\n")
    (PROCESSED / "alphafold_removed_similar.txt").write_text("\n".join(sorted(removed)) + "\n")
    return kept


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=50_000,
                        help="usable structures wanted, not accessions attempted")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--rate", type=float, default=4.0,
                        help="requests per second across all workers")
    parser.add_argument("--min-plddt", type=float, default=70.0)
    parser.add_argument("--min-len", type=int, default=30)
    parser.add_argument("--max-len", type=int, default=256)
    parser.add_argument("--shard-size", type=int, default=2000)
    args = parser.parse_args()

    global limiter
    limiter = RateLimiter(args.rate)

    SHARDS.mkdir(parents=True, exist_ok=True)
    candidates = candidate_accessions(args)

    # One request first. Starting a long run while the server is rate limiting us only
    # keeps the limit alive, and the threads would sit in backoff doing nothing.
    _, reason = download_one(candidates[0], 0, 1, 10_000)
    if reason == "http_429":
        sys.exit("rate limited (429) before starting. Wait, then rerun with fewer "
                 "--workers. 24 triggered the limit; 4 to 8 is the safe range.")
    done, kept_already = already_done()
    todo = [a for a in candidates if a not in done]

    wanted = max(0, args.n - kept_already)
    print(f"{len(candidates):,} candidates, {kept_already:,} structures already kept, "
          f"{wanted:,} still wanted, {len(todo):,} accessions left to try", flush=True)
    if not wanted or not todo:
        sys.exit(0)

    index = len(list(SHARDS.glob("shard_*.pt")))
    structures, skipped, reasons = [], [], {}
    attempted, kept, start = 0, 0, time.time()

    def save_shard():
        nonlocal index, structures, skipped
        torch.save({"structures": structures, "skipped": skipped},
                   SHARDS / f"shard_{index:03d}.pt")
        index += 1
        structures, skipped = [], []

    # Work through the candidates in chunks and stop once we have enough, since more than
    # half of them turn out to have no model.
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for chunk_start in range(0, len(todo), args.shard_size):
            chunk = todo[chunk_start:chunk_start + args.shard_size]
            for acc, (record, reason) in zip(chunk, pool.map(
                    lambda a: download_one(a, args.min_plddt, args.min_len, args.max_len),
                    chunk)):
                attempted += 1
                if record:
                    structures.append(record)
                    kept += 1
                else:
                    skipped.append((acc, reason))
                    reasons[reason] = reasons.get(reason, 0) + 1

            save_shard()
            rate = attempted / (time.time() - start)
            remaining = (wanted - kept) / max(0.01, kept / attempted) / max(rate, 0.01)
            print(f"kept {kept:,}/{wanted:,}  tried {attempted:,}  {rate:.1f}/s  "
                  f"eta {remaining / 60:.0f} min  skips {reasons}", flush=True)
            if kept >= wanted:
                break

    if structures or skipped:
        save_shard()
    print(f"\ndone. {kept_already + kept:,} usable structures in {SHARDS}", flush=True)


if __name__ == "__main__":
    main()
