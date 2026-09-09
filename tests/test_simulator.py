"""Régressions physiques, calendaires, financières et interface.

Tests réels facultatifs : BATTERY_TEST_DATA_DIR=/chemin/des/xlsx pytest -q
"""
from io import BytesIO
from pathlib import Path
import os
import json
import sys

import numpy as np
import pandas as pd
import pytest
from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from loaders import (_parse_datetime, _numeric, _finalize, load_meter_file, load_meter_files,
                     prepare_simulation_data, UnsupportedFormatError)
from simulation import simulate, grid_search, _tariff_vectors, _dispatch, simple_payback
from recommend import recommend, best_per_capacity, MODE_SETTINGS, fixed_grid
from i18n import study_assumptions
from report import generate_battery_report, monthly_before_after


def options(frame, meta, **updates):
    result = dict(dt_hours=meta.dt_hours, roundtrip_eff=.92, tariff_import=.2932, tariff_export=.06,
        coverage_days=meta.coverage_days, soc_min_pct=5., timestamps=frame.timestamp,
        tariff_import_ht=.2932, tariff_import_bt=.1927, high_tariff_periods=((7., 12.), (17., 23.)),
        valid_mask=frame.simulation_valid.to_numpy(bool), reset_before=frame.reset_before.to_numpy(bool))
    result.update(updates)
    return result


def synthetic_frame(n=192, start="2025-06-01", missing=()):
    ts = pd.date_range(start, periods=n, freq="15min", tz="Europe/Zurich").tz_convert("UTC")
    hour = ts.tz_convert("Europe/Zurich").hour
    imp = np.where((hour < 8) | (hour >= 18), .5, 0.).astype(float)
    exp = np.where((hour >= 10) & (hour < 16), .8, 0.).astype(float)
    imp[list(missing)] = np.nan
    exp[list(missing)] = np.nan
    return _finalize(pd.DataFrame({"timestamp": ts, "import_kWh": imp, "export_kWh": exp}), "test", "test.csv")


def assert_physics(frame, sim):
    eta = np.sqrt(sim.roundtrip_eff)
    valid = sim.valid
    charge, discharge = sim.charge_by_interval[valid], sim.discharge_by_interval[valid]
    assert (charge >= -1e-9).all() and (discharge >= -1e-9).all()
    assert (charge + discharge <= sim.power_kW * sim.dt_hours + 1e-8).all()
    assert (sim.import_after[valid] >= -1e-9).all() and (sim.export_after[valid] >= -1e-9).all()
    assert np.nanmin(sim.soc_pct) >= sim.soc_min_pct - 1e-8
    assert np.nanmax(sim.soc_pct) <= 100 + 1e-8
    np.testing.assert_allclose(sim.soc[valid] - sim.soc_start[valid], charge * eta - discharge / eta, atol=1e-8)
    assert sim.charge_total_kWh - sim.discharge_total_kWh == pytest.approx(
        sim.conversion_losses_kWh + sim.final_stock_kWh + sim.untransferred_stock_kWh, abs=1e-7)
    assert sim.gain_chf == pytest.approx(sim.gain_ht_chf + sim.gain_bt_chf - sim.export_value_lost_chf, abs=1e-7)
    assert sim.import_before - sim.import_after_total == pytest.approx(sim.import_avoided, abs=1e-7)
    assert sim.export_before - sim.export_after_total == pytest.approx(sim.export_stored, abs=1e-7)


def test_swiss_dates_and_explicit_offsets():
    raw = pd.Series(["01.01.2025 00:00", "01.07.2025 00:00"])
    parsed = _parse_datetime(raw)
    assert parsed.dt.tz_convert("Europe/Zurich").dt.hour.tolist() == [0, 0]
    assert parsed.dt.hour.tolist() == [23, 22]
    offsets = _parse_datetime(pd.Series(["2025-07-01 00:00+02:00", "2025-01-01 00:00 CET"]))
    assert offsets.dt.hour.tolist() == [22, 23]
    assert offsets.dt.tz_convert("Europe/Zurich").dt.hour.tolist() == [0, 0]


@pytest.mark.parametrize("date,expected", [("2025-03-30", 92), ("2025-10-26", 100)])
def test_dst_days_preserve_physical_intervals(date, expected):
    start = pd.Timestamp(date, tz="Europe/Zurich")
    end = pd.Timestamp(pd.Timestamp(date) + pd.Timedelta(days=1), tz="Europe/Zurich")
    actual = pd.date_range(start, end, freq="15min", inclusive="left")
    naive = pd.Series(actual.tz_localize(None).strftime("%d.%m.%Y %H:%M"))
    parsed = _parse_datetime(naive)
    assert len(parsed) == expected
    assert not parsed.duplicated().any()
    assert np.allclose(np.diff(pd.DatetimeIndex(parsed).asi8) / 3.6e12, .25)


