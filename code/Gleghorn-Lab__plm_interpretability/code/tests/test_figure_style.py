"""The one naming scheme for probed states: its two renderings, its check for old names, and Protify's labels."""

from __future__ import annotations

import pytest

from pathlib import Path

from plm_interpretability.figure_style import (CONTROLS, INTERVAL_FILL, KIND_COLORS, KIND_TAGS, LABEL_SET_COLORS, MEAN_ONLY_COLORS, MODEL_COLORS, OTHER_SERIES, PROBE_COLORS, PROTIFY_ROW_BAND,
                                      PUBLISHED_COLOR, READ_STATE_COLORS, ROW_BAND, SITE_PARTS, STRUCTURE_COLORS, TASK_NAMES, install, interval_marks, site_math, site_tex, stale_names)


def test_a_site_has_its_family_and_a_true_subscript() -> None:
    assert site_math("mlp_gate") == r"$\mathrm{MLP}_{\mathrm{gate}}$"
    assert site_tex("mlp_gate") == r"\site{MLP}{gate}"
    assert site_tex("q_rot") == r"\site{Attn}{Qrot}"
    assert site_tex("final_norm") == r"\site{Resid}{final}"
    assert site_tex("embedding") == r"\site{Resid}{embed}"


def test_the_structure_stream_has_no_subscript() -> None:
    assert site_math("structural") == r"$\mathrm{Struct}$"
    assert site_tex("structural") == r"\site{Struct}{}"


@pytest.mark.parametrize("text", ["attn LN", "Attention LN", "Q rotated", "MLP up", "mlp_gate", "final norm", "structure stream", "Q", "embedding",
                                  "structure stream minus best stream state"])
def test_old_names_are_stale(text: str) -> None:
    assert stale_names([text]) == [text]


@pytest.mark.parametrize("text", ["MLP", "MLP minus linear", "MLP sites", "residual stream", "token embedding here", site_math("mlp_up"), "A"])
def test_other_words_are_not_stale(text: str) -> None:
    assert stale_names([text]) == []


def test_install_renames_every_protify_site_and_refuses_an_old_name_at_save(tmp_path: Path) -> None:
    pytest.importorskip("matplotlib")
    from src.protify.interpretability import figures

    install()
    install()  # a second call does not wrap the save twice
    assert set(figures.SITE_LABELS) == set(SITE_PARTS)
    assert all(label == site_math(site) for site, label in figures.SITE_LABELS.items())
    plt = figures._pyplot()
    figure, axis = plt.subplots()
    axis.plot([0, 1], [0, 1], label="final norm")  # spelled out in Protify's code, so replaced at save
    legend = axis.legend()
    figures._save(figure, tmp_path / "spelled.png")
    assert legend.get_texts()[0].get_text() == site_math("final_norm")
    figure, axis = plt.subplots()
    axis.set_xticks([0.0])
    axis.set_xticklabels(["MLP gate"])
    with pytest.raises(ValueError, match="MLP gate"):
        figures._save(figure, tmp_path / "stale.png")


def test_saving_gives_row_bands_and_intervals_their_contrast(tmp_path: Path) -> None:
    pytest.importorskip("matplotlib")
    from matplotlib.colors import to_rgba
    from src.protify.interpretability import figures

    install()
    plt = figures._pyplot()
    figure, axis = plt.subplots()
    band = axis.axhspan(0.0, 1.0, color=PROTIFY_ROW_BAND, lw=0)
    interval = axis.fill_between([0.0, 1.0], [0.0, 0.0], [1.0, 1.0], color="#2a78d6", alpha=0.15, lw=0)
    violin = axis.fill_between([0.0, 1.0], [0.0, 0.0], [1.0, 1.0], color="#2a78d6", alpha=0.35, lw=0)
    figures._save(figure, tmp_path / "bands.png")
    assert band.get_facecolor() == to_rgba(ROW_BAND)
    assert interval.get_facecolor()[0][3] == pytest.approx(INTERVAL_FILL)
    assert interval.get_edgecolor()[0][:3] == pytest.approx(to_rgba("#2a78d6")[:3])
    assert violin.get_alpha() == 0.35  # a filled shape that is no interval keeps its look


def test_the_model_hues_mean_models_and_nothing_else() -> None:
    others = {*PROBE_COLORS.values(), *MEAN_ONLY_COLORS.values(), *KIND_COLORS.values(), *STRUCTURE_COLORS.values(), *LABEL_SET_COLORS, *OTHER_SERIES, PUBLISHED_COLOR,
              *(color for pair in READ_STATE_COLORS.values() for color in pair), *(style.color for style in CONTROLS.values())}
    assert not others & set(MODEL_COLORS.values())
    assert all(len({style.color[1:3], style.color[3:5], style.color[5:7]}) == 1 for style in CONTROLS.values())  # controls are neutral grays


def test_kind_tags_only_break_the_full_name() -> None:
    assert all(tag.replace("\n", " ") == kind for kind, tag in KIND_TAGS.items())


def test_a_control_keeps_its_mark_on_an_interval(tmp_path: Path) -> None:
    pytest.importorskip("matplotlib")
    from src.protify.interpretability import figures

    install()
    plt = figures._pyplot()
    figure, axis = plt.subplots()
    interval_marks(axis, [0.5], [0.0], [0.4], [0.6], CONTROLS["one-hot"].color, marker=CONTROLS["one-hot"].marker)
    points = axis.collections[-1]
    assert points.get_edgecolor()[0][:3].tolist() != [1.0, 1.0, 1.0]  # a line mark is its own edge, not lost in a white one
    plt.close(figure)


def test_the_pair_tasks_have_their_names_in_task_lists() -> None:
    pytest.importorskip("matplotlib")
    from src.protify.interpretability import figures

    install()
    assert figures.SHORT_LABELS["ppi"] == TASK_NAMES["ppi"] == "Interaction (2024)"
    assert figures.SHORT_LABELS["ppi2"] == TASK_NAMES["ppi2"] == "Interaction (2026)"
    assert figures.target_label("charge_at_ph4_7") == "charge, pH 4.7"
