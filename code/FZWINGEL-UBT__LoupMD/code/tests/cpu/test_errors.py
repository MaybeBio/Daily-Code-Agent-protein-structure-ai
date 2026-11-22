"""The error classes of loupmd.errors: printed shape, bases, pickling. Needs neither the library nor a GPU."""
from __future__ import annotations

import pickle

import pytest

from loupmd.errors import BackendError, InputError, LoupError


def test_a_plain_error_prints_only_what_happened():
    assert str(LoupError("the bundle has no oxygen")) == "the bundle has no oxygen"


def test_why_and_next_step_are_printed_on_their_own_lines():
    err = LoupError("the bundle has no oxygen", why="it was exported for Sr and Ti", next_step="export it again")
    assert str(err) == "the bundle has no oxygen\nWhy: it was exported for Sr and Ti\nNext: export it again"
    assert (err.what, err.why, err.next_step) == ("the bundle has no oxygen", "it was exported for Sr and Ti",
                                                  "export it again")


def test_backend_error_carries_the_call_and_the_engine_text():
    err = BackendError("loup_evaluate: singular or zero cell", call="loup_evaluate")
    assert err.call == "loup_evaluate"
    assert str(err) == "loup_evaluate: singular or zero cell"


def test_bases_keep_existing_handlers_working():
    """Callers that caught RuntimeError from the engine or ValueError from the wrapper's shape checks still do."""
    assert issubclass(BackendError, LoupError) and issubclass(BackendError, RuntimeError)
    assert issubclass(InputError, LoupError) and issubclass(InputError, ValueError)
    with pytest.raises(RuntimeError, match="singular"):
        raise BackendError("loup_evaluate: singular or zero cell", call="loup_evaluate")


@pytest.mark.parametrize("err", [
    LoupError("a", why="b", next_step="c"),
    BackendError("loup_run: no system set", call="loup_run"),
    InputError("positions has shape (3,), expected (5, 3)"),
])
def test_errors_survive_pickling(err):
    back = pickle.loads(pickle.dumps(err))
    assert type(back) is type(err) and str(back) == str(err) and back.__dict__ == err.__dict__


def test_every_class_of_the_family_prints_its_message_and_its_way_out():
    from loupmd import errors

    family = [errors.BackendError, errors.InputError, errors.CheckpointTrustError, errors.CacheLocationError,
              errors.UnsupportedModel, errors.ModelElementError, errors.PlanRefused, errors.CapacityError,
              errors.GateFailed, errors.GateUnavailable, errors.RestartMismatch, errors.NonFiniteError,
              errors.CellDivergedError]
    for cls in family:
        assert issubclass(cls, LoupError), cls
        err = cls("something happened", why="because of that")
        text = str(err)
        assert "something happened" in text and "\nWhy: because of that" in text, cls
        if cls.default_next_step:
            assert text.endswith("\nNext: " + cls.default_next_step), cls
        own = cls("x", next_step="do this instead")
        assert str(own).endswith("\nNext: do this instead"), cls
        back = pickle.loads(pickle.dumps(err))
        assert type(back) is cls and str(back) == text
    assert len({cls.__name__ for cls in family}) == 13


def test_plan_refused_lists_every_reason_and_is_a_value_error():
    from loupmd.errors import PlanRefused

    err = PlanRefused(["precision='float64' is not built (use the float32 engine)", "reproducible=True is not built"])
    assert err.reasons == ("precision='float64' is not built (use the float32 engine)", "reproducible=True is not built")
    assert str(err).startswith("plan refused: precision='float64' is not built (use the float32 engine); "
                               "reproducible=True is not built\nNext: Change the inputs each reason names")
    assert isinstance(err, ValueError) and PlanRefused("one reason").reasons == ("one reason",)


def test_attributes_of_the_classes_that_carry_a_record():
    from loupmd import errors

    assert errors.UnsupportedModel("no kernels", signature="p0=abc").signature == "p0=abc"
    assert errors.GateFailed("gate failed", gate_record={"forces": 4.2}).gate_record == {"forces": 4.2}
    assert errors.CellDivergedError("cell diverged", step=1200).step == 1200