def test_ambiguous_and_nonexistent_hours_rejected():
    with pytest.raises(UnsupportedFormatError, match="ambigu"):
        _parse_datetime(pd.Series(["26.10.2025 02:15"]), ambiguous_policy="raise")
    with pytest.raises(UnsupportedFormatError, match="inexistante"):
        _parse_datetime(pd.Series(["30.03.2025 02:15"]))
    summer = _parse_datetime(pd.Series(["26.10.2025 02:15"]), ambiguous_policy="daylight")
    winter = _parse_datetime(pd.Series(["26.10.2025 02:15"]), ambiguous_policy="standard")
    assert winter.iloc[0] - summer.iloc[0] == pd.Timedelta(hours=1)


def test_automatic_autumn_keeps_measurements_and_reports_assumption(tmp_path):
    path = tmp_path / "autumn.csv"
    labels = ["01:45", "02:00", "02:15", "02:30", "02:45", "03:00"]
    path.write_text("Date;Import (kW);Export (kW)\n" + "".join(
        f"26.10.2025 {hour};2;0\n" for hour in labels))
    raw, meta = load_meter_file(path)
    assert meta.source_rows == meta.valid_rows == 6
    assert meta.absent_rows == 4 and meta.invalid_rows == 0
    assert raw.import_kWh.sum() == pytest.approx(3.)
    assert raw.loc[~raw.valid, ["import_kWh", "export_kWh"]].isna().all().all()
    assert any("4 horodatage(s)" in w and "convention automatique" in w for w in meta.warnings)
    assert any("première occurrence (été)" in w for w in meta.warnings)
    with pytest.raises(UnsupportedFormatError, match="ambigu"):
        load_meter_file(path, ambiguous_policy="raise")
    for policy, expected in [("auto", "2025-10-26 00:15Z"), ("standard", "2025-10-26 01:15Z")]:
        parsed = _parse_datetime(pd.Series(["26.10.2025 02:15"]), ambiguous_policy=policy)
        assert parsed.iloc[0] == pd.Timestamp(expected)
        assert parsed.attrs["ambiguous_assumed"] == 1


def test_automatic_autumn_preserves_both_explicit_occurrences():
    parsed = _parse_datetime(pd.Series(["2025-10-26 02:15+02:00", "2025-10-26 02:15+01:00"]))
    assert parsed.iloc[1] - parsed.iloc[0] == pd.Timedelta(hours=1)
    assert parsed.attrs["ambiguous_assumed"] == 0
    with pytest.raises(UnsupportedFormatError, match="Plus de deux occurrences"):
        _parse_datetime(pd.Series(["26.10.2025 02:15"] * 3))


def test_numeric_locales_and_unknown():
    values = _numeric(pd.Series(["1,5", "1.5", "1'234,5", "1 234.5", "1.234,5", "1,234.5", "Manquant", "inf"]))
    np.testing.assert_allclose(values[:6], [1.5, 1.5, 1234.5, 1234.5, 1234.5, 1234.5])
    assert values[6:].isna().all()


@pytest.mark.parametrize("unit,raw_value,expected", [("kW", 4, 1), ("W", 4000, 1), ("Wh", 1000, 1), ("kWh", 1, 1)])
def test_unit_conversion_and_end_labels(tmp_path, unit, raw_value, expected):
    path = tmp_path / "energy.csv"
    path.write_text(f"Date;Import ({unit});Export ({unit})\n01.01.2025 00:15;{raw_value};0\n01.01.2025 00:30;{raw_value};0\n")
    frame, meta = load_meter_file(path)
    assert frame.import_kWh.tolist() == [expected, expected]
    assert pd.Timestamp(meta.start).hour == 0 and pd.Timestamp(meta.start).minute == 0
    assert meta.coverage_days == pytest.approx(.5 / 24)


def test_unknown_units_and_consumption_are_not_assumed(tmp_path):
    path = tmp_path / "energy.csv"
    path.write_text("Date;Import;Export\n01.01.2025 00:15;1;0\n01.01.2025 00:30;1;0\n")
    with pytest.raises(UnsupportedFormatError, match="Unité"):
        load_meter_file(path)
    assert load_meter_file(path, data_unit="kWh")[0].import_kWh.sum() == 2
    path.write_text("Date;Consommation (kWh);Export (kWh)\n01.01.2025 00:15;1;0\n01.01.2025 00:30;1;0\n")
    with pytest.raises(UnsupportedFormatError, match="ambigu"):
        load_meter_file(path)


