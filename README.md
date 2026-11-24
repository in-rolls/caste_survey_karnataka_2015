# Karnataka Social and Educational Survey, 2015

Constituency abstracts of households and population by caste or community. The district covers name the Karnataka State Backward Classes Commission and identify the survey as the Social and Educational Survey, 2015. The Udupi cover also carries the year 2018. The workbooks tabulate counts within villages and urban wards. The statewide detail table reports aggregate counts for caste/community entries within localities.

## Dataset credit and access

**Varun Karekurve-Ramachandra** is the creator and access contact for this dataset release. The Karnataka State Backward Classes Commission conducted the original survey.

To request the data, email Varun directly at [varun.rama@usc.edu](mailto:varun.rama@usc.edu). The Zenodo record is public and the data files require approval. [Zenodo record](https://doi.org/10.5281/zenodo.24489667)

## Public schema

The field catalog lists every column in the five Parquet tables, in file order, with its Arrow type and whether the file permits nulls. Each table also lists its row count, what one row represents, and its key where defined. The dictionary explains how to join tables and interpret missing values. [Machine-readable schema](data/release/schema.json) · [Data dictionary](DATA_DICTIONARY.md)

## Archive and coverage

The source supplied for this inventory is `Constituencies-20210217T023644Z-001.zip`, 313,232,334 bytes, SHA-256 `434772cefd7d0c7fcc2564b781fc4d99e22fc16ada729cd849ddfe48e966f009`. Its Desktop download metadata points to Google Drive. The original supplier and redistribution terms are under review. The [national SECC repo](https://github.com/in-rolls/secc) documents a separate survey conducted in 2011.

| Source type | ZIP entries | Distinct contents by SHA-256 |
| --- | ---: | ---: |
| Excel workbooks with .xlsx suffix | 333 | 229 |
| Workbook with .tmp suffix | 2 | 1 |
| Tab-delimited exports with .xls suffix | 20 | 10 |
| Word district covers and constituency rosters | 61 | 30 |
| Spreadsheet formula notes | 6 | 3 |
| Office lock files, Finder files and directory entry | 9 | 4 |

The 30 covers list 224 assembly segments. Every listed number occurs exactly once in the combined cover roster and appears in at least one .xlsx filename. The statewide table below accounts for the locality blocks found in those files. No independent statewide roster of survey localities was available for a coverage comparison.

- [Archive members](inventory/members.csv) lists every original path, byte size, file type, SHA-256 and segment number where available in the filename.
- [Constituency roster](inventory/constituencies.csv) gives each segment number, constituency name, original Word document and serial number on that cover. District names should come from the source itself. A copy of the Chikkaballapura cover sits in the Tumkuru folder.
- [Workbook headers](inventory/workbook_headers.csv) records the sheet names and labels found in the first twelve rows of every sheet for each distinct workbook. Empty fields are unresolved by this inspection.

## Reading the tables

The basic observation is one printed caste or community entry within a locality block. A block carries a village name or ward label, a printed total, then detail rows. Section headings inside the block include Scheduled Castes, Scheduled Tribes and “Minorities **”. Retain the printed section and the exact code and label. A blank section field in the pilot means no section heading has appeared since the start of that locality. Numeric response codes, including 33333 and 44444, can occur beside textual explanatory labels.

The parser retains the original caste labels, including slash-separated names, and preserves explicit zeros. It checks locality totals against caste/community entries for all five measures. Some constituency totals are spreadsheet formulas that refer to the detail rows, so agreement is an arithmetic check.

The files numbered 91 (Kampli) and 177 (Anekal) print segment numbers 92 and 176 in their headers. For Jayanagar, the first sheet is a ward summary and the second sheet contains the detailed abstract for segment 173. The dictionary records how these sources were reconciled.

## Statewide data

The statewide extract contains **1,048,479 caste/community entries in 34,844 locality blocks across 224 assembly constituencies**. The source labels 29,473 village blocks and 5,369 ward blocks. Two blocks with 931 detail entries have no locality heading. One block is an occurrence within a constituency, so a repeated ward label may refer to a different place.

| File | Rows | How to use it |
| --- | ---: | --- |
| `detail.parquet` | 1,048,479 | One printed caste/community entry, geographic context and five counts |
| `localities.parquet` | 34,844 | Printed locality controls, recomputed detail sums and block checks |
| `constituencies.parquet` | 224 | Printed constituency controls, sums from the two lower levels and cover names |
| `exceptions.parquet` | 83 | Source coordinates and evidence for missing cells, conflicting labels and failed or incomplete checks |
| `auxiliary.parquet` | 63 | Cached rows from secondary worksheets |

The [dictionary](DATA_DICTIONARY.md) defines keys, units, missing values and the decisions made where source versions differ. The [variant comparisons](data/release/variants.csv) and [source accounting](data/release/row_accounting.csv) identify the exact files used.

**Reconciliation.** All five counts reconcile in 32,965 blocks. Two more have numerical differences and one has a missing count. Of the remaining blocks, 1,004 print zero totals and contain no detail rows, and 872 have neither detail nor a printed total. The latter have unknown counts. Summing only populated cells can hide these distinctions.

At the constituency level, all five detail measures agree with the workbook controls in 220 of 224 seats. The exceptions can be traced to four specific places.

| Segment | What the source shows |
| --- | --- |
| 110 Honnali | The household total formula stops earlier in the worksheet than the other constituency formulas. |
| 126 Tarikere | A printed locality household total disagrees with its detail. The constituency formula returns a fractional household count. |
| 135 Gubbi | A detail row’s sex counts disagree with its printed population. The locality female count also differs from the sum of detail. |
| 151 K.R. Pura | One detail row gives all three sex counts but leaves its population cell empty. The extract preserves that missing value. |

The 224 printed constituency population controls sum to 59,814,534. That figure is a sum of workbook controls, several of which average detail and locality totals using Excel formulas. Summing only the nonmissing population cells in the detail gives 59,814,126 and omits one observation. Neither figure is an independently verified statewide headcount.

## Reproduce the tables

From the checkout with Python 3.11 or later, set `archive` to the ZIP path.

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
archive="$HOME/Desktop/Constituencies-20210217T023644Z-001.zip"
.venv/bin/python scripts/inventory.py "$archive" inventory
.venv/bin/python scripts/profile_headers.py "$archive" inventory/members.csv inventory/workbook_headers.csv
mkdir -p build
.venv/bin/python scripts/pilot.py "$archive" build/pilot.csv
.venv/bin/python scripts/extract_sheets.py "$archive" build/sheets
.venv/bin/python scripts/parse_statewide.py build/sheets data/release
.venv/bin/python scripts/verify_statewide.py "$archive" data/release
.venv/bin/python scripts/describe_release.py
.venv/bin/python scripts/package_release.py
```

The extractor uses Calamine to read cached Excel values and checks the source ZIP fingerprint. It checkpoints each distinct member on disk. The verifier reopens the ZIP and uses openpyxl for Excel and a fresh TSV read for text exports. It checks every published detail row against its source coordinate, caste code and label, section, locality name, and five counts.
