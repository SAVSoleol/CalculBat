"""Battery recommendation based on tariff value and diminishing marginal returns.

The physical and financial simulation is performed in simulation.py. This module then:
1. keeps the best power for each battery capacity;
2. calculates the extra annual saving delivered by each added kWh;
3. stops when the next added capacity no longer delivers enough annual value;
4. verifies that the selected battery still reaches the internal cycle floor.

Swissolar remains a separate plausibility reference in app.py. It does not directly force
or cap the simulated recommendation.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

Msg = tuple[str, dict]

CYCLES_HEALTHY_LOW = 250.0
CYCLES_HEALTHY_HIGH = 300.0
CYCLES_OVERSIZED_BELOW = 150.0

MODE_CYCLES_LOW = {
    "residential": 150.0,
    "autoconsommation": 150.0,
    "pme": 130.0,
    "ci": 100.0,
    "c&i": 100.0,
    "industrie": 100.0,
    "industrial": 100.0,
    "c_i": 100.0,
}


@dataclass(frozen=True)
class BrandSpec:
    key: str
    name: str
    cycles_low: float
    cycles_high: float
    oversized_below: float
    design_cycles_yr: float
    sources: tuple[tuple[str, str], ...]


GOODWE = BrandSpec(
    key="goodwe",
    name="GoodWe Lynx D (GW8.3-BAT)",
    cycles_low=250.0,
    cycles_high=350.0,
    oversized_below=150.0,
    design_cycles_yr=1000.0,
    sources=(),
)

HUAWEI = BrandSpec(
    key="huawei",
    name="Huawei (LUNA2000)",
    cycles_low=250.0,
    cycles_high=300.0,
    oversized_below=150.0,
    design_cycles_yr=263.0,
    sources=(),
)

BRANDS: dict[str, BrandSpec] = {GOODWE.key: GOODWE, HUAWEI.key: HUAWEI}
DEFAULT_BRAND = GOODWE


@dataclass
class Recommendation:
    best: pd.Series
    frontier: pd.DataFrame
    max_gain_pick: pd.Series
    gain_max: float
    knee_capacity_kWh: float | None = None
    knee_gain_chf: float | None = None
    knee_method: str = "marginal_value"
    study_mode: str = "autoconsommation"
    recommended_min_kWh: float | None = None
    recommended_max_kWh: float | None = None
    recommendation_score: float | None = None
    marginal_floor_chf_per_kwh: float | None = None
    selected_marginal_chf_per_kwh: float | None = None
    next_marginal_chf_per_kwh: float | None = None
    limiting_reason: str | None = None
    warnings: list[Msg] = field(default_factory=list)
    notes: list[Msg] = field(default_factory=list)


def _best_per_capacity(results: pd.DataFrame) -> pd.DataFrame:
    """Return the highest-gain power option for each tested capacity."""
    idx = results.groupby("Cap_kWh")["Gain_CHF"].idxmax()
    return results.loc[idx].sort_values("Cap_kWh").reset_index(drop=True)


def _marginal_diagnostics(frontier: pd.DataFrame, mode: str, absolute_floor: float = 0.0) -> tuple[pd.DataFrame, float]:
    """Calculate gain delivered by every additional kWh and the stopping threshold.

    The threshold is relative to the client curve: 30% of the strongest observed
    marginal gain. This avoids a fixed CHF threshold that would behave differently
    for small and large projects. A two-step forward average prevents one noisy
    capacity step from moving the result.
    """
    f = frontier.sort_values("Cap_kWh").reset_index(drop=True).copy()
    f["Gain_mono"] = f["Gain_CHF"].cummax()

    dcap = f["Cap_kWh"].diff()
    f["Marginal_CHF_per_kWh"] = (f["Gain_mono"].diff() / dcap).replace([np.inf, -np.inf], np.nan)

    valid = f["Marginal_CHF_per_kWh"].dropna().clip(lower=0.0)
    peak = float(valid.max()) if not valid.empty else 0.0
    relative_factor = 0.30
    floor = peak * relative_factor

    # Value of capacity added AFTER the current row.
    next_1 = f["Marginal_CHF_per_kWh"].shift(-1)
    next_2 = f["Marginal_CHF_per_kWh"].shift(-2)
    f["Forward_marginal_2step"] = pd.concat([next_1, next_2], axis=1).mean(axis=1, skipna=True)
    f["Marginal_floor_CHF_per_kWh"] = floor
    f["Marginal_peak_CHF_per_kWh"] = peak
    f["Marginal_relative"] = (f["Marginal_CHF_per_kWh"] / peak).clip(lower=0.0) if peak > 0 else 0.0
    f["Forward_marginal_relative_2step"] = (f["Forward_marginal_2step"] / peak).clip(lower=0.0) if peak > 0 else 0.0
    return f, floor


def _marginal_pick(
    frontier: pd.DataFrame,
    mode: str,
    min_cycles: float,
    absolute_floor: float,
) -> tuple[pd.Series, pd.DataFrame, float, str]:
    """Select the last capacity before added kWh lose sufficient annual value."""
    f, floor = _marginal_diagnostics(frontier, mode, absolute_floor)
    if f.empty:
        raise ValueError("frontier is empty")

    min_cycles = max(0.0, float(min_cycles))
    cycle_ok = f["Cycles_per_year"] >= min_cycles

    # Start from the smallest tested capacity and stop before the first capacity for
    # which the following one/two kWh fall below the marginal-value threshold.
    chosen_idx = int(f.index[0])
    reason = "marginal_value"
    for i in range(len(f)):
        if not bool(cycle_ok.iloc[i]):
            reason = "cycles"
            break

        chosen_idx = i
        forward = f.loc[i, "Forward_marginal_2step"]
        if pd.notna(forward) and float(forward) < floor:
            reason = "marginal_value"
            break

    # Never retain a capacity below the cycle floor when a smaller eligible row exists.
    eligible_idx = f.index[cycle_ok].tolist()
    if eligible_idx:
        chosen_idx = min(chosen_idx, max(eligible_idx))
    else:
        chosen_idx = int(f["Cycles_per_year"].idxmax())
        reason = "no_cycle_candidate"

    chosen = f.loc[chosen_idx]
    cap = float(chosen["Cap_kWh"])
    source_row = frontier.loc[np.isclose(frontier["Cap_kWh"], cap)].iloc[0]
    return source_row, f, floor, reason


def _offer_range(
    diagnostics: pd.DataFrame,
    selected_cap: float,
    min_cycles: float,
    marginal_floor: float,
) -> tuple[float, float]:
    """Build a practical range of one module below/above the central result.

    The adjacent capacity is included only when it remains technically eligible and its
    marginal value is not completely collapsed. This produces ranges such as 10-12 kWh
    around an 11 kWh central result, without extending into the flat tail of the curve.
    """
    f = diagnostics.sort_values("Cap_kWh").reset_index(drop=True)
    matches = f.index[np.isclose(f["Cap_kWh"], float(selected_cap))].tolist()
    if not matches:
        return float(selected_cap), float(selected_cap)

    i = int(matches[0])
    lo = hi = float(selected_cap)
    min_cycles = max(0.0, float(min_cycles))

    if i > 0:
        prev = f.iloc[i - 1]
        if float(prev["Cycles_per_year"]) >= min_cycles:
            lo = float(prev["Cap_kWh"])

    if i + 1 < len(f):
        nxt = f.iloc[i + 1]
        nxt_marg = float(nxt["Marginal_CHF_per_kWh"]) if pd.notna(nxt["Marginal_CHF_per_kWh"]) else 0.0
        if float(nxt["Cycles_per_year"]) >= min_cycles and nxt_marg >= 0.60 * marginal_floor:
            hi = float(nxt["Cap_kWh"])

    return lo, hi


def _ci_pick(frontier: pd.DataFrame, gain_max: float, cycles_low: float, gain_share: float = 0.95) -> pd.Series:
    """Keep the existing saturation logic for C&I studies."""
    f = frontier.sort_values("Cap_kWh").reset_index(drop=True).copy()
    f["Gain_mono"] = f["Gain_CHF"].cummax()
    candidates = f[f["Gain_mono"] >= float(gain_max) * float(gain_share)]
    if candidates.empty:
        return f.loc[f["Gain_CHF"].idxmax()]
    healthy = candidates[candidates["Cycles_per_year"] >= float(cycles_low)]
    return healthy.iloc[0] if not healthy.empty else candidates.iloc[0]


def recommend(
    results: pd.DataFrame,
    gain_threshold: float = 0.90,
    cycles_low: float | None = None,
    coverage_days: float | None = None,
    brand: BrandSpec = DEFAULT_BRAND,
    marginal_gain_floor_chf_per_kwh: float = 5.0,
    knee_window_kwh: float = 5.0,
    min_gain_share: float = 0.85,
    study_mode: str = "autoconsommation",
    ci_gain_share: float = 0.95,
    min_cycles_per_year: float = 0.0,
) -> Recommendation:
    """Recommend a battery using marginal annual value rather than a geometric knee."""
    if results.empty:
        raise ValueError("results table is empty.")

    warnings: list[Msg] = []
    notes: list[Msg] = []
    mode = str(study_mode or "autoconsommation").lower()
    frontier_raw = _best_per_capacity(results)

    max_gain_pick = results.sort_values(
        ["Gain_CHF", "Cap_kWh", "Power_kW"], ascending=[False, True, True]
    ).iloc[0]
    gain_max = float(max_gain_pick["Gain_CHF"])

    if cycles_low is None:
        cycles_low = MODE_CYCLES_LOW.get(mode, brand.cycles_low)
    min_cycles = max(0.0, float(min_cycles_per_year or cycles_low))

    if gain_max <= 0:
        best = frontier_raw.iloc[0]
        diagnostics, marginal_floor = _marginal_diagnostics(
            frontier_raw, mode, marginal_gain_floor_chf_per_kwh
        )
        reason = "no_savings"
        warnings.append(("no_savings", {}))
    elif mode in {"ci", "c&i", "industrie", "industrial", "c_i"}:
        best = _ci_pick(frontier_raw, gain_max, min_cycles, ci_gain_share)
        diagnostics, marginal_floor = _marginal_diagnostics(
            frontier_raw, mode, marginal_gain_floor_chf_per_kwh
        )
        reason = "ci_saturation"
    else:
        best, diagnostics, marginal_floor, reason = _marginal_pick(
            frontier_raw,
            mode=mode,
            min_cycles=min_cycles,
            absolute_floor=marginal_gain_floor_chf_per_kwh,
        )

    selected_cap = float(best["Cap_kWh"])
    rec_min = rec_max = selected_cap
    if mode not in {"ci", "c&i", "industrie", "industrial", "c_i"}:
        rec_min, rec_max = _offer_range(diagnostics, selected_cap, min_cycles, marginal_floor)

    row_idx = diagnostics.index[np.isclose(diagnostics["Cap_kWh"], selected_cap)].tolist()
    selected_marginal = None
    next_marginal = None
    if row_idx:
        i = int(row_idx[0])
        val = diagnostics.loc[i, "Marginal_CHF_per_kWh"]
        selected_marginal = float(val) if pd.notna(val) else None
        if i + 1 < len(diagnostics):
            val2 = diagnostics.loc[i + 1, "Marginal_CHF_per_kWh"]
            next_marginal = float(val2) if pd.notna(val2) else None

    cyc = float(best.get("Cycles_per_year", 0.0))
    band = {"low": float(min_cycles), "high": float(brand.cycles_high)}
    if cyc < min_cycles:
        warnings.append(("no_healthy", {"cycles_low": min_cycles, "cyc": cyc}))
    elif cyc <= brand.cycles_high:
        notes.append(("within_band", {"cyc": cyc, **band}))
    else:
        notes.append(("above_band", {"cyc": cyc, **band}))

    peak_marginal = float(diagnostics["Marginal_peak_CHF_per_kWh"].iloc[0]) if not diagnostics.empty else 0.0
    next_ratio = (float(next_marginal or 0.0) / peak_marginal) if peak_marginal > 0 else 0.0
    notes.append(("marginal_stop", {
        "relative_floor": 0.30,
        "next_ratio": next_ratio,
        "next": float(next_marginal or 0.0),
    }))

    if coverage_days is not None and coverage_days < 360:
        warnings.append(("partial_year", {"days": float(coverage_days)}))

    return Recommendation(
        best=best,
        frontier=diagnostics,
        max_gain_pick=max_gain_pick,
        gain_max=gain_max,
        knee_capacity_kWh=None,
        knee_gain_chf=None,
        knee_method="marginal_value",
        study_mode=mode,
        recommended_min_kWh=rec_min,
        recommended_max_kWh=rec_max,
        recommendation_score=float(best["Gain_CHF"] / gain_max) if gain_max > 0 else None,
        marginal_floor_chf_per_kwh=float(marginal_floor),
        selected_marginal_chf_per_kwh=selected_marginal,
        next_marginal_chf_per_kwh=next_marginal,
        limiting_reason=reason,
        warnings=warnings,
        notes=notes,
    )


if __name__ == "__main__":
    print("recommend.py OK")
