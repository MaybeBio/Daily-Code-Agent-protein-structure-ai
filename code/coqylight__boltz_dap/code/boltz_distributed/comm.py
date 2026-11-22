"""
DAP Communication Primitives for Boltz

Adapted from FastFold's fastfold/distributed/comm.py

Modified for Boltz-DAP: padded sharding, group-aware row/column transport,
and inference-only host staging and attention communication helpers.
FastFold-derived portions remain Apache-2.0; see ../THIRD_PARTY_NOTICES.md
and ../licenses/FastFold-LICENSE.txt.

These primitives handle tensor distribution across GPUs:
- scatter: Split tensor across GPUs
- gather: Collect tensor shards from all GPUs
- row_to_col / col_to_row: All-to-all for attention axis swaps
"""

from typing import Tuple

import torch
import torch.distributed as dist
from torch import Tensor

from .core import get_dap_size, get_dap_rank, get_dap_group, ensure_divisibility


def divide(numerator, denominator):
    """Divide, rounding up to handle non-divisible sizes."""
    return (numerator + denominator - 1) // denominator


def _reduce(tensor: Tensor) -> Tensor:
    """All-reduce operation across DAP group."""
    dap_size = get_dap_size()
    if dap_size == 1:
        return tensor

    group = get_dap_group()
    dist.all_reduce(tensor, op=dist.ReduceOp.SUM, group=group, async_op=False)
    return tensor


def _split(tensor: Tensor, dim: int = -1) -> Tensor:
    """Split tensor along dimension and keep only local shard.
    
    Handles non-divisible sizes by padding, then removing padding on the last rank.
    """
    dap_size = get_dap_size()
    if dap_size == 1:
        return tensor

    dap_rank = get_dap_rank()
    size = tensor.shape[dim]
    
    # Calculate split size (round up)
    split_size = divide(size, dap_size)
    
    # Pad if necessary
    padded_size = split_size * dap_size
    if padded_size > size:
        pad_amount = padded_size - size
        # Create padding shape
        pad_shape = list(tensor.shape)
        pad_shape[dim] = pad_amount
        padding = torch.zeros(pad_shape, dtype=tensor.dtype, device=tensor.device)
        tensor = torch.cat([tensor, padding], dim=dim)
    
    # Split and take local shard
    tensor_list = torch.split(tensor, split_size, dim=dim)
    output = tensor_list[dap_rank].contiguous()
    
    return output


def _gather(tensor: Tensor, dim: int = -1, original_size: int = None) -> Tensor:
    """Gather tensor shards from all GPUs.
    
    If original_size is provided, trims the result to that size (removes padding).
    """
    dap_size = get_dap_size()
    if dap_size == 1:
        return tensor

    group = get_dap_group()
    
    if dim == 1 and list(tensor.shape)[0] == 1:
        output_shape = list(tensor.shape)
        output_shape[1] *= dap_size
        output = torch.empty(output_shape, dtype=tensor.dtype, device=tensor.device)
        tensor_list = output.chunk(dap_size, dim=1)
        dist.all_gather(list(tensor_list), tensor, group=group, async_op=False)
    else:
        tensor_list = [torch.empty_like(tensor) for _ in range(dap_size)]
        dist.all_gather(tensor_list, tensor, group=group, async_op=False)
        output = torch.cat(tensor_list, dim=dim)
    
    # Trim to original size if provided (remove padding)
    if original_size is not None and output.shape[dim] > original_size:
        indices = [slice(None)] * len(output.shape)
        indices[dim] = slice(0, original_size)
        output = output[tuple(indices)]

    return output


