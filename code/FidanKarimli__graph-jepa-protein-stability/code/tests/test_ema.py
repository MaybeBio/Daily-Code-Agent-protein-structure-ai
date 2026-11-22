"""The teacher must trail the student by exactly the stated amount, and never learn."""
import pytest
import torch

from pobj.models.ema import EMATeacher
from pobj.models.encoder import Encoder
from pobj.utils import set_seed


@pytest.fixture
def student():
    set_seed(0)
    return Encoder(dim=16, layers=2, dropout=0.0)


def test_teacher_starts_as_a_copy(student):
    teacher = EMATeacher(student)
    for t, s in zip(teacher.encoder.parameters(), student.parameters()):
        assert torch.equal(t, s)


def test_teacher_takes_no_gradients(student):
    teacher = EMATeacher(student)
    assert all(not p.requires_grad for p in teacher.encoder.parameters())


def test_update_moves_by_one_minus_momentum(student):
    """teacher <- m * teacher + (1 - m) * student, checked against hand arithmetic."""
    teacher = EMATeacher(student, momentum_start=0.9, momentum_end=0.9, total_steps=10)
    before = [p.clone() for p in teacher.encoder.parameters()]

    with torch.no_grad():
        for p in student.parameters():
            p.add_(1.0)                       # move the student a known distance

    teacher.update(student)
    for old, new, s in zip(before, teacher.encoder.parameters(), student.parameters()):
        assert torch.allclose(new, 0.9 * old + 0.1 * s, atol=1e-6)


def test_momentum_rises_to_the_end_value(student):
    teacher = EMATeacher(student, momentum_start=0.99, momentum_end=0.9999,
                         total_steps=100)
    assert teacher.momentum() == pytest.approx(0.99)
    teacher.steps = 50
    assert teacher.momentum() == pytest.approx(0.99495)
    teacher.steps = 100
    assert teacher.momentum() == pytest.approx(0.9999)
    teacher.steps = 500                        # never past the end value
    assert teacher.momentum() == pytest.approx(0.9999)


def test_teacher_lags_rather_than_following(student):
    """After one update the teacher must have moved, but nowhere near all the way."""
    teacher = EMATeacher(student, momentum_start=0.99, momentum_end=0.99, total_steps=1)
    start = [p.clone() for p in teacher.encoder.parameters()]

    with torch.no_grad():
        for p in student.parameters():
            p.add_(1.0)
    teacher.update(student)

    moved = sum(float((new - old).abs().sum())
                for old, new in zip(start, teacher.encoder.parameters()))
    total = sum(p.numel() for p in student.parameters())
    assert moved == pytest.approx(0.01 * total, rel=1e-3)
