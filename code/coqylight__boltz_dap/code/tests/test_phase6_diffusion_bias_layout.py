from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import weakref

import torch

import dap_diffusion_score
from boltz.model.layers.token_bias import LayerwiseTokenBias
from boltz.model.modules.transformersv2 import DiffusionTransformer
from dap_cached_token_attention import (
    CachedTokenAttentionService, ShardedTokenBiasCache, plan_cached_query_intervals, run_cached_token_stack,
    run_cached_diffusion_sampling,
)


class _IdentityLayer(torch.nn.Module):
    pass


def _run_with_bias(token_bias: torch.Tensor) -> list[torch.Tensor]:
    captured_biases = []

    def run_layer(
        layer,
        activation,
        conditioning,
        local_bias,
        mask,
        query_start,
        query_end,
    ):
        del layer, conditioning, mask
        captured_biases.append(local_bias.clone())
        return activation[:, query_start:query_end]

    transformer = SimpleNamespace(
        layers=torch.nn.ModuleList([_IdentityLayer(), _IdentityLayer()])
    )
    activation = torch.zeros(1, 3, 4)
    with patch.object(
        dap_diffusion_score,
        "run_query_sharded_diffusion_layer",
        run_layer,
    ):
        dap_diffusion_score._run_token_stack(
            transformer,
            activation,
            torch.zeros_like(activation),
            token_bias,
            torch.ones(1, 3),
            query_rows=2,
        )
    return captured_biases


