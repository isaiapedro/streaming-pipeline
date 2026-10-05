import json
from pathlib import Path

from scripts.render_grafana_assets import render_assets
from scripts.replay_benchmark_to_influx import (
    BENCHMARK_MEASUREMENT,
    PROGRESS_MEASUREMENT,
    _numeric_fields,
    load_cells,
    points_for_cell,
)


ROOT = Path(__file__).parents[2]


def test_presentation_dashboard_and_benchmark_replay(tmp_path):
    dashboard = json.loads(
        (ROOT / "grafana/provisioning/dashboards/presentation.json").read_text()
    )
    assert dashboard["refresh"] == "5s"
    assert dashboard["timepicker"]["refresh_intervals"][0] == "5s"
    assert "EDGE" in dashboard["panels"][0]["options"]["content"]
    assert "CLOUD" in dashboard["panels"][0]["options"]["content"]
    assert "replays completed synthetic benchmark evidence" in dashboard["panels"][-1]["options"]["content"]
    data_panels = [panel for panel in dashboard["panels"] if panel.get("targets")]
    assert data_panels
    datasource_uid = "$" + "{DS_INFLUXDB_CLOUD}"
    assert {panel["datasource"]["uid"] for panel in data_panels} == {datasource_uid}
    assert all(
        'r.evidence_mode == "replay"' in target["query"]
        for panel in data_panels for target in panel["targets"]
    )
    session = next(item for item in dashboard["templating"]["list"] if item["name"] == "session")
    assert session["includeAll"] is True
    assert session["allValue"] == ".*"
    assert 'r._field == "completed_cells"' in session["query"]
    assert PROGRESS_MEASUREMENT in session["query"]
    assert "rename(" not in session["query"]
    assert all(
        "${session:regex}" in target["query"]
        for panel in data_panels for target in panel["targets"]
    )
    assert all(
        BENCHMARK_MEASUREMENT in target["query"] or PROGRESS_MEASUREMENT in target["query"]
        for panel in data_panels for target in panel["targets"]
    )

    csv_path = tmp_path / "benchmark.csv"
    csv_path.write_text(
        "run_id,scenario,signal_seed,noise_seed,approach,duration_s,detection_run_rate,scoring_detection_latency_ms\n"
        "run-1,synthetic,1000,2000,A,60,1,10\n"
        "run-1,synthetic,1000,2000,B,60,1,20\n"
        "run-1,synthetic,1000,2000,C,60,0,\n"
    )
    cells = load_cells(csv_path)
    assert len(cells) == 1
    points = points_for_cell(
        cells[0], session="orientator-demo", source_sha256="a" * 64,
        completed_cells=1, total_cells=1, timestamp_ns=1_800_000_000_000_000_000,
    )
    lines = [point.to_line_protocol() for point in points]
    assert len(lines) == 4
    assert all("evidence_mode=replay" in line for line in lines)
    assert "completion_pct=100" in lines[-1]
    assert f"{BENCHMARK_MEASUREMENT}," in lines[0]
    assert f"{PROGRESS_MEASUREMENT}," in lines[-1]

    numeric = _numeric_fields({
        "time_in_alarm_pct": "0.0",
        "alarm_episode_rate_per_patient_day": "144.0",
        "alarm_episode_count": "1",
    })
    assert isinstance(numeric["time_in_alarm_pct"], float)
    assert isinstance(numeric["alarm_episode_rate_per_patient_day"], float)
    assert isinstance(numeric["alarm_episode_count"], int)

    rendered_dir = tmp_path / "rendered"
    render_assets("approved-bucket", rendered_dir)
    rendered_text = (rendered_dir / "dashboards/presentation.json").read_text()
    rendered = json.loads(rendered_text)
    bucket = next(item for item in rendered["templating"]["list"] if item["name"] == "bucket")
    assert bucket["query"] == "approved-bucket"
    assert "__INFLUX_BUCKET__" not in rendered_text
