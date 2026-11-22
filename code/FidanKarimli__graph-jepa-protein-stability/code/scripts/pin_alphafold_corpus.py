"""Record exactly which AlphaFold structures the pretraining corpus contains.

Run from the repo root:  python scripts/pin_alphafold_corpus.py

SCOPe has data/processed/pretrain_ids.txt. Without the equivalent here the corpus is only
"whatever is in the shards", and accessions skipped for a retryable reason (878 of them
were rate-limited) would be fetched by any later run, quietly changing the corpus under the
same name. This writes the list and a short summary, both of which are committed.
"""
import collections
from pathlib import Path

import torch

SHARDS = Path("data/processed/alphafold")
IDS = Path("data/processed/alphafold_ids.txt")
SUMMARY = Path("data/processed/alphafold_corpus.md")


def main():
    shards = sorted(SHARDS.glob("shard_*.pt"))
    if not shards:
        raise SystemExit(f"no shards in {SHARDS}")

    accessions, lengths, plddt = [], [], []
    skipped = collections.Counter()
    for shard in shards:
        blob = torch.load(shard, weights_only=False)
        for record in blob["structures"]:
            accessions.append(record["acc"])
            lengths.append(len(record["seq"]))
            plddt.append(record["plddt"])
        for entry in blob["skipped"]:
            skipped[entry[1] if isinstance(entry, tuple) else "unrecorded"] += 1

    if len(set(accessions)) != len(accessions):
        raise SystemExit(f"duplicate accessions: {len(accessions) - len(set(accessions))}")

    order = sorted(accessions)
    IDS.write_text("\n".join(order) + "\n")

    lengths.sort()
    attempted = len(accessions) + sum(skipped.values())
    summary = [
        "# AlphaFold pretraining corpus",
        "",
        f"- structures: **{len(accessions):,}**",
        f"- attempted: {attempted:,} accessions ({len(accessions) / attempted:.1%} usable)",
        f"- residues: {sum(lengths):,}",
        f"- length: min {lengths[0]}, median {lengths[len(lengths) // 2]}, max {lengths[-1]}",
        f"- mean pLDDT: {sum(plddt) / len(plddt):.1f} (filter was >= 70)",
        f"- shards: {len(shards)}",
        "",
        "Skipped, by reason:",
        "",
        *[f"- {reason}: {count:,}" for reason, count in skipped.most_common()],
        "",
        "Sampled with seed 0 from `alphafold_candidates.txt`, which is Swiss-Prot filtered",
        "to 30-256 residues and screened against all 298 MegaScale proteins with MMseqs2.",
        "Accession list: `alphafold_ids.txt`.",
    ]
    SUMMARY.write_text("\n".join(summary) + "\n")

    print("\n".join(summary))
    print(f"\nwrote {IDS} and {SUMMARY}")


if __name__ == "__main__":
    main()
