import csv

import json

import numpy as np
import pytest

from scripts.validate_distributions import correlation_matrix, kl_synthetic_reference, load_reference, validate


def test_distribution_tool_reads_required_columns_and_scores_equal_series(tmp_path):
    path = tmp_path / "reference.csv"
    columns = ["heart_rate", "spo2", "systolic_bp", "respiratory_rate", "temperature"]
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for value in range(3):
            writer.writerow({column: value + 1 for column in columns})
    values = load_reference(path)
    assert set(values) == set(columns)
    assert kl_synthetic_reference(values["heart_rate"], values["heart_rate"]) == 0.0


def test_kl_direction_is_synthetic_to_reference():
    reference = np.array([0.0, 0.0, 0.0, 0.0, 1.0])
    synthetic = np.array([0.0, 0.0, 0.0, 1.0, 1.0])
    forward = kl_synthetic_reference(reference, synthetic, bins=2)
    reverse = kl_synthetic_reference(synthetic, reference, bins=2)
    assert forward != reverse


def test_distribution_outputs_only_aggregates_and_provenance(tmp_path):
    source = tmp_path / "source.csv"
    columns = ["heart_rate", "spo2", "systolic_bp", "respiratory_rate", "temperature"]
    with source.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for value in range(1, 5):
            writer.writerow({column: value for column in columns})
    output = tmp_path / "output"
    validate(source, source, output, "APPROVED-AGGREGATE-01", "selected numeric columns; no identifiers")
    metrics = list(csv.DictReader((output / "kl_divergence.csv").open()))
    provenance = json.loads((output / "provenance.json").read_text())
    assert len(metrics) == 5
    assert all(float(row["kl_synthetic_reference"]) == 0.0 for row in metrics)
    assert provenance["approved_reference_source_id"] == "APPROVED-AGGREGATE-01"
    assert provenance["kl_direction"] == "synthetic_to_reference"
    assert (output / "synthetic_vs_reference.png").is_file()
    assert (output / "kl_divergence.png").is_file()
    assert (output / "inter_signal_correlation.png").is_file()
    correlations = list(csv.DictReader((output / "correlation_matrix.csv").open()))
    assert len(correlations) == 25
    assert not (output / source.name).exists()


def test_distribution_rejects_unset_reference_source(tmp_path):
    with pytest.raises(ValueError, match="source-id"):
        validate(tmp_path / "missing.csv", tmp_path / "missing.csv", tmp_path / "out", "unset", "method")


def test_correlation_matrix_is_symmetric_with_identity_diagonal():
    values = {
        "heart_rate": np.array([1.0, 2.0, 3.0, 4.0]),
        "spo2": np.array([4.0, 3.0, 2.0, 1.0]),
        "systolic_bp": np.array([2.0, 4.0, 6.0, 8.0]),
        "respiratory_rate": np.array([1.0, 3.0, 2.0, 5.0]),
        "temperature": np.array([5.0, 6.0, 8.0, 7.0]),
    }
    matrix = correlation_matrix(values)
    assert matrix.shape == (5, 5)
    assert np.allclose(matrix, matrix.T)
    assert np.allclose(np.diag(matrix), 1.0)
