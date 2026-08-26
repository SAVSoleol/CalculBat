"""Battery dispatch simulation + (cap, power) grid search.

Dispatch model:
  per interval, charge the battery from solar surplus, then discharge it to cover grid import,
  respecting capacity, power and round-trip efficiency.

Financial model:
  The recommendation should be driven by tariff value, not battery price:
      gain = import avoided at high tariff
           + import avoided at low tariff
           - export/sale revenue lost because this surplus was stored.

Cycle definition:
  equivalent_full_cycles = total energy discharged to load / usable battery capacity.
  usable capacity = nameplate capacity x (1 - SOC_min).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

try:
    from numba import njit

    HAS_NUMBA = True
except Exception:  # pragma: no cover
    HAS_NUMBA = False

    def njit(*args, **kwargs):
        def _wrap(fn):
            return fn

        return _wrap(args[0]) if args and callable(args[0]) else _wrap


@njit(cache=True)
def _dispatch(imp, exp, capacity, power_per_step, eta):
    """Inner loop. Returns import/export after battery, SOC, total charge, total discharge."""
    n = imp.shape[0]
    imp_after = np.empty(n)
    exp_after = np.empty(n)
    soc = np.empty(n)

    soc_val = 0.0
    charge_tot = 0.0
    discharge_tot = 0.0

    for i in range(n):
        # Charge from surplus
        charge_i = exp[i]
        if charge_i > power_per_step:
            charge_i = power_per_step

        max_charge = (capacity - soc_val) / eta
        if charge_i > max_charge:
            charge_i = max_charge
        if charge_i < 0.0:
            charge_i = 0.0

        soc_val += charge_i * eta
        exp_after[i] = exp[i] - charge_i
        charge_tot += charge_i

        # Discharge to cover grid import
        discharge_i = imp[i]
        if discharge_i > power_per_step:
            discharge_i = power_per_step

        max_discharge = soc_val * eta
        if discharge_i > max_discharge:
            discharge_i = max_discharge
        if discharge_i < 0.0:
            discharge_i = 0.0

        soc_val -= discharge_i / eta
        imp_after[i] = imp[i] - discharge_i
        discharge_tot += discharge_i

        soc[i] = soc_val

    return imp_after, exp_after, soc, charge_tot, discharge_tot


@njit(cache=True)
def _dispatch_peak_shaving(imp, exp, capacity, power_per_step, eta, dt_hours, peak_target_kw, reserve_fraction, grid_recharge):
    """Combined self-consumption + peak-shaving dispatch.

    Priority:
    1) charge from PV surplus;
    2) shave import above ``peak_target_kw`` using all available SOC;
    3) use only SOC above the configured reserve for ordinary self-consumption.

    Optional controlled grid charging can maintain the peak-shaving reserve without
    exceeding the configured grid-power target.
    """
    n = imp.shape[0]
    imp_after = np.empty(n)
    exp_after = np.empty(n)
    soc = np.empty(n)

    reserve_energy = capacity * reserve_fraction
    # A C&I peak-shaving controller normally starts with its reserve available.
    # This avoids making the result depend on the arbitrary first timestamp of the file.
    soc_val = reserve_energy
    charge_tot = 0.0
    discharge_tot = 0.0
    peak_step = peak_target_kw * dt_hours

    for i in range(n):
        charge_i = exp[i]
        if charge_i > power_per_step:
            charge_i = power_per_step
        max_charge = (capacity - soc_val) / eta
        if charge_i > max_charge:
            charge_i = max_charge
        if charge_i < 0.0:
            charge_i = 0.0

        soc_val += charge_i * eta
        exp_after[i] = exp[i] - charge_i
        charge_tot += charge_i

        # Keep the reserve topped up from the grid when there is headroom below the
        # target. This is not energy arbitrage: grid charging stops at the reserve
        # level and never creates a new peak above the configured target.
        grid_charge_i = 0.0
        if grid_recharge and soc_val < reserve_energy and imp[i] < peak_step:
            headroom = peak_step - imp[i]
            missing_input = (reserve_energy - soc_val) / eta
            grid_charge_i = headroom
            if grid_charge_i > power_per_step:
                grid_charge_i = power_per_step
            if grid_charge_i > missing_input:
                grid_charge_i = missing_input
            if grid_charge_i < 0.0:
                grid_charge_i = 0.0
            soc_val += grid_charge_i * eta

        import_with_grid_charge = imp[i] + grid_charge_i

        # First priority: shave the part of the interval above the target.
        peak_need = import_with_grid_charge - peak_step
        if peak_need < 0.0:
            peak_need = 0.0
        if peak_need > power_per_step:
            peak_need = power_per_step

        max_discharge_full = soc_val * eta
        discharge_peak = peak_need
        if discharge_peak > max_discharge_full:
            discharge_peak = max_discharge_full

        soc_val -= discharge_peak / eta
        remaining_import = import_with_grid_charge - discharge_peak

        # Second priority: ordinary self-consumption, but preserve the reserve.
        normal_power_left = power_per_step - discharge_peak
        available_above_reserve = soc_val - reserve_energy
        if available_above_reserve < 0.0:
            available_above_reserve = 0.0
        normal_soc_available = available_above_reserve * eta

        discharge_normal = remaining_import
        if discharge_normal > normal_power_left:
            discharge_normal = normal_power_left
        if discharge_normal > normal_soc_available:
            discharge_normal = normal_soc_available
        if discharge_normal < 0.0:
            discharge_normal = 0.0

        soc_val -= discharge_normal / eta
        discharge_i = discharge_peak + discharge_normal
        imp_after[i] = import_with_grid_charge - discharge_i
        discharge_tot += discharge_i
        soc[i] = soc_val

    return imp_after, exp_after, soc, charge_tot, discharge_tot


@dataclass
class SimResult:
    capacity_kWh: float
    power_kW: float

    soc: np.ndarray
    import_after: np.ndarray
    export_after: np.ndarray

    import_before: float
    export_before: float

    import_avoided: float
    import_avoided_ht: float
    import_avoided_bt: float

    export_stored: float

    gain_chf: float
    gain_ht_chf: float
    gain_bt_chf: float
    export_value_lost_chf: float

    peak_shaving_enabled: bool
    peak_target_kW: float | None
    peak_reserve_pct: float
    peak_before_kW: float
    peak_after_kW: float
    peak_reduction_kW: float
    peak_savings_chf: float
    peak_billing_mode: str
    peak_power_tariff_chf_per_kw_month: float

    cycles_per_year: float
    usable_capacity_kWh: float
    soc_min_pct: float
    charge_total_kWh: float
    discharge_total_kWh: float

    surplus_captured: float
    import_reduction: float

    @property
    def import_after_total(self) -> float:
        return float(self.import_after.sum())

    @property
    def export_after_total(self) -> float:
        return float(self.export_after.sum())


def _as_datetime_index(timestamps) -> pd.DatetimeIndex | None:
    if timestamps is None:
        return None
    try:
        idx = pd.to_datetime(timestamps, errors="coerce")
        if len(idx) == 0 or pd.isna(idx).all():
            return None
        return pd.DatetimeIndex(idx)
    except Exception:
        return None


def _is_high_tariff(ts: pd.Timestamp, high_tariff_periods, weekend_low_tariff: bool) -> bool:
    if pd.isna(ts):
        return True

    if weekend_low_tariff and ts.weekday() >= 5:
        return False

    hour = ts.hour + ts.minute / 60.0 + ts.second / 3600.0
    for start, end in high_tariff_periods:
        # Normal same-day window, e.g. 07:00 -> 22:00
        if start <= end:
            if start <= hour < end:
                return True
        # Overnight window, e.g. 22:00 -> 06:00
        else:
            if hour >= start or hour < end:
                return True

    return False


def _tariff_vectors(
    n: int,
    timestamps=None,
    tariff_import: float = 0.32,
    tariff_import_ht: float | None = None,
    tariff_import_bt: float | None = None,
    high_tariff_periods=((7.0, 22.0),),
    weekend_low_tariff: bool = False,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return tariff vector and boolean masks for HT/BT.

    Backward-compatible behaviour:
    - if timestamps are not supplied, all intervals use `tariff_import`;
    - if HT/BT are not supplied, they fall back to `tariff_import`.
    """

    if tariff_import_ht is None:
        tariff_import_ht = tariff_import
    if tariff_import_bt is None:
        tariff_import_bt = tariff_import

    idx = _as_datetime_index(timestamps)

    # Existing app.py currently passes only arrays, not timestamps.
    # In that case we preserve the old single-tariff behaviour.
    if idx is None or len(idx) != n:
        tariffs = np.full(n, float(tariff_import), dtype=np.float64)
        ht_mask = np.ones(n, dtype=bool)
        bt_mask = np.zeros(n, dtype=bool)
        return tariffs, ht_mask, bt_mask

    ht_mask = np.array(
        [_is_high_tariff(ts, high_tariff_periods, weekend_low_tariff) for ts in idx],
        dtype=bool,
    )
    bt_mask = ~ht_mask

    tariffs = np.where(ht_mask, float(tariff_import_ht), float(tariff_import_bt)).astype(np.float64)
    return tariffs, ht_mask, bt_mask