def test_missing_not_zero_and_stock_reset():
    frame, meta = synthetic_frame(missing=(50, 51, 52))
    assert meta.invalid_rows == 3
    assert frame.import_kWh.iloc[50:53].isna().all()
    with pytest.raises(UnsupportedFormatError):
        prepare_simulation_data(frame, meta)
    frame, meta = prepare_simulation_data(frame, meta, "segments")
    sim = simulate(frame.import_kWh, frame.export_kWh, 10, 4, **options(frame, meta))
    assert sim.soc_start[53] == 0
    assert sim.untransferred_stock_kWh > 0
    assert np.isnan(sim.soc[50:53]).all()
    assert_physics(frame, sim)


def test_estimation_uses_only_measured_comparable_days():
    frame, meta = synthetic_frame(96 * 60, missing=(96 * 30 + 44,))
    estimated, modified = prepare_simulation_data(frame, meta, "estimate")
    assert modified.estimated_rows == 1
    assert not estimated.valid.iloc[96 * 30 + 44]
    assert estimated.estimated.iloc[96 * 30 + 44]
    assert estimated.simulation_valid.all()
    assert estimated.export_kWh.iloc[96 * 30 + 44] == .8
    assert modified.completeness == meta.completeness
    assert frame.export_kWh.isna().sum() == 1  # caller's measurements unchanged


def test_duplicate_content_overlap_and_mixed_steps(tmp_path):
    first, second = tmp_path / "a.csv", tmp_path / "b.csv"
    first.write_text("Date;Import (kWh);Export (kWh)\n01.01.2025 00:15;1;0\n01.01.2025 00:30;2;0\n")
    second.write_bytes(first.read_bytes())
    with pytest.raises(UnsupportedFormatError, match="même contenu"):
        load_meter_files([first, second], same_meter=True)
    second.write_text(first.read_text().replace(";2;0", ";3;0"))
    with pytest.raises(UnsupportedFormatError, match="chevauch"):
        load_meter_files([first, second], same_meter=True)
    with pytest.raises(UnsupportedFormatError, match="point de mesure"):
        load_meter_files([first, second])
    second.write_text("Date;Import (kWh);Export (kWh)\n02.01.2025 00:30;1;0\n02.01.2025 01:00;2;0\n")
    with pytest.raises(UnsupportedFormatError, match="différents"):
        load_meter_files([first, second], same_meter=True)


def test_irregular_and_sparse_timestamps_rejected():
    for times in (["2025-01-01 00:00", "2025-01-01 00:15", "2025-01-01 00:35"],
                  ["2025-01-01 00:00", "2025-01-01 00:15", "2025-12-31 00:00"]):
        df = pd.DataFrame({"timestamp": pd.to_datetime(times, utc=True), "import_kWh": [1, 1, 1], "export_kWh": [0, 0, 0]})
        with pytest.raises(UnsupportedFormatError):
            _finalize(df, "test", "test")


def test_huawei_month_boundary_and_reset(tmp_path):
    def write(path, times, imp, exp):
        pd.DataFrame({"Heure début": times, "Énergie active négative (kWh)": imp,
                      "Énergie active positive (kWh)": exp, "Appareil": ["A"] * len(times)}).to_excel(path, index=False, startrow=3)
    # XLSX authoring here is strictly a disposable parser test fixture.
    a, b = tmp_path / "a.xlsx", tmp_path / "b.xlsx"
    write(a, ["31.01.2025 23:45", "01.02.2025 00:00"], [100, 101], [200, 201])
    write(b, ["01.02.2025 00:00", "01.02.2025 00:15", "01.02.2025 00:30"], [101, 104, 1], [201, 203, 1])
    frame, meta = load_meter_files([a, b], same_meter=True)
    assert frame.import_kWh.iloc[1:3].tolist() == [1, 3]
    assert frame.export_kWh.iloc[1:3].tolist() == [1, 2]
    assert frame.import_kWh.iloc[[0, 3]].isna().all()
    assert any("remise" in n for n in meta.warnings)