def distributed_cache_probe():
    import torch.distributed as dist

    dist.init_process_group("gloo", timeout=timedelta(seconds=30))
    rank = dist.get_rank()
    torch.set_num_threads(1)
    torch.manual_seed(2028157270)
    layers = torch.nn.ModuleList([
        torch.nn.Sequential(torch.nn.LayerNorm(4), torch.nn.Linear(4, 2, bias=False))
        for _ in range(2)
    ]).eval()
    transformer = DiffusionTransformer(depth=2, heads=2, dim=8, dim_single_cond=8).eval()
    for parameter in transformer.parameters():
        parameter.data.normal_(0, 0.1)
    source = torch.randn(2, 7, 7, 4).transpose(1, 2)
    provider = LayerwiseTokenBias(layers, source, 2) if rank == 0 else None
    mask = torch.tensor([[1, 1, 1, 1, 1, 0, 0], [1, 1, 1, 0, 0, 0, 0]]).float()
    with torch.no_grad():
        cache = ShardedTokenBiasCache.build(
            provider, layers, tokens=7, batch=2, query_rows=4, projection_rows=2,
            device="cpu", binding="distributed-test", cache_capacity_bytes=0 if rank == 0 else 100000)
        projections = cache.projection_calls
        transfers = cache.source_transfer_bytes
        for _ in range(3):
            activation, conditioning = torch.randn(2, 7, 8), torch.randn(2, 7, 8)
            rng = torch.get_rng_state().clone()
            actual = run_cached_token_stack(transformer, activation, conditioning, cache, mask,
                                            binding="distributed-test")
            assert torch.equal(rng, torch.get_rng_state())
            assert cache.projection_calls == projections and cache.source_transfer_bytes == transfers
            if rank == 0:
                with patch.dict(os.environ, {"BOLTZ_DIFFUSION_STREAM_TOKEN_BIAS": "1",
                                             "BOLTZ_DIFFUSION_REUSE_TOKEN_PROJECTIONS": "1"}):
                    expected = dap_diffusion_score._run_token_stack(
                        transformer, activation, conditioning, provider, mask, 4)
                torch.testing.assert_close(actual, expected, rtol=0, atol=0)
        cache.close()
        service = CachedTokenAttentionService(transformer, layers, device="cpu", binding="service-test",
                                               query_rows=4, projection_rows=2)
        if rank == 0:
            service.prepare(provider)
            projection_calls = service.cache.projection_calls
            for _ in range(3):
                activation, conditioning = torch.randn(2, 7, 8), torch.randn(2, 7, 8)
                with patch.dict(os.environ, {"BOLTZ_DIFFUSION_STREAM_TOKEN_BIAS": "1",
                                             "BOLTZ_DIFFUSION_REUSE_TOKEN_PROJECTIONS": "1"}):
                    expected = dap_diffusion_score._run_token_stack(
                        transformer, activation, conditioning, provider, mask, 4)
                rng = torch.get_rng_state().clone()
                actual = service.run(transformer, activation, conditioning, provider, mask, 4)
                torch.testing.assert_close(actual, expected, rtol=0, atol=0)
                assert torch.equal(rng, torch.get_rng_state())
                assert service.cache.projection_calls == projection_calls
            service.close()
        else:
            service.serve()
        for prediction in range(2):
            source = torch.randn(2, 7, 7, 4).transpose(1, 2)
            provider = LayerwiseTokenBias(layers, source, 2)
            with torch.autocast("cpu", dtype=torch.bfloat16):
                expected_bias = torch.stack([
                    torch.cat([layer(source[:, start:start + 2]) for start in range(0, 7, 2)], dim=1)
                    for layer in layers
                ]).float()
            sampling_calls = []

            def sample(**kwargs):
                assert kwargs["num_sampling_steps"] == 3
                assert not torch.is_autocast_enabled("cpu")
                sampling_calls.append(kwargs)
                for _ in range(kwargs["num_sampling_steps"]):
                    activation, conditioning = torch.randn(2, 7, 8), torch.randn(2, 7, 8)
                    rng = torch.get_rng_state().clone()
                    actual = dap_diffusion_score._run_token_stack(
                        transformer, activation, conditioning, provider, mask, 4)
                    expected = activation
                    for index, layer in enumerate(transformer.layers):
                        expected = dap_diffusion_score.run_chunked_diffusion_layer(
                            layer, expected, conditioning, expected_bias[index], mask, 4)
                    torch.testing.assert_close(actual, expected, rtol=0, atol=0)
                    assert torch.equal(rng, torch.get_rng_state())
                return {"sample_atom_coords": actual}

            structure = SimpleNamespace(score_model=SimpleNamespace(token_transformer=transformer), sample=sample)
            kwargs = {"num_sampling_steps": 3, "diffusion_conditioning": {"token_trans_bias": provider}}
            with torch.autocast("cpu", dtype=torch.bfloat16):
                result = run_cached_diffusion_sampling(
                    structure, layers, kwargs if rank == 0 else None, device="cpu",
                    binding=f"bf16-prediction-{prediction}", projection_precision="bf16-mixed",
                    query_rows=4, projection_rows=2)
                assert torch.is_autocast_enabled("cpu")
            assert len(sampling_calls) == (1 if rank == 0 else 0)
            assert (result is not None) == (rank == 0)
            assert not hasattr(transformer, "_dap_token_attention_service")
            assert structure._dap_cache_receipt["closed"]
            assert structure._dap_cache_receipt["projection_precision"] == "bf16-mixed"
    dist.destroy_process_group()


