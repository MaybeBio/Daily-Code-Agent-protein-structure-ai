"""``lm.protocols`` (plan task S3-T06): schedules, their whole-step resolution, the schedule position and the
profiles. Pure Python."""
from __future__ import annotations

import pytest

from loupmd import protocols
from loupmd.errors import InputError
from loupmd.protocols import PROFILES, Schedule, ScheduleState, hold, ramp


def test_ramps_and_holds_concatenate_and_a_jump_is_refused():
    schedule = ramp(0, 400, ps=1.0) + hold(400, ps=0.5) + ramp(400, 100, rate_K_per_ps=-300)
    assert [s.phase for s in schedule.segments] == ["heating", "hold", "cooling"]
    assert schedule.duration_ps == pytest.approx(2.5)
    with pytest.raises(InputError, match="temperature jump: a segment ends at 400.0 K and the next starts at 300.0 K"):
        ramp(0, 400, ps=1.0) + hold(300, ps=1.0)


@pytest.mark.parametrize("make,message", [
    (lambda: ramp(0, 400), "needs exactly one of ps= and rate_K_per_ps="),
    (lambda: ramp(0, 400, ps=1.0, rate_K_per_ps=400), "needs exactly one of"),
    (lambda: ramp(0, 400, rate_K_per_ps=-100), "does not lead from 0.0 K to 400.0 K"),
    (lambda: ramp(-5, 400, ps=1.0), "start temperature must be finite and at least 0 K"),
    (lambda: hold(300, ps=0.0), "ps must be positive and finite"),
    (lambda: ramp(0, 400, ps=1e-6).resolve(1.0), "rounds to 0 steps at 1 fs"),
    (lambda: Schedule(()), "at least one segment"),
])
def test_bad_segments_are_refused(make, message):
    with pytest.raises(InputError) as caught:
        make()
    assert message in str(caught.value)


def test_resolution_rounds_half_up_to_whole_steps():
    resolved = (ramp(0, 400, ps=0.0105) + hold(400, ps=0.0045)).resolve(1.0)       # 10.5 and 4.5 steps
    assert resolved.segment_steps == (11, 5) and resolved.boundaries == (0, 11, 16) and resolved.total_steps == 16
    assert resolved.durations_ps == (0.011, 0.005)
    assert resolved.rates_K_per_ps[0] == pytest.approx(400 / 0.011) and resolved.rates_K_per_ps[1] == 0.0


def test_the_target_is_the_end_point_of_each_step():
    resolved = (ramp(0, 400, ps=0.004) + hold(400, ps=0.002) + ramp(400, 200, ps=0.004)).resolve(1.0)
    assert resolved.targets(0, 10) == [0.0, 100.0, 200.0, 300.0, 400.0, 400.0, 400.0, 350.0, 300.0, 250.0, 200.0]
    assert [resolved.phase(s) for s in (0, 1, 4, 5, 6, 7, 10)] == ["heating", "heating", "heating", "hold", "hold",
                                                                    "cooling", "cooling"]
    assert resolved.max_target(5, 9) == 400.0 and resolved.min_target(1, 9) == 100.0
    assert resolved.next_boundary(0) == 4 and resolved.next_boundary(4) == 6 and resolved.next_boundary(7) == 10
    assert resolved.output_steps(3) == [0, 3, 4, 6, 9, 10]            # step 0, every third, every boundary
    with pytest.raises(InputError, match="step 11 is outside the schedule"):
        resolved.target(11)


def test_the_schedule_position_and_its_restart_record():
    state = ScheduleState(ramp(0, 400, ps=0.004) + hold(400, ps=0.002), 1.0)
    assert (state.total_steps, state.remaining, state.finished, state.target_K) == (6, 6, False, 0.0)
    assert state.steps_to_run() == 6 and state.steps_to_run(2) == 2
    state.advance(3)
    assert state.step == 3 and state.target_K == 300.0
    record = state.to_restart()
    assert record == {"segments": [{"kind": "ramp", "start_K": 0.0, "end_K": 400.0, "ps": 0.004, "steps": 4},
                                   {"kind": "hold", "temperature_K": 400.0, "ps": 0.002, "steps": 2}],
                      "timestep_fs": 1.0, "step": 3, "target_K": 300.0}
    back = ScheduleState.from_restart(record)
    assert (back.step, back.target_K, back.schedule) == (3, 300.0, state.schedule)
    with pytest.raises(InputError, match="beyond the schedule: 3 of its 6 steps remain"):
        state.steps_to_run(4)
    state.advance(3)
    with pytest.raises(InputError, match="finished"):
        state.steps_to_run()
    with pytest.raises(InputError, match="stored target 123.0 K differs"):
        ScheduleState.from_restart(dict(record, target_K=123.0))
    with pytest.raises(InputError, match="stored segment steps"):
        ScheduleState.from_restart(dict(record, timestep_fs=2.0))