def gather_to_rank0_cpu(tensor: Tensor, dim: int = -1, original_size: int = None) -> Tensor | None:
    """Gather sharded tensors into CPU memory on rank 0 only.

    Unlike :func:`_gather`, this helper never materializes the full gathered
    tensor on CUDA and returns ``None`` on non-zero DAP ranks. It is intended
    for inference handoffs where only rank 0 consumes the full tensor after a
    DAP-sharded trunk.
    """
    dap_size = get_dap_size()
    if dap_size == 1:
        output = tensor.detach().cpu()
        if original_size is not None and output.shape[dim] > original_size:
            indices = [slice(None)] * output.ndim
            indices[dim] = slice(0, original_size)
            output = output[tuple(indices)]
        return output

    dap_rank = get_dap_rank()
    group = get_dap_group()
    dim = dim if dim >= 0 else tensor.ndim + dim
    local = tensor.detach().contiguous()
    local_dim = local.shape[dim]

    def _global_rank(rank: int) -> int:
        if group is None:
            return rank
        return dist.get_global_rank(group, rank)

    def _copy_shard(output: Tensor, shard: Tensor, rank: int) -> None:
        start = rank * local_dim
        stop = start + local_dim
        if original_size is not None:
            stop = min(stop, original_size)
        if stop <= start:
            return
        src_indices = [slice(None)] * shard.ndim
        dst_indices = [slice(None)] * output.ndim
        src_indices[dim] = slice(0, stop - start)
        dst_indices[dim] = slice(start, stop)
        output[tuple(dst_indices)].copy_(shard[tuple(src_indices)].cpu())

    if dap_rank == 0:
        output_shape = list(local.shape)
        output_shape[dim] = local_dim * dap_size
        if original_size is not None:
            output_shape[dim] = min(output_shape[dim], original_size)
        output = torch.empty(output_shape, dtype=local.dtype, device="cpu")
        _copy_shard(output, local, 0)
        recv_buf = torch.empty_like(local)
        for src_rank in range(1, dap_size):
            dist.recv(recv_buf, src=_global_rank(src_rank), group=group)
            _copy_shard(output, recv_buf, src_rank)
        return output

    dist.send(local, dst=_global_rank(0), group=group)
    return None


# Autograd-compatible wrappers with proper gradient handling

class Copy(torch.autograd.Function):
    """Copy operation - identity forward, reduce backward."""
    
    @staticmethod
    def forward(ctx, input: Tensor) -> Tensor:
        return input

    @staticmethod
    def backward(ctx, grad_output: Tensor) -> Tensor:
        return _reduce(grad_output)


class Scatter(torch.autograd.Function):
    """Scatter operation - split forward, gather backward."""
    
    @staticmethod
    def forward(ctx, input: Tensor, dim: int = -1) -> Tensor:
        ctx.save_for_backward(torch.tensor([dim]))
        return _split(input, dim=dim)

    @staticmethod
    def backward(ctx, grad_output: Tensor) -> Tuple[Tensor, None]:
        dim, = ctx.saved_tensors
        return _gather(grad_output, dim=int(dim)), None


class Reduce(torch.autograd.Function):
    """Reduce operation - all-reduce forward, identity backward."""
    
    @staticmethod
    def forward(ctx, input: Tensor) -> Tensor:
        return _reduce(input)

    @staticmethod
    def backward(ctx, grad_output: Tensor) -> Tensor:
        return grad_output


class Gather(torch.autograd.Function):
    """Gather operation - gather forward, split backward."""
    
    @staticmethod
    def forward(ctx, input: Tensor, dim: int = -1) -> Tensor:
        ctx.save_for_backward(torch.tensor([dim]))
        return _gather(input, dim=dim)

    @staticmethod
    def backward(ctx, grad_output: Tensor) -> Tuple[Tensor, None]:
        dim, = ctx.saved_tensors
        return _split(grad_output, dim=int(dim)), None


