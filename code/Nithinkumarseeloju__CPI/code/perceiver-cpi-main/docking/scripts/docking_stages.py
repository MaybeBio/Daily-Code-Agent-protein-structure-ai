"""Wall-clock timings and failure stages for one docking job."""
from contextvars import ContextVar
from datetime import datetime
from functools import wraps
from time import perf_counter

_events = ContextVar("docking_events", default=None)


def start_trace():
    events = []
    _events.set(events)
    return events


class Stage:
    def __init__(self, name):
        self.name = name

    def __enter__(self):
        self.start = perf_counter()
        print(f"{datetime.now().isoformat(timespec='seconds')} START {self.name}", flush=True)
        return self

    def __exit__(self, kind, error, traceback):
        elapsed = perf_counter() - self.start
        state = "FAILED" if kind else "END"
        print(f"{datetime.now().isoformat(timespec='seconds')} {state} {self.name} {elapsed:.2f}s", flush=True)
        events = _events.get()
        if events is not None:
            events.append(dict(stage=self.name, seconds=round(elapsed, 3), failed=bool(kind)))
        if error is not None and not hasattr(error, "docking_stage"):
            error.docking_stage = self.name


def timed(name):
    def decorate(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            with Stage(name):
                return fn(*args, **kwargs)
        return wrapper
    return decorate
