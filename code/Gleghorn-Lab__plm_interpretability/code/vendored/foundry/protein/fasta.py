"""One streaming FASTA reader, gzip-transparent, for every project that reads sequences.

Fourteen readers in this tree each parsed the same format their own way, and each returned a
different shape: a dict, two parallel lists, tuples, or their own record class. Some raised on a
malformed file and some returned it half-read. This is the one reader, and it is strict, because a
FASTA file that a pipeline misreads silently produces sequences that are wrong rather than absent:

- residue lines before the first header raise, rather than being dropped;
- an empty identifier raises;
- a header with no residues raises, rather than yielding an empty sequence;
- a file with no records raises, rather than yielding nothing.

A record's identifier is the first whitespace-delimited token of its header, which is what every
copy here used and what Biopython's `record.id` gives, so switching a caller does not change which
sequences it reads. `description` keeps the rest of the header for a caller that wants it.

Residue case is preserved. Lowercase means a masked or low-complexity residue in some sources, so
upper-casing is the caller's decision, through `uppercase=True`.

A path ending in `.gz` opens through gzip, by `foundry.compression`.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass

from foundry.compression import PathLike, open_text_maybe_gzip


@dataclass(frozen=True, slots=True)
class FastaRecord:
    """One FASTA record: its identifier, its residues, and the rest of its header."""

    id: str
    sequence: str
    description: str = ""


def iter_fasta(path: PathLike, *, uppercase: bool = False) -> Iterator[FastaRecord]:
    """Yield each record of a file in order, without reading the file into memory.

    Duplicate identifiers are yielded as they appear: whether a repeat is an error is the caller's
    question, and `fasta_sequences` answers it one way.
    """

    with open_text_maybe_gzip(path, "rt", encoding="utf-8") as handle:
        yield from _parse(handle, str(path), uppercase)


def iter_fasta_text(text: str, *, uppercase: bool = False, source: str = "FASTA text") -> Iterator[FastaRecord]:
    """Yield each record of FASTA text already in memory, such as an API response body.

    `source` names the text in any error, since there is no path to name.
    """

    yield from _parse(text.splitlines(), source, uppercase)


def read_fasta(path: PathLike, *, uppercase: bool = False) -> list[FastaRecord]:
    """Every record of a file in order, identifiers, order, and duplicates preserved."""

    return list(iter_fasta(path, uppercase=uppercase))


def read_fasta_text(
    text: str, *, uppercase: bool = False, source: str = "FASTA text"
) -> list[FastaRecord]:
    """Every record of FASTA text in order."""

    return list(iter_fasta_text(text, uppercase=uppercase, source=source))


def _parse(lines: Iterable[str], source: str, uppercase: bool) -> Iterator[FastaRecord]:
    """The one parse, over any source of lines."""

    identifier: str | None = None
    description = ""
    residues: list[str] = []
    found = False
    for number, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line:
            continue
        if line.startswith(">"):
            if identifier is not None:
                found = True
                yield _record(identifier, description, residues, source, uppercase)
            header = line[1:].strip()
            parts = header.split(maxsplit=1)
            if not parts:
                raise ValueError(f"{source}, line {number}: a FASTA header has no identifier.")
            identifier, description = parts[0], parts[1] if len(parts) > 1 else ""
            residues = []
        else:
            if identifier is None:
                raise ValueError(
                    f"{source}, line {number}: residues appear before the first FASTA header."
                )
            residues.append("".join(line.split()))
    if identifier is not None:
        found = True
        yield _record(identifier, description, residues, source, uppercase)
    if not found:
        raise ValueError(f"{source} holds no FASTA records.")


def fasta_sequences(
    path: PathLike, *, uppercase: bool = False, unique: bool = True
) -> dict[str, str]:
    """Identifier to sequence, in file order.

    `unique=True` raises on a repeated identifier, because a dict would silently drop one of two
    different sequences. `unique=False` keeps the last, which is what a dict comprehension does.
    """

    sequences: dict[str, str] = {}
    for record in iter_fasta(path, uppercase=uppercase):
        if unique and record.id in sequences:
            raise ValueError(f"{path} holds more than one record for {record.id!r}.")
        sequences[record.id] = record.sequence
    return sequences


def write_fasta(
    path: PathLike, records: Mapping[str, str] | list[FastaRecord], *, line_width: int = 60
) -> int:
    """Write records and return how many. A mapping is written in its own order.

    `line_width` wraps residues, as most tools emit; 0 writes each sequence on one line. Lines end in a line
    feed on every platform, because a Linux tool reads a Windows carriage return as part of an identifier.
    """

    items = (
        [FastaRecord(name, sequence) for name, sequence in records.items()]
        if isinstance(records, Mapping)
        else list(records)
    )
    if not items:
        raise ValueError("write_fasta needs at least one record.")
    with open_text_maybe_gzip(path, "wt", encoding="utf-8", newline="\n") as handle:
        for record in items:
            header = f">{record.id}" + (f" {record.description}" if record.description else "")
            handle.write(f"{header}\n")
            sequence = record.sequence
            if line_width <= 0:
                handle.write(f"{sequence}\n")
                continue
            for start in range(0, len(sequence), line_width):
                handle.write(f"{sequence[start : start + line_width]}\n")
    return len(items)


def _record(
    identifier: str, description: str, residues: list[str], source: str, uppercase: bool
) -> FastaRecord:
    sequence = "".join(residues)
    if not sequence:
        raise ValueError(f"{source}: FASTA record {identifier!r} has a header but no residues.")
    return FastaRecord(
        id=identifier,
        sequence=sequence.upper() if uppercase else sequence,
        description=description,
    )


__all__ = [
    "FastaRecord",
    "fasta_sequences",
    "iter_fasta",
    "iter_fasta_text",
    "read_fasta",
    "read_fasta_text",
    "write_fasta",
]
