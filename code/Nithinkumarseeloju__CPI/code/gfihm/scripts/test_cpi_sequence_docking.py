import math
import tempfile
import threading
import time
import unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch

import torch
from rdkit import Chem
import cpi_sequence_docking as docking
from cpi_docking import _meeko_rejected_residues, _pose_matches_query, _rejected_residues_in_box
from cpi_sequence_docking import MAX_SEQUENCE_LENGTH, _read_pockets, predict_and_dock
from predict_esmfold import _find_cached_checkpoint, _infer_pdb_text, _inference_dtype, _install_tm_nan_guard


class PocketPredictionTests(unittest.TestCase):
    def test_reads_padded_p2rank_csv_and_orders_by_rank(self):
        contents = (
            " rank , score , probability , center_x , center_y , center_z , residue_ids \n"
            "2,0.72,0.81,10.0,11.0,12.0,\"A_10,A_11\"\n"
            "1,0.94,0.93,1.0,2.0,3.0,\"A_1,A_2\"\n"
            "3,0.15,1.4,4.0,5.0,6.0,A_3\n"
            "4,0.12,nan,4.0,5.0,6.0,A_4\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pockets.csv"
            path.write_text(contents, encoding="utf-8")

            pockets = _read_pockets(path)

        self.assertEqual([pocket["rank"] for pocket in pockets], [1, 2])
        self.assertEqual(pockets[0]["center"], [1.0, 2.0, 3.0])
        self.assertEqual(pockets[0]["residue_ids"], "A_1,A_2")

    def test_rejects_malformed_pocket_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pockets.csv"
            path.write_text("rank,score,probability,center_x\n1,0.8,0.9,1.0\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "invalid pocket row"):
                _read_pockets(path)

    def test_rejects_sequences_over_esmfold_limit_before_starting_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, f"up to {MAX_SEQUENCE_LENGTH} residues"):
                predict_and_dock("CCO", "A" * (MAX_SEQUENCE_LENGTH + 1), directory)


class ESMFoldSetupTests(unittest.TestCase):
    def test_upcasts_bfloat16_outputs_before_pdb_serialization(self):
        seen_dtypes = []

        def output_to_pdb(output):
            seen_dtypes.extend(value.dtype for value in output.values())
            return ["ATOM"]

        model = SimpleNamespace(
            infer=lambda sequence: {
                "coordinates": torch.ones(3, dtype=torch.bfloat16),
                "residue_index": torch.ones(1, dtype=torch.long),
            },
            output_to_pdb=output_to_pdb,
        )

        self.assertEqual(_infer_pdb_text(model, "ACD", torch), "ATOM")
        self.assertEqual(seen_dtypes, [torch.float32, torch.long])

    def test_meeko_rejected_residues_are_parsed_and_overlapping_pockets_are_skipped(self):
        residues = _meeko_rejected_residues(
            "No template matched for residue_key='A:337'\n"
            "No template matched for residue_key='A:362'\n"
        )
        self.assertEqual(residues, ["A:337", "A:362"])

        rejected_atoms = {
            "A:362": [[5.5, -6.1, -6.2]],
            "A:337": [[52.0, 0.0, 0.0]],
        }
        self.assertEqual(_rejected_residues_in_box(rejected_atoms, [0, 0, 0], [22, 22, 22]), ["A:362"])
        self.assertEqual(_rejected_residues_in_box(rejected_atoms, [42, 0, 0], [22, 22, 22]), ["A:337"])

    def test_selects_bfloat16_when_supported_and_float32_otherwise(self):
        torch_stub = SimpleNamespace(
            bfloat16="bfloat16",
            float32="float32",
            cuda=SimpleNamespace(is_bf16_supported=lambda: True),
        )
        self.assertEqual(_inference_dtype(torch_stub), "bfloat16")

        torch_stub.cuda.is_bf16_supported = lambda: False
        self.assertEqual(_inference_dtype(torch_stub), "float32")

    def test_prefers_complete_checkpoint_in_huggingface_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_home = Path(directory)
            snapshot = (
                cache_home
                / "hub"
                / "models--facebook--esmfold_v1"
                / "snapshots"
                / "cached-revision"
            )
            snapshot.mkdir(parents=True)
            (snapshot / "config.json").write_text("{}", encoding="utf-8")
            (snapshot / "pytorch_model.bin").write_bytes(b"checkpoint")
            refs = snapshot.parent.parent / "refs"
            refs.mkdir()
            (refs / "main").write_text("cached-revision", encoding="utf-8")

            self.assertEqual(_find_cached_checkpoint(cache_home), snapshot)

    def test_ignores_incomplete_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_home = Path(directory)
            blobs = cache_home / "hub" / "models--facebook--esmfold_v1" / "blobs"
            blobs.mkdir(parents=True)
            (blobs / "model.safetensors.incomplete").write_bytes(b"partial")

            self.assertIsNone(_find_cached_checkpoint(cache_home))

    def test_tm_logits_are_upcast_and_nonfinite_score_is_explicitly_unavailable(self):
        seen_dtypes = []

        def fake_compute_tm(logits, *args, **kwargs):
            seen_dtypes.append(logits.dtype)
            return logits.sum()

        esm_modeling = SimpleNamespace(compute_tm=fake_compute_tm)
        status = _install_tm_nan_guard(torch, esm_modeling)

        self.assertEqual(esm_modeling.compute_tm(torch.ones(2)), torch.tensor(2.0))
        self.assertEqual(seen_dtypes, [torch.float32])
        self.assertTrue(status["ptm_score_available"])

        with self.assertWarns(RuntimeWarning):
            result = esm_modeling.compute_tm(torch.tensor([float("nan")]))

        self.assertTrue(math.isnan(result.item()))
        self.assertFalse(status["ptm_score_available"])

    def test_serializes_parallel_esmfold_invocations(self):
        counter_lock = threading.Lock()
        active = 0
        maximum_active = 0

        def fake_run(*args, **kwargs):
            nonlocal active, maximum_active
            with counter_lock:
                active += 1
                maximum_active = max(maximum_active, active)
            time.sleep(0.03)
            with counter_lock:
                active -= 1
            return "done"

        with patch.object(docking, "_run_logged", side_effect=fake_run):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(
                    pool.map(
                        lambda _: docking._run_fold_logged([], Path("fold.log"), 1, Path("."), {}),
                        range(2),
                    )
                )

        self.assertEqual(results, ["done", "done"])
        self.assertEqual(maximum_active, 1)


class DockingPoseValidationTests(unittest.TestCase):
    def test_accepts_unspecified_stereochemistry_but_preserves_specified_centers(self):
        unspecified = Chem.MolFromSmiles("CC(O)F")
        generated_stereo = Chem.MolFromSmiles("C[C@H](O)F")
        specified = Chem.MolFromSmiles("C[C@H](O)F")
        opposite = Chem.MolFromSmiles("C[C@@H](O)F")

        self.assertTrue(_pose_matches_query(unspecified, generated_stereo))
        self.assertTrue(_pose_matches_query(specified, generated_stereo))
        self.assertFalse(_pose_matches_query(specified, opposite))

    def test_rejects_pose_with_different_connectivity(self):
        query = Chem.MolFromSmiles("CCO")
        pose = Chem.MolFromSmiles("CCN")

        self.assertFalse(_pose_matches_query(query, pose))


if __name__ == "__main__":
    unittest.main()