def _all_to_all(tensor: Tensor, in_dim: int = -1, out_dim: int = -1) -> Tensor:
    """All-to-all operation for dimension swapping.
    
    Handles non-divisible sizes by using split_size that works with the padded tensor.
    """
    dap_size = get_dap_size()
    if dap_size == 1:
        return tensor

    group = get_dap_group()
    
    # The tensor should already be padded from scatter, so it should be divisible
    size = tensor.shape[in_dim]
    split_size = divide(size, dap_size)
    
    if split_size * dap_size != size:
        part_shape = list(tensor.shape)
        part_shape[in_dim] = split_size
        input_buffer = torch.empty(
            (dap_size, *part_shape),
            dtype=tensor.dtype,
            device=tensor.device,
        )
        input_tensor_list = list(input_buffer.unbind(0))
        for part_index, part in enumerate(input_tensor_list):
            source_start = part_index * split_size
            source_end = min(source_start + split_size, size)
            valid_size = max(0, source_end - source_start)
            if valid_size:
                source_index = [slice(None)] * tensor.ndim
                source_index[in_dim] = slice(source_start, source_end)
                target_index = [slice(None)] * part.ndim
                target_index[in_dim] = slice(0, valid_size)
                part[tuple(target_index)].copy_(tensor[tuple(source_index)])
            if valid_size < split_size:
                padding_index = [slice(None)] * part.ndim
                padding_index[in_dim] = slice(valid_size, split_size)
                part[tuple(padding_index)].zero_()
    else:
        input_buffer = None
        input_tensor_list = [
            part.contiguous()
            for part in torch.split(tensor, split_size, dim=in_dim)
        ]

    if out_dim == 1:
        output_shape = list(input_tensor_list[0].shape)
        output_shape[1] *= dap_size
        if output_shape[0] == 1:
            output = torch.empty(output_shape, dtype=tensor.dtype, device=tensor.device)
            output_tensor_list = output.chunk(dap_size, dim=1)
            dist.all_to_all(list(output_tensor_list), input_tensor_list, group=group, async_op=False)
            del input_tensor_list, input_buffer
        else:
            # Dimension-1 chunks are non-contiguous when a leading batch/template
            # dimension is greater than one, which NCCL all_to_all rejects.
            output_tensor_list = [torch.empty_like(t) for t in input_tensor_list]
            dist.all_to_all(output_tensor_list, input_tensor_list, group=group, async_op=False)
            del input_tensor_list, input_buffer, tensor
            output = torch.cat(output_tensor_list, dim=1)
    else:
        output_tensor_list = [torch.empty_like(t) for t in input_tensor_list]
        dist.all_to_all(output_tensor_list, input_tensor_list, group=group, async_op=False)
        del input_tensor_list, input_buffer, tensor
        output = torch.cat(output_tensor_list, dim=out_dim)

    return output


class All_to_All(torch.autograd.Function):
    """All-to-all operation with autograd support."""
    
    @staticmethod
    def forward(ctx, input: Tensor, in_dim: int = -1, out_dim: int = -1) -> Tensor:
        ctx.save_for_backward(torch.tensor([in_dim, out_dim]))
        return _all_to_all(input, in_dim=in_dim, out_dim=out_dim)

    @staticmethod
    def backward(ctx, grad_output: Tensor) -> Tuple[Tensor, None, None]:
        saved_tensors = ctx.saved_tensors[0]
        return _all_to_all(
            grad_output, 
            in_dim=int(saved_tensors[1]), 
            out_dim=int(saved_tensors[0])
        ), None, None


# Public API with gradient support

def copy(input: Tensor) -> Tensor:
    """Copy tensor (identity forward, reduce backward for gradients)."""
    if torch.is_grad_enabled() and input.requires_grad:
        return Copy.apply(input)
    return input


def scatter(input: Tensor, dim: int = -1) -> Tensor:
    """Scatter tensor across GPUs along specified dimension."""
    if torch.is_grad_enabled() and input.requires_grad:
        return Scatter.apply(input, dim)
    return _split(input, dim=dim)


def reduce(input: Tensor) -> Tensor:
    """All-reduce tensor across GPUs."""
    if torch.is_grad_enabled() and input.requires_grad:
        return Reduce.apply(input)
    return _reduce(input)


def gather(input: Tensor, dim: int = -1, original_size: int = None) -> Tensor:
    """Gather tensor from all GPUs along specified dimension.
    
    If original_size is provided, trims the result to remove padding.
    """
    if torch.is_grad_enabled() and input.requires_grad:
        output = Gather.apply(input, dim)
        # Trim padding if needed
        if original_size is not None and output.shape[dim] > original_size:
            indices = [slice(None)] * len(output.shape)
            indices[dim] = slice(0, original_size)
            output = output[tuple(indices)]
        return output
    return _gather(input, dim=dim, original_size=original_size)


def col_to_row(input: Tensor) -> Tensor:
    """Convert column-distributed to row-distributed tensor."""
    if torch.is_grad_enabled() and input.requires_grad:
        return All_to_All.apply(input, 1, 2)
    return _all_to_all(input, in_dim=1, out_dim=2)


