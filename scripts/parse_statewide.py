"""Read the survey abstracts, reconcile printed totals and compare alternate sources."""

import csv
import gzip
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from contextlib import ExitStack
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from inventory import write_csv

COUNTS = ("households", "male", "female", "third_gender", "population")
SECTIONS = {"SCHEDULED CASTES", "SCHEDULED TRIBES", "MINORITIES **"}
CODE = re.compile(r"(?:[A-Z]\d+|\d+|CASTES NOT IDENTIFIABLE)", re.I)
I, S, F = pa.int32(), pa.string(), pa.float64()
ORIGIN = [("segment", I), ("sha256", S), ("sheet", S)]
LOC = [
    ("block", I),
    ("district", S),
    ("tehsil", S),
    ("town", S),
    ("locality_type", S),
    ("locality_name", S),
]
MEASURES = [(name, I) for name in COUNTS]
CONTROL = [(f"printed_{name}", F) for name in COUNTS] + [
    (f"detail_{name}", I) for name in COUNTS
]
SCHEMAS = {
    "detail": ORIGIN
    + LOC
    + [("source_row", I), ("section", S), ("caste_code", S), ("caste_name", S)]
    + MEASURES,
    "localities": ORIGIN
    + LOC
    + [("heading_row", I), ("total_row", I), ("detail_rows", I), ("check", S)]
    + CONTROL,
    "constituencies": ORIGIN
    + [
        ("cover_name", S),
        ("internal_segment", I),
        ("constituency_label", S),
        ("total_label", S),
        ("total_row", I),
        ("detail_source_sha256", S),
        ("blocks", I),
        ("detail_rows", I),
        ("check", S),
    ]
    + CONTROL
    + [(f"locality_{name}", F) for name in COUNTS],
    "exceptions": ORIGIN
    + [("block", I), ("source_row", I), ("issue", S), ("evidence", S)],
    "auxiliary": ORIGIN + [("source_row", I), ("cells", pa.list_(S))],
}


def inventory(name):
    with Path("inventory", name + ".csv").open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def source_groups():
    headers = {
        r["sha256"]: r for r in inventory("workbook_headers") if r["header_segment"]
    }
    groups = defaultdict(list)
    seen = set()
    for r in inventory("members"):
        digest = r["sha256"]
        if r["kind"] not in {"excel", "excel_temp", "tab_delimited"} or digest in seen:
            continue
        seen.add(digest)
        h = headers.get(digest, {})
        ac = int(r["filename_segment"] or h["header_segment"])
        groups[ac].append(
            {**r, "sheet": h.get("sheet_name", "TSV"), "header": h, "segment": ac}
        )
    for ac, sources in groups.items():
        # The nested copies preserve four additional named blocks across these seats.
        sources.sort(
            key=lambda r: (
                r["kind"] != "excel",
                (("/New folder/" in r["member"]) != (ac in {140, 143})),
                r["member"],
            )
        )
        if sources[0]["kind"] != "excel":
            raise ValueError("Missing primary workbook")
    return groups


def strict_sum(values):
    return sum(values) if values and None not in values else None


def check(printed, sums):
    if any(p != s for p, s in zip(printed, sums) if p is not None and s is not None):
        return "difference"
    if None in printed or None in sums:
        return "incomplete"
    return "match"


def control_fields(printed, sums):
    return {
        **dict(zip(("printed_" + c for c in COUNTS), printed)),
        **dict(zip(("detail_" + c for c in COUNTS), sums)),
    }


