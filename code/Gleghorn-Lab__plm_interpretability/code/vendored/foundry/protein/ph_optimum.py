"""The optimum pH that a UniProtKB pH-dependence text states, read sentence by sentence, and the rules that keep it as one label.

A curator states what a cited paper reports of the pH an enzyme works at in the ``phDependence`` text of a ``biophysicochemical
properties`` comment, and a text whose own evidence names ``ECO:0000269`` summarizes that paper. `judge_text` gives a text the
first of these reasons (`TEXT_REASONS`) that applies, or its one optimum when none does:

1. ``no_evidence_tag``: the text names no evidence key. UniProt's own index counts such a text as experimental, which the XML does
   not say, so it is not admitted.
2. ``no_experimental_evidence``: it names keys, and none of them is ``ECO:0000269`` (curator-inferred, similarity and other codes).
3. ``molecule_scoped_statement``: the comment names a ``molecule`` (an isoform, a chain or a processed product), or the text names
   an isoform, so the statement is not about the canonical sequence of the entry.
4. ``no_optimum_stated``: no sentence holds the words "optimum pH" (a stable range, an active range, a loss of activity, "optimum
   activity at pH 7.5"). A sentence that does is an optimum sentence, read as below.
5. ``unparseable_optimum``: an optimum sentence has a value the reader does not parse (a comma for a decimal, a chain of three
   numbers, a word where a number should stand). ``qualitative_optimum``: it states no number ("Optimum pH is acidic").
6. ``interval_optimum``: an optimum sentence states a range ("6.5-7.0", "between 6 and 9", "from 4 to 8"), or a bound ("below
   6.5", ">9.5", "5.5 or less"). An interval is not a point label without a separately frozen transformation; `optimum_statement`
   returns its low and high values.
7. ``several_ph_values``: the optimum sentences state more than one pH, as two sentences with different values or as one sentence
   with another bare pH-like number after its first ("8.5 at 30 degrees Celsius and 7.5 at 60 degrees Celsius"). A number
   followed by degrees, a percent sign or another unit of `UNITS` is no pH.
8. ``ph_outside_scale``: the point is not on the 0 to 14 scale (`SCALE`).
9. ``mutant_or_variant``: the text names a mutant, variant, chimera, truncation, fusion, engineered protein, substitution, deletion
   or insertion (`MUTANT_WORDS`), or a residue substitution such as E123A (`MUTATION_TOKEN`), so the protein reported is not the
   accession's sequence. BRENDA's comments are read with the same words.

What a release asks beyond the text, such as a citation behind its experiment, a whole sequence of a supported length and one row
per distinct assertion, its reader applies.

An optimum sentence is read word by word. The words are the sentence split at white space. The sentence is an optimum sentence
when it holds the words "optimum" and "pH" in a row. After them, "for", "to" or "of" and everything up to the first "is" are
skipped, or a bare "is" or "=" is. A hedge (about, around, approximately, near) and a word "pH" are then skipped, and the next
word, less its trailing punctuation, decides: "between" or "from" opens an interval, "above", "below", "over", "under" or a
leading "<" or ">" opens a bound, a number is a point unless "to", "-" or "or less" follows it, two numbers joined by a hyphen are
an interval, and no digit anywhere after "optimum pH" is a qualitative statement.
"""

from __future__ import annotations

import re

from collections.abc import Collection
from dataclasses import dataclass

from .uniprot_xml import EXPERIMENTAL, sentences_of


SCALE = (0.0, 14.0)
TRAILING = ".,;:)"
NUMBER = re.compile(r"[0-9]+(?:\.[0-9]+)?")
PAIR = re.compile(r"([0-9]+(?:\.[0-9]+)?)-([0-9]+(?:\.[0-9]+)?)")
HEDGES = ("about", "around", "approximately", "near")
BOUNDS = ("above", "below", "over", "under")
OPEN_ENDS = {"less": "high", "lower": "high", "more": "low", "higher": "low", "greater": "low"}
# A bare number followed by one of these is a temperature, a concentration, a time or a mass, never a second pH.
UNITS = frozenset({"degrees", "°c", "%", "mm", "m", "um", "µm", "nm", "mg", "min", "minutes", "h", "hours", "s", "seconds", "kda"})
# A free-text comment that names one of these reports a protein other than the accession's sequence.
MUTANT_WORDS = re.compile(
    r"\b(?:mutants?|mutations?|mutated|variants?|chimer\w*|truncat\w*|fusion|engineered|site-directed|"
    r"substitutions?|deletions?|insertions?)\b", re.IGNORECASE)
MUTATION_TOKEN = re.compile(r"\b[A-Z][0-9]{1,4}[A-Z]\b")
TEXT_REASONS = (
    "no_evidence_tag", "no_experimental_evidence", "molecule_scoped_statement", "no_optimum_stated", "unparseable_optimum",
    "qualitative_optimum", "interval_optimum", "several_ph_values", "ph_outside_scale", "mutant_or_variant",
)


@dataclass(frozen=True, slots=True)
class Statement:
    """What one optimum sentence states: a point, an interval (a range or a one-sided bound), or neither.

    `low` and `high` are equal for a point and hold the stated bounds of an interval (an open end is None). `extras` counts the
    other pH-like numbers that stand after the statement in its sentence.
    """

    kind: str
    low: float | None
    high: float | None
    extras: int


def _strip(word: str) -> str:
    return word.rstrip(TRAILING)


def _number(word: str) -> float | None:
    matched = NUMBER.fullmatch(_strip(word))
    return float(matched.group()) if matched else None


def _pair(word: str) -> tuple[float, float] | None:
    matched = PAIR.fullmatch(_strip(word))
    return (float(matched.group(1)), float(matched.group(2))) if matched else None