def test_segments_as_data_refuse_unknown_keys():
    schedule = ramp(0, 400, rate_K_per_ps=200) + hold(400, ps=1.0)
    assert Schedule.from_data(schedule.to_data()) == schedule
    with pytest.raises(InputError, match=r"ramp segment: missing \['end_K'\], unknown \['stop_K'\]"):
        Schedule.from_data([{"kind": "ramp", "start_K": 0, "stop_K": 400, "ps": 1.0}])
    with pytest.raises(InputError, match="segments must be a list"):
        Schedule.from_data({"kind": "hold"})


def test_the_four_profiles():
    assert sorted(PROFILES) == ["anneal", "fast", "slow", "ultrafast"]
    fast = PROFILES["fast"]
    assert fast.schedule == ramp(0, 400, ps=3.0) + ramp(400, 0, ps=24.0) and fast.sample_interval == 100
    for name, heat, cool in (("slow", 30.0, 240.0), ("fast", 3.0, 24.0), ("ultrafast", 1.0, 8.0)):
        segments = PROFILES[name].schedule.segments
        assert (segments[0].ps, segments[1].ps) == (heat, cool) and cool == 8 * heat
    anneal = PROFILES["anneal"]
    assert anneal.schedule.segments[1].end_K == 250.0 and anneal.trajectory_interval == 20
    assert anneal.relax_fmax == 0.01 and anneal.quench["bin_K"] == 100.0 and anneal.quench["per_bin"] == 2
    assert anneal.schedule.resolve(1.0).total_steps == 270_000


def test_profiles_from_data_and_files(tmp_path):
    data = {"name": "mine", "segments": [{"kind": "ramp", "start_K": 0, "end_K": 300, "ps": 2.0},
                                         {"kind": "hold", "temperature_K": 300, "ps": 5.0}], "sample_interval": 50}
    profile = protocols.profile_from_data(data)
    assert profile.name == "mine" and profile.sample_interval == 50 and profile.schedule.duration_ps == 7.0
    with pytest.raises(InputError, match=r"unknown profile keys \['thermostat'\]"):
        protocols.profile_from_data(dict(data, thermostat="langevin"))
    file = tmp_path / "mine.toml"
    file.write_text('name = "mine"\nsample_interval = 50\n[[segments]]\nkind = "ramp"\nstart_K = 0\nend_K = 300\n'
                    'ps = 2.0\n[[segments]]\nkind = "hold"\ntemperature_K = 300\nps = 5.0\n')
    assert protocols.load_profile(file) == profile
    with pytest.raises(InputError, match="profile files are .toml"):
        protocols.load_profile(tmp_path / "mine.yaml")


def test_a_profile_s_ensemble_and_pressure(tmp_path):
    """Owner's decision O23: a profile runs NVT or NPT at a constant pressure (0 GPa unless it names one)."""
    schedule = hold(300, ps=1.0)
    nvt = protocols.Profile("p", schedule)
    assert (nvt.ensemble, nvt.pressure_GPa) == ("NVT", None)
    assert nvt.md_options() == {"schedule": schedule, "ensemble": "NVT"}
    npt = protocols.Profile("p", schedule, ensemble="npt")
    assert (npt.ensemble, npt.pressure_GPa) == ("NPT", 0.0)
    pressed = protocols.Profile("p", schedule, ensemble="NPT", pressure_GPa=2)
    assert pressed.md_options() == {"schedule": schedule, "ensemble": "NPT", "pressure_GPa": 2.0}
    assert isinstance(pressed.pressure_GPa, float)
    with pytest.raises(InputError, match="pressure schedules are not supported"):
        protocols.Profile("p", schedule, ensemble="NPT", pressure_GPa=[0.0, 1.0])
    with pytest.raises(InputError, match="profile 'p': pressure_GPa=1.0 needs ensemble 'NPT'"):
        protocols.Profile("p", schedule, pressure_GPa=1.0)
    with pytest.raises(InputError, match="pressure_GPa must be a finite number of GPa"):
        protocols.Profile("p", schedule, ensemble="NPT", pressure_GPa=float("inf"))
    with pytest.raises(InputError, match="ensemble must be 'NVT' or 'NPT'"):
        protocols.Profile("p", schedule, ensemble="NVE")
    file = tmp_path / "press.toml"
    file.write_text('name = "press"\nensemble = "NPT"\npressure_GPa = 0.5\n[[segments]]\nkind = "hold"\n'
                    'temperature_K = 300\nps = 1.0\n')
    found = protocols.find_profile(str(file))
    assert (found.name, found.ensemble, found.pressure_GPa) == ("press", "NPT", 0.5)
    assert protocols.find_profile("fast") is protocols.PROFILES["fast"]
    assert all(profile.ensemble == "NVT" for profile in protocols.PROFILES.values())