def parse_file(cache, source):
    src = {k: source[k] for k in ("segment", "sha256", "sheet")}
    detail, blocks, issues, aux = [], [], [], []
    kinds = Counter()
    district = tehsil = town = section = current = ac_row = ac_label = None
    ac_counts = [None] * 5
    tab = source["kind"] == "tab_delimited"

    def issue(row, reason, evidence):
        issues.append(
            {
                **src,
                "block": current["block"] if current else None,
                "source_row": row,
                "issue": reason,
                "evidence": evidence,
            }
        )

    def new_block(row, kind=None, name=None):
        block = {
            **src,
            "block": len(blocks) + 1,
            "district": district,
            "tehsil": tehsil,
            "town": town,
            "locality_type": kind,
            "locality_name": name,
            "heading_row": row,
            "total_row": None,
            "printed": [None] * 5,
            "rows": [],
        }
        blocks.append(block)
        return block

    with gzip.open(
        cache / (source["sha256"] + ".jsonl.gz"), "rt", encoding="utf-8"
    ) as handle:
        for line in handle:
            item = json.loads(line)
            if isinstance(item, str):
                sheet = item
                continue
            row, cells = item
            if sheet != src["sheet"]:
                aux.append({**src, "sheet": sheet, "source_row": row, "cells": cells})
                continue
            first = (cells + [""] * 7)[:7]
            code, label, *numeric = [c.strip() for c in first]
            upper = code.upper()
            if upper.startswith(("DISTRICT:", "TEHSIL:", "TOWN:", "VILLAGE:", "WARD:")):
                tags = {
                    k.strip().upper(): v.strip()
                    for cell in first
                    if ":" in cell
                    for k, v in [cell.split(":", 1)]
                }
                if "DISTRICT" in tags:
                    district = tags["DISTRICT"]
                    tehsil = tags.get("TEHSIL")
                    town = tags.get("TOWN")
                if "TEHSIL" in tags:
                    tehsil = tags["TEHSIL"]
                if "TOWN" in tags:
                    town = tags["TOWN"]
                for kind in ("VILLAGE", "WARD"):
                    if kind in tags:
                        if kind == "VILLAGE":
                            town = None
                        current = new_block(row, kind.lower(), tags[kind])
                        section = None
                kinds["geography"] += 1
            elif upper.startswith("TOTAL OF ") or (
                not tab and row == 5 and not code and not label and all(numeric)
            ):
                if ac_row is not None:
                    raise ValueError(f"Repeated constituency control {src} {row}")
                ac_row, ac_label = row, code or None
                ac_counts = [float(v) if v else None for v in numeric]
                kinds["constituency_control"] += 1
            elif upper == "TOTAL":
                if (
                    current is None
                    or current["total_row"] is not None
                    or current["rows"]
                ):
                    current = new_block(None)
                    section = None
                    issue(
                        row,
                        "missing_locality_heading",
                        "Control starts an unlabeled block",
                    )
                current["total_row"] = row
                current["printed"] = [float(v) if v else None for v in numeric]
                kinds["locality_control"] += 1
            elif upper in SECTIONS:
                section = first[0]
                kinds["section"] += 1
            elif upper.startswith(
                ("CONSTITUENCY", "SOCIAL AND EDUCATIONAL", "CASTE CODE")
            ):
                kinds["report_heading"] += 1
            elif (
                CODE.fullmatch(code)
                and label
                and all(not v or v.isdecimal() for v in numeric)
            ):
                if current is None:
                    current = new_block(None)
                    issue(
                        row,
                        "missing_locality_heading",
                        "Detail starts an unlabeled block",
                    )
                counts = [int(v) if v else None for v in numeric]
                record = {
                    "source_row": row,
                    "section": section,
                    "caste_code": first[0],
                    "caste_name": first[1],
                    **dict(zip(COUNTS, counts)),
                }
                current["rows"].append(record)
                detail.append(record)
                if None in counts:
                    issue(row, "missing_count", str(numeric))
                elif sum(counts[1:4]) != counts[4]:
                    issue(row, "sex_counts_disagree", str(numeric))
                kinds["detail"] += 1
            elif not code and not label and (tab or not any(numeric)):
                kinds["worksheet_helpers"] += 1
            else:
                issue(row, "unclassified_row", json.dumps(cells, ensure_ascii=False))
                kinds["unclassified"] += 1
    return blocks, detail, (ac_row, ac_label, ac_counts), issues, aux, kinds