def _following_ph(words: list[str], index: int) -> int:
    """`index` moved past one bare ``pH`` word, so "from pH 4 to pH 8" reads like "from 4 to 8"."""
    return index + 1 if index < len(words) and words[index].lower() == "ph" else index


def _expression(rest: list[str]) -> tuple[str, float | None, float | None, int]:
    """Read the value that follows "optimum pH is": ``(kind, low, high, words used)``, the kind one of the `Statement` kinds."""
    index = 1 if rest and rest[0].lower() in HEDGES else 0
    index = _following_ph(rest, index)
    if index >= len(rest):
        return "unparseable", None, None, len(rest)
    word, lowered = rest[index], _strip(rest[index]).lower()
    if lowered in ("between", "from"):
        start = _following_ph(rest, index + 1)
        if start >= len(rest):
            return "unparseable", None, None, len(rest)
        joined = _pair(rest[start])
        if joined is not None:
            return "interval", joined[0], joined[1], start + 1
        low = _number(rest[start])
        end = _following_ph(rest, start + 2)
        if low is not None and start + 1 < len(rest) and rest[start + 1].lower() in ("and", "to") and end < len(rest):
            high = _number(rest[end])
            if high is not None:
                return "interval", low, high, end + 1
        return "unparseable", None, None, len(rest)
    if lowered in BOUNDS or word[:1] in ("<", ">"):
        named = lowered in BOUNDS
        bound = _number(rest[index + 1] if named and index + 1 < len(rest) else word.lstrip("<>="))
        if bound is None:
            return "unparseable", None, None, len(rest)
        below = lowered in ("below", "under") or word.startswith("<")
        return "interval", None if below else bound, bound if below else None, index + (2 if named else 1)
    value = _number(word)
    if value is not None:
        following = [item.lower() for item in rest[index + 1:index + 3]]
        if len(following) == 2 and following[0] in ("to", "-", "–"):
            end = _following_ph(rest, index + 2)
            high = _number(rest[end]) if end < len(rest) else None
            if high is not None:
                return "interval", value, high, end + 1
        if len(following) == 2 and following[0] == "or" and following[1].rstrip(TRAILING) in OPEN_ENDS:
            low_end = OPEN_ENDS[following[1].rstrip(TRAILING)] == "high"
            return "interval", None if low_end else value, value if low_end else None, index + 3
        return "point", value, value, index + 1
    joined = _pair(word)
    if joined is not None:
        return "interval", joined[0], joined[1], index + 1
    if not any(character.isdigit() for item in rest for character in item):
        return "qualitative", None, None, len(rest)
    return "unparseable", None, None, len(rest)


def _extra_numbers(words: list[str]) -> int:
    """How many words are a bare pH-like number (0 to 14) that no unit follows."""
    count = 0
    for index, word in enumerate(words):
        value = _number(word)
        following = _strip(words[index + 1]).lower() if index + 1 < len(words) else ""
        if value is not None and SCALE[0] <= value <= SCALE[1] and following not in UNITS:
            count += 1
    return count


def optimum_statement(sentence: str) -> Statement | None:
    """What `sentence` states as the optimum pH, or None when it is not an optimum sentence (no word pair "optimum pH")."""
    words = sentence.split()
    lowered = [word.lower() for word in words]
    found = [index for index in range(len(words) - 1) if lowered[index] == "optimum" and lowered[index + 1] == "ph"]
    if not found:
        return None
    rest = words[found[0] + 2:]
    if rest and rest[0].lower() in ("for", "to", "of"):
        verbs = [index for index, word in enumerate(rest) if word.lower() == "is"]
        rest = rest[verbs[0] + 1:] if verbs else []
    elif rest and rest[0].lower() in ("is", "="):
        rest = rest[1:]
    kind, low, high, used = _expression(rest)
    return Statement(kind, low, high, _extra_numbers(rest[used:]))


def judge_text(text: str, codes: Collection[str], *, scoped: bool = False) -> tuple[str | None, float | None, list[str]]:
    """The first reason of `TEXT_REASONS` that keeps `text` from being one point optimum, and its optimum when none does.

    `codes` are the ECO codes of the text's own evidence keys, and `scoped` says its comment names a molecule. Returns
    ``(reason, value, optimum sentences)``: the reason is None for a kept text, whose pH is `value`.
    """
    if not codes:
        return "no_evidence_tag", None, []
    if EXPERIMENTAL not in codes:
        return "no_experimental_evidence", None, []
    words = [word.strip("()[],;:.").lower() for word in text.split()]
    if scoped or any(word.startswith("isoform") for word in words):
        return "molecule_scoped_statement", None, []
    read = [(sentence, optimum_statement(sentence)) for sentence in sentences_of(text)]
    sentences = [sentence for sentence, statement in read if statement is not None]
    stated = [statement for _, statement in read if statement is not None]
    if not stated:
        return "no_optimum_stated", None, []
    numeric = [statement for statement in stated if statement.kind in ("point", "interval")]
    if any(statement.kind == "unparseable" for statement in stated):
        reason = "unparseable_optimum"
    elif not numeric:
        reason = "qualitative_optimum"
    elif any(statement.kind == "interval" for statement in numeric):
        reason = "interval_optimum"
    elif len({statement.low for statement in numeric}) > 1 or any(statement.extras for statement in numeric):
        reason = "several_ph_values"
    elif not SCALE[0] <= numeric[0].low <= SCALE[1]:
        reason = "ph_outside_scale"
    elif MUTANT_WORDS.search(text) or MUTATION_TOKEN.search(text):
        reason = "mutant_or_variant"
    else:
        return None, numeric[0].low, sentences
    return reason, None, sentences
