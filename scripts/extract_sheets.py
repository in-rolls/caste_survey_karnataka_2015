"""Cache nonblank source rows once per distinct workbook or tab export."""

import csv
import gzip
import hashlib
import json
import sys
from io import BytesIO, StringIO
from pathlib import Path
from zipfile import ZipFile

from python_calamine import CalamineWorkbook


def cell(value):
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value) if value is not None else ""


def sheets(data, kind):
    if kind == "tab_delimited":
        yield "TSV", enumerate(
            csv.reader(StringIO(data.decode("utf-8")), delimiter="\t"), 1
        )
        return
    with CalamineWorkbook.from_filelike(BytesIO(data)) as book:
        for name in book.sheet_names:
            sheet = book.get_sheet_by_name(name)
            if sheet.start is None:
                yield name, ()
                continue
            first_row, first_col = sheet.start
            yield name, enumerate(
                ([""] * first_col + row for row in sheet.to_python()), first_row + 1
            )


def extract(archive, output):
    with archive.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    if digest != "434772cefd7d0c7fcc2564b781fc4d99e22fc16ada729cd849ddfe48e966f009":
        raise ValueError(f"Unrecognized source archive: {digest}")
    output.mkdir(parents=True, exist_ok=True)
    with open("inventory/members.csv", encoding="utf-8") as handle:
        members = list(csv.DictReader(handle))
    with ZipFile(archive) as source:
        for item in members:
            kind = item["kind"]
            if kind not in {"excel", "excel_temp", "tab_delimited"}:
                continue
            digest = item["sha256"]
            result = output / f"{digest}.jsonl.gz"
            if result.exists():
                continue
            data = source.read(item["member"])
            if hashlib.sha256(data).hexdigest() != digest:
                raise ValueError(item["member"])
            temp = result.with_suffix(".partial")
            with gzip.open(temp, "wt", encoding="utf-8", compresslevel=1) as handle:
                for name, rows in sheets(data, kind):
                    handle.write(json.dumps(name) + "\n")
                    for number, row in rows:
                        values = [cell(v) for v in row]
                        while values and not values[-1].strip():
                            values.pop()
                        if values:
                            handle.write(
                                json.dumps([number, values], ensure_ascii=False) + "\n"
                            )
            temp.replace(result)


if __name__ == "__main__":
    extract(Path(sys.argv[1]), Path(sys.argv[2]))
