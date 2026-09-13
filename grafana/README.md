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

`alerting/rules.yml` contains a paused synthetic critical-event rule. It has no
contact point or secret. Configure an approved destination outside Git, run a
synthetic event, retain a screenshot or sanitized rule evaluation, and only
then unpause the rule.
