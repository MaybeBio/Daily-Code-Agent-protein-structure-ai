"""Move the paper's datasets to GleghornLab, make every repository it uses public and file them in one collection.

    py -m projects.representation.plm_interpretability.scripts.publish_collection [--apply]

The paper's public Gleghorn Lab collection holds every model and dataset it uses; every repository moves to GleghornLab
except the FastPLMs models and the Bernett datasets. Without `--apply` it prints the plan. A moved
repository keeps its history and commit hashes, and the Hub redirects the old name.
"""

import sys

from pathlib import Path
from huggingface_hub import HfApi, hf_hub_download

from foundry.secrets_env import load_secrets_env


MOVES = (("Synthyra/protein_concept_probing", "GleghornLab/protein_concept_probing"),
         ("Synthyra/esmc300_tap_probing_results", "GleghornLab/esmc_tap_probing_results"))
DATASETS = ("GleghornLab/protein_concept_probing", "Synthyra/bernett_gold_ppi_2", "Synthyra/bernett_gold_ppi",
            "GleghornLab/esmc_tap_probing_results")
MODELS = ("Synthyra/ESMplusplus_small", "Synthyra/ESMplusplus_large", "Synthyra/ESMplusplus_6B")
TITLE = "Exhaustive hidden-state probing"
DESCRIPTION = "Models, datasets and results of the exhaustive hidden-state probing study of ESM Cambrian models."
NOTES = {
    "Synthyra/ESMplusplus_small": "ESMC-300, FastPLMs implementation",
    "Synthyra/ESMplusplus_large": "ESMC-600, FastPLMs implementation",
    "Synthyra/ESMplusplus_6B": "ESMC-6B, FastPLMs implementation",
    "GleghornLab/protein_concept_probing": "22 concept tasks with homology splits",
    "Synthyra/bernett_gold_ppi_2": "Bernett et al. 2026 least-biased PPI gold standard (Supplement)",
    "Synthyra/bernett_gold_ppi": "Bernett et al. 2024 PPI gold standard (main text)",
    "GleghornLab/esmc_tap_probing_results": "First archive: every score, selection, interval and analysis table of the survey",
}

apply = "--apply" in sys.argv
load_secrets_env(path=Path.home() / "Dropbox" / ".secrets.env")
api = HfApi()
for source, target in MOVES:
    if api.repo_exists(target, repo_type="dataset"):
        print("already moved:", target)
        continue
    print("move", source, "->", target)
    if apply:
        api.move_repo(source, target, repo_type="dataset")
unmoved = {target: source for source, target in MOVES if not api.repo_exists(target, repo_type="dataset")}
for repo, kind in [(repo, "dataset") for repo in DATASETS] + [(repo, "model") for repo in MODELS]:
    repository = api.repo_info(unmoved.get(repo, repo), repo_type=kind)
    print(repo, "private" if repository.private else "public", repository.sha[:8])
    if repository.private and apply:
        api.update_repo_settings(repo, repo_type=kind, private=False)
existing = [collection for collection in api.list_collections(owner="GleghornLab", limit=100) if collection.title == TITLE]
print("collection:", existing[0].slug if existing else "to create")
if apply:
    collection = existing[0] if existing else api.create_collection(TITLE, namespace="GleghornLab", description=DESCRIPTION, private=False)
    for repo, kind in [(repo, "model") for repo in MODELS] + [(repo, "dataset") for repo in DATASETS]:
        api.add_collection_item(collection.slug, repo, kind, note=NOTES[repo], exists_ok=True)
    collection = api.get_collection(collection.slug)
    print("collection:", collection.slug, "private" if collection.private else "public", len(collection.items), "items")
    for item in collection.items:
        repository = api.repo_info(item.item_id, repo_type=item.item_type)
        print(" ", item.item_type, item.item_id, "private" if repository.private else "public", repository.sha[:8])
# The results card names the repositories as they were when it was written.
card_path = Path(hf_hub_download(MOVES[1][1], "README.md", repo_type="dataset"))
card = card_path.read_text(encoding="utf-8")
renamed = card
for source, target in MOVES:
    renamed = renamed.replace(source, target)
renamed = renamed.replace("# ESMC tap-probing results", "# Exhaustive hidden-state probing: results")
print("results card:", "up to date" if renamed == card else "names to update")
if apply and renamed != card:
    commit = api.upload_file(path_or_fileobj=renamed.encode("utf-8"), path_in_repo="README.md", repo_id=MOVES[1][1], repo_type="dataset",
                             commit_message="Card: repositories renamed to GleghornLab")
    print("results card updated:", commit.oid[:8])