def test_huawei_device_aggregation_is_explicit_and_aligned(tmp_path):
    path = tmp_path / "devices.xlsx"
    pd.DataFrame({"Heure début": ["01.01.2025 00:00", "01.01.2025 00:15", "01.01.2025 00:30"] * 2,
                  "Énergie active négative (kWh)": [100, 101, 103, 200, 210, 220],
                  "Énergie active positive (kWh)": [100, 100, 100, 200, 200, 201],
                  "Appareil": ["A"] * 3 + ["B"] * 3}).to_excel(path, index=False)
    with pytest.raises(UnsupportedFormatError, match="Plusieurs appareils"):
        load_meter_file(path)
    frame, _ = load_meter_file(path, aggregate_devices=True)
    assert frame.import_kWh.iloc[1:].tolist() == [11, 12]
    assert frame.export_kWh.iloc[1:].tolist() == [0, 1]


def test_partial_period_never_silently_annualized():
    frame, meta = synthetic_frame(96 * 10)
    assert not meta.annualization_allowed
    frame, meta = prepare_simulation_data(frame, meta)
    sim = simulate(frame.import_kWh, frame.export_kWh, 10, 4, **options(frame, meta))
    assert sim.gain_annual_chf is None and np.isnan(sim.cycles_per_year)
    with pytest.raises(ValueError, match="Annualisation"):
        simulate(frame.import_kWh, frame.export_kWh, 10, 4, **options(frame, meta, annualize=True))


@pytest.mark.parametrize("soc", [0, 5, 30, 95])
@pytest.mark.parametrize("order", ["discharge_first", "charge_first"])
def test_random_physical_invariants(soc, order):
    rng = np.random.default_rng(87)
    imp, exp = rng.uniform(0, 2, (2, 1000))
    sim = simulate(imp, exp, 10, 1, .25, .8, .3, .07, soc_min_pct=soc, dispatch_order=order)
    assert_physics(None, sim)
    assert sim.gain_chf == pytest.approx(sim.import_avoided * .3 - sim.export_stored * .07)
    assert np.isnan(sim.cycles_per_year)


def test_internal_cycle_definition_and_efficiency():
    # 12.5 kWh AC at 80% each way puts 10 kWh DC in, then supplies 8 kWh AC.
    sim = simulate([0, 8], [12.5, 0], 10, 20, 1, .64, .3, .05, soc_min_pct=0)
    assert sim.soc.tolist() == pytest.approx([10, 0])
    assert sim.cycles_period == pytest.approx(1.)
    assert sim.discharge_total_kWh == 8
    assert sim.conversion_losses_kWh == pytest.approx(4.5)


def test_grid_and_simulation_are_identical():
    frame, meta = synthetic_frame()
    frame, meta = prepare_simulation_data(frame, meta)
    opts = options(frame, meta)
    gs = grid_search(frame.import_kWh, frame.export_kWh, [5, 10], [1, 4], max_c_rate=.5, **opts)
    assert 2.5 in gs[gs.Cap_kWh == 5].Power_kW.tolist()
    for _, row in gs.iterrows():
        sim = simulate(frame.import_kWh, frame.export_kWh, row.Cap_kWh, row.Power_kW, **opts)
        assert row.Gain_CHF == sim.gain_chf
        assert row.Cycles_period == sim.cycles_period


def test_tariff_boundary_and_schedule():
    times = pd.DatetimeIndex([pd.Timestamp("2025-06-02 06:45", tz="Europe/Zurich")])
    buy, high, sell, high_value = _tariff_vectors(1, times, tariff_import_ht=.4, tariff_import_bt=.2,
        high_tariff_periods=((7, 12),), dt_hours=.5, tariff_export=.06)
    assert buy[0] == pytest.approx(.3)
    assert high[0] == .5
    assert high_value[0] == pytest.approx(.2)
    dates = pd.date_range("2025-12-31 23:45", periods=2, freq="15min", tz="Europe/Zurich")
    schedule = [dict(start="2025-01-01", end="2026-01-01", ht=.3, bt=.3, export=.05),
                dict(start="2026-01-01", end="2027-01-01", ht=.4, bt=.4, export=.06)]
    prices = _tariff_vectors(2, dates, tariff_schedule=schedule)
    np.testing.assert_allclose(prices[0], [.3, .4])
    with pytest.raises(ValueError, match="trou"):
        _tariff_vectors(2, dates, tariff_schedule=schedule[:1])
    with pytest.raises(ValueError, match="chevauchement"):
        _tariff_vectors(2, dates, tariff_schedule=schedule + schedule)


@pytest.mark.parametrize("parameter,value", [("soc_min_pct", -1), ("soc_min_pct", 100),
    ("roundtrip_eff", 0), ("roundtrip_eff", 1.01), ("dt_hours", 0), ("power_kW", -1),
    ("capacity_kWh", np.nan), ("tariff_export", np.inf)])
