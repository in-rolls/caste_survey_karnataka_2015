"""Write the public schema from the five released Parquet file headers."""

import json
from pathlib import Path

import pyarrow.parquet as pq

TABLES = {
    "detail": ("One printed caste/community entry", ["sha256", "sheet", "source_row"]),
    "localities": ("One locality block within a constituency", ["segment", "block"]),
    "constituencies": ("One assembly constituency", ["segment"]),
    "exceptions": ("One flagged source or parsing issue", None),
    "auxiliary": ("One secondary worksheet row", ["sha256", "sheet", "source_row"]),
}


def describe(directory):
    tables = {}
    for name, (unit, key) in TABLES.items():
        filename = f"{name}.parquet"
        parquet = pq.ParquetFile(directory / filename)
        tables[filename] = {
            "unit": unit,
            "rows": parquet.metadata.num_rows,
            "key": key,
            "columns": {
                field.name: {"type": str(field.type), "nullable": field.nullable}
                for field in parquet.schema_arrow
            },
        }
    (directory / "schema.json").write_text(
        json.dumps(tables, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    describe(Path("data/release"))