def col_to_row_inplace(input: Tensor, output: Tensor) -> Tensor:
    """Convert column-distributed input into preallocated row storage."""
    if torch.is_grad_enabled() and (input.requires_grad or output.requires_grad):
        raise RuntimeError("col_to_row_inplace does not support autograd")

    dap_size = get_dap_size()
    if dap_size == 1:
        output.copy_(input)
        return output

    if input.device != output.device or input.dtype != output.dtype:
        raise ValueError("input and output must have the same device and dtype")
    if input.ndim != output.ndim:
        raise ValueError("input and output must have the same rank")
    if input.shape[1] % dap_size != 0:
        raise ValueError("column-distributed rows must be divisible by DAP size")

    group = get_dap_group()
    row_split = input.shape[1] // dap_size
    local_cols = input.shape[2]
    if output.shape[1] != row_split:
        raise ValueError(
            f"output local rows must be {row_split}, got {output.shape[1]}"
        )
    if output.shape[2] > local_cols * dap_size:
        raise ValueError("output has more columns than the distributed input")
    for dim in (0, *range(3, input.ndim)):
        if input.shape[dim] != output.shape[dim]:
            raise ValueError("input and output non-distributed dimensions differ")

    input_parts = [part.contiguous() for part in torch.split(input, row_split, dim=1)]
    received_parts = [torch.empty_like(part) for part in input_parts]
    dist.all_to_all(received_parts, input_parts, group=group, async_op=False)
    del input_parts

    for src_rank, part in enumerate(received_parts):
        col_start = src_rank * local_cols
        col_end = min(col_start + local_cols, output.shape[2])
        if col_end > col_start:
            output[:, :, col_start:col_end].copy_(
                part[:, :, : col_end - col_start]
            )
    del received_parts
    return output


def row_to_col(input: Tensor) -> Tensor:
    """Convert row-distributed to column-distributed tensor."""
    if torch.is_grad_enabled() and input.requires_grad:
        return All_to_All.apply(input, 2, 1)
    return _all_to_all(input, in_dim=2, out_dim=1)


def row_to_col_destructive(input: Tensor, *, host_staging: bool = False) -> Tensor:
    """Convert a batch-one row shard after releasing its packed input storage."""
    if torch.is_grad_enabled():
        raise RuntimeError("row_to_col_destructive is inference-only")

    dap_size = get_dap_size()
    if dap_size == 1:
        return input
    if input.ndim != 4 or input.shape[0] != 1:
        raise ValueError("row_to_col_destructive requires a batch-one pair tensor")

    group = get_dap_group()
    size = input.shape[2]
    split_size = divide(size, dap_size)
    part_shape = list(input.shape)
    part_shape[2] = split_size
    if host_staging:
        device = input.device
        source_tensor = input.to(device="cpu", copy=True)
        input.set_(input.new_empty(0))
        output_shape = list(part_shape)
        output_shape[1] *= dap_size
        output = torch.empty(output_shape, dtype=source_tensor.dtype, device=device)
        send = torch.empty(part_shape, dtype=source_tensor.dtype, device=device)
        received = torch.empty_like(send)
        dap_rank = get_dap_rank()

        def global_rank(group_rank: int) -> int:
            if group is None:
                return group_rank
            return dist.get_global_rank(group, group_rank)

        for offset in range(dap_size):
            destination = (dap_rank + offset) % dap_size
            source = (dap_rank - offset) % dap_size
            source_start = destination * split_size
            valid_size = max(0, min(split_size, size - source_start))
            send.zero_()
            if valid_size:
                send[:, :, :valid_size].copy_(
                    source_tensor[:, :, source_start:source_start + valid_size]
                )
            if offset == 0:
                received_part = send
            else:
                requests = dist.batch_isend_irecv(
                    [
                        dist.P2POp(dist.isend, send, global_rank(destination), group=group),
                        dist.P2POp(dist.irecv, received, global_rank(source), group=group),
                    ]
                )
                for request in requests:
                    request.wait()
                received_part = received
            row_start = source * source_tensor.shape[1]
            output[:, row_start:row_start + source_tensor.shape[1]].copy_(received_part)
        del send, received, received_part, source_tensor
        return output

    input_buffer = torch.empty(
        (dap_size, *part_shape),
        dtype=input.dtype,
        device=input.device,
    )
    for part_index, part in enumerate(input_buffer.unbind(0)):
        source_start = part_index * split_size
        source_end = min(source_start + split_size, size)
        valid_size = max(0, source_end - source_start)
        if valid_size:
            part[:, :, :valid_size].copy_(
                input[:, :, source_start:source_end]
            )
        if valid_size < split_size:
            part[:, :, valid_size:].zero_()

    output_shape = part_shape
    output_shape[1] *= dap_size
    input.set_(input.new_empty(0))
    output = torch.empty(output_shape, dtype=input.dtype, device=input.device)
    output_parts = list(output.chunk(dap_size, dim=1))
    input_parts = list(input_buffer.unbind(0))
    dist.all_to_all(output_parts, input_parts, group=group, async_op=False)
    del output_parts, input_parts, input_buffer
    return output


