from __future__ import annotations
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import torch
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / 'boltz' / 'src'))
sys.path.insert(0, str(PROJECT_ROOT / 'boltz_dap' / 'boltz_dap_v2'))
from phase6_execution import configure_phase6_execution, inference_precision_context

class _StructureModule(torch.nn.Module):

    def preconditioned_network_forward(self, *_args, **_kwargs):
        return 'legacy'

class _Model(torch.nn.Module):

    def __init__(self) -> None:
        super().__init__()
        self.structure_module = _StructureModule()

class Phase6ExecutionTest(unittest.TestCase):

    def test_cached_diffusion_is_opt_in_and_preserves_projection_precision(self) -> None:
        model = _Model()
        options = dict(execution_mode='candidate_sharded_fp32', diffusion_samples=1, token_query_rows=128, atom_window_rows=32, precision='bf16-mixed')
        with patch.dict(os.environ, {'BOLTZ_DIFFUSION_CACHED_TOKEN_ATTENTION': '1', 'BOLTZ_DIFFUSION_BIAS_LAYOUT': 'layerwise'}):
            contract = configure_phase6_execution(model, **options)
        self.assertTrue(contract['cached_token_attention'])
        self.assertEqual(contract['cache_projection_precision'], 'bf16-mixed')
        self.assertEqual(model._dap_cached_diffusion_config, {'projection_precision': 'bf16-mixed', 'query_rows': 128})
        with patch.dict(os.environ, {'BOLTZ_DIFFUSION_CACHED_TOKEN_ATTENTION': '0'}):
            contract = configure_phase6_execution(model, **options)
        self.assertFalse(contract['cached_token_attention'])
        self.assertFalse(hasattr(model, '_dap_cached_diffusion_config'))
        with patch.dict(os.environ, {'BOLTZ_DIFFUSION_CACHED_TOKEN_ATTENTION': '1', 'BOLTZ_DIFFUSION_BIAS_LAYOUT': 'layer_major'}):
            with self.assertRaisesRegex(ValueError, 'layerwise bias'):
                configure_phase6_execution(model, **options)

    def test_trunk_acceleration_contract_rejects_incompatible_modes(self) -> None:
        from phase6_execution import validate_trunk_acceleration
        with patch.dict(os.environ, {'BOLTZ_DAP_FUSED_TRI_ATT': '1', 'BOLTZ_TRIMUL_IN_OVERLAP_ONLY': '1', 'BOLTZ_TRIMUL_IN_REUSE_GROUP': '4'}):
            options = {'precision': 'bf16-mixed', 'no_kernels': False, 'execution_mode': 'candidate_sharded_fp32'}
            contract = validate_trunk_acceleration(**options)
            self.assertTrue(contract['fused_triangle_attention'] and contract['trimul_in_overlap_only'])
            self.assertEqual(contract['fused_triangle_query_tile'], 1024)
            self.assertEqual(contract['trimul_in_reuse_group'], 4)
            for field, value in (('precision', '32-true'), ('no_kernels', True), ('execution_mode', 'legacy_dap')):
                with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'requires'):
                    validate_trunk_acceleration(**{**options, field: value})

    def test_fused_query_tiles_preserve_reference_math_and_projection_reuse(self) -> None:
        import dap_tri_att
        from boltz.model.layers.triangular_attention.attention import TriangleAttentionStartingNode
        torch.manual_seed(1946153776)
        layer = TriangleAttentionStartingNode(128, 32, 4).eval()
        with torch.no_grad():
            for parameter in layer.parameters():
                parameter.uniform_(-0.1, 0.1)
            for tokens in (129, 259, 1038):
                values = torch.randn(1, 1, tokens, 128)
                bias = torch.randn(1, 1, 4, tokens, tokens)
                mask = torch.ones(1, 1, 1, 1, tokens)
                mask[..., ::7] = 0
                mask_bias = 1000000000.0 * (mask - 1)
                expected = layer.mha(values, values, bias, mask_bias, mask, use_kernels=False)
                calls = []

                def reference_kernel(queries, keys, projected_values, triangle_bias, key_mask, scale):
                    calls.append(queries.shape[-2])
                    self.assertEqual(keys.shape[-2], tokens)
                    return dap_tri_att._attention(queries * scale, keys, projected_values, [1000000000.0 * (key_mask - 1), triangle_bias])
                rng = torch.get_rng_state().clone()
                with patch.object(dap_tri_att, 'kernel_triangular_attn', new=reference_kernel), patch.object(dap_tri_att, '_project_kv', wraps=dap_tri_att._project_kv) as projections:
                    actual = dap_tri_att._mha_q_chunked_fused(layer.mha, values, values, bias, mask, 128)
                torch.testing.assert_close(actual, expected, atol=1e-06, rtol=1e-06)
                self.assertEqual(projections.call_count, 1)
                self.assertEqual(sum(calls), tokens)
                self.assertTrue(all((size >= 128 for size in calls)))
                self.assertTrue(torch.equal(rng, torch.get_rng_state()))

    def test_fused_attention_rejects_unvalidated_execution_modes(self) -> None:
        import dap_tri_att
        from boltz.model.layers.triangular_attention.attention import TriangleAttentionStartingNode
        layer = TriangleAttentionStartingNode(128, 32, 4).eval()
        values = torch.zeros(1, 1, 17, 128)
        bias, mask = (torch.zeros(1, 1, 4, 17, 17), torch.ones(1, 1, 1, 1, 17))
        with patch.dict(os.environ, {'BOLTZ_DAP_FUSED_TRI_ATT': '1'}), torch.no_grad(), self.assertRaisesRegex(ValueError, 'BF16 CUDA'):
            dap_tri_att._mha_q_chunked(layer.mha, values, values, bias, mask, mask, q_chunk=7, prefix='test')
        with patch.dict(os.environ, {'BOLTZ_DAP_FUSED_TRI_ATT': 'yes'}), self.assertRaisesRegex(ValueError, 'must be 0 or 1'):
            dap_tri_att._mha_q_chunked(layer.mha, values, values, bias, mask, mask, q_chunk=7, prefix='test')

    def test_streamed_pair_initialization_matches_native_mixed_precision(self) -> None:
        from boltz.model.modules.encodersv2 import RelativePositionEncoder
        from boltz.model.modules.trunkv2 import ContactConditioning
        from dap_trunk import _add_contact_conditioning_to_row_shard_, _add_relative_position_encoding_to_row_shard_
        from validate_trunk_relative_position_streaming import make_contact_features, make_features
        torch.manual_seed(1946153776)
        encoder = RelativePositionEncoder(token_z=16, fix_sym_check=True, cyclic_pos_enc=False).eval()
        conditioner = ContactConditioning(token_z=16, cutoff_min=2.0, cutoff_max=20.0).eval()
        features = make_features(13, 'cpu')
        features['asym_id'] = torch.arange(13)[None] // 4
        features['sym_id'] = features['asym_id'].clone()
        features['residue_index'] = torch.arange(13)[None] % 4
        contacts = make_contact_features(6, 13, 'cpu', varied=True)
        for dtype in (torch.bfloat16, torch.float32):
            with self.subTest(dtype=dtype), torch.no_grad(), inference_precision_context('bf16-mixed', 'cpu'):
                initial = torch.randn(1, 6, 13, 16).to(dtype)
                encoded = encoder(features)[:, 8:13]
                expected = initial + torch.cat((encoded, torch.zeros_like(encoded[:, :1])), dim=1)
                actual = _add_relative_position_encoding_to_row_shard_(encoder, features, initial.clone(), original_size=13, global_row_start=8, valid_rows=5, chunk_rows=2)
                self.assertEqual(actual.dtype, expected.dtype)
                torch.testing.assert_close(actual, expected, rtol=0, atol=0)
                torch.testing.assert_close(actual[:, 5:], initial[:, 5:], rtol=0, atol=0)
                expected = expected + conditioner(contacts)
                actual = _add_contact_conditioning_to_row_shard_(conditioner, contacts, actual, chunk_rows=2)
                self.assertEqual(actual.dtype, expected.dtype)
                torch.testing.assert_close(actual, expected, rtol=0, atol=0)

    def test_streamed_conditioning_promotes_only_when_native_addition_does(self) -> None:
        from boltz.model.modules.trunkv2 import ContactConditioning
        from dap_trunk import _add_contact_conditioning_to_row_shard_
        from validate_trunk_relative_position_streaming import make_contact_features
        conditioner = ContactConditioning(token_z=16, cutoff_min=2.0, cutoff_max=20.0).eval()
        contacts = make_contact_features(3, 5, 'cpu', varied=True)
        initial = torch.randn(1, 3, 5, 16).bfloat16()
        with inference_precision_context('32-true', 'cpu'), self.assertRaisesRegex(TypeError, 'require BF16 mixed precision'):
            _add_contact_conditioning_to_row_shard_(conditioner, contacts, initial, chunk_rows=2)
        native_forward = conditioner.forward

        def fp32_update(features):
            return native_forward(features).float()
        with torch.no_grad(), inference_precision_context('bf16-mixed', 'cpu'), patch.object(conditioner, 'forward', side_effect=fp32_update):
            expected = initial + conditioner(contacts)
            actual = _add_contact_conditioning_to_row_shard_(conditioner, contacts, initial, chunk_rows=2)
        self.assertEqual(actual.dtype, torch.float32)
        torch.testing.assert_close(actual, expected, rtol=0, atol=0)
        self.assertEqual(initial.dtype, torch.bfloat16)

    def test_bf16_eval_dropout_matches_native_promotion_and_rng(self) -> None:
        from boltz.model.layers.dropout import get_dropout_mask as native_dropout
        from dap_pairformer_noseq import get_dropout_mask
        full = torch.ones(1, 7, 7, 4, dtype=torch.bfloat16)
        local = full[:, :4]
        for columnwise in (False, True):
            with self.subTest(columnwise=columnwise):
                before = torch.get_rng_state()
                native = native_dropout(0.25, full, False, columnwise)
                expected_rng = torch.get_rng_state()
                torch.set_rng_state(before)
                with patch.dict(os.environ, {'BOLTZ_STOCK_EVAL_RNG_SCHEDULE': '1'}):
                    actual = get_dropout_mask(0.25, local, False, columnwise, stock_pair_size=7)
                self.assertTrue(torch.equal(torch.get_rng_state(), expected_rng))
                self.assertIsInstance(actual, torch.Tensor)
                self.assertEqual(actual.dtype, native.dtype)
                expected = native if columnwise else native[:, :4]
                torch.testing.assert_close(actual, expected, rtol=0, atol=0)
                self.assertEqual((local + actual * local).dtype, torch.float32)

    def test_tiled_residual_preserves_native_dtype_promotion(self) -> None:
        from dap_trimul import _add_residual_from_result_
        for dtype in (torch.bfloat16, torch.float32):
            with self.subTest(dtype=dtype):
                residual = torch.ones(1, 3, 5, 4, dtype=dtype)
                update = torch.full_like(residual, 0.00390625)
                scale = torch.ones(1, 3, 1, 1, dtype=torch.float32)
                expected = residual + scale * update
                with patch('dap_trimul._log', return_value=0), patch.dict(os.environ, {'BOLTZ_TRIMUL_FINAL_TILE': '2'}):
                    actual = _add_residual_from_result_(residual, update, scale, 'test')
                self.assertEqual(actual.dtype, expected.dtype)
                torch.testing.assert_close(actual, expected, rtol=0, atol=0)
                if dtype == torch.float32:
                    self.assertIs(actual, residual)

    def test_confidence_bf16_source_transport_is_lossless_and_bounded(self) -> None:
        from dap_confidence import _scatter_confidence_z_rows
        source = (torch.arange(5 * 5 * 4).reshape(1, 5, 5, 4).float() / 37).bfloat16()
        sent = []
        with patch.dict(os.environ, {'BOLTZ_CONFIDENCE_Z_TRANSPORT_DTYPE': 'fp32'}), patch('torch.distributed.send', side_effect=lambda value, dst: sent.append((dst, value.clone()))), inference_precision_context('bf16-mixed', 'cpu'):
            local = _scatter_confidence_z_rows(source, batch_size=1, num_tokens=5, pair_dim=4, padded_tokens=6, chunk_tokens=3, dap_rank=0, dap_size=2, local_device=torch.device('cpu'))
        self.assertEqual(local.dtype, torch.float32)
        self.assertEqual(sent[0][0], 1)
        self.assertEqual(sent[0][1].shape, (1, 3, 5, 4))
        restored = torch.cat((local, sent[0][1]), dim=1)
        torch.testing.assert_close(restored[:, :5], source.float(), rtol=0, atol=0)
        self.assertEqual(restored[:, 5:].count_nonzero(), 0)

    def test_confidence_rejects_bf16_source_outside_mixed_precision(self) -> None:
        from dap_confidence import _scatter_confidence_z_rows
        with inference_precision_context('32-true', 'cpu'), self.assertRaisesRegex(TypeError, 'must be FP32'):
            _scatter_confidence_z_rows(torch.zeros(1, 2, 2, 4, dtype=torch.bfloat16), batch_size=1, num_tokens=2, pair_dim=4, padded_tokens=2, chunk_tokens=2, dap_rank=0, dap_size=1, local_device=torch.device('cpu'))

    def test_bf16_pairformer_casts_pair_bias_at_native_fp32_boundary(self) -> None:
        from boltz.model.layers.pairformer import PairformerLayer
        from dap_pairformer import DAPPairformerLayer
        layer = DAPPairformerLayer(PairformerLayer(32, 16, v2=True)).eval()
        observed = []
        hook = layer.attention.proj_z.register_forward_pre_hook(lambda module, args: observed.append(args[0].dtype))
        sequence = torch.randn(1, 4, 32)
        pair = torch.randn(1, 4, 4, 16, dtype=torch.bfloat16)
        mask = torch.ones(1, 4)
        try:
            with torch.no_grad(), inference_precision_context('bf16-mixed', 'cpu'):
                sequence_out, pair_out = layer(sequence, pair, mask, mask[:, :, None] * mask[:, None, :])
        finally:
            hook.remove()
        self.assertEqual(observed, [torch.float32])
        self.assertTrue(torch.isfinite(sequence_out).all())
        self.assertTrue(torch.isfinite(pair_out).all())

    def test_precision_context_matches_native_mixed_precision(self) -> None:
        from pytorch_lightning.plugins.precision import MixedPrecision
        layer = torch.nn.Linear(8, 8).eval()
        value = torch.randn(2, 8)
        with torch.no_grad(), MixedPrecision('bf16-mixed', 'cpu').forward_context():
            expected = layer(value)
        with torch.no_grad(), inference_precision_context('bf16-mixed', 'cpu'):
            actual = layer(value)
            self.assertTrue(torch.is_autocast_enabled('cpu'))
            with torch.autocast('cpu', enabled=False):
                self.assertEqual(layer(value.float()).dtype, torch.float32)
            self.assertTrue(torch.is_autocast_enabled('cpu'))
        self.assertEqual(actual.dtype, torch.bfloat16)
        torch.testing.assert_close(actual, expected, rtol=0, atol=0)
        self.assertFalse(torch.is_autocast_enabled('cpu'))
        self.assertEqual(layer.weight.dtype, torch.float32)

    def test_fp32_context_disables_outer_autocast_and_restores_it(self) -> None:
        layer = torch.nn.Linear(8, 8).eval()
        value = torch.randn(2, 8)
        with torch.autocast('cpu', dtype=torch.bfloat16):
            with inference_precision_context('32-true', 'cpu'):
                self.assertFalse(torch.is_autocast_enabled('cpu'))
                self.assertEqual(layer(value).dtype, torch.float32)
            self.assertTrue(torch.is_autocast_enabled('cpu'))

    def test_precision_rejects_unknown_mode(self) -> None:
        with self.assertRaisesRegex(ValueError, 'unsupported inference precision'):
            inference_precision_context('bf16-true', 'cpu')

    def test_projection_reuse_is_explicit_and_recorded(self) -> None:
        for enabled in ('0', '1'):
            with patch.dict(os.environ, {'BOLTZ_DIFFUSION_REUSE_TOKEN_PROJECTIONS': enabled, 'BOLTZ_DIFFUSION_REUSE_ATOM_PROJECTIONS': enabled, 'BOLTZ_DIFFUSION_STREAM_TOKEN_BIAS': enabled, 'BOLTZ_DIFFUSION_DETERMINISTIC_POOLING': enabled}):
                contract = configure_phase6_execution(_Model(), execution_mode='candidate_sharded_fp32', diffusion_samples=1, token_query_rows=128, atom_window_rows=32)
            self.assertEqual(contract['reuse_token_projections'], enabled == '1')
            self.assertEqual(contract['reuse_atom_projections'], enabled == '1')
            self.assertEqual(contract['stream_token_bias'], enabled == '1')
            self.assertEqual(contract['deterministic_pooling'], enabled == '1')

    def test_new_options_reject_invalid_switches_before_mutation(self) -> None:
        for name in ('BOLTZ_DIFFUSION_STREAM_TOKEN_BIAS', 'BOLTZ_DIFFUSION_DETERMINISTIC_POOLING'):
            model = _Model()
            original = model.structure_module.preconditioned_network_forward.__func__
            with patch.dict(os.environ, {name: 'yes'}), self.assertRaisesRegex(ValueError, 'must be 0 or 1'):
                configure_phase6_execution(model, execution_mode='candidate_sharded_fp32', diffusion_samples=1, token_query_rows=128, atom_window_rows=32)
            self.assertIs(model.structure_module.preconditioned_network_forward.__func__, original)

    def test_projection_reuse_rejects_invalid_switch(self) -> None:
        model = _Model()
        original = model.structure_module.preconditioned_network_forward.__func__
        with patch.dict(os.environ, {'BOLTZ_DIFFUSION_REUSE_ATOM_PROJECTIONS': 'yes'}):
            with self.assertRaisesRegex(ValueError, 'must be 0 or 1'):
                configure_phase6_execution(model, execution_mode='candidate_sharded_fp32', diffusion_samples=1, token_query_rows=128, atom_window_rows=32)
        self.assertIs(model.structure_module.preconditioned_network_forward.__func__, original)

    def test_legacy_mode_preserves_method(self) -> None:
        model = _Model()
        original = model.structure_module.preconditioned_network_forward.__func__
        contract = configure_phase6_execution(model, execution_mode='legacy_dap', diffusion_samples=3, token_query_rows=0, atom_window_rows=0)
        self.assertFalse(contract['candidate_score_selected'])
        self.assertFalse(contract['stock_eval_rng_schedule'])
        self.assertIs(model.structure_module.preconditioned_network_forward.__func__, original)

    def test_candidate_mode_is_explicit_and_bounded(self) -> None:
        model = _Model()
        contract = configure_phase6_execution(model, execution_mode='candidate_sharded_fp32', diffusion_samples=1, token_query_rows=64, atom_window_rows=16)
        self.assertTrue(contract['candidate_score_selected'])
        self.assertEqual(contract['confidence_transport'], 'fp32')
        self.assertTrue(contract['stock_eval_rng_schedule'])
        self.assertEqual(contract['token_query_rows'], 64)
        self.assertEqual(contract['atom_window_rows'], 16)

    def test_candidate_rejects_multiple_samples(self) -> None:
        with self.assertRaisesRegex(ValueError, 'one diffusion sample'):
            configure_phase6_execution(_Model(), execution_mode='candidate_sharded_fp32', diffusion_samples=2, token_query_rows=64, atom_window_rows=16)
if __name__ == '__main__':
    unittest.main()
