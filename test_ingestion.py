from io import BytesIO
import zipfile

import pandas as pd

from mas_platform.reports.ingestion import (
    combine_related_tables,
    date_tables,
    read_uploaded_datasets,
)


def _factory_files():
    return {
        "line-productivity.csv": (
            "Date|Product|Batch|Operator|Start Time|End Time\n"
            "2024-08-29|OR-600|422111|Mac|11:50:00|14:05:00\n"
            "2024-08-30|LE-600|422112|Dee|14:05:00|15:45:00\n"
        ),
        "line-downtime.csv": (
            "Batch|Factor 1|2|3\n"
            "Batch|1.0|2.0|3.0\n"
            "422111||60.0|15.0\n"
            "422112|20.0||\n"
        ),
        "products.csv": (
            "Product|Flavor|Size|Min batch time\n"
            "OR-600|Orange|600 ml|60\n"
            "LE-600|Lemon lime|600 ml|60\n"
        ),
        "metadata.csv": "Table,Field,Description\nLine productivity,Date,Production date\n",
    }


def test_directory_of_related_pipe_delimited_csv_files_joins_without_fixed_headers():
    files = [
        (name, contents.encode())
        for name, contents in _factory_files().items()
    ]

    tables, warnings = read_uploaded_datasets(files)

    assert warnings == []
    assert len(tables) == 4
    primary = date_tables(tables)[0]
    combined, notes = combine_related_tables(tables, primary.name)

    assert len(combined) == 2
    assert combined.loc[0, "Record count"] == 1
    assert combined.loc[0, "Batch duration (min)"] == 135
    assert combined.loc[0, "line-downtime — Total downtime (min)"] == 75
    assert combined.loc[0, "products — Flavor"] == "Orange"
    assert any("Product" in note for note in notes)
    assert any("Batch" in note for note in notes)


def test_zip_upload_reads_multiple_files_and_skips_metadata():
    archive_buffer = BytesIO()
    with zipfile.ZipFile(archive_buffer, "w") as archive:
        for name, contents in _factory_files().items():
            archive.writestr(f"dataset/{name}", contents)

    tables, warnings = read_uploaded_datasets([("factory.zip", archive_buffer.getvalue())])

    assert warnings == []
    assert len(date_tables(tables)) == 1
    combined, _ = combine_related_tables(tables, date_tables(tables)[0].name)
    assert combined["line-downtime — Total downtime (min)"].tolist() == [75, 20]


def test_json_records_and_unsupported_files_are_reported():
    tables, warnings = read_uploaded_datasets([
        ("sales.json", b'{"orders":[{"date":"2024-01-01","amount":12},{"date":"2024-01-02","amount":20}]}'),
        ("image.png", b"not an image"),
    ])

    assert len(tables) == 1
    assert tables[0].frame["amount"].tolist() == [12, 20]
    assert len(warnings) == 1
    assert "unsupported format" in warnings[0]


def test_excel_and_parquet_files_are_read_as_tables():
    frame = pd.DataFrame({"Date": ["2024-01-01", "2024-01-02"], "Sales": [10, 15]})
    excel = BytesIO()
    frame.to_excel(excel, index=False, sheet_name="Sales")
    parquet = BytesIO()
    frame.to_parquet(parquet, index=False)

    tables, warnings = read_uploaded_datasets([
        ("sales.xlsx", excel.getvalue()),
        ("sales.parquet", parquet.getvalue()),
    ])

    assert warnings == []
    assert len(tables) == 2
    assert tables[0].name.endswith("Sales")
    assert tables[1].frame["Sales"].tolist() == [10, 15]
