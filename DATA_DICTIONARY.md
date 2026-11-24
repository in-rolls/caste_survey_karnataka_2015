# Karnataka survey tables

The five Parquet files hold the printed caste/community entries, two levels of printed totals, the exceptions found during parsing, and the secondary worksheets. The unit of publication is a count within a locality. The input archive contains constituency abstracts of Karnataka’s 2015 Social and Educational Survey.

The public schema gives the exact fields and Arrow types in each file. A nullable field permits a missing value even when every observation in this release has a value. The exceptions table has no declared unique key. [Schema by table](data/release/schema.json)

## Joining records

- In `detail.parquet`, one row is one count-bearing caste/community entry, including explicit zero and refusal categories. The source key is `(sha256, sheet, source_row)`. A caste code can recur, including under different sections.
- In `localities.parquet`, one row is one locality block in source order, including blocks with a heading and no detail. The key is `(segment, block)`. Each detail row belongs to exactly one locality block. Ward numbers can repeat within a constituency.
- In `constituencies.parquet`, one row is one of the 224 segments in the district cover roster. Join to detail or localities on `segment`. Constituency controls come from Excel even when tab-delimited exports supply that constituency’s detail.
- In `exceptions.parquet`, one row is one parser or source issue. Several issues can refer to the same place. In `auxiliary.parquet`, one row preserves one nonempty row of cached cells on a secondary worksheet. Adding auxiliary rows to the detail table would double-count some information.
- `row_accounting.csv` has one row per distinct input used for the comparison or the release, with a representative archive path and SHA-256. Join that file by hash to look up a source path. The full archive member inventory includes duplicate paths for identical contents.

## Columns

| Column | Type and meaning |
| --- | --- |
| `segment` | Integer assembly constituency number from the file and checked against the district cover roster. |
| `sha256`, `sheet` | Source member’s SHA-256 fingerprint and worksheet name. For the ten tab-delimited files the sheet value is `TSV`. |
| `source_row`, `heading_row`, `total_row` | One-based Excel row or logical TSV record number. A missing heading or printed total has a null coordinate. Some workbook-level exceptions have no single source row. |
| `block` | One-based locality sequence within the selected source for the segment. An unlabeled new total starts its own block. |
| `district`, `tehsil`, `town` | Text from the current geographic headings. Tehsil is a subdistrict. The named town applies to following wards until the geography changes. Missing geographic labels are null. These are source labels, without an external geographic crosswalk. |
| `locality_type`, `locality_name` | `village` or `ward` and the text after the heading prefix. Ward `0023` retains its leading zeros. Both fields are null for two blocks. |
| `section` | The most recent source section heading in the block, including Scheduled Castes, Scheduled Tribes or Minorities **. Null means there has been no section heading in the current block. |
| `caste_code`, `caste_name` | Source code stored as text and source label in its original spelling, capitalization and punctuation. Numeric response codes and the textual unidentified-caste category are retained. Slash-delimited names stay together. |
| `households`, `male`, `female`, `third_gender`, `population` | Printed integer counts. Households count households, the other four count people. Explicit zero is preserved. One missing population cell is null. |
| `printed_*` | Five cached Excel or printed TSV controls for the block or segment. Stored as numbers permitting fractions because two workbook formulas return half counts. A missing control stays null. |
| `detail_*`, `locality_*` | Strict sums of the detail measures or printed locality measures, respectively. A missing component or an empty set of detail observations yields null. |
| `detail_rows`, `blocks` | Number of published detail records in the block or segment, and number of locality blocks in the segment. |
| `check` | Compares all five printed measures with sums of detail. Values are `match`, `difference`, and `incomplete`. A known numerical difference takes precedence over missingness. For blocks with no detail, `empty_printed_zero` means five printed zeros and `empty_no_total` means the total row is absent. |
| `cover_name`, `internal_segment`, `constituency_label`, `total_label` | The cover’s constituency name, the workbook’s internal number, and its two printed name labels. These remain readable where the archive disagrees with itself. |
| `detail_source_sha256` | Source for the segment’s detail and localities. The constituency row’s own `sha256` identifies its printed control workbook. |
| `issue`, `evidence` | Reason for a flag and the observed cell values or comparison. A constituency-control flag can arise from missing locality totals even when its detail reconciles. |
| `cells` | List of cached cell values as text in column order starting at A, with interior blanks retained and trailing blank cells omitted. |

## Source selection and changes to representation

1. Every distinct substantive member has a hash. Archive copies with the same bytes count once. Sixteen additional source variants were compared with the chosen Excel workbooks. The five alternate .xlsx copies and one .tmp workbook add no substantive counts. The nested versions of segments 140 and 143 include four named blocks absent from their other Excel versions, and are used in the comparison and release.
2. For ten constituencies, the tab exports have the same locality order, ordered substantive detail, and all overlapping printed totals as the chosen Excel workbooks. They preserve 3,794 additional explicit all-zero unidentified-caste rows and 155 additional printed all-zero locality totals. They also supply tehsil or town information missing from the Excel version for 2,110 blocks. The matching test allows only those explicit zero-row and zero-control differences in the counts. Published detail, controls at locality level, and local geography for these ten constituencies come together from their tab exports.
3. Segment 91 carries the Siruguppa number and name inside the Kampli workbook. Its first village is Nelludi, which the delimitation order places in 91 Kampli. The district cover, filename and sheet name also support 91. Segment 177’s workbook prints the number 176 beside the name Anekal. Its cover, filename, sheet name and constituency total label support 177 Anekal. [Election Commission delimitation order](https://www.eci.gov.in/Documents/Delimitation/DelimitationofParliamentaryAssemblyConstituenciesOrder-2008%28English%29.pdf)
4. Uppercase comparisons recognize headings and codes during parsing. The output preserves the two caste fields as supplied in the selected source. Numeric Excel code cells become their text representations. Geographic labels lose the field prefix and surrounding whitespace. Source totals are stored separately from detail and count disagreements remain visible.
5. The Jayanagar detail is on its second sheet. Three secondary sheets contain 63 nonempty cached rows, preserved separately. One isolated TSV record in the Virajpet export contains stray text and has been retained verbatim in the exception ledger.
