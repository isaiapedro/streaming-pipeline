# Benchmark results and claim boundary

## Scope

These are deterministic, in-process results from synthetic scenarios, not a
clinical validation and not an end-to-end cloud latency study. The experiment
uses 25 fully crossed signal/noise seed cells per scenario and approach. The
stable-baseline observation is 24 simulated hours per seed cell. All three
approaches see the same generated observations in each cell.

An alarm episode opens with the first alarming scoring observation and closes
after ten continuously clear seconds. Detection requires a newly opened alarm
episode at or after the scenario's known onset. An alarm already active at
onset does not count as detecting that event.

## Main result

The experiment supports a trade-off, not a universal winner:

- Approach B detected every positive run (Wilson 95% CI 0.867–1.0). Its median
  scoring latency was about 30 seconds for sudden scenarios and 121 seconds for
  sepsis/COPD. It had the lowest negative-scenario burden, but still
  false-alarmed in 20% of transient-storm runs (95% CI 0.089–0.391) and every
  24-hour stable run (95% CI 0.867–1.0), with 40.08 stable episodes/day and
  5.16% of stable time in alarm.
- Approach C detected 80% of sepsis, cardiac, and hypertensive runs and every
  COPD run. Its median latency was about 67 seconds for sepsis, 111 seconds for
  COPD, and below 35 ms among detected sudden-event runs. It false-alarmed in
  every negative run (95% CI 0.867–1.0), with 567.48 stable episodes/day and
  19.55% of stable time in alarm.
- Approach A was already in alarm for 89% of stable-baseline time on average.
  Consequently, its newly-opened-episode detection rate was only 60% for
  sepsis/COPD and 20% for sudden cardiac/hypertensive scenarios, despite very
  short latency among the subset it detected. It false-alarmed in every
  negative run (95% CI 0.867–1.0).

The operational interpretation is that batching reduced episode burden and
achieved the most reliable event detection here, at the cost of detection
delay. Continuous composite scoring recovered latency but created much higher
burden and sometimes remained active across the true onset, so it cannot be
called universally superior. Per-signal thresholding produced an unacceptable
sustained-alarm baseline under this generator and threshold set.

## Quality caveats

- Run probabilities are not clinical TPR/FPR because each run contains a
  single labelled scenario rather than independently labelled clinical windows.
- Episode counts are analysis-layer alarm-state episodes, not notifications
  acknowledged by clinicians.
- A 24-hour random walk may drift unrealistically. Until comparison with an
  approved reference dataset is executed, the magnitude of the stable-baseline
  result establishes a model sensitivity, not a real-world alarm rate.
- Scoring latency excludes broker, network, and storage latency. The live
  protocol evidence is separate and only partially executed.
- The measurements were generated from a dirty worktree. The final manifest
  command now refuses this state and any dependency, matrix, duration, run-log,
  or input-hash inconsistency.

See `benchmark_aggregate.csv` for all estimates, dispersion, quartiles, and
confidence intervals; see `manifest.json` for provenance and execution status.