def _peak_power_savings(
    imp: np.ndarray,
    imp_after: np.ndarray,
    dt_hours: float,
    timestamps,
    tariff_chf_per_kw_month: float,
    billing_mode: str,
) -> tuple[float, float, float, float]:
    """Return annual peak-power saving and peak diagnostics.

    billing_mode:
    - "annual_band": the highest 15-min demand of the analysed year defines one
      billed power band for the whole year. Saving = reduced annual peak x tariff x 12.
    - "monthly_max": each month's maximum demand is billed independently.

    The tariff input remains in CHF/kW/month in both modes.
    """
    if len(imp) == 0 or dt_hours <= 0:
        return 0.0, 0.0, 0.0, 0.0

    before_kw = np.asarray(imp, dtype=float) / float(dt_hours)
    after_kw = np.asarray(imp_after, dtype=float) / float(dt_hours)

    peak_before_kw = float(np.max(before_kw))
    peak_after_kw = float(np.max(after_kw))
    peak_reduction_kw = max(0.0, peak_before_kw - peak_after_kw)

    tariff = max(0.0, float(tariff_chf_per_kw_month))
    mode = str(billing_mode or "annual_band").lower()

    if tariff <= 0:
        return 0.0, peak_before_kw, peak_after_kw, peak_reduction_kw

    if mode == "annual_band":
        saving = peak_reduction_kw * tariff * 12.0
        return float(saving), peak_before_kw, peak_after_kw, peak_reduction_kw

    idx = _as_datetime_index(timestamps)
    if idx is None or len(idx) != len(imp):
        return 0.0, peak_before_kw, peak_after_kw, peak_reduction_kw

    monthly = pd.DataFrame({
        "month": idx.to_period("M"),
        "before_kw": before_kw,
        "after_kw": after_kw,
    })
    monthly_peaks = monthly.groupby("month")[["before_kw", "after_kw"]].max()
    monthly_reduction = (
        monthly_peaks["before_kw"] - monthly_peaks["after_kw"]
    ).clip(lower=0.0)
    saving = float(monthly_reduction.sum() * tariff)
    return saving, peak_before_kw, peak_after_kw, peak_reduction_kw

