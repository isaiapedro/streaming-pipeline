# Dissertation figure captions

- `abc_detection_latency.png` — Scoring-only latency for positive scenarios.
  Grey lines connect the same seed cell across approaches; colored markers show
  median and IQR. Labels give detected runs/25 because missing detections must
  not disappear behind conditional latency.
- `abc_false_alarm_probability.png` — Probability that a negative-scenario run
  contains at least one alarm episode. Intervals are bounded Wilson 95%
  intervals; absent positive-scenario values are inapplicable, not zero.
- `abc_alarm_episode_rate.png` — Debounced alarm episodes normalized by each
  scenario's duration. This is an operational burden proxy, not a clinician
  notification count.
- `abc_tradeoff.png` — Descriptive comparison of conditional median scoring
  latency and mean negative-scenario episode burden. Marker size and labels
  encode mean detection-run rate, preventing fast but unreliable methods from
  appearing unqualifiedly superior. It is not a significance test.
- `abc_representative_timeline.png` — One predeclared sepsis seed cell showing
  all five scoped NEWS2 inputs on separate axes, ground-truth onset, B/C NEWS2
  response, and the first new A/B/C alarm episodes. It is explanatory;
  aggregate claims come from all 25 seed cells.
- `evidence_status.png` — Completeness map for the dissertation evidence
  package. Grey or magenta entries are unavailable gates, never zero-valued
  results.
- `protocol_latency.png` — Local publish-to-consume P50/P99 for NATS and MQTT
  over 100 messages each. This partial comparison excludes broker restart,
  persistence, packet-level loss, storage, and hosted-network behavior.
- `scale_status.png` — Target throughput for T1–T4 on a labelled logarithmic
  scale. Only T1 has an achieved measurement; T2–T4 are explicitly marked
  unexecuted rather than plotted as zero.
- `traceability_status.png` — Required provenance tags are implemented and
  unit-tested on emitted records, while the live stored-record coverage query
  remains unexecuted. It supports an implementation claim, not 100% live
  storage coverage.
- `architecture_status.png` — Solid nodes identify implemented core and
  supplemental paths; dashed nodes distinguish unverified live integrations
  from future suppression. It prevents planned components from appearing as
  demonstrated results.
