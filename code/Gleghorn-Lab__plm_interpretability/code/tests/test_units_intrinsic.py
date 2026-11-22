from __future__ import annotations

import numpy as np

from plm_interpretability.units import intrinsic


def test_intervals_are_one_based_and_inclusive() -> None:
    assert intrinsic.intervals(np.array([True, True, False, True])) == [(1, 2), (4, 4)]
    assert intrinsic.intervals(np.zeros(3, dtype=bool)) == []


def test_window_cover_spans_each_hit_window() -> None:
    hits = np.array([False, True, False, False])  # window starts over a length-6 sequence with window 3
    assert intrinsic.window_cover(hits, 3, 6).tolist() == [False, True, True, True, False, False]


def test_residues_and_termini() -> None:
    terms = intrinsic.intrinsic_terms("MKCAKC")
    assert terms["residue:K"] == [(2, 2), (5, 5)]
    assert terms["residue:C"] == [(3, 3), (6, 6)]
    assert terms["terminus:n"] == [(1, 5)] and terms["terminus:c"] == [(2, 6)]
    assert "residue:W" not in terms


def _covers(found: list[tuple[int, int]], core: tuple[int, int], bound: tuple[int, int]) -> bool:
    """One interval that contains the core and stays inside the bound (qualifying windows may reach into flanks)."""
    return len(found) == 1 and found[0][0] <= core[0] and found[0][1] >= core[1] and found[0][0] >= bound[0] and found[0][1] <= bound[1]


def test_low_complexity_flags_a_repeat_and_spares_a_diverse_stretch() -> None:
    diverse = "ACDEFGHIKLMNPQRSTVWY"
    terms = intrinsic.intrinsic_terms(diverse + "Q" * 15 + diverse)
    # The run is residues 21 to 35; a 12-window needs seven Q to fall below 2.2 bits, so at most five flank residues join.
    assert _covers(terms["low_complexity"], (21, 35), (16, 40))


def test_hydrophobic_stretch_finds_a_transmembrane_like_segment() -> None:
    sequence = "DEKRDEKRSTNQ" + "LIVLAFLIVALLIVAVLFL" + "DEKRDEKRSTNQ"
    assert _covers(intrinsic.intrinsic_terms(sequence)["hydrophobic_stretch"], (13, 31), (6, 38))
    assert "hydrophobic_stretch" not in intrinsic.intrinsic_terms("DEKRDEKRSTNQ" * 3)


def test_amphipathic_helix_pattern_scores_and_a_uniform_one_does_not() -> None:
    # Hydrophobic and charged residues alternating with the helical period of about 3.6 residues.
    helix = "LKKLLKKLLKKLLKKLLKKL"
    assert "amphipathic" in intrinsic.intrinsic_terms(helix)
    assert "amphipathic" not in intrinsic.intrinsic_terms("L" * 20)


def test_runs_of_charge_and_proline_glycine() -> None:
    terms = intrinsic.intrinsic_terms("AAAAKRKRKAAAAEEDEDAAPGPGAA")
    # Runs at 5-9 (KRKRK), 14-18 (EEDED) and 21-24 (PGPG); a 6-window needs five charges or four of P and G.
    assert _covers(terms["charge_run:positive"], (5, 9), (4, 10))
    assert _covers(terms["charge_run:negative"], (14, 18), (13, 19))
    assert _covers(terms["proline_glycine_rich"], (21, 24), (19, 26))


def test_every_term_is_declared() -> None:
    terms = intrinsic.intrinsic_terms("MKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQAPILSRVGDGTQDNLSGAEKAVQVKVKALPDAQFEVVHSLAKWKRQTLGQHDFSAGEGLYTHMKALRPDEDRLSPLHSVYVDQWDWERVMGDGERQFSTLKSTVEAIWAGIKATEAAVSEEFGLAPFLPDQIHFVHSQELLSRYPDLDAKGRERAIAKDLGAVFLVGIGGKLSDGHRHDVRAPDYDDWUAPSAPDF".replace("U", "C"))
    assert set(terms) <= set(intrinsic.TERMS)