def simulate(
    import_kWh: np.ndarray,
    export_kWh: np.ndarray,
    capacity_kWh: float,
    power_kW: float,
    dt_hours: float,
    roundtrip_eff: float,
    tariff_import: float,
    tariff_export: float,
    coverage_days: float | None = None,
    soc_min_pct: float = 5.0,
    timestamps=None,
    tariff_import_ht: float | None = None,
    tariff_import_bt: float | None = None,
    high_tariff_periods=((7.0, 22.0),),
    weekend_low_tariff: bool = False,
    peak_shaving_enabled: bool = False,
    peak_target_kW: float | None = None,
    peak_power_tariff_chf_per_kw_month: float = 0.0,
    peak_billing_mode: str = "annual_band",
    peak_reserve_pct: float = 30.0,
    peak_grid_recharge: bool = True,
) -> SimResult:
    """Run one battery simulation.

    Financial gain is calculated from avoided import at the interval tariff minus the
    export revenue lost when surplus is stored instead of sold.
    """

    imp = np.ascontiguousarray(import_kWh, dtype=np.float64)
    exp = np.ascontiguousarray(export_kWh, dtype=np.float64)

    if imp.shape[0] != exp.shape[0]:
        raise ValueError("import_kWh and export_kWh must have the same length.")

    eta = float(np.sqrt(roundtrip_eff))
    power_per_step = float(power_kW * dt_hours)

    usable_capacity_kWh = float(capacity_kWh) * (1.0 - float(soc_min_pct) / 100.0)
    usable_capacity_kWh = max(usable_capacity_kWh, 0.0)

    peak_active = bool(peak_shaving_enabled and peak_target_kW is not None and float(peak_target_kW) >= 0.0)
    if peak_active:
        reserve_fraction = min(max(float(peak_reserve_pct) / 100.0, 0.0), 1.0)
        imp_after, exp_after, soc, charge_tot, discharge_tot = _dispatch_peak_shaving(
            imp, exp, usable_capacity_kWh, power_per_step, eta, float(dt_hours),
            float(peak_target_kW), reserve_fraction, bool(peak_grid_recharge)
        )
    else:
        imp_after, exp_after, soc, charge_tot, discharge_tot = _dispatch(
            imp, exp, usable_capacity_kWh, power_per_step, eta
        )

    avoided_by_interval = imp - imp_after
    stored_by_interval = exp - exp_after

    tariffs, ht_mask, bt_mask = _tariff_vectors(
        len(imp),
        timestamps=timestamps,
        tariff_import=tariff_import,
        tariff_import_ht=tariff_import_ht,
        tariff_import_bt=tariff_import_bt,
        high_tariff_periods=high_tariff_periods,
        weekend_low_tariff=weekend_low_tariff,
    )

    import_avoided_ht = float(avoided_by_interval[ht_mask].sum())
    import_avoided_bt = float(avoided_by_interval[bt_mask].sum())

    gain_import = float((avoided_by_interval * tariffs).sum())
    export_value_lost = float(stored_by_interval.sum() * tariff_export)

    peak_savings_chf, peak_before_kw, peak_after_kw, peak_reduction_kw = _peak_power_savings(
        imp,
        imp_after,
        dt_hours,
        timestamps,
        peak_power_tariff_chf_per_kw_month,
        peak_billing_mode,
    ) if peak_active else (
        0.0,
        float(imp.max() / dt_hours) if len(imp) and dt_hours > 0 else 0.0,
        float(imp_after.max() / dt_hours) if len(imp_after) and dt_hours > 0 else 0.0,
        max(
            0.0,
            (float(imp.max() / dt_hours) if len(imp) and dt_hours > 0 else 0.0)
            - (float(imp_after.max() / dt_hours) if len(imp_after) and dt_hours > 0 else 0.0),
        ),
    )

    gain = gain_import - export_value_lost + peak_savings_chf

    gain_ht = float(import_avoided_ht * (tariff_import_ht if tariff_import_ht is not None else tariff_import))
    gain_bt = float(import_avoided_bt * (tariff_import_bt if tariff_import_bt is not None else tariff_import))

    import_before = float(imp.sum())
    export_before = float(exp.sum())
    import_avoided = float(discharge_tot)
    export_stored = float(charge_tot)

    days = coverage_days if coverage_days and coverage_days > 0 else len(imp) * dt_hours / 24.0
    cycles_total = discharge_tot / usable_capacity_kWh if usable_capacity_kWh > 0 else 0.0
    cycles_per_year = cycles_total * 365.0 / days if days > 0 else 0.0

    surplus_captured = (export_stored / export_before) if export_before > 0 else 0.0
    import_reduction = (import_avoided / import_before) if import_before > 0 else 0.0

    return SimResult(
        capacity_kWh=float(capacity_kWh),
        power_kW=float(power_kW),
        soc=soc,
        import_after=imp_after,
        export_after=exp_after,
        import_before=import_before,
        export_before=export_before,
        import_avoided=import_avoided,
        import_avoided_ht=import_avoided_ht,
        import_avoided_bt=import_avoided_bt,
        export_stored=export_stored,
        gain_chf=float(gain),
        gain_ht_chf=float(gain_ht),
        gain_bt_chf=float(gain_bt),
        export_value_lost_chf=export_value_lost,
        peak_shaving_enabled=peak_active,
        peak_target_kW=float(peak_target_kW) if peak_active else None,
        peak_reserve_pct=float(peak_reserve_pct),
        peak_before_kW=peak_before_kw,
        peak_after_kW=peak_after_kw,
        peak_reduction_kW=peak_reduction_kw,
        peak_savings_chf=peak_savings_chf,
        peak_billing_mode=str(peak_billing_mode),
        peak_power_tariff_chf_per_kw_month=float(peak_power_tariff_chf_per_kw_month),
        cycles_per_year=float(cycles_per_year),
        usable_capacity_kWh=float(usable_capacity_kWh),
        soc_min_pct=float(soc_min_pct),
        charge_total_kWh=float(charge_tot),
        discharge_total_kWh=float(discharge_tot),
        surplus_captured=float(surplus_captured),
        import_reduction=float(import_reduction),
    )


