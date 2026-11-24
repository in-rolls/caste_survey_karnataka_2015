"""Check the released rows against freshly read source cells and geography headings."""

import argparse
import csv
from concurrent.futures import ProcessPoolExecutor
from io import BytesIO, StringIO
from pathlib import Path
from zipfile import ZipFile

import pyarrow.parquet as pq
from openpyxl import load_workbook

MEASURES = ("households", "male", "female", "third_gender", "population")


def numeric(value):
    if value is None or not str(value).strip():
        return None
    return int(value)


def check_printed(record, values):
    counts = tuple(
        None if v is None or not str(v).strip() else float(v) for v in values[2:7]
    )
    if counts != tuple(record["printed_" + c] for c in MEASURES):
        raise ValueError(
            f"Printed control mismatch in {record['segment']} at {record['total_row']}"
        )


def check_segment(job):
    archive, path, index, source, control, control_member = job
    segment = control["segment"]
    localities = (
        pq.ParquetFile(path.with_name("localities.parquet"))
        .read_row_group(index)
        .to_pylist()
    )
    headings = {r["heading_row"]: r for r in localities if r["heading_row"] is not None}
    totals = {r["total_row"]: r for r in localities if r["total_row"] is not None}
    rows = pq.ParquetFile(path).read_row_group(index).to_pylist()
    if {r["segment"] for r in rows} != {segment} or {r["sha256"] for r in rows} != {
        source["sha256"]
    }:
        raise ValueError(f"Unexpected source in row group {index}")
    expected = {r["source_row"]: r for r in rows}
    if len(expected) != len(rows):
        raise ValueError(f"Duplicate source coordinate in {source['member']}")
    with ZipFile(archive) as z:
        data = z.read(source["member"])
        if source["sha256"] != control["sha256"]:
            control_book = load_workbook(
                BytesIO(z.read(control_member)), read_only=True, data_only=True
            )
            try:
                n = control["total_row"]
                values = next(
                    control_book[control["sheet"]].iter_rows(
                        min_row=n, max_row=n, max_col=7, values_only=True
                    )
                )
                check_printed(control, values)
            finally:
                control_book.close()
    book = None
    if source["kind"] == "tab_delimited":
        reader = csv.reader(StringIO(data.decode("utf-8")), delimiter="\t")
    else:
        book = load_workbook(BytesIO(data), read_only=True, data_only=True)
        sheet = book[rows[0]["sheet"]]
        sheet.reset_dimensions()
        reader = sheet.iter_rows(max_col=7, values_only=True)
    seen = set()
    block = 0
    section, place = None, None
    new_heading = False
    try:
        for number, values in enumerate(reader, 1):
            v = (list(values[:7]) + [None] * 7)[:7]
            a, b = ("" if s is None else str(s) for s in v[:2])
            if source["sha256"] == control["sha256"] and number == control["total_row"]:
                check_printed(control, v)
            if not a.strip() and not b.strip():
                continue
            fields = [str(s).strip() for s in v if s is not None]
            heading = next(
                (s for s in fields if s.startswith(("VILLAGE:", "WARD:"))), None
            )
            if heading:
                place = heading.split(":", 1)[1].strip()
                block += 1
                h = headings.pop(number)
                if (h["block"], h["locality_name"]) != (block, place):
                    raise ValueError(f"Heading mismatch: {segment} row {number}")
                section, new_heading = None, True
            if a.strip().upper() == "TOTAL":
                if not new_heading:
                    section, place = None, None
                    block += 1
                ctrl = totals.pop(number)
                if (ctrl["block"], ctrl["locality_name"]) != (block, place):
                    raise ValueError(
                        f"Total assigned to wrong block: {segment} row {number}"
                    )
                check_printed(ctrl, v)
                new_heading = False
            if a.strip().upper() in {
                "SCHEDULED CASTES",
                "SCHEDULED TRIBES",
                "MINORITIES **",
            }:
                section = a
            # Detect candidate rows independently of the parser’s caste-code pattern.
            if (
                not b.strip()
                or not any(str(s).strip().isdigit() for s in v[2:] if s is not None)
                or heading
            ):
                continue
            r = expected.get(number)
            actual = (block, a, b, section, place, *(numeric(s) for s in v[2:]))
            if r is None or actual != tuple(
                r[k]
                for k in (
                    "block",
                    "caste_code",
                    "caste_name",
                    "section",
                    "locality_name",
                    *MEASURES,
                )
            ):
                raise ValueError(
                    f"{source['member']} row {number}: {actual!r} vs {r!r}"
                )
            seen.add(number)
    finally:
        if book:
            book.close()
    if headings or totals or block != len(localities):
        raise ValueError(f"Unmatched locality controls or headings in {segment}")
    if set(expected) != seen:
        raise ValueError(
            f"{segment}: unmatched output rows {sorted(set(expected)-seen)[:10]}"
        )
    return len(seen)


def verify(archive, output, workers):
    with open("inventory/members.csv", encoding="utf-8") as f:
        members = {r["sha256"]: r for r in csv.DictReader(f)}
    controls = pq.read_table(output / "constituencies.parquet").to_pylist()
    if sorted(r["segment"] for r in controls) != list(range(1, 225)):
        raise ValueError("Incomplete constituency roster")
    detail = output / "detail.parquet"
    if pq.ParquetFile(detail).num_row_groups != len(controls):
        raise ValueError("Expected one row group per segment")
    jobs = [
        (
            archive,
            detail,
            i,
            members[r["detail_source_sha256"]],
            r,
            members[r["sha256"]]["member"],
        )
        for i, r in enumerate(controls)
    ]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        counts = list(pool.map(check_segment, jobs))
    if counts != [r["detail_rows"] for r in controls]:
        raise ValueError("Constituency detail counts differ")
    print(f"Matched {sum(counts):,} detail rows in {len(counts)} constituencies.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    verify(args.archive, args.output, args.workers)
