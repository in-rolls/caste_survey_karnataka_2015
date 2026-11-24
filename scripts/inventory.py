"""Index archive members and extract the constituency roster from the Word covers."""

import csv
import hashlib
import re
import sys
from collections import Counter
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile, is_zipfile


def file_kind(name, data):
    path = Path(name)
    if name.endswith("/"):
        return "directory"
    if path.name.startswith("~$"):
        return "office_lock"
    if path.suffix in {".xlsx", ".tmp", ".docx"} and is_zipfile(BytesIO(data)):
        with ZipFile(BytesIO(data)) as office:
            if "xl/workbook.xml" in office.namelist():
                return "excel" if path.suffix == ".xlsx" else "excel_temp"
            if "word/document.xml" in office.namelist():
                return "district_cover"
    if path.suffix == ".xls" and data.startswith(b"DISTRICT:") and b"\t" in data:
        return "tab_delimited"
    if path.name == "formula.txt":
        return "formula_note"
    if path.name == ".DS_Store":
        return "finder_metadata"
    return "unclassified"


def cover_rows(data):
    with ZipFile(BytesIO(data)) as document:
        root = ElementTree.fromstring(document.read("word/document.xml"))
    for table in root.findall(".//{*}tbl"):
        for row in table.findall("{*}tr")[1:]:
            cells = [
                "".join(t.text or "" for t in cell.findall(".//{*}t")).strip()
                for cell in row.findall("{*}tc")
            ]
            serial, segment, name = cells
            yield int(serial), int(segment), name


def write_csv(path, columns, rows):
    with path.open("w", newline="", encoding="utf-8") as out:
        writer = csv.writer(out, lineterminator="\n")
        writer.writerow(columns)
        writer.writerows(rows)


def inventory(archive, output):
    output.mkdir(parents=True, exist_ok=True)
    members, covers, seen = [], [], set()
    segments = set()
    with ZipFile(archive) as source:
        for entry in sorted(source.infolist(), key=lambda x: x.filename):
            data = source.read(entry)
            name = entry.filename
            kind = file_kind(name, data)
            digest = hashlib.sha256(data).hexdigest()
            match = re.match(r"(\d+)", Path(name).name)
            segment = (
                int(match[1]) if match and kind in {"excel", "tab_delimited"} else None
            )
            members.append((name, kind, len(data), digest, segment))
            if kind == "excel" and segment is not None:
                segments.add(segment)
            if kind == "district_cover" and digest not in seen:
                covers.extend(
                    (ac, label, name, row) for row, ac, label in cover_rows(data)
                )
            seen.add(digest)
    roster = Counter(row[0] for row in covers)
    if roster != Counter(range(1, 225)) or set(roster) != segments:
        raise ValueError(
            f"Compare the cover roster and filename IDs: {roster}, {segments}"
        )
    write_csv(
        output / "members.csv",
        ("member", "kind", "bytes", "sha256", "filename_segment"),
        members,
    )
    write_csv(
        output / "constituencies.csv",
        ("segment", "cover_name", "cover_member", "cover_serial"),
        sorted(covers),
    )
    with archive.open("rb") as handle:
        print("Archive SHA-256", hashlib.file_digest(handle, "sha256").hexdigest())
    print("Kind, entries, distinct contents")
    for kind in sorted({r[1] for r in members}):
        hashes = [r[3] for r in members if r[1] == kind]
        print(kind, len(hashes), len(set(hashes)))
    print(len(roster), "distinct roster IDs match the Excel filenames")


if __name__ == "__main__":
    inventory(Path(sys.argv[1]), Path(sys.argv[2]))
