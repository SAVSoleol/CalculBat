"""Dimensionnement par valeur marginale : heuristique énergétique, sans CAPEX caché.

La grille physique est fixe par mode. La fenêtre de lissage est exprimée en kWh,
et la référence de seuil est lissée de la même manière. Les seuils de cycles sont
des critères internes sur la capacité utile, pas des garanties constructeur.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np
import pandas as pd

MODE_SETTINGS = {
    "residential": {"label": "Résidentiel", "capacity": (5., 50., 1.), "power": (1., 20., 1.),
                    "efficiency": .92, "soc_min": 5., "c_rate": None, "cycles": 150., "window": 5.},
    "pme": {"label": "PME", "capacity": (50., 150., 5.), "power": (5., 100., 5.),
            "efficiency": .88, "soc_min": 5., "c_rate": .5, "cycles": 130., "window": 20.},
    "ci": {"label": "C&I / Industrie", "capacity": (150., 1000., 10.), "power": (20., 500., 10.),
           "efficiency": .80, "soc_min": 30., "c_rate": .5, "cycles": 100., "window": 50.},
}


@dataclass
class Recommendation:
    best: pd.Series
    frontier: pd.DataFrame
    max_gain_pick: pd.Series
    gain_max: float
    study_mode: str
    limiting_reason: str
    marginal_floor_chf_per_kwh: float
    selected_marginal_chf_per_kwh: float | None
    next_marginal_chf_per_kwh: float | None
    recommended_min_kWh: float
    recommended_max_kWh: float
    recommended: bool
    power_gain_share: float = .99
    warnings: list[tuple[str, dict]] = field(default_factory=list)
    notes: list[tuple[str, dict]] = field(default_factory=list)


def fixed_grid(low, high, step, anchor):
    """Fixed physical lattice plus the exact requested technical endpoints."""
    values = [float(low), float(high), float(step), float(anchor)]
    if not np.isfinite(values).all() or low <= 0 or high < low or step <= 0:
        raise ValueError("Limites techniques invalides.")
    first = anchor + np.ceil((low - anchor) / step) * step
    count = max(0, int(np.floor((high - first) / step)) + 1)
    if count > 10_000:
        raise ValueError("Trop de points de grille.")
    return sorted(set([float(low), float(high)] + np.round(first + np.arange(count) * step, 9).tolist()))


def best_per_capacity(results, power_gain_share=.99):
    if not 0 < power_gain_share <= 1:
        raise ValueError("Part de gain cible attendue entre 0 et 1.")
    rows = []
    for _, group in results.groupby("Cap_kWh", sort=True):
        gain_max = float(group.Gain_CHF.max())
        target = gain_max * power_gain_share if gain_max > 0 else gain_max
        options = group[group.Gain_CHF >= target - 1e-9].sort_values(["Power_kW", "Gain_CHF"], ascending=[True, False])
        row = options.iloc[0].copy()
        row["Max_gain_at_capacity_CHF"] = gain_max
        rows.append(row)
    return pd.DataFrame(rows).reset_index(drop=True)


def _marginal_diagnostics(frontier, window_kwh=5., relative_factor=.30):
    f = frontier.sort_values("Cap_kWh").reset_index(drop=True).copy()
    x = f.Cap_kWh.to_numpy(float)
    raw = f.Max_gain_at_capacity_CHF.to_numpy(float)
    y = np.maximum.accumulate(raw)
    right = np.minimum(x + window_kwh, x[-1])
    dx = right - x
    forward = np.divide(np.interp(right, x, y) - y, dx, out=np.full(len(x), np.nan), where=dx > 1e-9)
    # Same window for both the strongest marginal value and the stopping criterion.
    full = dx >= window_kwh - 1e-9
    reference = forward[full] if full.any() else forward[np.isfinite(forward)]
    peak = max(0., float(reference.max())) if len(reference) else 0.
    floor = peak * relative_factor
    f["Gain_envelope_CHF"] = y
    f["Forward_marginal_CHF_per_kWh"] = forward
    f["Marginal_floor_CHF_per_kWh"] = floor
    return f, floor


def recommend(results, *, study_mode="residential", min_cycles_per_year=None,
              power_gain_share=.99, marginal_relative_floor=.30, window_kwh=None,
              minimum_annual_saving_chf=10.):
    required = ["Cap_kWh", "Power_kW", "Gain_CHF", "Cycles_per_year"]
    if results.empty or any(c not in results for c in required):
        raise ValueError("Aucun résultat exploitable pour le dimensionnement.")
    if study_mode not in MODE_SETTINGS:
        raise ValueError("Mode d'étude inconnu.")
    numeric = results[["Cap_kWh", "Power_kW", "Gain_CHF"]].to_numpy(float)
    if not np.isfinite(numeric).all() or (numeric[:, :2] <= 0).any():
        raise ValueError("Résultats non finis ou capacités/puissances invalides.")
    settings = MODE_SETTINGS[study_mode]
    window = settings["window"] if window_kwh is None else float(window_kwh)
    min_cycles = settings["cycles"] if min_cycles_per_year is None else float(min_cycles_per_year)
    if not np.isfinite([window, min_cycles, marginal_relative_floor, minimum_annual_saving_chf]).all() or (
            window <= 0 or min_cycles < 0 or minimum_annual_saving_chf < 0 or not 0 < marginal_relative_floor <= 1):
        raise ValueError("Seuils de dimensionnement invalides.")
    frontier = best_per_capacity(results, power_gain_share)
    f, floor = _marginal_diagnostics(frontier, window, marginal_relative_floor)
    best_max = results.sort_values(["Gain_CHF", "Cap_kWh", "Power_kW"], ascending=[False, True, True]).iloc[0]
    gain_max = float(best_max.Gain_CHF)
    warnings, notes = [], []
    annual_known = np.isfinite(f.Cycles_per_year.to_numpy(float)).all()
    eligible = f.Cycles_per_year >= min_cycles if annual_known else pd.Series(True, index=f.index)
    if not annual_known:
        warnings.append(("cycles_unavailable", {}))
    if gain_max <= 1e-9:
        chosen = 0
        reason = "no_savings"
        warnings.append(("no_savings", {}))
        recommended = False
    elif not eligible.any():
        chosen = int(f.Cycles_per_year.idxmax())
        reason = "no_cycle_candidate"
        warnings.append(("no_healthy", {"cycles_low": min_cycles}))
        recommended = False
    else:
        # Stop on diminishing returns, but examine ALL cycle-eligible capacities.
        indices = f.index[eligible].tolist()
        chosen = indices[-1]
        reason = "upper_bound"
        for i in indices:
            forward = f.loc[i, "Forward_marginal_CHF_per_kWh"]
            if np.isfinite(forward) and (forward <= 1e-9 or forward < floor):
                chosen = i
                reason = "marginal_value"
                break
        if chosen == indices[-1] and indices[-1] < len(f) - 1 and reason == "upper_bound":
            reason = "cycles"
        recommended = True
    best = f.loc[chosen].copy()
    if best.Gain_CHF <= 1e-9:
        recommended = False
        if reason != "no_savings":
            warnings.append(("no_savings", {}))
    annual_gain = pd.to_numeric(pd.Series([best.get("Gain_annual_CHF")]), errors="coerce").iloc[0]
    if pd.notna(annual_gain) and annual_gain < minimum_annual_saving_chf:
        warnings.append(("negligible_gain", {"threshold": minimum_annual_saving_chf}))
        recommended = False
    if chosen == len(f) - 1 and reason != "no_savings":
        warnings.append(("upper_bound", {}))
    if chosen == 0 and reason != "no_savings":
        warnings.append(("lower_bound", {}))
    if (np.diff(f.Max_gain_at_capacity_CHF) < -1e-6).any():
        warnings.append(("non_monotone", {}))
    if annual_known and eligible.any():
        notes.append(("cycles_definition", {"cycles_low": min_cycles}))
    notes.append(("heuristic", {"window": window, "floor": 100 * marginal_relative_floor,
                                 "power_share": 100 * power_gain_share}))
    # Neighbouring grid points are not commercial battery modules: no invented offer range.
    marginal = best.Forward_marginal_CHF_per_kWh
    next_value = f.loc[chosen + 1, "Forward_marginal_CHF_per_kWh"] if chosen + 1 < len(f) else np.nan
    return Recommendation(best, f, best_max, gain_max, study_mode, reason, floor,
        float(marginal) if np.isfinite(marginal) else None,
        float(next_value) if np.isfinite(next_value) else None,
        float(best.Cap_kWh), float(best.Cap_kWh), recommended, power_gain_share, warnings, notes)