def signature(block):
    # Coordinates can change between formats. Compare the complete ordered block.
    sequence = [
        [r["section"], r["caste_code"], r["caste_name"], *[r[c] for c in COUNTS]]
        for r in block["rows"]
    ]
    evidence = [
        block["locality_type"],
        block["locality_name"],
        block["printed"],
        sequence,
    ]
    return hashlib.sha256(json.dumps(evidence, ensure_ascii=False).encode()).hexdigest()


def compared_rows(block):
    return [
        (r["section"], r["caste_code"], r["caste_name"], tuple(r[c] for c in COUNTS))
        for r in block["rows"]
    ]


def compare_sources(primary, alternate, base, alt):
    left = [signature(b) for b in primary]
    right = [signature(b) for b in alternate]
    lc, rc = Counter(left), Counter(right)
    changes = Counter()
    if alt["kind"] == "tab_delimited":
        if len(primary) != len(alternate):
            raise ValueError(f"Different block counts: {alt['member']}")
        for b, a in zip(primary, alternate, strict=True):
            keys = ("locality_type", "locality_name")
            if any(b[k] != a[k] for k in keys):
                raise ValueError(f"Different locality: {alt['member']} {a['block']}")
            br, ar = compared_rows(b), compared_rows(a)

            def is_placeholder(r):
                return (
                    r[1:3] == ("CASTES NOT IDENTIFIABLE", "CASTES NOT IDENTIFIABLE")
                    and r[3] == (0,) * 5
                )

            if [r for r in br if not is_placeholder(r)] != [
                r for r in ar if not is_placeholder(r)
            ] or Counter(br) - Counter(ar):
                raise ValueError(f"Detail conflict: {alt['member']} {a['block']}")
            changes["additional_zero_rows"] += len(ar) - len(br)
            if a["printed"] != b["printed"]:
                if b["printed"] != [None] * 5 or a["printed"] != [0.0] * 5:
                    raise ValueError(f"Different totals: {alt['member']} {a['block']}")
                changes["additional_zero_totals"] += 1
            if any(a[k] and not b[k] for k in ("town", "tehsil")):
                changes["richer_geography"] += 1
    elif rc - lc:
        raise ValueError(f"Workbook loses blocks present in {alt['member']}")
    return {
        "segment": base["segment"],
        "primary_workbook": base["member"],
        "comparison_member": alt["member"],
        "comparison_sha256": alt["sha256"],
        "kind": alt["kind"],
        "workbook_blocks": len(left),
        "comparison_blocks": len(right),
        "identical_blocks": sum((lc & rc).values()),
        "same_order": left == right,
        **{
            k: changes[k]
            for k in (
                "additional_zero_rows",
                "additional_zero_totals",
                "richer_geography",
            )
        },
    }


