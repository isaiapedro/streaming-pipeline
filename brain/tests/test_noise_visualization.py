import csv

from data.generators.noise import NoiseConfig
from scripts.validate_distributions import SIGNALS
from scripts.visualize_noise_injection import render


def _write_signals(path, rows=20):
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SIGNALS)
        writer.writeheader()
        for index in range(rows):
            writer.writerow({signal: 50 + offset + index / 10 for offset, signal in enumerate(SIGNALS)})


def test_noise_visualization_emits_only_figure_aggregates_and_provenance(tmp_path):
    source = tmp_path / "synthetic.csv"
    _write_signals(source)
    output = tmp_path / "output"
    summary = render(
        source,
        output,
        config=NoiseConfig(packet_loss_rate=1.0),
        seed=2_000,
        sample_interval_ms=1_000,
        samples=20,
    )
    assert len(summary) == 5
    assert all(row["dropped"] == 20 and row["retained"] == 0 for row in summary)
    assert (output / "noise_dropout_injection.png").is_file()
    assert (output / "noise_injection_summary.csv").is_file()
    assert (output / "noise_injection_provenance.json").is_file()
    assert not (output / source.name).exists()
