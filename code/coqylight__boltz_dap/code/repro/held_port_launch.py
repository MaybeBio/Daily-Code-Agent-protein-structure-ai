"""Keep an OS-assigned TCPStore port bound throughout static torchrun startup."""

from datetime import timedelta
import json
import os
from pathlib import Path
import sys
from threading import Event
import time


def publish(path, record):
    temporary = path.with_suffix(f".{os.getpid()}.tmp")
    with temporary.open("x") as handle:
        json.dump(record, handle, sort_keys=True, allow_nan=False)
        handle.flush()
        os.fsync(handle.fileno())
    if path.exists():
        raise FileExistsError(path)
    temporary.rename(path)


def held_endpoint(output, arguments, timeout_seconds=180):
    import torch.distributed as distributed

    nodes = int(arguments.nnodes)
    if (nodes < 1 or not 0 <= arguments.node_rank < nodes or arguments.rdzv_backend != "static"
            or arguments.max_restarts != 0):
        raise ValueError("Fixed-size static rendezvous without retries required")
    expected = {"job_id": os.environ.get("SLURM_JOB_ID", "local-test"), "output": str(output.resolve()),
                "host": arguments.master_addr, "nodes": nodes, "listener_held": True}
    endpoint_path = output / "rendezvous_endpoint.json"
    timeout = timedelta(seconds=timeout_seconds)
    if arguments.node_rank == 0:
        if endpoint_path.exists():
            raise FileExistsError(endpoint_path)
        store = distributed.TCPStore(arguments.master_addr, 0, is_master=True, wait_for_workers=False,
                                     multi_tenant=True, timeout=timeout)
        record = dict(expected, port=store.port, owner_pid=os.getpid())
        store.set("held_port_launch_binding", json.dumps(record, sort_keys=True))
        publish(endpoint_path, record)
    else:
        deadline = time.monotonic() + timeout_seconds
        event = Event()
        while not endpoint_path.exists():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Master did not publish a held rendezvous endpoint")
            event.wait(min(0.1, remaining))
        record = json.loads(endpoint_path.read_text())
        if any(record.get(key) != value for key, value in expected.items()):
            raise ValueError("Rendezvous endpoint belongs to a different launch")
        if not isinstance(record.get("port"), int) or not 0 < record["port"] < 65536:
            raise ValueError("Invalid held rendezvous port")
        store = distributed.TCPStore(record["host"], record["port"], is_master=False, timeout=timeout)
        if store.get("held_port_launch_binding").decode() != json.dumps(record, sort_keys=True):
            raise ValueError("TCPStore does not match the published launch binding")
    publish(output / f"rendezvous_node_{arguments.node_rank}.json", dict(record, node_rank=arguments.node_rank, connected=True))
    return store, record


def probe_worker(output):
    import torch
    import torch.distributed as distributed

    distributed.init_process_group("gloo", timeout=timedelta(seconds=90))
    rank, world_size = distributed.get_rank(), distributed.get_world_size()
    value = torch.tensor([rank], dtype=torch.int64)
    distributed.all_reduce(value)
    if value.item() != world_size * (world_size - 1) // 2 or torch.cuda.is_initialized():
        raise AssertionError("CPU startup probe failed")
    publish(output / f"startup_probe_rank{rank}.json", {"rank": rank, "world_size": world_size,
            "all_reduce_sum": value.item(), "passed": True, "cuda_initialized": False,
            "master_port": int(os.environ["MASTER_PORT"]), "job_id": os.environ.get("SLURM_JOB_ID"),
            "host": os.uname().nodename})
    distributed.barrier()
    distributed.destroy_process_group()


def verify_probe(output):
    import hashlib

    endpoint_path = output / "rendezvous_endpoint.json"
    endpoint = json.loads(endpoint_path.read_text())
    reports = [json.loads((output / f"startup_probe_rank{rank}.json").read_text()) for rank in range(32)]
    job_id = os.environ["SLURM_JOB_ID"]
    if endpoint["nodes"] != 4 or endpoint["job_id"] != job_id or not endpoint["listener_held"]:
        raise ValueError("Unexpected CPU probe endpoint")
    if len({report["host"] for report in reports}) != 4:
        raise ValueError("CPU probe did not span four hosts")
    for rank, report in enumerate(reports):
        if (report["rank"] != rank or report["world_size"] != 32 or report["all_reduce_sum"] != 496
                or report["passed"] is not True or report["cuda_initialized"] is not False
                or report["job_id"] != job_id or report["master_port"] != endpoint["port"]):
            raise ValueError("Incomplete 32-process CPU startup proof")
    for rank in range(4):
        receipt = json.loads((output / f"rendezvous_node_{rank}.json").read_text())
        if receipt != dict(endpoint, node_rank=rank, connected=True):
            raise ValueError("Launcher node used a different rendezvous")
    paths = [endpoint_path, *sorted(output.glob("rendezvous_node_*.json")), *sorted(output.glob("startup_probe_rank*.json"))]
    publish(output / "report.json", {"passed": True, "nodes": 4, "workers": 32, "job_id": job_id,
            "cuda_initialized": False, "learned_weights_loaded": False,
            "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "evidence": {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}})
    print("Four-node 32-process held-port startup probe passed", flush=True)


def main():
    if sys.argv[1] == "--probe-worker":
        return probe_worker(Path(sys.argv[2]))
    if sys.argv[1] == "--verify-probe":
        return verify_probe(Path(sys.argv[2]))
    from torch.distributed.run import get_args_parser, run

    output = Path(sys.argv[1]).resolve()
    arguments = get_args_parser().parse_args(sys.argv[2:])
    store, endpoint = held_endpoint(output, arguments)
    arguments.master_port = endpoint["port"]
    print(f"[RENDEZVOUS] node={arguments.node_rank} host={endpoint['host']} port={store.port} listener_held=True", flush=True)
    run(arguments)


if __name__ == "__main__":
    main()