def reconcile(source, result, cover, workbook, workbook_control):
    blocks, detail, _, issues, aux, kinds = result
    ac_row, ac_label, ac_counts = workbook_control
    src = {k: source[k] for k in ("segment", "sha256", "sheet")}
    localities = []
    for b in blocks:
        rows = b["rows"]
        sums = [strict_sum([r[c] for r in rows]) for c in COUNTS]
        geography = {k: b[k] for k, _ in LOC}
        for r in rows:
            r.update(src, **geography)
        status = check(b["printed"], sums)
        if not rows and b["printed"] in ([None] * 5, [0] * 5):
            status = (
                "empty_no_total" if b["total_row"] is None else "empty_printed_zero"
            )
        localities.append(
            {
                **src,
                **geography,
                "heading_row": b["heading_row"],
                "total_row": b["total_row"],
                "detail_rows": len(rows),
                "check": status,
                **control_fields(b["printed"], sums),
            }
        )
        if status in {"difference", "incomplete"}:
            issues.append(
                {
                    **src,
                    "block": b["block"],
                    "source_row": b["total_row"] or b["heading_row"],
                    "issue": "locality_" + status,
                    "evidence": f"printed={b['printed']} detail={sums}",
                }
            )
    sums = [strict_sum([r[c] for r in detail]) for c in COUNTS]
    local = [strict_sum([b["printed"][i] for b in blocks]) for i in range(5)]
    src = {k: workbook[k] for k in ("segment", "sha256", "sheet")}
    h = workbook["header"]
    total = {
        **src,
        "detail_source_sha256": source["sha256"],
        "cover_name": cover,
        "internal_segment": int(h["header_segment"]),
        "constituency_label": h["constituency_label"],
        "total_label": ac_label,
        "total_row": ac_row,
        "blocks": len(blocks),
        "detail_rows": len(detail),
        "check": check(ac_counts, sums),
        **control_fields(ac_counts, sums),
        **dict(zip(("locality_" + c for c in COUNTS), local)),
    }
    if total["check"] != "match" or check(ac_counts, local) != "match":
        issues.append(
            {
                **src,
                "source_row": ac_row,
                "issue": "constituency_controls",
                "evidence": f"printed={ac_counts} detail={sums} locality={local}",
            }
        )
    if total["internal_segment"] != src["segment"]:
        issues.append(
            {
                **src,
                "source_row": None,
                "issue": "segment_header",
                "evidence": h["segment_label"] + " / " + h["constituency_label"],
            }
        )
    if (
        ac_label
        and ac_label.removeprefix("TOTAL OF ").strip()
        != h["constituency_label"].partition(":")[2].strip()
    ):
        issues.append(
            {
                **src,
                "source_row": ac_row,
                "issue": "constituency_total_label",
                "evidence": ac_label + " / " + h["constituency_label"],
            }
        )
    return dict(
        detail=detail,
        localities=localities,
        constituencies=[total],
        exceptions=issues,
        auxiliary=aux,
    )


def build(cache, output):

    output.mkdir(parents=True, exist_ok=True)
    covers = {int(r["segment"]): r["cover_name"] for r in inventory("constituencies")}
    groups = source_groups()
    if set(groups) != set(covers):
        raise ValueError("Source coverage differs from the cover roster")
    comparisons, accounts = [], []
    with ExitStack() as stack:
        writers = {
            name: stack.enter_context(
                pq.ParquetWriter(
                    output / (name + ".partial"), pa.schema(fields), compression="zstd"
                )
            )
            for name, fields in SCHEMAS.items()
        }
        for segment, sources in sorted(groups.items()):
            base = sources[0]
            primary = parse_file(cache, base)
            has_text = any(s["kind"] == "tab_delimited" for s in sources)
            accounts.append(
                {
                    "segment": segment,
                    "sha256": base["sha256"],
                    "sheet": base["sheet"],
                    "member": base["member"],
                    "role": "workbook_controls" if has_text else "detail_and_controls",
                    **primary[-1],
                }
            )
            selected, result = base, primary
            for alt in sources[1:]:
                alternate = parse_file(cache, alt)
                comparisons.append(compare_sources(primary[0], alternate[0], base, alt))
                accounts.append(
                    {
                        "segment": segment,
                        "sha256": alt["sha256"],
                        "sheet": alt["sheet"],
                        "member": alt["member"],
                        "role": (
                            "detail_and_localities"
                            if alt["kind"] == "tab_delimited"
                            else "alternate_workbook"
                        ),
                        **alternate[-1],
                    }
                )
                if alt["kind"] == "tab_delimited":
                    selected, result = alt, alternate
            tables = reconcile(selected, result, covers[segment], base, primary[2])
            tables["auxiliary"] = primary[4]
            for name, rows in tables.items():
                if rows:
                    writers[name].write_table(
                        pa.Table.from_pylist(rows, schema=pa.schema(SCHEMAS[name]))
                    )
    for name in writers:
        (output / (name + ".partial")).replace(output / (name + ".parquet"))
    for name, records in [("variants", comparisons), ("row_accounting", accounts)]:
        fields = list(dict.fromkeys(k for r in records for k in r))
        write_csv(
            output / (name + ".csv"),
            fields,
            ([r.get(k, 0) for k in fields] for r in records),
        )


if __name__ == "__main__":
    build(Path(sys.argv[1]), Path(sys.argv[2]))
