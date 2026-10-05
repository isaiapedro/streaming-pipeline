import csv

from scripts.generate_synthetic_validation_data import generate
from scripts.validate_distributions import SIGNALS


def test_synthetic_validation_extract_is_identifier_free_and_deterministic(tmp_path):
    first = tmp_path / "first.csv"
    second = tmp_path / "second.csv"
    first_metadata = generate(first, 2, 1_000, 1_767_225_600_000, 60_000)
    second_metadata = generate(second, 2, 1_000, 1_767_225_600_000, 60_000)

    rows = list(csv.DictReader(first.open()))
    assert len(rows) == 12
    assert tuple(rows[0]) == SIGNALS
    assert all("patient_id" not in row for row in rows)
    assert first.read_bytes() == second.read_bytes()
    assert first_metadata["csv_sha256"] == second_metadata["csv_sha256"]
    assert first_metadata["runtime_cadence_reproduced"] is False
