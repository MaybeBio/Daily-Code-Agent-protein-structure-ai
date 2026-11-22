"""LoupMD's exceptions and their message shape.

Every exception LoupMD raises derives from ``LoupError``. Its message has one shape, so that no traceback needs
reading: what happened; why, in a sentence or two; what to do next. This module imports nothing else of the package.
"""
from __future__ import annotations


def _restore(cls, args, state):
    """Unpickle an exception without calling its ``__init__`` (whose signature differs per class)."""
    error = cls.__new__(cls)
    error.args = args
    error.__dict__.update(state)
    return error


class LoupError(Exception):
    """Base class of every error LoupMD raises: ``LoupError(what, why=None, next_step=None)``."""

    default_next_step = None

    def __init__(self, what, why=None, next_step=None):
        super().__init__(str(what))
        self.what = str(what)
        self.why = why
        self.next_step = self.default_next_step if next_step is None else next_step

    def __str__(self):
        lines = [self.what]
        if self.why:
            lines.append(f"Why: {self.why}")
        if self.next_step:
            lines.append(f"Next: {self.next_step}")
        return "\n".join(lines)

    def __reduce__(self):
        return _restore, (type(self), self.args, dict(self.__dict__))


class BackendError(LoupError, RuntimeError):
    """A call into libloupmd failed or was refused. ``what`` is the library's own message (``loup_last_error``);
    ``call`` names the C function."""

    def __init__(self, what, why=None, next_step=None, call=None):
        super().__init__(what, why, next_step)
        self.call = call


class InputError(LoupError, ValueError):
    """An argument is refused before the library reads it (a wrong array shape, for example)."""


class CheckpointTrustError(LoupError):
    """A checkpoint would be unpickled without a matching SHA-256 or ``trusted=True``."""

    default_next_step = ("Pass sha256= with the file's published hash, or trusted=True for a file you trust; "
                         "a checkpoint is a pickle and runs code when loaded.")


class CacheLocationError(LoupError):
    """The cache root is somewhere it must not be (inside the Python installation)."""


# --------------------------------------------------------------------------------------------- model and plan

class UnsupportedModel(LoupError):
    """The library has no compiled kernels for this model's architecture. ``signature`` names the missing kernels."""

    default_next_step = ("Build a library with this model's kernels: loupmd build-kernels MODEL (needs nvcc), or use a "
                         "model of a supported architecture.")

    def __init__(self, what, why=None, next_step=None, signature=None):
        super().__init__(what, why, next_step)
        self.signature = signature


class ModelElementError(LoupError):
    """The structure has an element the model has no embedding for."""

    default_next_step = "Use a model trained on that element, or remove it from the structure."


class PlanRefused(LoupError, ValueError):
    """The run cannot be planned as asked. ``reasons`` lists every reason at once; nothing is replaced silently."""

    default_next_step = "Change the inputs each reason names; a refused setting is never replaced by another."

    def __init__(self, reasons, why=None, next_step=None):
        self.reasons = (reasons,) if isinstance(reasons, str) else tuple(str(r) for r in reasons)
        super().__init__("plan refused: " + "; ".join(self.reasons), why, next_step)


class CapacityError(LoupError):
    """The system does not fit the GPU in the execution mode asked for."""

    default_next_step = ("Let LoupMD choose the mode (capacity='auto'), which runs large cells tiled, or use a "
                         "smaller cell or a GPU with more memory.")


# ------------------------------------------------------------------------------------------------- the gate

class _GateError(LoupError):
    """A gate result that stops the run; ``gate_record`` holds the comparison."""

    def __init__(self, what, why=None, next_step=None, gate_record=None):
        super().__init__(what, why, next_step)
        self.gate_record = gate_record


class GateFailed(_GateError):
    """The accuracy gate on the user's structure failed (the 3x rule against MACE float64)."""

    default_next_step = "Read the failed quantities in the gate record, and report the model and structure."


class GateUnavailable(_GateError):
    """The gate's reference could not be computed (the export extra is missing, or no device has the memory)."""

    default_next_step = ("Install the export extra (pip install 'loupmd[export]'), or run without the gate "
                         "(check=\"skip\"), which the run then records.")


# ------------------------------------------------------------------------------------------ restart, runtime

class RestartMismatch(LoupError):
    """A restart does not belong to this model, element set or atom count."""

    default_next_step = "Resume with the model and structure the restart was written with."


class NonFiniteError(LoupError):
    """A non-finite energy or force stopped the run; it is never patched over."""

    default_next_step = "Check the structure and the timestep, and resume from the last restart point."


class CellDivergedError(LoupError):
    """An NPT run's cell left the range its integrator allows; ``step`` is the step whose cell was checked."""

    default_next_step = ("The structure left its condensed phase or the barostat diverged: raise the pressure, lower "
                         "the temperature, or couple the cell more slowly. No restart is written at the stop; the last "
                         "one written before it holds an earlier state.")

    def __init__(self, what, why=None, next_step=None, step=None):
        super().__init__(what, why, next_step)
        self.step = step
