"""Read the first twelve rows of each distinct Excel file, including temp copies."""

import csv
import re
import sys
from contextlib import closing
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from openpyxl import load_workbook

from inventory import write_csv


def profile_headers(archive, inventory, output):
    with inventory.open(encoding="utf-8") as source:
        files = list(csv.DictReader(source))
    seen = set()
    results = []
    with ZipFile(archive) as source:
        for entry in files:
            if entry["kind"] not in {"excel", "excel_temp"} or entry["sha256"] in seen:
                continue
            seen.add(entry["sha256"])
            with closing(
                load_workbook(
                    BytesIO(source.read(entry["member"])),
                    read_only=True,
                    data_only=True,
                )
            ) as book:
                for sheet in book.worksheets:
                    cells = [
                        [
                            str(v).strip()
                            for v in row
                            if v is not None and str(v).strip()
                        ]
                        for row in sheet.iter_rows(
                            max_row=12, max_col=20, values_only=True
                        )
                    ]
                    labels = [label for row in cells for label in row]
                    ac = next((v for v in labels if "SEGMENT" in v.upper()), "")
                    number = re.search(r"\d+", ac)
                    name = next(
                        (v for v in labels if "CONSTITUENCY NAME" in v.upper()), ""
                    )
                    total = next(
                        (v for v in labels if v.upper().startswith("TOTAL OF ")), ""
                    )
                    results.append(
                        (
                            entry["member"],
                            entry["sha256"],
                            entry["filename_segment"],
                            sheet.title,
                            ac,
                            number[0] if number else "",
                            name,
                            total,
                        )
                    )
    write_csv(
        output,
        (
            "member",
            "sha256",
            "filename_segment",
            "sheet_name",
            "segment_label",
            "header_segment",
            "constituency_label",
            "total_label",
        ),
        results,
    )


if __name__ == "__main__":
    profile_headers(*(Path(arg) for arg in sys.argv[1:]))
