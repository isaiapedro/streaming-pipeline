"""Deterministic clinical scenario trajectories for the benchmark suite.

Each scenario defines an additive delta, per signal, layered on top of the
baseline generator output — the generator still runs its normal stochastic
walk; the scenario only shifts its target. `onset_offset_ms` is the exact
ground-truth deterioration timestamp, which is what makes detection-latency
measurement possible (real bedside data has no such label).

Six scenarios per plan-detailed.md L1: sepsis, cardiac deterioration, COPD
exacerbation, false positive storm, hypertensive crisis, stable baseline.
"""

from dataclasses import dataclass


@dataclass
class Scenario:
    scenario_id: str
    description: str
    duration_s: float
    onset_offset_ms: int
    ramp_ms: int
    peak_deltas: dict            # signal_type -> peak additive delta
    shape: str                   # "ramp_sustained" | "step_sustained" | "spike_recover" | "none"
    recover_ms: int = 0          # used by "spike_recover"
    copd_flag_override: bool | None = None
    expect_alarm: bool = True    # ground truth: should a *correct* detector fire?

    def delta_at(self, elapsed_ms: int) -> dict:
        """Return {signal_type: delta} at `elapsed_ms` since scenario start."""
        if self.shape == "none" or elapsed_ms < self.onset_offset_ms:
            return {}

        t = elapsed_ms - self.onset_offset_ms

        if self.shape == "step_sustained":
            frac = 1.0
        elif self.shape == "ramp_sustained":
            frac = min(1.0, t / self.ramp_ms) if self.ramp_ms else 1.0
        elif self.shape == "spike_recover":
            if t <= self.ramp_ms:
                frac = (t / self.ramp_ms) if self.ramp_ms else 1.0
            elif t <= self.ramp_ms + self.recover_ms:
                frac = 1.0 - (t - self.ramp_ms) / self.recover_ms
            else:
                frac = 0.0
        else:
            raise ValueError(f"Unknown scenario shape: {self.shape}")

        return {sig: delta * frac for sig, delta in self.peak_deltas.items()}


SCENARIOS: dict[str, Scenario] = {
    "sepsis_progression": Scenario(
        scenario_id="sepsis_progression",
        description="Gradual sepsis ramp: HR up, RR up, SpO2 down, Temp up over ~5 min",
        duration_s=600,
        onset_offset_ms=60_000,
        ramp_ms=300_000,
        peak_deltas={"heart_rate": 35, "respiratory_rate": 10, "spo2": -6, "temperature": 1.8},
        shape="ramp_sustained",
    ),
    "cardiac_deterioration": Scenario(
        scenario_id="cardiac_deterioration",
        description="Sudden cardiac step: HR spikes, SpO2 drops sharply",
        duration_s=300,
        onset_offset_ms=90_000,
        ramp_ms=15_000,
        peak_deltas={"heart_rate": 45, "spo2": -12},
        shape="step_sustained",
    ),
    "copd_exacerbation": Scenario(
        scenario_id="copd_exacerbation",
        description="Gradual COPD exacerbation: RR up, SpO2 down, HR moderate rise",
        duration_s=600,
        onset_offset_ms=60_000,
        ramp_ms=240_000,
        peak_deltas={"respiratory_rate": 14, "spo2": -8, "heart_rate": 15},
        shape="ramp_sustained",
        copd_flag_override=True,
    ),
    "false_positive_storm": Scenario(
        scenario_id="false_positive_storm",
        description="Transient SpO2 dip that fully recovers within ~10s — should NOT alarm",
        duration_s=300,
        onset_offset_ms=120_000,
        ramp_ms=4_000,
        recover_ms=6_000,
        peak_deltas={"spo2": -9},
        shape="spike_recover",
        expect_alarm=False,
    ),
    "hypertensive_crisis": Scenario(
        scenario_id="hypertensive_crisis",
        description="Step + sustained hypertensive crisis: SysBP up sharply, HR up",
        duration_s=300,
        onset_offset_ms=90_000,
        ramp_ms=20_000,
        # SysBP must clear the NEWS2 >=220 emergency band (baseline 120 + 110 = 230);
        # a peak of only +70 (190) sits inside NEWS2's 111-219 "0 points" band, which
        # made the composite score cap at 4 and Approach B/C never alarm — a real
        # miscalibration bug found via the benchmark visualization notebook.
        peak_deltas={"systolic_bp": 110, "heart_rate": 45},
        shape="step_sustained",
    ),
    "stable_baseline": Scenario(
        scenario_id="stable_baseline",
        description="No injected event — physiological noise only",
        duration_s=600,
        onset_offset_ms=0,
        ramp_ms=0,
        peak_deltas={},
        shape="none",
        expect_alarm=False,
    ),
}
