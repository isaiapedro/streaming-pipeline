import csv
import json
import zipfile

from scripts.extract_mimiciii_demo_vitals import METHOD_ID, SIGNALS, SOURCE_ID, extract


def test_extracts_identifier_free_complete_hourly_rows(tmp_path):
    headers = ["SUBJECT_ID", "HADM_ID", "ICUSTAY_ID", "ITEMID", "CHARTTIME", "VALUENUM", "ERROR"]
    rows = [
        ["123", "456", "789", "211", "2100-01-01 12:01:00", "80", ""],
        ["123", "456", "789", "211", "2100-01-01 12:30:00", "100", ""],
        ["123", "456", "789", "646", "2100-01-01 12:02:00", "96", ""],
        ["123", "456", "789", "51", "2100-01-01 12:03:00", "120", ""],
        ["123", "456", "789", "618", "2100-01-01 12:04:00", "18", ""],
        ["123", "456", "789", "678", "2100-01-01 12:05:00", "98.6", ""],
    ]
    source = tmp_path / "demo.zip"
    chart = tmp_path / "CHARTEVENTS.csv"
    with chart.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)
    with zipfile.ZipFile(source, "w") as archive:
        archive.write(chart, "mimiciii-demo-1.4/CHARTEVENTS.csv")

    output = tmp_path / "aligned.csv"
    provenance = tmp_path / "provenance.json"
    assert extract(source, output, provenance) == 1

    with output.open(newline="") as handle:
        extracted = list(csv.DictReader(handle))
    assert tuple(extracted[0]) == SIGNALS
    assert float(extracted[0]["heart_rate"]) == 90.0
    assert float(extracted[0]["temperature"]) == 37.0
    assert "123" not in output.read_text()
    assert output.stat().st_mode & 0o777 == 0o600
    metadata = json.loads(provenance.read_text())
    assert metadata["source"] == SOURCE_ID
    assert metadata["method"] == METHOD_ID
    assert metadata["complete_window_rows"] == 1
    assert metadata["aggregation_window_hours"] == 6
