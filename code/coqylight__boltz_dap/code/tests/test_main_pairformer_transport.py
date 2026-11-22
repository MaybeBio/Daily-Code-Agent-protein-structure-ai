import ast
import copy
import inspect
import json
from pathlib import Path
import sys
import tempfile
import textwrap
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import torch
import dap_pairformer as pairformer

def transport_from_source(source, namespace):
    tree = ast.parse(textwrap.dedent(source))
    forward = next((node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == 'forward'))
    start = next((index for index, node in enumerate(forward.body) if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and (node.value.func.id == '_save_z') and (node.value.args[0].value == 'after_trimul_out'))) + 1
    end = next((index for index, node in enumerate(forward.body) if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and (node.value.func.id == '_mem') and (node.value.args[0].value == 'after tri_mul_in')))
    wrapper = ast.parse('def transport(self, z, pair_mask, original_N, use_kernels=False):\n    return z\n')
    wrapper.body[0].body = forward.body[start:end] + wrapper.body[0].body
    exec(compile(ast.fix_missing_locations(wrapper), '<main-pairformer-transport>', 'exec'), namespace)
    return namespace['transport']

class MainPairformerTransportTests(unittest.TestCase):

    def test_noseq_eval_stages_column_before_return_transport(self):
        import dap_pairformer_noseq as noseq

        class Stage:

            def __init__(self, offset):
                self.offset = offset

            def forward_with_residual(self, value, *args, **kwargs):
                return value + self.offset
        layer = SimpleNamespace(training=False, dropout=0.0, _diag_enabled=False, _save_subop_checkpoints=False, tri_mul_out=Stage(1), tri_mul_in=Stage(2), tri_att_start=Stage(3), tri_att_end=Stage(4), transition_z=Stage(5))
        value = torch.arange(40, dtype=torch.float32).reshape(1, 2, 5, 4)
        expected = value + 15

        def destructive(source, *, host_staging=False):
            self.assertTrue(host_staging)
            column = source.clone()
            source.set_(source.new_empty(0))
            return column

        def staged(source, original_size, *, host_staging=False):
            self.assertTrue(host_staging)
            self.assertEqual(original_size, 5)
            result = source.clone()
            source.set_(source.new_empty(0))
            return result
        rng = torch.get_rng_state().clone()
        with torch.no_grad(), patch.object(noseq, 'get_dropout_mask', return_value=1.0), patch.object(noseq, 'row_to_col_destructive', side_effect=destructive), patch.object(noseq, 'row_to_col', side_effect=lambda source: source.clone()), patch.object(noseq, 'col_to_row_streamed', side_effect=staged) as transport:
            actual = noseq.DAPPairformerNoSeqLayer.forward(layer, value, torch.ones(1, 2, 5))
        torch.testing.assert_close(actual, expected, rtol=0, atol=0)
        self.assertEqual(transport.call_count, 1)
        self.assertTrue(torch.equal(rng, torch.get_rng_state()))

    def test_staged_return_releases_before_allocations_and_preserves_rank_layout(self):
        import boltz_distributed.comm as comm
        original_empty = torch.empty
        for world, tokens in ((2, 8), (2, 9), (32, 33)):
            local_rows = (tokens + world - 1) // world
            padded = local_rows * world
            full = torch.arange(padded * padded * 4, dtype=torch.float32).reshape(1, padded, padded, 4)
            for rank in range(world):
                with self.subTest(world=world, tokens=tokens, rank=rank):
                    column = full[:, :, rank * local_rows:(rank + 1) * local_rows].clone()
                    allocations = []

                    def allocate(*args, **kwargs):
                        self.assertEqual(column.numel(), 0)
                        allocations.append(args[0])
                        return original_empty(*args, **kwargs)

                    def exchange(operations):
                        send, receive = operations
                        expected_send = full[:, send.peer * local_rows:(send.peer + 1) * local_rows, rank * local_rows:(rank + 1) * local_rows]
                        torch.testing.assert_close(send.tensor, expected_send, rtol=0, atol=0)
                        receive.tensor.copy_(full[:, rank * local_rows:(rank + 1) * local_rows, receive.peer * local_rows:(receive.peer + 1) * local_rows])
                        return [SimpleNamespace(wait=lambda: None)]
                    rng = torch.get_rng_state().clone()
                    with torch.no_grad(), patch.object(comm, 'get_dap_size', return_value=world), patch.object(comm, 'get_dap_rank', return_value=rank), patch.object(comm, 'get_dap_group', return_value=None), patch.object(comm.dist, 'P2POp', side_effect=lambda op, tensor, peer, group: SimpleNamespace(tensor=tensor, peer=peer)), patch.object(comm.dist, 'batch_isend_irecv', side_effect=exchange), patch.object(comm.torch, 'empty', side_effect=allocate):
                        actual = comm.col_to_row_streamed(column, tokens, host_staging=True)
                    expected = full[:, rank * local_rows:(rank + 1) * local_rows, :tokens]
                    torch.testing.assert_close(actual, expected, rtol=0, atol=0)
                    self.assertEqual(len(allocations), 2)
                    self.assertTrue(torch.equal(rng, torch.get_rng_state()))

    def test_eval_uses_bounded_transport_and_preserves_object(self):

        class Incoming:

            def forward_with_residual(self, column, mask, dropout, **kwargs):
                column.add_(2)
                return column

        class Layer:
            training = False
            dropout = 0.0
            tri_mul_in = Incoming()
        row = torch.arange(40, dtype=torch.float32).reshape(1, 2, 5, 4)
        expected = row + 2
        mask = torch.ones(1, 2, 5)
        original_object = row
        calls = []

        def destructive(value):
            calls.append('destructive')
            column = value.clone()
            value.set_(value.new_empty(0))
            return column

        def streamed(value, original_size):
            self.assertEqual(original_size, 5)
            self.assertEqual(row.numel(), 0)
            calls.append('streamed')
            result = value.clone()
            value.set_(value.new_empty(0))
            return result
        namespace = dict(vars(pairformer))
        namespace.update(row_to_col_destructive=destructive, col_to_row_streamed=streamed, row_to_col=lambda value: value.clone(), col_to_row=lambda value: self.fail('unbounded inference return'), get_dropout_mask=lambda *args, **kwargs: 1.0)
        transport = transport_from_source(inspect.getsource(pairformer.DAPPairformerLayer.forward), namespace)
        rng = torch.get_rng_state().clone()
        with torch.no_grad():
            actual = transport(Layer(), row, mask, 5)
        self.assertIs(actual, original_object)
        torch.testing.assert_close(actual, expected, rtol=0, atol=0)
        self.assertEqual(calls, ['destructive', 'streamed'])
        self.assertTrue(torch.equal(rng, torch.get_rng_state()))

    def test_fallback_values_and_training_gradients(self):

        class Incoming:

            def __call__(self, column, **kwargs):
                return column * 2

            def forward_with_residual(self, column, mask, dropout, **kwargs):
                return column * 3

        class Layer:
            dropout = 0.0
            tri_mul_in = Incoming()
        for batch, training, gradients in ((2, False, False), (1, True, True), (1, False, True)):
            with self.subTest(batch=batch, training=training, gradients=gradients):
                layer = Layer()
                layer.training = training
                namespace = dict(vars(pairformer))
                namespace.update(row_to_col=lambda value: value.clone(), col_to_row=lambda value: value.clone(), row_to_col_destructive=lambda value: self.fail('destructive fallback'), col_to_row_streamed=lambda *args, **kwargs: self.fail('streamed fallback'), get_dropout_mask=lambda *args, **kwargs: 1.0)
                transport = transport_from_source(inspect.getsource(pairformer.DAPPairformerLayer.forward), namespace)
                with torch.set_grad_enabled(gradients):
                    values = torch.randn(batch, 2, 5, 4, requires_grad=gradients)
                    actual = transport(layer, values.clone(), torch.ones(batch, 2, 5), 5)
                    torch.testing.assert_close(actual, values * 3, atol=0, rtol=0)
                    if gradients:
                        actual.sum().backward()
                        torch.testing.assert_close(values.grad, torch.full_like(values, 3), atol=0, rtol=0)