def test_invalid_parameters(parameter, value):
    args = dict(capacity_kWh=10, power_kW=2, dt_hours=.25, roundtrip_eff=.9, tariff_import=.3, tariff_export=.05)
    args[parameter] = value
    with pytest.raises(ValueError):
        simulate([1, 2], [0, 0], **args)


def test_no_admissible_grid_and_no_payback():
    with pytest.raises(ValueError, match="admissible"):
        grid_search([1, 2], [0, 1], [150], [500], .25, .9, .3, .05, max_c_rate=.5)
    for cost, gain in [(None, 10), (0, 10), (100, 0), (100, -1), (100, None)]:
        assert simple_payback(cost, gain) is None
    assert simple_payback(5000, 500) == 10


def table(caps, gains, cycles):
    return pd.DataFrame({"Cap_kWh": caps, "Power_kW": [1.] * len(caps), "Gain_CHF": gains,
                         "Cycles_per_year": cycles, "Cycles_period": cycles})


def test_flat_gain_keeps_smallest_and_checks_all_cycle_candidates():
    rec = recommend(table([5, 6, 7], [100, 100, 100], [200, 200, 200]))
    assert rec.best.Cap_kWh == 5
    rec = recommend(table([5, 6, 7], [100, 130, 150], [100, 200, 190]))
    assert rec.best.Cap_kWh in [6, 7]
    assert rec.best.Cycles_per_year >= 150
    rec = recommend(table([5, 6, 7], [0, 0, 0], [200, 200, 200]))
    assert not rec.recommended


def test_smallest_power_at_99_percent():
    results = pd.DataFrame({"Cap_kWh": [12.] * 3, "Power_kW": [3., 4., 8.],
                           "Gain_CHF": [403.4, 406.4, 407.8], "Cycles_per_year": [200.] * 3})
    assert best_per_capacity(results).iloc[0].Power_kW == 4


def test_negligible_annual_gain_is_not_endorsed():
    results = table([5, 6], [.2, .3], [200, 200])
    results["Gain_annual_CHF"] = results.Gain_CHF
    rec = recommend(results)
    assert not rec.recommended
    assert "negligible_gain" in [code for code, _ in rec.warnings]


def test_months_separate_years_and_preserve_unknown_month():
    frame, meta = synthetic_frame(96 * 400, start="2025-01-01")
    feb = frame.timestamp.dt.tz_convert("Europe/Zurich").dt.month == 2
    frame.loc[feb, ["import_kWh", "export_kWh"]] = np.nan
    frame.loc[feb, "valid"] = False
    frame, meta = prepare_simulation_data(frame, meta, "segments")
    sim = simulate(frame.import_kWh, frame.export_kWh, 10, 4, **options(frame, meta))
    monthly = monthly_before_after(frame, sim)
    assert pd.Period("2025-01") in monthly.index and pd.Period("2026-01") in monthly.index
    assert pd.isna(monthly.loc[pd.Period("2025-02"), "Import avant"])


def test_numba_and_python_kernel_equivalence():
    if not hasattr(_dispatch, "py_func"):
        pytest.skip("Numba optionnel non installé")
    rng = np.random.default_rng(88)
    imp, exp = rng.uniform(0, 2, (2, 100))
    valid = np.ones(100, bool)
    valid[20:23] = False
    resets = valid & ~np.r_[False, valid[:-1]]
    args = imp, exp, valid, resets, 9.5, .25, np.sqrt(.92), False
    for accelerated, plain in zip(_dispatch(*args), _dispatch.py_func(*args)):
        np.testing.assert_allclose(accelerated, plain, equal_nan=True, atol=1e-12)


def test_original_three_page_report_quality_and_soc():
    frame, meta = synthetic_frame(missing=(50,))
    frame, meta = prepare_simulation_data(frame, meta, "segments")
    opts = options(frame, meta, soc_min_pct=30.)
    gs = grid_search(frame.import_kWh, frame.export_kWh, [10, 15], [2, 4], **opts)
    rec = recommend(gs)
    sim = simulate(frame.import_kWh, frame.export_kWh, rec.best.Cap_kWh, rec.best.Power_kW, **opts)
    assumptions = study_assumptions(sim, meta, rec, tariff_profile="Test", tariff_year=2026,
        tariff_note="Scénario de test", tariff_import_ht=.2932, tariff_import_bt=.1927, tariff_export=.06,
        periods=((7, 12), (17, 23)), weekend_low=False)
    base = dict(df=frame, meta=meta, rec=rec, sim=sim, assumptions=assumptions)
    pdf = PdfReader(BytesIO(generate_battery_report(**base)))
    assert len(pdf.pages) == 3
    text = "\n".join(page.extract_text() for page in pdf.pages)
    assert "30 %" in text and "valeurs inconnues" in text
    assert "SOC initial" in text
    assert "Import évité + export évité" not in text
    audit = json.loads(pdf.attachments["hypotheses_et_qualite.json"][0])
    assert audit["hypotheses"] == assumptions
    assert audit["periodes_inconnues"] == meta.missing_periods
    with pytest.raises(ValueError, match="trois pages"):
        generate_battery_report(**base, sections=["soc"])