def grid_search(
    import_kWh: np.ndarray,
    export_kWh: np.ndarray,
    caps: Iterable,
    powers: Iterable,
    dt_hours: float,
    roundtrip_eff: float,
    tariff_import: float,
    tariff_export: float,
    coverage_days: float | None = None,
    soc_min_pct: float = 5.0,
    timestamps=None,
    tariff_import_ht: float | None = None,
    tariff_import_bt: float | None = None,
    high_tariff_periods=((7.0, 22.0),),
    weekend_low_tariff: bool = False,
    max_c_rate: float | None = None,
    peak_shaving_enabled: bool = False,
    peak_target_kW: float | None = None,
    peak_power_tariff_chf_per_kw_month: float = 0.0,
    peak_billing_mode: str = "annual_band",
    peak_reserve_pct: float = 30.0,
    peak_grid_recharge: bool = True,
) -> pd.DataFrame:
    """Simulate every valid (capacity, power) pair.

    If max_c_rate is set, combinations above Power_kW = Cap_kWh * max_c_rate
    are excluded from the search. Example: max_c_rate=0.5 enforces a 0.5C battery.

    Returns a table with total tariff-based gain and the underlying HT/BT components.
    """

    imp = np.ascontiguousarray(import_kWh, dtype=np.float64)
    exp = np.ascontiguousarray(export_kWh, dtype=np.float64)

    if imp.shape[0] != exp.shape[0]:
        raise ValueError("import_kWh and export_kWh must have the same length.")

    eta = float(np.sqrt(roundtrip_eff))
    days = coverage_days if coverage_days and coverage_days > 0 else len(imp) * dt_hours / 24.0

    tariffs, ht_mask, bt_mask = _tariff_vectors(
        len(imp),
        timestamps=timestamps,
        tariff_import=tariff_import,
        tariff_import_ht=tariff_import_ht,
        tariff_import_bt=tariff_import_bt,
        high_tariff_periods=high_tariff_periods,
        weekend_low_tariff=weekend_low_tariff,
    )

    ht_price = tariff_import_ht if tariff_import_ht is not None else tariff_import
    bt_price = tariff_import_bt if tariff_import_bt is not None else tariff_import

    rows = []

    for cap in caps:
        for p in powers:
            # Optional C-rate constraint.
            # Example 0.5C: 200 kWh -> max 100 kW, 1000 kWh -> max 500 kW.
            if max_c_rate is not None and float(p) > float(cap) * float(max_c_rate) + 1e-9:
                continue

            usable_cap = float(cap) * (1.0 - float(soc_min_pct) / 100.0)
            usable_cap = max(usable_cap, 0.0)

            peak_active = bool(peak_shaving_enabled and peak_target_kW is not None and float(peak_target_kW) >= 0.0)
            if peak_active:
                reserve_fraction = min(max(float(peak_reserve_pct) / 100.0, 0.0), 1.0)
                imp_after, exp_after, _, charge_tot, discharge_tot = _dispatch_peak_shaving(
                    imp, exp, usable_cap, float(p) * dt_hours, eta, float(dt_hours),
                    float(peak_target_kW), reserve_fraction, bool(peak_grid_recharge)
                )
            else:
                imp_after, exp_after, _, charge_tot, discharge_tot = _dispatch(
                    imp, exp, usable_cap, float(p) * dt_hours, eta
                )

            avoided_by_interval = imp - imp_after
            stored_by_interval = exp - exp_after

            import_avoided_ht = float(avoided_by_interval[ht_mask].sum())
            import_avoided_bt = float(avoided_by_interval[bt_mask].sum())
            export_stored = float(stored_by_interval.sum())

            gain_import = float((avoided_by_interval * tariffs).sum())
            export_value_lost = float(export_stored * tariff_export)

            peak_savings_chf, peak_before_kw, peak_after_kw, peak_reduction_kw = _peak_power_savings(
                imp,
                imp_after,
                dt_hours,
                timestamps,
                peak_power_tariff_chf_per_kw_month,
                peak_billing_mode,
            ) if peak_active else (
                0.0,
                float(imp.max() / dt_hours) if len(imp) and dt_hours > 0 else 0.0,
                float(imp_after.max() / dt_hours) if len(imp_after) and dt_hours > 0 else 0.0,
                max(
                    0.0,
                    (float(imp.max() / dt_hours) if len(imp) and dt_hours > 0 else 0.0)
                    - (float(imp_after.max() / dt_hours) if len(imp_after) and dt_hours > 0 else 0.0),
                ),
            )

            gain = gain_import - export_value_lost + peak_savings_chf

            cycles_year = (
                discharge_tot / usable_cap * 365.0 / days
                if (usable_cap > 0 and days > 0)
                else 0.0
            )

            rows.append(
                {
                    "Cap_kWh": float(cap),
                    "Power_kW": float(p),
                    "Gain_CHF": float(gain),
                    "Gain_import_HT_CHF": float(import_avoided_ht * ht_price),
                    "Gain_import_BT_CHF": float(import_avoided_bt * bt_price),
                    "Export_value_lost_CHF": float(export_value_lost),
                    "Peak_savings_CHF": float(peak_savings_chf),
                    "Peak_before_kW": float(peak_before_kw),
                    "Peak_after_kW": float(peak_after_kw),
                    "Peak_reduction_kW": float(peak_reduction_kw),
                    "Peak_target_kW": float(peak_target_kW) if peak_active else np.nan,
                    "Peak_billing_mode": str(peak_billing_mode),
                    "Import_avoided_kWh": float(discharge_tot),
                    "Import_avoided_HT_kWh": float(import_avoided_ht),
                    "Import_avoided_BT_kWh": float(import_avoided_bt),
                    "Export_stored_kWh": float(export_stored),
                    "Cycles_per_year": float(cycles_year),
                    "Usable_capacity_kWh": float(usable_cap),
                    "SOC_min_pct": float(soc_min_pct),
                }
            )

    return pd.DataFrame(rows)


if __name__ == "__main__":
    print("simulation.py OK")
