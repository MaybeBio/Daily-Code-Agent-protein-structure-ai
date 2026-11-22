"""CPU distributed regression for exact, bounded row/column transport."""

import ast
from contextlib import nullcontext
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

import torch
import torch.distributed as dist
import torch.multiprocessing as multiprocessing
import torch.nn.functional as functional
from torch.multiprocessing.reductions import StorageWeakRef


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from boltz_distributed import comm


def check_group(group, members):
    rank = members.index(dist.get_rank())
    world = len(members)
    cases = 0
    with patch.object(comm, 'get_dap_group', return_value=group), \
         patch.object(comm, 'get_dap_size', return_value=world), \
         patch.object(comm, 'get_dap_rank', return_value=rank):
        for dtype in (torch.float32, torch.bfloat16):
            for tokens in (1, 5, 8, 9, 17, 65):
                rows = (tokens + world - 1) // world
                values = torch.arange(rows * tokens * 7, dtype=torch.float32)
                values = (values + rank * rows * tokens * 7).reshape(1, rows, tokens, 7).to(dtype)
                shards = [torch.empty_like(values) for _ in members]
                dist.all_gather(shards, values, group=group)
                padded = ((tokens + world - 1) // world) * world
                expected = functional.pad(torch.cat(shards, dim=1), (0, 0, 0, padded - tokens))
                width = padded // world
                expected = expected[:, :, rank * width:(rank + 1) * width]
                original = values.clone()
                before = torch.get_rng_state().clone()
                actual = comm.row_to_col_destructive(values, host_staging=True)
                torch.testing.assert_close(actual, expected, rtol=0, atol=0)
                if world > 1:
                    assert values.numel() == 0
                restored = comm.col_to_row_streamed(actual, tokens, host_staging=True)
                torch.testing.assert_close(restored, original, rtol=0, atol=0)
                assert torch.equal(before, torch.get_rng_state())
                cases += 1
        with torch.enable_grad():
            try:
                comm.row_to_col_destructive(torch.zeros(1, 1, 1, 1), host_staging=True)
            except RuntimeError:
                pass
            else:
                raise AssertionError('Gradient-enabled destructive transport accepted')
        if world > 1:
            try:
                comm.row_to_col_destructive(torch.zeros(2, 1, 1, 1), host_staging=True)
            except ValueError:
                pass
            else:
                raise AssertionError('Batch larger than one accepted')
    return cases


def check_ending_attention(world):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'boltz_dap_v2'))
    import dap_tri_att as attention
    from boltz.model.layers.triangular_attention.attention import TriangleAttentionEndingNode

    def exchange(outputs, inputs, group=None, async_op=False):
        assert not async_op
        packed = torch.cat([item.reshape(-1) for item in inputs])
        received = torch.empty_like(packed)
        dist.all_to_all_single(received, packed, group=group)
        offset = 0
        for output in outputs:
            output.copy_(received[offset:offset + output.numel()].view(output.shape))
            offset += output.numel()

    rank = dist.get_rank()
    forward = attention.row_to_col_destructive
    backward = attention.col_to_row_streamed
    calls = []

    def staged_forward(source, *, host_staging=False):
        assert host_staging
        calls.append('row_to_column')
        return forward(source, host_staging=True)

    def staged_backward(source, original_size, *, host_staging=False):
        assert host_staging
        calls.append('column_to_row')
        storage = StorageWeakRef(source.untyped_storage())
        allocate = torch.empty

        def checked_allocate(*args, **kwargs):
            assert storage.expired(), 'Ending-attention backing storage survived host staging'
            return allocate(*args, **kwargs)

        with patch.object(comm.torch, 'empty', side_effect=checked_allocate):
            result = backward(source, original_size, host_staging=True)
        assert storage.expired()
        return result

    cases = 0
    with patch.object(comm, 'get_dap_group', return_value=None), \
         patch.object(comm, 'get_dap_size', return_value=world), \
         patch.object(comm, 'get_dap_rank', return_value=rank), \
         patch.object(attention, 'get_dap_group', return_value=None), \
         patch.object(attention, 'get_dap_size', return_value=world), \
         patch.object(dist, 'all_to_all', side_effect=exchange):
        for dtype, autocast in ((torch.float32, False), (torch.bfloat16, False),
                                (torch.float32, True)):
            with torch.random.fork_rng(devices=[]):
                torch.manual_seed(700786)
                inner = TriangleAttentionEndingNode(8, 3, 2, inf=1e9).to(dtype).eval()
                for parameter in inner.parameters():
                    parameter.uniform_(-0.3, 0.3)
            wrapper = attention.DAPTriAttEnd(inner).eval()
            for tokens in (1, 5, 8, 9, 17):
                values = torch.arange(tokens * tokens * 8, dtype=torch.float32)
                values = (values.reshape(1, tokens, tokens, 8) / 64).to(dtype)
                mask = torch.ones(1, tokens, tokens)
                mask[:, ::3, 1::2] = 0
                if tokens == 17:
                    mask.zero_()
                shard = comm.scatter(values, dim=1)
                shard_mask = comm.scatter(mask, dim=1)
                for tensor_scale in (False, True):
                    scale = torch.ones(1, 1, tokens, 1) if tensor_scale else 1.25
                    if tensor_scale:
                        scale[:, :, ::3] = 0
                        scale[:, :, 1::3] = 1.25
                    context = torch.autocast('cpu', dtype=torch.bfloat16) if autocast else nullcontext()
                    with context:
                        before = torch.get_rng_state().clone()
                        expected = shard + scale * wrapper(shard.clone(), shard_mask, chunk_size=2)
                        candidate = shard.clone()
                        calls.clear()
                        normalization_rows = []
                        original_normalize = inner.layer_norm.forward

                        def normalize_rows(source):
                            normalization_rows.append(source.shape[1])
                            return original_normalize(source)

                        with patch.object(attention, 'row_to_col_destructive', side_effect=staged_forward), \
                                patch.object(attention, 'col_to_row_streamed', side_effect=staged_backward), \
                             patch.object(inner.layer_norm, 'forward', new=normalize_rows):
                            actual = wrapper.forward_with_residual(candidate, shard_mask, scale, chunk_size=2)
                        assert len(normalization_rows) == (shard.shape[1] + 1) // 2
                        assert all(rows <= 2 for rows in normalization_rows)
                    torch.testing.assert_close(actual, expected.to(dtype), rtol=0, atol=0)
                    assert actual is candidate and actual.dtype == dtype
                    assert tuple(actual.shape) == tuple(shard.shape)
                    assert torch.isfinite(actual).all()
                    assert calls == ['row_to_column', 'column_to_row']
                    assert torch.equal(before, torch.get_rng_state())
                    cases += 1
    return cases


