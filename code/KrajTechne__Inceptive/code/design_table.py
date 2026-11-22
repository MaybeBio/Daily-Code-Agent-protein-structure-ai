"""Build the designs table Optimus expects, from a finished BindCraft2 run.

Shared by run_validation.py (builds the CSV before validating) and rescore_validation.py (rebuilds the same
table to re-score saved predictions). It runs on Modal, inside the bridge image, where the Optimus helpers
(designs_from_structures, StrucTools) are available.
"""
import shutil
import tempfile


def build_design_table(run_name: str, top_n, binder_chain: str, identical_segments: dict,
                       read_mount: str, ref_mount: str):
    """
    One row per ranked design (best `top_n`, or all when top_n is None).

    read_mount: where the runs Volume is mounted in this container (to read the ranked designs).
    ref_mount : where Optimus will see the same Volume (/outputs); recorded as each design's reference structure.
    identical_segments: {target chain letter: "start-end,start-end"} for targets that repeat inside one chain,
                        written as the `identical_segments_target_<chain>` column ({} for none).
    """
    import pandas as pd
    from designs_from_structures import designs_from_structures  # from Optimus

    ranked_dir = f"{read_mount}/{run_name}/design/3_Ranked"
    ranked = pd.read_csv(f"{ranked_dir}/!_Ranked.csv").sort_values("rank")
    if top_n is not None:
        ranked = ranked.head(top_n)
    if ranked.empty:
        raise ValueError(f"No ranked designs found in {ranked_dir}")

    # Copy just the chosen designs into a scratch folder for Optimus's script.
    with tempfile.TemporaryDirectory() as scratch:
        for name in ranked["design"]:
            shutil.copy(f"{ranked_dir}/{name}.cif", scratch)
        designs = designs_from_structures(scratch, binder_chain=binder_chain)

    # Optimus compares each prediction with the BindCraft2 design structure (RMSD columns). The scratch copy is gone
    # after this function, so point at the design's file on the Volume, at the path Optimus sees it under.
    designs["path_structure_ref"] = [f"{ref_mount}/{run_name}/design/3_Ranked/{name}.cif"
                                     for name in designs["design_name"]]
    for chain, segments in (identical_segments or {}).items():
        designs[f"identical_segments_target_{chain}"] = segments
    return designs
