"""The Meltome Atlas workbook's melting points, read row by row with each row's first structural reason for exclusion.

The source is the workbook `SD_Fig.2.xlsx` of Jarzab et al., Nature Methods 2020 (figshare 11829780 v1, file 21653313, CC BY
4.0): sheet `Fig. 2a` lists, for 13 organisms, each protein the thermal proteome profiling of lysates quantified, the organism's
optimal growth temperature, and the protein's melting point in degrees Celsius averaged across replicates, or none when no curve
could be fitted. `thermal_tm_experimental_v1`'s reader (`production_suite.meltome_tm`) and the annotation compendium's melting
temperature view read it through this module (promoted 2026-10-21).

- `read_workbook(path)`: each sheet of an .xlsx as `(title, header, rows)`, read from its zip and XML parts with the standard
  library, empty cells kept as None so that columns stay aligned.
- `read_rows(workbook, *, workbook_sha256)`: every data row of `Fig. 2a` in order, refusing a changed file or layout, each with
  its first structural reason: `no_melting_point` (the row states none, so the protein is unknown and never a stable one), then
  `not_a_uniprot_accession` (the protein id's head is neither a UniProtKB accession nor an isoform of one; the sheet holds one
  reversed-database decoy, `REV__E7F5E1_`).

What a reader does with a row past those two (the release its sequence comes from, the organism check, a length limit) is its own.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
import zipfile

from dataclasses import dataclass
from pathlib import Path

from foundry.digests import sha256_file
from .uniprot_xml import ACCESSION, ISOFORM


__all__ = [
    "CITATION", "MELTING_POINTS_SHEET", "MELTING_POINT_HEADER", "SPECIES", "WORKBOOK_FILE", "MeltomeRow", "Sheet", "column_index",
    "identifier_of", "read_rows", "read_workbook",
]

SHEET = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
RELATIONSHIP = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
WORKBOOK_FILE = "SD_Fig.2.xlsx"
CITATION = "doi:10.1038/s41592-020-0801-4"
MELTING_POINTS_SHEET = "Fig. 2a"
MELTING_POINT_HEADER = ("Species", "Protein ID", "Optimal growth temperature [°C]", "Melting point [°C] (averaged across replicates)")
# The species of the sheet and the binomial name UniProtKB gives their proteins.
SPECIES = {
    "A.thaliana": "Arabidopsis thaliana", "B.subtilis": "Bacillus subtilis", "C.elegans": "Caenorhabditis elegans",
    "D.melanogaster": "Drosophila melanogaster", "D.rerio": "Danio rerio", "E.coli": "Escherichia coli",
    "G.stearothermophilus": "Geobacillus stearothermophilus", "H.sapiens": "Homo sapiens", "M.musculus": "Mus musculus",
    "O.antarctica": "Oleispira antarctica", "P.torridus": "Picrophilus torridus", "S.cerevisiae": "Saccharomyces cerevisiae",
    "T.thermophilus": "Thermus thermophilus",
}

# One worksheet: its title, its header row, and its data rows, with an empty cell as None.
Sheet = tuple[str, tuple[str | None, ...], list[tuple[str | None, ...]]]


@dataclass(frozen=True, slots=True)
class MeltomeRow:
    """One data row of `Fig. 2a`: its spreadsheet row, species, protein id, growth temperature, melting point (the cell's text and
    its number, None when empty), the UniProtKB identifier the protein id starts with, and its first structural reason, if any."""

    number: int
    species: str
    protein_id: str
    growth_temperature: float
    tm_text: str | None
    tm: float | None
    identifier: str | None
    reason: str | None

    @property
    def locator(self) -> str:
        return f"{MELTING_POINTS_SHEET}/R{self.number}"


def column_index(reference: str) -> int:
    """Zero-based column of a cell reference such as ``AB12``."""
    number = 0
    for character in reference:
        if not character.isalpha():
            break
        number = number * 26 + ord(character.upper()) - ord("A") + 1
    return number - 1


def read_workbook(path: Path) -> dict[str, Sheet]:
    """Each sheet as ``name: (title, header, rows)``, with empty cells kept as None so columns stay aligned.

    A sheet whose first row is not a single title cell, or whose second row is not the header, is refused.
    """
    with zipfile.ZipFile(path) as archive:
        strings: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            for item in ET.fromstring(archive.read("xl/sharedStrings.xml")).findall(SHEET + "si"):
                strings.append("".join(node.text or "" for node in item.iter(SHEET + "t")))
        relations = {rel.get("Id"): rel.get("Target") for rel in ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))}
        sheets: dict[str, Sheet] = {}
        for sheet in ET.fromstring(archive.read("xl/workbook.xml")).find(SHEET + "sheets"):
            target = relations[sheet.get(RELATIONSHIP + "id")]
            member = target.lstrip("/") if target.startswith("/") else "xl/" + target
            rows: list[tuple[str | None, ...]] = []
            with archive.open(member) as handle:
                for _, element in ET.iterparse(handle, events=("end",)):
                    if element.tag != SHEET + "row":
                        continue
                    cells: dict[int, str | None] = {}
                    for cell in element.findall(SHEET + "c"):
                        value = cell.find(SHEET + "v")
                        if cell.get("t") == "s" and value is not None:
                            text = strings[int(value.text)]
                        elif cell.get("t") == "inlineStr":
                            text = "".join(node.text or "" for node in cell.iter(SHEET + "t"))
                        else:
                            text = value.text if value is not None else None
                        cells[column_index(cell.get("r"))] = text
                    rows.append(tuple(cells.get(index) for index in range(max(cells, default=-1) + 1)))
                    element.clear()
            if len(rows) < 2 or len(rows[0]) != 1 or rows[0][0] is None:
                raise ValueError(f"sheet {sheet.get('name')!r} does not start with a single title cell")
            sheets[sheet.get("name")] = (rows[0][0].strip(), rows[1], rows[2:])
    return sheets


def _number(text: str, what: str, number: int) -> float:
    try:
        value = float(text)
    except ValueError as error:
        raise ValueError(f"{MELTING_POINTS_SHEET} row {number}: {what} {text!r} is not a number") from error
    if not math.isfinite(value):
        raise ValueError(f"{MELTING_POINTS_SHEET} row {number}: {what} {text!r} is not finite")
    return value


def identifier_of(protein_id: str) -> str | None:
    """The UniProtKB accession or isoform identifier a ``<accession>_<gene or locus tag>`` protein id starts with, or None."""
    head = protein_id.split("_", 1)[0]
    return head if ACCESSION.fullmatch(head) or ISOFORM.fullmatch(head) else None


def read_rows(workbook: Path, *, workbook_sha256: str) -> list[MeltomeRow]:
    """Every data row of sheet `Fig. 2a`, in order, with its first structural reason for exclusion."""
    if sha256_file(workbook) != workbook_sha256:
        raise ValueError(f"pinned workbook changed: {workbook}")
    sheets = read_workbook(workbook)
    _, header, sheet_rows = sheets[MELTING_POINTS_SHEET]
    if header != MELTING_POINT_HEADER:
        raise ValueError("the melting point sheet's header differs from the pinned layout")
    rows: list[MeltomeRow] = []
    for number, cells in enumerate(sheet_rows, start=3):
        if len(cells) > len(header):
            raise ValueError(f"{MELTING_POINTS_SHEET} row {number} has more cells than its header")
        species, protein_id, growth, text = cells + (None,) * (len(header) - len(cells))
        if species not in SPECIES or not protein_id or growth is None:
            raise ValueError(f"{MELTING_POINTS_SHEET} row {number} is not a known species, a protein id, a growth temperature and a melting point")
        text = text if text else None
        identifier = identifier_of(protein_id)
        reason = "no_melting_point" if text is None else "not_a_uniprot_accession" if identifier is None else None
        rows.append(MeltomeRow(number, species, protein_id, _number(growth, "growth temperature", number), text,
                               None if text is None else _number(text, "melting point", number), identifier, reason))
    return rows
