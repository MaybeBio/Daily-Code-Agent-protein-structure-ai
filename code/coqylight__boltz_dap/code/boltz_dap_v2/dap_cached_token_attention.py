from __future__ import annotations

import copy
import json
import os

import torch
import torch.distributed as dist

from dap_diffusion_transformer import run_chunked_diffusion_layer


def plan_cached_query_intervals(tokens, query_rows, batch, heads, layers, capacities):
    if min(tokens, query_rows, batch, heads, layers) < 1 or not capacities or min(capacities) < 0:
        raise ValueError("Invalid cache planning dimensions or capacities")
    chunk_bytes = batch * query_rows * tokens * heads * layers * 4
    limits = [capacity // chunk_bytes for capacity in capacities]
    chunks = (tokens + query_rows - 1) // query_rows
    if sum(limits) < chunks:
        raise MemoryError("Insufficient aggregate FP32 cache headroom")
    counts = [0] * len(capacities)
    for _ in range(chunks):
        selected = min((rank for rank, limit in enumerate(limits) if counts[rank] < limit),
                       key=lambda rank: (counts[rank], rank))
        counts[selected] += 1
    intervals = []
    start = 0
    for count in counts:
        end = min(start + count * query_rows, tokens)
        intervals.append((start, end))
        start = end
    return intervals


class ShardedTokenBiasCache:
    """Prediction-scoped FP32 bias rows; construction requires an immutable binding."""

    def __init__(self, values, intervals, rank, query_rows, binding):
        if not binding or values.dtype != torch.float32 or values.ndim != 5:
            raise ValueError("Cache requires a binding and [L, B, local N, N, H] FP32 values")
        self.values = values
        self.intervals = tuple(intervals)
        self.rank = rank
        self.query_rows = query_rows
        self.binding = binding
        self.projection_calls = 0
        self.source_transfer_bytes = 0
        self.hits = 0
        self.closed = False

    @classmethod
    def build(cls, provider, projection_layers, *, tokens, batch, query_rows, projection_rows,
              device, binding, cache_capacity_bytes, group=None, projection_precision="32-true"):
        if torch.is_grad_enabled() or any(layer.training for layer in projection_layers):
            raise ValueError("Cached bias requires inference-only evaluation")
        if projection_precision not in ("32-true", "bf16-mixed"):
            raise ValueError("Unsupported cached bias projection precision")
        if not binding or projection_rows < 1 or query_rows < 1 or query_rows % projection_rows:
            raise ValueError("Cache requires a binding and projection-aligned query chunks")
        device = torch.device(device)
        if torch.is_autocast_enabled(device.type) or (device.type == "cuda" and (
                torch.backends.cuda.matmul.allow_tf32 or torch.backends.cudnn.allow_tf32)):
            raise ValueError("Cached bias requires FP32 without autocast or TF32")
        if group is not None:
            raise ValueError("Cached attention currently requires the default process group")
        world = dist.get_world_size(group) if dist.is_initialized() else 1
        rank = dist.get_rank(group) if dist.is_initialized() else 0
        capacities = [None] * world
        if world > 1:
            dist.all_gather_object(capacities, cache_capacity_bytes, group=group)
        else:
            capacities[0] = cache_capacity_bytes
        heads = projection_layers[0][1].out_features
        width = projection_layers[0][1].in_features
        admission = {"binding": binding, "tokens": tokens, "batch": batch, "heads": heads,
                     "layers": len(projection_layers), "query_rows": query_rows,
                     "required_cache_bytes": batch * tokens * tokens * heads * len(projection_layers) * 4,
                     "chunk_bytes": batch * query_rows * tokens * heads * len(projection_layers) * 4,
                     "capacities_bytes": capacities, "planning_passed": False}
        try:
            intervals = plan_cached_query_intervals(tokens, query_rows, batch, heads,
                                                   len(projection_layers), capacities)
        except MemoryError as error:
            admission["failure"] = str(error)
            if rank == 0:
                print("[CACHED_DIFFUSION_ADMISSION] " + json.dumps(admission, sort_keys=True), flush=True)
            raise
        admission.update(planning_passed=True, intervals=intervals)
        if rank == 0:
            print("[CACHED_DIFFUSION_ADMISSION] " + json.dumps(admission, sort_keys=True), flush=True)
        error = None
        if rank == 0 and (provider is None or provider.conditioned.shape != (batch, tokens, tokens, width)
                          or provider.chunk_rows != projection_rows or len(provider) != len(projection_layers)):
            error = "Root provider does not match cache dimensions"
        errors = [error]
        if world > 1:
            dist.broadcast_object_list(errors, src=0, group=group)
        if errors[0]:
            raise ValueError(errors[0])
        start, end = intervals[rank]
        values = torch.empty(len(projection_layers), batch, end - start, tokens, heads,
                             dtype=torch.float32, device=device)
        cache = cls(values, intervals, rank, query_rows, binding)
        cache.projection_precision = projection_precision
        layers = copy.deepcopy(projection_layers).to(device=device)
        if any(parameter.dtype != torch.float32 for parameter in layers.parameters()):
            raise ValueError("Cached bias projections must remain FP32")
        with torch.autocast(device_type=device.type, dtype=torch.bfloat16,
                            enabled=projection_precision == "bf16-mixed"):
            for owner, (owned_start, owned_end) in enumerate(intervals):
                if rank not in (0, owner):
                    continue
                for tile_start in range(owned_start, owned_end, projection_rows):
                    tile_end = min(tile_start + projection_rows, tokens)
                    if rank == 0:
                        tile = provider.conditioned[:, tile_start:tile_end].to(device=device).contiguous()
                        if owner != 0:
                            dist.send(tile, dst=owner, group=group)
                    else:
                        tile = torch.empty(batch, tile_end - tile_start, tokens, width,
                                           dtype=torch.float32, device=device)
                        dist.recv(tile, src=0, group=group)
                    if rank == owner:
                        cache.source_transfer_bytes += tile.numel() * tile.element_size()
                        for index, layer in enumerate(layers):
                            values[index, :, tile_start - start:tile_end - start].copy_(layer(tile))
                            cache.projection_calls += 1
                    del tile
        del layers
        if world > 1:
            dist.barrier(group=group)
        return cache

    def rows(self, layer, start, end, binding):
        if self.closed or binding != self.binding:
            raise ValueError("Closed cache or changed conditioning binding")
        owned_start, owned_end = self.intervals[self.rank]
        if not 0 <= layer < self.values.shape[0] or not owned_start <= start < end <= owned_end:
            raise ValueError("Cache request exceeds owned rows or layers")
        self.hits += 1
        return self.values[layer, :, start - owned_start:end - owned_start]

    def close(self):
        self.values = None
        self.closed = True


def run_cached_token_stack(transformer, activation, conditioning, cache, mask, *, binding, group=None):
    if cache.closed or binding != cache.binding:
        raise ValueError("Closed cache or changed conditioning binding")
    if len(transformer.layers) != cache.values.shape[0] or cache.values.shape[1] != activation.shape[0]:
        raise ValueError("Cache does not match the token transformer")
    world = dist.get_world_size(group) if dist.is_initialized() else 1
    rank = dist.get_rank(group) if dist.is_initialized() else 0
    if rank != cache.rank or world != len(cache.intervals):
        raise ValueError("Cache communicator or rank changed")
    batch, tokens, width = activation.shape
    max_rows = max(end - start for start, end in cache.intervals)

    def gather(local):
        if world == 1:
            return local
        padded = activation.new_zeros(batch, max_rows, width)
        padded[:, :local.shape[1]].copy_(local)
        gathered = activation.new_empty(world * batch, max_rows, width)
        dist.all_gather_into_tensor(gathered, padded, group=group)
        gathered = gathered.view(world, batch, max_rows, width)
        output = activation.new_empty(batch, tokens, width)
        for owner, (start, end) in enumerate(cache.intervals):
            output[:, start:end].copy_(gathered[owner, :, :end - start])
        return output

    for index, layer in enumerate(transformer.layers):
        activation = run_chunked_diffusion_layer(
            layer, activation, conditioning,
            lambda start, end: cache.rows(index, start, end, binding), mask, cache.query_rows,
            query_interval=cache.intervals[rank], gather_pre_output=gather)
    return activation


class CachedTokenAttentionService:
    """Keep the native sampler on rank zero and dispatch only token attention."""

    def __init__(self, transformer, projection_layers, *, device, binding, query_rows=128,
                 projection_rows=32, workspace_bytes=4096 * 2**20, gpu_gate_bytes=77000 * 2**20,
                 cpu_cache_capacity_bytes=2**30, projection_precision="32-true"):
        self.transformer = transformer
        self.projection_layers = projection_layers
        self.device = torch.device(device)
        if self.device.type == "cuda" and self.device.index is None:
            self.device = torch.device("cuda", torch.cuda.current_device())
        self.binding = binding
        self.query_rows = query_rows
        self.projection_rows = projection_rows
        self.workspace_bytes = workspace_bytes
        if gpu_gate_bytes is not None and gpu_gate_bytes <= 0:
            raise ValueError("GPU cache ceiling must be positive or device-derived")
        self.gpu_gate_bytes = gpu_gate_bytes
        self.cpu_cache_capacity_bytes = cpu_cache_capacity_bytes
        self.projection_precision = projection_precision
        self.rank = dist.get_rank()
        self.cache = None
        self.provider = None
        self.provider_tensor = None
        self.budget = None

    def _command(self, value=0):
        command = torch.tensor([value], dtype=torch.int64, device=self.device)
        dist.broadcast(command, src=0)
        return int(command.item())

    def _tensor(self, value=None):
        metadata = [(tuple(value.shape), value.dtype) if self.rank == 0 else None]
        dist.broadcast_object_list(metadata, src=0)
        shape, dtype = metadata[0]
        if dtype != torch.float32:
            raise ValueError("Token service transport must be FP32")
        tensor = value.contiguous() if self.rank == 0 else torch.empty(shape, dtype=dtype, device=self.device)
        if tensor.device != self.device:
            raise ValueError("Token service tensor is on the wrong device")
        dist.broadcast(tensor, src=0)
        return tensor

    def _prepare(self, provider=None):
        metadata = [tuple(provider.conditioned.shape) if self.rank == 0 else None]
        dist.broadcast_object_list(metadata, src=0)
        batch, tokens, _, _ = metadata[0]
        self.transformer.to(device=self.device)
        if self.device.type == "cuda":
            torch.cuda.empty_cache()
            allocated = torch.cuda.memory_allocated(self.device)
            free, total = torch.cuda.mem_get_info(self.device)
            gpu_gate_bytes = total if self.gpu_gate_bytes is None else min(self.gpu_gate_bytes, total)
            capacity = max(0, min(gpu_gate_bytes - allocated, free) - self.workspace_bytes)
        else:
            allocated, free, total = 0, self.cpu_cache_capacity_bytes, self.cpu_cache_capacity_bytes
            capacity = self.cpu_cache_capacity_bytes
            gpu_gate_bytes = self.gpu_gate_bytes
        self.budget = {"rank": self.rank, "allocated_before_cache": allocated, "driver_free_bytes": free,
                       "gpu_total_bytes": total, "workspace_reserve_bytes": self.workspace_bytes,
                       "cache_capacity_bytes": capacity, "gpu_gate_bytes": gpu_gate_bytes,
                       "gpu_limit_policy": "device_total" if self.gpu_gate_bytes is None else "configured_ceiling",
                       "reserved_before_cache": torch.cuda.memory_reserved(self.device) if self.device.type == "cuda" else 0}
        print("[CACHED_DIFFUSION_BUDGET] " + json.dumps(self.budget, sort_keys=True), flush=True)
        self.cache = ShardedTokenBiasCache.build(
            provider, self.projection_layers, tokens=tokens, batch=batch,
            query_rows=self.query_rows, projection_rows=self.projection_rows,
            device=self.device, binding=self.binding, cache_capacity_bytes=capacity,
            projection_precision=self.projection_precision)
        self.budget["cache_bytes"] = self.cache.values.numel() * self.cache.values.element_size()
        self.budget["intervals"] = self.cache.intervals
        self.budget["projection_precision"] = self.projection_precision
        if self.rank == 0:
            self.provider = provider
            self.provider_tensor = provider.conditioned

    def prepare(self, provider):
        if self.rank != 0 or self.cache is not None:
            raise ValueError("Only rank zero may prepare a fresh token service")
        self._command(1)
        self._prepare(provider)

    def run(self, transformer, activation, conditioning, provider, mask, query_rows):
        if (self.rank != 0 or self.cache is None or transformer is not self.transformer
                or provider is not self.provider or provider.conditioned is not self.provider_tensor
                or query_rows != self.query_rows):
            raise ValueError("Token service conditioning, model, or layout changed")
        self._command(2)
        return self._run(activation, conditioning, mask)

    def _run(self, activation=None, conditioning=None, mask=None):
        activation = self._tensor(activation)
        conditioning = self._tensor(conditioning)
        mask = self._tensor(mask)
        return run_cached_token_stack(self.transformer, activation, conditioning, self.cache, mask,
                                      binding=self.binding)

    def serve(self):
        if self.rank == 0:
            raise ValueError("Rank zero owns the native sampler")
        while True:
            command = self._command()
            if command == 1 and self.cache is None:
                self._prepare()
            elif command == 2 and self.cache is not None:
                self._run()
            elif command == 3:
                self._close()
                return
            else:
                raise ValueError("Invalid token service command or lifetime")

    def _close(self):
        if self.cache is not None:
            self.cache.close()
        self.provider = self.provider_tensor = None
        if self.rank != 0:
            self.transformer.cpu()
        if self.device.type == "cuda":
            torch.cuda.empty_cache()
        dist.barrier()

    def close(self):
        if self.rank != 0:
            raise ValueError("Only rank zero may stop the token service")
        self._command(3)
        self._close()


def run_cached_diffusion_sampling(structure_module, projection_layers, sample_kwargs, *,
                                 device, binding, projection_precision, query_rows=128,
                                 projection_rows=32):
    transformer = structure_module.score_model.token_transformer
    if getattr(transformer, "_dap_token_attention_service", None) is not None:
        raise ValueError("A token cache is already active for this transformer")
    rank = dist.get_rank()
    gpu_limit = os.environ.get("BOLTZ_DIFFUSION_CACHE_GPU_LIMIT_MIB", "77000")
    service = CachedTokenAttentionService(
        transformer, projection_layers, device=device, binding=binding,
        query_rows=query_rows, projection_rows=projection_rows,
        projection_precision=projection_precision,
        gpu_gate_bytes=None if gpu_limit == "device" else int(gpu_limit) * 2**20,
        workspace_bytes=(16 * 2**30 if rank == 0 else 3 * 2**30))
    output = None
    with torch.autocast(device_type=torch.device(device).type, enabled=False):
        if rank == 0:
            provider = sample_kwargs["diffusion_conditioning"]["token_trans_bias"]
            service.prepare(provider)
            initial_counters = (service.cache.projection_calls, service.cache.source_transfer_bytes)
            transformer._dap_token_attention_service = service
            try:
                output = structure_module.sample(**sample_kwargs)
                if initial_counters != (service.cache.projection_calls, service.cache.source_transfer_bytes):
                    raise AssertionError("Static bias was rebuilt during diffusion sampling")
            finally:
                del transformer._dap_token_attention_service
                service.close()
        else:
            service.serve()
    receipt = dict(service.budget, rank=rank, binding=binding, closed=service.cache.closed,
                   projection_calls=service.cache.projection_calls,
                   source_transfer_bytes=service.cache.source_transfer_bytes,
                   cache_hits=service.cache.hits)
    structure_module._dap_cache_receipt = receipt
    print("[CACHED_DIFFUSION] " + json.dumps(receipt, sort_keys=True), flush=True)
    return output