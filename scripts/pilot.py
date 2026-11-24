"""Extract the first complete locality in each of two specified workbooks."""

import csv
import sys
from contextlib import closing
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from openpyxl import load_workbook

MEMBERS = (
    "Constituencies/Udupi/122-Karkala_constituency_new.xlsx",
    "Constituencies/Constituencies/Bangalore(U)/160-Sarvagnanagar.xlsx",
)
COUNTS = ("households", "male", "female", "third_gender", "population")
SECTIONS = {"Scheduled Castes", "Scheduled Tribes", "Minorities **"}


def first_locality(sheet):
    section = None
    detail = []
    printed = None
    locality = None
    for number, row in enumerate(sheet.iter_rows(max_col=7, values_only=True), 1):
        code, label = (str(v).strip() if v is not None else "" for v in row[:2])
        if code.startswith(("VILLAGE:", "WARD:")):
            if locality is not None:
                break
            locality = code
            continue
        if locality is None:
            continue
        if code == "TOTAL":
            if printed is not None:
                raise ValueError(f"Duplicate control in {locality} at row {number}")
            printed = row[2:]
        elif code in SECTIONS:
            section = code
        elif not any(v is not None and str(v).strip() for v in row):
            continue
        elif code and label and all(type(v) is int for v in row[2:]):
            if sum(row[3:6]) != row[6]:
                raise ValueError(f"Population mismatch at row {number}")
            detail.append((number, locality, section, code, label, *row[2:]))
        else:
            raise ValueError(f"Unknown row {number}: {row}")
    if not detail or printed is None:
        raise ValueError("Missing detail or printed total")
    totals = tuple(map(sum, zip(*(r[-5:] for r in detail))))
    print(locality, len(detail), "rows. Summed:", totals, "Printed:", printed)
    if totals != printed:
        raise ValueError(f"Detail disagrees with control for {locality}")
    return detail


def pilot(archive, output):
    rows = []
    with ZipFile(archive) as source:
        for member in MEMBERS:
            with closing(
                load_workbook(
                    BytesIO(source.read(member)), read_only=True, data_only=True
                )
            ) as book:
                sheet = book.worksheets[0]
                rows.extend((member, sheet.title, *r) for r in first_locality(sheet))
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(
            (
                "member",
                "sheet",
                "source_row",
                "locality_label",
                "section",
                "caste_code",
                "caste_name",
                *COUNTS,
            )
        )
        writer.writerows(rows)


if __name__ == "__main__":
    pilot(Path(sys.argv[1]), Path(sys.argv[2]))