def summary_cards(at):
    return [m.value for m in at.markdown if 'class="mar-card-grid-5"' in m.value]


def test_streamlit_upload_soc_views_and_pdf():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=60).run()
    assert not at.exception
    # Two-day synthetic CSV exercises the real uploader and actual application.
    raw, _ = synthetic_frame()
    csv = raw[["timestamp", "import_kWh", "export_kWh"]].rename(columns={
        "timestamp": "Date", "import_kWh": "Import (kWh)", "export_kWh": "Export (kWh)"}).to_csv(index=False).encode()
    at.file_uploader[0].set_value(("test.csv", csv, "text/csv")).run()
    assert not at.exception and not at.error
    for period in ["Semaine", "Mois", "Année", "Jour"]:
        at.get("button_group")[0].set_value(period).run()
        assert not at.exception and not at.error
    at.slider(key="soc_min_residential").set_value(35).run()
    assert not at.exception
    assert any("35-100 %" in c.value for c in at.caption)
    assert [tab.label for tab in at.tabs] == ["📈 Gain vs capacité", "Rentabilité", "🔋 État de charge", "♻️ Cycles cumulés", "📊 Avant / Après"]
    before = summary_cards(at)
    at.select_slider(key="display_step").set_value(5).run()
    assert before == summary_cards(at)
    at.button(key="prepare_pdf").click().run()
    assert not at.exception and not at.error
    assert at.session_state["report_bytes"].startswith(b"%PDF")
    at.slider(key="soc_min_residential").set_value(40).run()
    assert "report_bytes" not in at.session_state


def test_streamlit_automatic_dates_and_gaps_with_manual_overrides():
    from streamlit.testing.v1 import AppTest
    raw, _ = synthetic_frame(n=196, start="2025-10-26")
    labels = raw.timestamp.dt.tz_convert("Europe/Zurich").dt.strftime("%Y-%m-%d %H:%M")
    csv_frame = raw.loc[~labels.duplicated(), ["import_kWh", "export_kWh"]].copy()
    csv_frame.insert(0, "Date", labels.loc[csv_frame.index])
    csv_frame.columns = ["Date", "Import (kWh)", "Export (kWh)"]
    csv_frame.loc[csv_frame.index[60], ["Import (kWh)", "Export (kWh)"]] = np.nan
    csv = csv_frame.to_csv(index=False).encode()
    at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=60)
    # Old widgets must not keep a previously blocked session in strict mode.
    at.session_state["ambiguous"] = "Signaler l'ambiguïté"
    at.session_state["missing_policy"] = "Attendre des données complètes"
    at.run()
    at.file_uploader[0].set_value(("autumn_missing.csv", csv, "text/csv")).run()
    assert not at.exception and not at.error
    assert at.selectbox(key="autumn_hour_policy").value == "Automatique (heure suisse)"
    assert at.radio(key="gap_treatment").value == "Calculer les segments mesurés"
    assert bool(summary_cards(at))
    assert any(m.label == "Intervalles absents" and m.value == "4" for m in at.metric)
    assert any(m.label == "Intervalles invalides" and m.value == "1" for m in at.metric)
    assert any("convention automatique" in w.value for w in at.warning)
    at.button(key="prepare_pdf").click().run()
    pdf = PdfReader(BytesIO(at.session_state["report_bytes"]))
    report_text = "\n".join(page.extract_text() for page in pdf.pages)
    assert "convention automatique" in report_text
    assert "première occurrence (été)" in report_text
    assert "Segments indépendants" in report_text
    at.selectbox(key="autumn_hour_policy").set_value("Seconde occurrence (hiver)").run()
    assert not at.exception and not at.error
    assert any("seconde occurrence (hiver)" in w.value for w in at.warning)
    assert "report_bytes" not in at.session_state
    at.selectbox(key="autumn_hour_policy").set_value("Signaler l'ambiguïté").run()
    assert any("Heure d'automne ambiguë" in e.value for e in at.error)
    at.selectbox(key="autumn_hour_policy").set_value("Automatique (heure suisse)").run()
    assert not at.exception and not at.error
    at.radio(key="gap_treatment").set_value("Attendre des données complètes").run()
    assert any("Données incomplètes" in w.value for w in at.warning)
    assert not bool(summary_cards(at))


