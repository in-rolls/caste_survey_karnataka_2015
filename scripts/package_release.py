"""Package the parsed survey, source inventories, and reproduction instructions."""

import hashlib
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


def package():
    out = Path("data/release")
    data = sorted([*out.glob("*.parquet"), *out.glob("*.csv")])
    if len(data) != 7:
        raise ValueError(f"Expected five tables and two ledgers, found {data}")
    manifest = out / "SHA256SUMS"
    manifest.write_text(
        "".join(
            f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n" for p in data
        ),
        encoding="utf-8",
    )
    files = sorted(
        [
            *data,
            manifest,
            *Path("inventory").glob("*.csv"),
            *Path("scripts").glob("*.py"),
            Path("README.md"),
            Path("DATA_DICTIONARY.md"),
            Path("requirements.txt"),
        ]
    )
    destination = out / "karnataka_survey_2015.zip"
    partial = destination.with_suffix(".partial")
    with ZipFile(partial, "w") as z:
        for path in files:
            info = ZipInfo(path.as_posix())
            info.compress_type = ZIP_DEFLATED
            z.writestr(info, path.read_bytes())
    with ZipFile(partial) as z:
        for path in files:
            if z.read(path.as_posix()) != path.read_bytes():
                raise ValueError(f"Archive differs from source: {path}")
    partial.replace(destination)


if __name__ == "__main__":
    package()
