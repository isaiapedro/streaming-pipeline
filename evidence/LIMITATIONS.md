# Evidence limitations

- The patient trajectories are parametric synthetic data. They test software
  behavior under controlled scenarios and do not establish clinical validity.
- A/B/C uses 25 deterministic cells from a fully crossed 5×5 signal/noise-seed
  design per scenario. Confidence intervals describe variation in those
  synthetic runs, not a patient population.
- A 24-hour random walk can accumulate unrealistic drift. Until the approved
  reference-distribution gate is executed, the stable-baseline magnitude is a
  generator/threshold sensitivity result rather than a clinical alarm-rate estimate.
- Run-level detection and false-alarm occurrence are not clinical TPR/FPR.
  Derived alarm episodes are an operational state proxy, not notifications
  received or acknowledged by clinicians.
- Scale and live latency depend on CPU allocation, broker configuration,
  network path, storage service load, and the selected pull timeout. Results
  are not portable without the accompanying machine and configuration context.
- Application timestamps use Unix epoch milliseconds and therefore include
  wall-clock resolution and synchronization error. The protocol reconnect
  harness uses a monotonic duration clock where an epoch timestamp is not
  required.
- Offline simulation metrics are not pipeline latency. Publish-to-consume and
  publish-to-successful-storage P99 values may only come from the live harness.
- Local Docker measurements do not represent hosted NATS, WAN, or InfluxDB
  behavior. Hosted and local results must be labelled separately.
- The final T1 run wrote its aggregate files but the NATS client process
  lingered during shutdown and required interruption. T2–T4 were not rerun on
  this worktree and remain `unexecuted`; this is an execution-gate limitation,
  not a failed tier result.
- Distribution similarity depends on an approved reference source and its
  transformation. The declared directional metric is
  KL(P_synthetic || P_reference), calculated over shared histogram bins with
  documented smoothing. Only aggregate histograms and metrics are retained;
  the row-level reference input remains outside this repository.
- The complete 450-row, 24-hour-stable-baseline development run was generated
  from a dirty worktree. Its manifest and hashes are auditable, but final mode
  must reject it until a clean release commit reproduces the run with an exact
  pinned dependency environment.
