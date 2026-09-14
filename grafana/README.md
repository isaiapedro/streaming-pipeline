# Grafana provisioning

`comparison.json` provides synchronized A/B/C alarm-state/observation views,
B/C-only NEWS2 scores, and version views with patient, scenario, and approach
filters. Approach A has no NEWS2 value, so the dashboard unions its
`patient_vitals` alarm state only where an A/B/C comparison is valid. The
observation panel is deliberately not called an episode rate. The dashboard
reads runtime telemetry from InfluxDB; dissertation aggregate figures remain
under `evidence/` and are not misrepresented as live measurements.

Validate the assets without contacting Grafana:

```bash
python -m json.tool grafana/provisioning/dashboards/comparison.json >/dev/null
pytest -q brain/tests/test_telemetry.py
```

Render deployable assets from the governed bucket configuration before loading
them into Grafana:

```bash
INFLUX_BUCKET=approved-bucket .venv/bin/python scripts/render_grafana_assets.py
```

Use `.runtime/grafana/provisioning` as the provisioning source. The committed
dashboard and alert files are templates and intentionally retain the
`__INFLUX_BUCKET__` marker. Rendering validates every template before writing
and emits the datasource, dashboard provider, both dashboards, and alert rules;
mount or upload the entire rendered directory rather than individual JSON
files.

`alerting/rules.yml` contains a paused synthetic critical-event rule. It has no
contact point or secret. Configure an approved destination outside Git, run a
synthetic event, retain a screenshot or sanitized rule evaluation, and only
then unpause the rule.

After counting one field per logical Influx record (`patient_vitals/value` and
`alarms/news2_score`), reconcile that count with the matching outbox lifetime:

```bash
.venv/bin/python scripts/reconcile_storage.py \
  --database .runtime/influx_outbox.sqlite3 --stored-count COUNT \
  --output evidence/storage_reconciliation.json --require-complete
```

An outbox that predates accounting support is reported as `incomplete` with
its missing aggregate schema components. Open it once through the current
Brain writer to apply the local schema migration, but note that migration
cannot reconstruct historical counters; a fresh accounting lifetime is still
required for a complete claim.