class TokenBiasLayoutTest(unittest.TestCase):
    def test_token_service_resolves_implicit_cuda_device(self) -> None:
        for local_rank in range(8):
            with self.subTest(local_rank=local_rank), \
                    patch("torch.distributed.get_rank", return_value=local_rank), \
                    patch("torch.cuda.current_device", return_value=local_rank):
                service = CachedTokenAttentionService(None, [], device="cuda", binding="device-test")
                self.assertEqual(service.device, torch.device("cuda", local_rank))
                explicit = CachedTokenAttentionService(None, [], device="cuda:7", binding="explicit-test")
                self.assertEqual(explicit.device, torch.device("cuda:7"))
                cpu = CachedTokenAttentionService(None, [], device="cpu", binding="cpu-test")
                self.assertEqual(cpu.device, torch.device("cpu"))

    def test_token_service_transport_keeps_strict_device_and_dtype_checks(self) -> None:
        for rank in (0, 3):
            with self.subTest(rank=rank), patch("torch.distributed.get_rank", return_value=rank), \
                    patch("torch.cuda.current_device", return_value=3):
                service = CachedTokenAttentionService(None, [], device="cuda", binding="transport-test")
                value = SimpleNamespace(shape=(1, 7, 8), dtype=torch.float32, device=torch.device("cuda:3"))
                value.contiguous = lambda: value

                def metadata(payload, src):
                    self.assertEqual(src, 0)
                    payload[0] = (value.shape, value.dtype)

                with patch("torch.distributed.broadcast_object_list", side_effect=metadata), \
                        patch("torch.distributed.broadcast") as broadcast, \
                        patch("torch.empty", return_value=value):
                    self.assertIs(service._tensor(value if rank == 0 else None), value)
                    broadcast.assert_called_once_with(value, src=0)
                    value.device = torch.device("cuda:2")
                    with self.assertRaisesRegex(ValueError, "wrong device"):
                        service._tensor(value if rank == 0 else None)
                    value.device = torch.device("cuda:3")
                    value.dtype = torch.bfloat16
                    with self.assertRaisesRegex(ValueError, "transport must be FP32"):
                        service._tensor(value if rank == 0 else None)

    def test_full60_layerwise_handoff_avoids_materialized_host_bias(self) -> None:
        from dap_trunk import _run_token_trans_bias_from_zcond_cpu

        tokens = 31140
        layers = torch.nn.ModuleList([
            torch.nn.Sequential(torch.nn.LayerNorm(128), torch.nn.Linear(128, 16, bias=False))
            for _ in range(24)
        ]).eval()
        source = torch.zeros(1).expand(1, tokens, tokens, 128)
        with torch.no_grad(), patch("dap_trunk.torch.empty", side_effect=AssertionError("host allocation")), \
                patch.object(torch.nn.Module, "cuda", side_effect=AssertionError("CUDA projection")):
            provider = _run_token_trans_bias_from_zcond_cpu(
                layers, source, 32, layout="layerwise", storage_dtype=torch.float32)
        self.assertIsInstance(provider, LayerwiseTokenBias)
        self.assertIs(provider.conditioned, source)
        self.assertEqual(len(provider), 24)
        self.assertEqual(source.untyped_storage().nbytes(), 4)
        self.assertEqual(tokens * tokens * 24 * 16 * 4, 1489458585600)

    @unittest.skipUnless(torch.cuda.is_available(), "requires CUDA")
    def test_bf16_cache_cuda_matches_streamed_reference(self) -> None:
        from dap_trunk import _run_token_trans_bias_from_zcond_cpu

        torch.manual_seed(2028157270)
        layers = torch.nn.ModuleList([
            torch.nn.Sequential(torch.nn.LayerNorm(128), torch.nn.Linear(128, 16, bias=False))
            for _ in range(24)
        ]).eval().cuda()
        source = torch.randn(1, 129, 129, 128)
        provider = LayerwiseTokenBias(layers, source, 32)
        matmul_tf32, cudnn_tf32 = torch.backends.cuda.matmul.allow_tf32, torch.backends.cudnn.allow_tf32
        torch.backends.cuda.matmul.allow_tf32 = torch.backends.cudnn.allow_tf32 = False
        try:
            with torch.no_grad():
                with torch.autocast("cuda", dtype=torch.bfloat16):
                    expected = _run_token_trans_bias_from_zcond_cpu(
                        layers, source, 32, layout="layer_major", storage_dtype=torch.float32)
                cpu_rng, cuda_rng = torch.get_rng_state().clone(), torch.cuda.get_rng_state().clone()
                cache = ShardedTokenBiasCache.build(
                    provider, layers, tokens=129, batch=1, query_rows=128, projection_rows=32,
                    device="cuda:0", binding="cuda-bf16", cache_capacity_bytes=2**30,
                    projection_precision="bf16-mixed")
                torch.testing.assert_close(cache.values.cpu(), expected, rtol=0, atol=0)
                self.assertTrue(torch.equal(cpu_rng, torch.get_rng_state()))
                self.assertTrue(torch.equal(cuda_rng, torch.cuda.get_rng_state()))
                cache.close()
        finally:
            torch.backends.cuda.matmul.allow_tf32 = matmul_tf32
            torch.backends.cudnn.allow_tf32 = cudnn_tf32

    def test_bf16_cache_projects_before_fp32_storage(self) -> None:
        torch.manual_seed(2028157270)
        layers = torch.nn.ModuleList([
            torch.nn.Sequential(torch.nn.LayerNorm(4), torch.nn.Linear(4, 2, bias=False))
            for _ in range(2)
        ]).eval()
        source = torch.randn(2, 7, 7, 4).transpose(1, 2)
        provider = LayerwiseTokenBias(layers, source, 2)
        with torch.no_grad():
            with torch.autocast("cpu", dtype=torch.bfloat16):
                expected = torch.stack([
                    torch.cat([layer(source[:, start:start + 2])
                               for start in range(0, 7, 2)], dim=1)
                    for layer in layers
                ]).float()
            rng = torch.get_rng_state().clone()
            cache = ShardedTokenBiasCache.build(
                provider, layers, tokens=7, batch=2, query_rows=4, projection_rows=2,
                device="cpu", binding="bf16-prediction", cache_capacity_bytes=100000,
                projection_precision="bf16-mixed")
            self.assertTrue(torch.equal(rng, torch.get_rng_state()))
            self.assertEqual(cache.values.dtype, torch.float32)
            self.assertEqual(cache.projection_precision, "bf16-mixed")
            torch.testing.assert_close(cache.values, expected, rtol=0, atol=0)
            torch.testing.assert_close(cache.values, cache.values.bfloat16().float(), rtol=0, atol=0)
            fp32_cache = ShardedTokenBiasCache.build(
                provider, layers, tokens=7, batch=2, query_rows=4, projection_rows=2,
                device="cpu", binding="fp32-prediction", cache_capacity_bytes=100000)
            self.assertFalse(torch.equal(cache.values, fp32_cache.values))
            cache.close()
            fp32_cache.close()
            with self.assertRaisesRegex(ValueError, "projection precision"):
                ShardedTokenBiasCache.build(
                    provider, layers, tokens=7, batch=2, query_rows=4, projection_rows=2,
                    device="cpu", binding="invalid", cache_capacity_bytes=100000,
                    projection_precision="16-mixed")

    def test_three_rank_cache_and_attention_exact_with_empty_root(self) -> None:
        environment = dict(os.environ, OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1")
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run(
                [sys.executable, "-m", "torch.distributed.run", "--standalone", "--nproc-per-node=3",
                 "--monitor-interval=0.1", str(Path(__file__).resolve()), "--distributed-cache-probe"],
                env=environment, cwd=temporary, capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_static_cache_reuses_projections_across_changed_activations(self) -> None:
        torch.manual_seed(2028157270)
        layers = torch.nn.ModuleList([
            torch.nn.Sequential(torch.nn.LayerNorm(4), torch.nn.Linear(4, 2, bias=False))
            for _ in range(2)
        ]).eval()
        provider = LayerwiseTokenBias(layers, torch.randn(2, 7, 7, 4).transpose(1, 2), 2)
        transformer = DiffusionTransformer(depth=2, heads=2, dim=8, dim_single_cond=8).eval()
        for parameter in transformer.parameters():
            parameter.data.normal_(0, 0.1)
        mask = torch.tensor([[1, 1, 1, 1, 1, 0, 0], [1, 1, 1, 0, 0, 0, 0]]).float()
        with torch.no_grad():
            rng = torch.get_rng_state().clone()
            cache = ShardedTokenBiasCache.build(
                provider, layers, tokens=7, batch=2, query_rows=4, projection_rows=2,
                device="cpu", binding="prediction-1", cache_capacity_bytes=100000)
            self.assertTrue(torch.equal(rng, torch.get_rng_state()))
            self.assertEqual(cache.projection_calls, 8)
            self.assertEqual(cache.source_transfer_bytes, provider.conditioned.numel() * 4)
            for step in range(3):
                activation, conditioning = torch.randn(2, 7, 8), torch.randn(2, 7, 8)
                with patch.dict(os.environ, {"BOLTZ_DIFFUSION_STREAM_TOKEN_BIAS": "1",
                                             "BOLTZ_DIFFUSION_REUSE_TOKEN_PROJECTIONS": "1"}):
                    expected = dap_diffusion_score._run_token_stack(
                        transformer, activation, conditioning, provider, mask, 4)
                rng = torch.get_rng_state().clone()
                actual = run_cached_token_stack(transformer, activation, conditioning, cache, mask,
                                                binding="prediction-1")
                torch.testing.assert_close(actual, expected, rtol=0, atol=0)
                self.assertTrue(torch.equal(rng, torch.get_rng_state()))
                self.assertEqual(cache.projection_calls, 8)
                self.assertEqual(cache.hits, (step + 1) * 4)
            with self.assertRaisesRegex(ValueError, "changed conditioning"):
                run_cached_token_stack(transformer, activation, conditioning, cache, mask, binding="prediction-2")
            cache.close()
            with self.assertRaisesRegex(ValueError, "Closed cache"):
                cache.rows(0, 0, 1, "prediction-1")

    def test_cache_planner_respects_uneven_capacity(self) -> None:
        chunk_bytes = 2 * 4 * 7 * 2 * 2 * 4
        self.assertEqual(plan_cached_query_intervals(7, 4, 2, 2, 2, [0, chunk_bytes, chunk_bytes]),
                         [(0, 0), (0, 4), (4, 7)])
        with self.assertRaisesRegex(MemoryError, "headroom"):
            plan_cached_query_intervals(7, 4, 2, 2, 2, [0, chunk_bytes])

    def test_full60_cache_plan_preserves_root_workspace(self) -> None:
        tokens = 31140
        baseline_bytes = 23708 * 2**20
        capacities = [77000 * 2**20 - baseline_bytes - reserve * 2**30
                      for reserve in [16] + [3] * 31]
        intervals = plan_cached_query_intervals(tokens, 128, 1, 16, 24, capacities)
        self.assertEqual(intervals[0][0], 0)
        self.assertEqual(intervals[-1][1], tokens)
        total_cache_bytes = 0
        for rank, (start, end) in enumerate(intervals):
            self.assertEqual(start % 128, 0)
            if rank:
                self.assertEqual(start, intervals[rank - 1][1])
            cache_bytes = (end - start) * tokens * 16 * 24 * 4
            self.assertLessEqual(cache_bytes, capacities[rank])
            total_cache_bytes += cache_bytes
        self.assertEqual(total_cache_bytes, tokens * tokens * 16 * 24 * 4)
        self.assertLess(intervals[0][1], intervals[1][1] - intervals[1][0])
        with self.assertRaisesRegex(MemoryError, "headroom"):
            plan_cached_query_intervals(tokens, 128, 1, 16, 24, [30 * 2**30] * 32)

    def test_deterministic_pooling_preserves_formula_rng_and_policy(self) -> None:
        features = torch.randn(2, 13, 8)
        indices = torch.arange(13).remainder(5).expand(2, -1)
        valid = torch.ones(2, 13, dtype=torch.bool)
        valid[:, -2:] = False
        expected = dap_diffusion_score._pool_atom_features_by_token(features, indices, valid, 5)
        enabled = torch.are_deterministic_algorithms_enabled()
        warn_only = torch.is_deterministic_algorithms_warn_only_enabled()
        rng = torch.get_rng_state().clone()
        actual = dap_diffusion_score._pool_atom_features_deterministically(features, indices, valid, 5)
        torch.testing.assert_close(actual, expected, rtol=0, atol=0)
        self.assertTrue(torch.equal(rng, torch.get_rng_state()))
        with patch.object(dap_diffusion_score, "_pool_atom_features_by_token", side_effect=RuntimeError("probe")):
            with self.assertRaisesRegex(RuntimeError, "probe"):
                dap_diffusion_score._pool_atom_features_deterministically(features, indices, valid, 5)
        self.assertEqual(torch.are_deterministic_algorithms_enabled(), enabled)
        self.assertEqual(torch.is_deterministic_algorithms_warn_only_enabled(), warn_only)

    def test_streamed_rows_preserve_tiles_and_exact_outputs(self) -> None:
        torch.manual_seed(2028157270)
        layers = torch.nn.ModuleList([
            torch.nn.Sequential(torch.nn.LayerNorm(4), torch.nn.Linear(4, 2, bias=False))
            for _ in range(2)
        ]).eval()
        values = torch.randn(2, 7, 7, 4).transpose(1, 2)
        provider = LayerwiseTokenBias(layers, values, 3)
        transformer = DiffusionTransformer(depth=2, heads=2, dim=8, dim_single_cond=8).eval()
        for parameter in transformer.parameters():
            parameter.data.normal_(0, 0.1)
        activation, conditioning = torch.randn(2, 7, 8), torch.randn(2, 7, 8)
        mask = torch.tensor([[1, 1, 1, 1, 1, 0, 0], [1, 1, 1, 1, 0, 0, 0]]).float()
        with torch.no_grad():
            full = provider.project_layer(0, torch.device("cpu"))
            for start, end in ((0, 1), (1, 5), (3, 7), (6, 7)):
                shapes = []
                hook = layers[0].register_forward_pre_hook(lambda module, args: shapes.append(args[0].shape[1]))
                try:
                    actual = provider.project_rows(0, start, end, torch.device("cpu"))
                finally:
                    hook.remove()
                torch.testing.assert_close(actual, full[:, start:end], rtol=0, atol=0)
                self.assertEqual(shapes, [min(3, 7 - tile) for tile in range(start // 3 * 3, end, 3)])
            for query_rows in (1, 2, 4, 7):
                with patch.dict(os.environ, {"BOLTZ_DIFFUSION_STREAM_TOKEN_BIAS": "0",
                                             "BOLTZ_DIFFUSION_REUSE_TOKEN_PROJECTIONS": "0"}):
                    expected = dap_diffusion_score._run_token_stack(
                        transformer, activation, conditioning, provider, mask, query_rows)
                for reuse in ("0", "1"):
                    rng = torch.get_rng_state().clone()
                    with patch.dict(os.environ, {"BOLTZ_DIFFUSION_STREAM_TOKEN_BIAS": "1",
                                                 "BOLTZ_DIFFUSION_REUSE_TOKEN_PROJECTIONS": reuse}), \
                            patch.object(provider, "project_layer", side_effect=AssertionError("Full bias materialized")):
                        actual = dap_diffusion_score._run_token_stack(
                            transformer, activation, conditioning, provider, mask, query_rows)
                    torch.testing.assert_close(actual, expected, rtol=0, atol=0)
                    self.assertTrue(torch.equal(rng, torch.get_rng_state()))
            with self.assertRaisesRegex(ValueError, "row interval"):
                provider.project_rows(0, 0, 8, torch.device("cpu"))
        with self.assertRaisesRegex(RuntimeError, "inference-only"):
            provider.project_rows(0, 0, 1, torch.device("cpu"))

    def test_projection_reuse_preserves_layouts_and_bias_lifetime(self) -> None:
        torch.manual_seed(2028157270)
        transformer = DiffusionTransformer(depth=2, heads=2, dim=8, dim_single_cond=8).eval()
        for parameter in transformer.parameters():
            parameter.data.normal_(0, 0.1)
        layers = torch.nn.ModuleList([
            torch.nn.Sequential(torch.nn.LayerNorm(4), torch.nn.Linear(4, 2, bias=False))
            for _ in range(2)
        ]).eval()
        values = torch.randn(1, 5, 5, 4)
        provider = LayerwiseTokenBias(layers, values, 2)
        activation, conditioning = torch.randn(1, 5, 8), torch.randn(1, 5, 8)
        mask = torch.tensor([[1, 1, 1, 0, 0]]).float()
        references = []
        original_project = provider.project_layer

        def project(index, device):
            self.assertTrue(all(reference() is None for reference in references))
            bias = original_project(index, device)
            references.append(weakref.ref(bias))
            return bias

        with torch.no_grad():
            materialized = torch.cat([
                torch.cat([layer(values[:, start:start + 2]) for start in range(0, 5, 2)], dim=1)
                for layer in layers
            ], dim=-1)
            layer_major = materialized.view(1, 5, 5, 2, 2).permute(3, 0, 1, 2, 4)
            for query_rows in (1, 2, 5):
                with patch.dict(os.environ, {"BOLTZ_DIFFUSION_REUSE_TOKEN_PROJECTIONS": "0"}):
                    expected = dap_diffusion_score._run_token_stack(
                        transformer, activation, conditioning, materialized, mask, query_rows,
                    )
                for bias in (materialized, layer_major, layer_major.contiguous(), provider):
                    initial_rng = torch.get_rng_state().clone()
                    with patch.dict(os.environ, {"BOLTZ_DIFFUSION_REUSE_TOKEN_PROJECTIONS": "1"}), \
                            patch.object(provider, "project_layer", side_effect=project):
                        actual = dap_diffusion_score._run_token_stack(
                            transformer, activation, conditioning, bias, mask, query_rows,
                        )
                    torch.testing.assert_close(actual, expected, rtol=0, atol=0)
                    self.assertTrue(torch.equal(initial_rng, torch.get_rng_state()))
                    self.assertTrue(all(reference() is None for reference in references))

    def test_layerwise_exact_and_releases_previous_bias(self) -> None:
        torch.manual_seed(11)
        transformer = DiffusionTransformer(depth=2, heads=2, dim=8, dim_single_cond=8).eval()
        for parameter in transformer.parameters():
            parameter.data.normal_(0, 0.1)
        layers = torch.nn.ModuleList([
            torch.nn.Sequential(torch.nn.LayerNorm(4), torch.nn.Linear(4, 2, bias=False))
            for _ in range(2)
        ]).eval()
        values = torch.randn(1, 5, 5, 4)
        provider = LayerwiseTokenBias(layers, values, 2)
        activation, conditioning = torch.randn(1, 5, 8), torch.randn(1, 5, 8)
        references = []
        original_project = provider.project_layer

        def project(index, device):
            self.assertTrue(all(reference() is None for reference in references))
            bias = original_project(index, device)
            references.append(weakref.ref(bias))
            return bias

        with torch.no_grad():
            materialized = torch.cat([
                torch.cat([layer(values[:, start:start + 2]) for start in range(0, 5, 2)], dim=1)
                for layer in layers
            ], dim=-1)
            initial_rng = torch.get_rng_state().clone()
            expected = dap_diffusion_score._run_token_stack(transformer, activation, conditioning,
                                                            materialized, torch.ones(1, 5), 2)
            with patch.object(provider, "project_layer", side_effect=project):
                actual = dap_diffusion_score._run_token_stack(transformer, activation, conditioning,
                                                              provider, torch.ones(1, 5), 2)
            self.assertTrue(torch.equal(expected, actual))
            self.assertTrue(torch.equal(initial_rng, torch.get_rng_state()))
            self.assertTrue(all(reference() is None for reference in references))

    def test_layer_major_matches_concatenated(self) -> None:
        concatenated = torch.arange(1 * 3 * 3 * 4).view(1, 3, 3, 4).float()
        layer_major = concatenated.view(1, 3, 3, 2, 2).permute(3, 0, 1, 2, 4)

        concatenated_biases = _run_with_bias(concatenated)
        layer_major_biases = _run_with_bias(layer_major)

        self.assertEqual(len(concatenated_biases), 4)
        self.assertEqual(len(layer_major_biases), 4)
        for expected, actual in zip(concatenated_biases, layer_major_biases):
            torch.testing.assert_close(actual, expected, rtol=0, atol=0)

    def test_rejects_wrong_layer_major_count(self) -> None:
        token_bias = torch.zeros(3, 1, 3, 3, 2)
        with self.assertRaisesRegex(
            ValueError,
            "first dimension does not match layer count",
        ):
            _run_with_bias(token_bias)


if __name__ == "__main__":
    if sys.argv[1:] == ["--distributed-cache-probe"]:
        distributed_cache_probe()
    else:
        unittest.main()