def col_to_row_streamed(input: Tensor, original_size: int, *, host_staging: bool = False) -> Tensor:
    """Convert a batch-one column shard with one receive part at a time."""
    if torch.is_grad_enabled():
        raise RuntimeError("col_to_row_streamed is inference-only")

    dap_size = get_dap_size()
    if dap_size == 1:
        return input
    if input.ndim != 4 or input.shape[0] != 1:
        raise ValueError("col_to_row_streamed requires a batch-one pair tensor")
    if input.shape[1] % dap_size != 0:
        raise ValueError("column-distributed rows must be divisible by DAP size")

    group = get_dap_group()
    dap_rank = get_dap_rank()
    row_split = input.shape[1] // dap_size
    local_columns = input.shape[2]
    padded_columns = local_columns * dap_size
    if original_size <= 0 or original_size > padded_columns:
        raise ValueError(
            f"original_size must be in [1, {padded_columns}], got {original_size}"
        )

    device = input.device
    source_tensor = input.to(device="cpu", copy=True) if host_staging else input
    if host_staging:
        input.set_(input.new_empty(0))
    output = torch.empty(
        (source_tensor.shape[0], row_split, original_size, source_tensor.shape[3]),
        dtype=source_tensor.dtype,
        device=device,
    )
    received = torch.empty(
        (source_tensor.shape[0], row_split, local_columns, source_tensor.shape[3]),
        dtype=source_tensor.dtype,
        device=device,
    )

    def global_rank(group_rank: int) -> int:
        if group is None:
            return group_rank
        return dist.get_global_rank(group, group_rank)

    for offset in range(dap_size):
        destination = (dap_rank + offset) % dap_size
        source = (dap_rank - offset) % dap_size
        send = source_tensor[:, destination * row_split:(destination + 1) * row_split].to(device=device)
        if offset == 0:
            received_part = send
        else:
            requests = dist.batch_isend_irecv(
                [
                    dist.P2POp(
                        dist.isend,
                        send,
                        global_rank(destination),
                        group=group,
                    ),
                    dist.P2POp(
                        dist.irecv,
                        received,
                        global_rank(source),
                        group=group,
                    ),
                ]
            )
            for request in requests:
                request.wait()
            received_part = received

        column_start = source * local_columns
        column_end = min(column_start + local_columns, original_size)
        if column_end > column_start:
            output[:, :, column_start:column_end].copy_(
                received_part[:, :, :column_end - column_start]
            )
        del send, received_part

    input.set_(input.new_empty(0))
    del received, source_tensor
    return output


# ── Async gather primitives (FastFold-style) ────────────────────────────

def gather_async(tensor: Tensor, dim: int = -1):
    """Start a non-blocking all_gather and return (output_list, work_handle).
    
    Allows overlapping communication with computation:
        out_list, handle = gather_async(x, dim=1)
        # ... do other compute here ...
        result = gather_async_opp(out_list, handle, dim=1)
    """
    dap_size = get_dap_size()
    if dap_size == 1:
        return [tensor], None

    group = get_dap_group()
    tensor_list = [torch.empty_like(tensor) for _ in range(dap_size)]
    work = dist.all_gather(tensor_list, tensor.contiguous(), group=group, async_op=True)
    return tensor_list, work


def gather_async_opp(tensor_list, work, dim: int = -1, original_size: int = None) -> Tensor:
    """Wait for async gather to complete and concatenate results.
    
    Args:
        tensor_list: List of tensors from gather_async
        work: Work handle from gather_async (None if dap_size==1)
        dim: Dimension to concatenate along
        original_size: If provided, trim to this size (remove padding)
    """
    if work is not None:
        work.wait()

    output = torch.cat(tensor_list, dim=dim)

    if original_size is not None and output.shape[dim] > original_size:
        indices = [slice(None)] * len(output.shape)
        indices[dim] = slice(0, original_size)
        output = output[tuple(indices)]

    return output