def worker(rank, world, rendezvous):
    dist.init_process_group('gloo', init_method='file://' + rendezvous, rank=rank, world_size=world)
    try:
        with torch.no_grad():
            cases = check_group(None, list(range(world)))
            members_by_group = ([0, 2], [1, 3])
            groups = [dist.new_group(members, backend='gloo') for members in members_by_group]
            for group, members in zip(groups, members_by_group):
                if rank in members:
                    cases += check_group(group, members)
            members_by_group = ([0], [1], [2], [3])
            groups = [dist.new_group(members, backend='gloo') for members in members_by_group]
            for group, members in zip(groups, members_by_group):
                if rank in members:
                    cases += check_group(group, members)
            ending_cases = check_ending_attention(world)
            dist.barrier()
        if rank == 0:
            print(f'PASS: {cases} cases/rank, FP32/BF16 exact round trips, padding, subgroups, RNG and guards')
            print(f'PASS: {ending_cases} ending-attention cases/rank, exact reference, staged callers, dtype, masks and RNG')
    finally:
        dist.destroy_process_group()


def main():
    caller = Path(__file__).resolve().parents[1] / 'boltz_dap_v2/dap_pairformer_noseq.py'
    calls = [node for node in ast.walk(ast.parse(caller.read_text()))
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
             and node.func.id == 'row_to_col_destructive']
    assert len(calls) == 1 and any(keyword.arg == 'host_staging'
        and isinstance(keyword.value, ast.Constant) and keyword.value.value is True
        for keyword in calls[0].keywords)
    attention = caller.with_name('dap_tri_att.py')
    ending = next(node for node in ast.parse(attention.read_text()).body
                  if isinstance(node, ast.ClassDef) and node.name == 'DAPTriAttEnd')
    staged = [node for node in ast.walk(ending) if isinstance(node, ast.Call)
              and isinstance(node.func, ast.Name)
              and node.func.id in ('row_to_col_destructive', 'col_to_row_streamed')]
    assert len(staged) == 2 and all(any(keyword.arg == 'host_staging'
        and isinstance(keyword.value, ast.Constant) and keyword.value.value is True
        for keyword in call.keywords) for call in staged)
    with tempfile.TemporaryDirectory(prefix='row_to_col_gloo_') as directory:
        multiprocessing.spawn(worker, args=(4, str(Path(directory) / 'rendezvous')), nprocs=4, join=True)


if __name__ == '__main__':
    main()