@pytest.mark.parametrize("pattern,mode,invalid,absent", [
    ("Mesures*.xlsx", "residential", 100, 4),
    ("Mivelaz*.xlsx", "ci", 0, 0),
    ("Stern*.xlsx", "residential", 71, 4),
    ("Groupe E - Ross*.xlsx", "residential", 58, 0),
])
def test_real_profiles_open_automatically(pattern, mode, invalid, absent):
    from streamlit.testing.v1 import AppTest
    directory = os.environ.get("BATTERY_TEST_DATA_DIR")
    if not directory:
        pytest.skip("BATTERY_TEST_DATA_DIR non renseigné")
    path = next(Path(directory).glob(pattern), None)
    if path is None:
        pytest.skip(f"Profil facultatif absent : {pattern}")
    at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=90).run()
    at.radio(key="study_mode").set_value(mode).run()
    at.file_uploader[0].set_value((path.name, path.read_bytes(),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")).run()
    assert not at.exception and not at.error
    assert bool(summary_cards(at))
    assert any(m.label == "Intervalles invalides" and m.value == str(invalid) for m in at.metric)
    assert any(m.label == "Intervalles absents" and m.value == str(absent) for m in at.metric)
    if absent:
        assert at.radio(key="gap_treatment").value == "Calculer les segments mesurés"
        assert any("convention automatique" in w.value for w in at.warning)
    else:
        assert not any("convention automatique" in w.value for w in at.warning)


@pytest.fixture(scope="module")
def real_profiles():
    directory = os.environ.get("BATTERY_TEST_DATA_DIR")
    if not directory:
        pytest.skip("BATTERY_TEST_DATA_DIR non renseigné ; fichiers clients facultatifs")
    root = Path(directory)
    res_path = next(root.glob("Mesures*.xlsx"))
    ci_path = next(root.glob("Mivelaz*.xlsx"))
    return {"residential": load_meter_file(res_path, ambiguous_policy="daylight"),
            "ci": load_meter_file(ci_path)}


def test_real_profile_totals_and_missing_dates(real_profiles):
    frame, meta = real_profiles["residential"]
    assert meta.invalid_rows == 100 and meta.absent_rows == 4
    assert frame.import_kWh.sum() == pytest.approx(3473.1975)
    assert frame.export_kWh.sum() == pytest.approx(11003.3975)
    assert any(p["debut"].startswith("2025-11-03T00:00") and p["heures"] == 25 for p in meta.missing_periods)
    frame, meta = real_profiles["ci"]
    assert meta.invalid_rows == meta.absent_rows == 0 and len(frame) == 35040
    assert frame.import_kWh.sum() == pytest.approx(1432951.369)
    assert frame.export_kWh.sum() == pytest.approx(254365.25)
    assert frame.import_kWh.max() / meta.dt_hours == 746


@pytest.mark.parametrize("mode", ["residential", "ci"])
def test_real_full_grid_and_soc_range(real_profiles, mode):
    raw, meta = real_profiles[mode]
    frame, meta = prepare_simulation_data(raw, meta, "segments")
    settings = MODE_SETTINGS[mode]
    opts = options(frame, meta, roundtrip_eff=settings["efficiency"], soc_min_pct=settings["soc_min"], annualize=True)
    cl, ch, cs = settings["capacity"]
    pl, ph, ps = settings["power"]
    results = grid_search(frame.import_kWh, frame.export_kWh, fixed_grid(cl, ch, cs, cl),
        fixed_grid(pl, ph, ps, pl), max_c_rate=settings["c_rate"], **opts)
    assert results.Gain_CHF.notna().all()
    rec = recommend(results, study_mode=mode)
    sim = simulate(frame.import_kWh, frame.export_kWh, rec.best.Cap_kWh, rec.best.Power_kW, **opts)
    assert_physics(frame, sim)
    for soc in [0., 5., 30., 80., 95.]:
        altered = simulate(frame.import_kWh, frame.export_kWh, rec.best.Cap_kWh, rec.best.Power_kW, **dict(opts, soc_min_pct=soc))
        assert_physics(frame, altered)
    print(f"\n{mode}: {len(results)} combinaisons, {sim.capacity_kWh:g} kWh / {sim.power_kW:g} kW, gain {sim.gain_chf:.2f} CHF, cycles DC {sim.cycles_per_year:.2f}/an")


@pytest.mark.parametrize("native,policy,zero_count", [(True, "auto", 3), (True, "unknown", 0), (False, "auto", 0)])
def test_only_native_groupe_e_one_sided_blanks_can_be_zero(monkeypatch, native, policy, zero_count):
    import loaders
    raw = pd.DataFrame({"Date": pd.date_range("2025-06-01", periods=10, freq="15min"),
        "Soutirage (kW)": ["", 1., "", "Erroné", "NaN", "N/A", np.nan, "", "", ""],
        "Surplus solaire (kW)": [2., "", "", 1., 1., 1., 1., -1., np.inf, 0.]})
    raw.attrs["groupe_e_meter_template"] = native
    monkeypatch.setattr(loaders, "_read_table", lambda _: raw.copy())
    frame = loaders._read_raw(Path("test.xlsx"), "auto", "auto", blank_policy=policy)
    assert frame.attrs["blank_zero_cells"] == zero_count
    assert frame.loc[2:8, "import_kWh"].isna().all()
    if zero_count:
        assert frame.loc[[0,9], "import_kWh"].eq(0).all()
        assert frame.loc[1, "export_kWh"] == 0
    else:
        assert pd.isna(frame.loc[0, "import_kWh"])
        assert pd.isna(frame.loc[1, "export_kWh"])


def test_ross_energy_totals_unknowns_and_physics():
    directory = os.environ.get("BATTERY_TEST_DATA_DIR")
    if not directory:
        pytest.skip("BATTERY_TEST_DATA_DIR non renseigné")
    path = next(Path(directory).glob("Groupe E - Ross*.xlsx"))
    raw, meta = load_meter_file(path)
    assert len(raw) == 35040
    assert meta.blank_zero_cells == 28491
    assert meta.invalid_rows == 58 and meta.absent_rows == 0
    assert meta.completeness == pytest.approx(34982 / 35040)
    assert raw.import_kWh.sum() == pytest.approx(13380.03)
    assert raw.export_kWh.sum() == pytest.approx(12730.4425)
    assert sorted(p["heures"] for p in meta.missing_periods) == [.25, 14.25]
    local = raw.timestamp.dt.tz_convert("Europe/Zurich")
    assert sum((local.dt.date == pd.Timestamp("2025-10-26").date()) & (local.dt.hour == 2)) == 8
    frame, meta = prepare_simulation_data(raw, meta, "segments")
    sim = simulate(frame.import_kWh, frame.export_kWh, 17., 6., **options(frame, meta))
    assert_physics(frame, sim)
    assert sim.import_before == pytest.approx(13380.03)
    assert sim.export_before == pytest.approx(12730.4425)
    strict, strict_meta = load_meter_file(path, blank_policy="unknown")
    assert strict_meta.invalid_rows == 28549 and strict_meta.blank_zero_cells == 0


def test_ross_ui_policy_cache_and_original_report():
    from streamlit.testing.v1 import AppTest
    directory = os.environ.get("BATTERY_TEST_DATA_DIR")
    if not directory:
        pytest.skip("BATTERY_TEST_DATA_DIR non renseigné")
    path = next(Path(directory).glob("Groupe E - Ross*.xlsx"))
    at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=90).run()
    at.file_uploader[0].set_value((path.name,path.read_bytes(),"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")).run()
    assert not at.exception and not at.error
    assert any(m.label == "Intervalles exploitables" and m.value == "99.83%" for m in at.sidebar.metric)
    assert not at.main.selectbox and not at.main.radio
    assert [e.label for e in at.main.expander] == ["Détail du gain tarifaire"]
    at.button(key="prepare_pdf").click().run()
    pdf = PdfReader(BytesIO(at.session_state["report_bytes"]))
    assert len(pdf.pages) == 3
    text = "\n".join(p.extract_text() for p in pdf.pages)
    assert "13 380" in text and "12 730" in text and "28491" in text
    assert "Graphiques principaux" in text and "ANALYSE TECHNIQUE" in text
    at.selectbox(key="groupe_e_blank_policy").set_value("Toujours inconnues").run()
    assert not at.exception and not at.error
    assert "report_bytes" not in at.session_state
    assert any(m.label == "Intervalles exploitables" and m.value == "18.52%" for m in at.sidebar.metric)
    at.selectbox(key="groupe_e_blank_policy").set_value("Automatique (convention de l'export)").run()
    assert not at.exception and not at.error
    assert any(m.label == "Intervalles exploitables" and m.value == "99.83%" for m in at.sidebar.metric)
