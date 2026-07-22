"""Modern energy-management dashboard for Battery Sizer.

The source meter profile contains grid import and PV-surplus export. This module only
shows flows that can be derived exactly from these measurements and the battery
simulation. A measured PV profile can later be added without changing the dashboard API.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

SOLEOL = "#ef5b32"
GREEN = "#27c77d"
BLUE = "#4f8cff"
CYAN = "#35c2e8"
PURPLE = "#9a6bff"
RED = "#ff5f57"
GRID = "rgba(148,163,184,.16)"
TEXT = "#f8fafc"
MUTED = "#94a3b8"
PANEL = "#151922"
PANEL_2 = "#11151d"


def _fmt(value: float, decimals: int = 1) -> str:
    return f"{float(value):,.{decimals}f}".replace(",", " ")


def _ratio(num: float, den: float) -> float:
    return float(num) / float(den) if float(den) > 0 else 0.0


def build_energy_frame(df: pd.DataFrame, sim) -> pd.DataFrame:
    ts = pd.to_datetime(df["timestamp"], errors="coerce")
    diffs = ts.sort_values().diff().dropna().dt.total_seconds() / 3600.0
    dt_hours = float(diffs.median()) if not diffs.empty else 0.25
    dt_hours = max(dt_hours, 1e-9)

    imp_before = np.asarray(df["import_kWh"], dtype=float)
    exp_before = np.asarray(df["export_kWh"], dtype=float)
    imp_after = np.asarray(sim.import_after, dtype=float)
    exp_after = np.asarray(sim.export_after, dtype=float)
    charge = np.maximum(exp_before - exp_after, 0.0)
    discharge = np.maximum(imp_before - imp_after, 0.0)

    usable = float(getattr(sim, "usable_capacity_kWh", 0.0) or 0.0)
    soc_min = float(getattr(sim, "soc_min_pct", 0.0) or 0.0)
    soc_raw = np.asarray(getattr(sim, "soc", np.zeros(len(df))), dtype=float)
    soc_pct = soc_min + soc_raw / usable * (100.0 - soc_min) if usable > 0 else np.zeros(len(df))

    frame = pd.DataFrame(
        {
            "timestamp": ts,
            "import_before_kWh": imp_before,
            "export_before_kWh": exp_before,
            "import_after_kWh": imp_after,
            "export_after_kWh": exp_after,
            "battery_charge_kWh": charge,
            "battery_discharge_kWh": discharge,
            "soc_pct": np.clip(soc_pct, 0.0, 100.0),
        }
    ).dropna(subset=["timestamp"])

    for col in [c for c in frame.columns if c.endswith("_kWh")]:
        frame[col.replace("_kWh", "_kW")] = frame[col] / dt_hours
    return frame.sort_values("timestamp").reset_index(drop=True)


def _controls(frame: pd.DataFrame) -> tuple[str, pd.DataFrame, bool, str]:
    modes = ["Jour", "Semaine", "Mois", "Année"]
    c1, c2 = st.columns([1.15, 2.85])
    with c1:
        if hasattr(st, "segmented_control"):
            mode = st.segmented_control("Période", modes, default="Jour", key="energy_mode")
        else:
            mode = st.radio("Période", modes, horizontal=True, key="energy_mode")
    mode = mode or "Jour"

    dates = frame["timestamp"].dt.date
    with c2:
        if mode == "Jour":
            chosen = st.date_input(
                "Date affichée",
                value=dates.iloc[len(dates) // 2],
                min_value=dates.min(),
                max_value=dates.max(),
                key="energy_day",
            )
            selected = frame[dates == chosen].copy()
            return mode, selected, True, "Heure"

        if mode == "Semaine":
            mondays = frame["timestamp"].dt.normalize() - pd.to_timedelta(frame["timestamp"].dt.weekday, unit="D")
            weeks = sorted(mondays.dt.date.unique().tolist())
            chosen = st.selectbox(
                "Semaine affichée",
                weeks,
                index=len(weeks) - 1,
                format_func=lambda d: f"Semaine du {pd.Timestamp(d).strftime('%d.%m.%Y')}",
                key="energy_week",
            )
            mask = mondays.dt.date == chosen
            selected = frame[mask].copy()
            return mode, selected, True, "Jour / heure"

        if mode == "Mois":
            periods = sorted(frame["timestamp"].dt.to_period("M").unique().tolist())
            labels = [p.strftime("%m.%Y") for p in periods]
            label = st.selectbox("Mois affiché", labels, index=len(labels) - 1, key="energy_month")
            period = periods[labels.index(label)]
            raw = frame[frame["timestamp"].dt.to_period("M") == period].copy()
            energy_cols = [c for c in frame.columns if c.endswith("_kWh")]
            selected = raw.set_index("timestamp")[energy_cols].resample("D").sum().reset_index()
            selected["soc_pct"] = raw.set_index("timestamp")["soc_pct"].resample("D").last().values
            return mode, selected, False, "Jour du mois"

        years = sorted(frame["timestamp"].dt.year.unique().tolist())
        year = st.selectbox("Année affichée", years, index=len(years) - 1, key="energy_year")
        raw = frame[frame["timestamp"].dt.year == int(year)].copy()
        energy_cols = [c for c in frame.columns if c.endswith("_kWh")]
        selected = raw.set_index("timestamp")[energy_cols].resample("MS").sum().reset_index()
        selected["soc_pct"] = raw.set_index("timestamp")["soc_pct"].resample("MS").last().values
        return mode, selected, False, "Mois"


def _totals(selected: pd.DataFrame) -> dict[str, float]:
    def total(col: str) -> float:
        return float(selected[col].sum()) if col in selected else 0.0

    return {
        "imp_before": total("import_before_kWh"),
        "imp_after": total("import_after_kWh"),
        "exp_before": total("export_before_kWh"),
        "exp_after": total("export_after_kWh"),
        "charge": total("battery_charge_kWh"),
        "discharge": total("battery_discharge_kWh"),
    }


def _chart(selected: pd.DataFrame, mode: str, use_power: bool, x_title: str) -> go.Figure:
    suffix = "kW" if use_power else "kWh"
    unit = suffix
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # Four principal visual signals. Import/export before battery remain available in legend.
    traces = [
        (f"export_before_{suffix}", "Surplus solaire", GREEN, "solid", None, True),
        (f"import_after_{suffix}", "Import réseau", RED, "solid", "tozeroy", True),
        (f"battery_charge_{suffix}", "Charge batterie", BLUE, "dot", None, True),
        (f"battery_discharge_{suffix}", "Décharge batterie", PURPLE, "dot", None, True),
        (f"import_before_{suffix}", "Besoin réseau avant batterie", SOLEOL, "dash", None, "legendonly"),
        (f"export_after_{suffix}", "Injection réseau", CYAN, "dash", None, "legendonly"),
    ]
    for col, name, color, dash, fill, visible in traces:
        if col not in selected:
            continue
        fig.add_trace(
            go.Scatter(
                x=selected["timestamp"],
                y=selected[col],
                name=name,
                mode="lines",
                visible=visible,
                fill=fill,
                fillcolor="rgba(255,95,87,.08)" if fill else None,
                line=dict(color=color, width=2.7 if dash == "solid" else 2.1, dash=dash),
                hovertemplate=f"{name}<br>%{{y:.2f}} {unit}<extra></extra>",
            ),
            secondary_y=False,
        )

    fig.add_trace(
        go.Scatter(
            x=selected["timestamp"],
            y=selected["soc_pct"],
            name="État de charge",
            mode="lines",
            line=dict(color="#d8dee9", width=1.8),
            hovertemplate="État de charge<br>%{y:.1f} %<extra></extra>",
        ),
        secondary_y=True,
    )

    fig.update_yaxes(title_text=unit, secondary_y=False, rangemode="tozero", gridcolor=GRID, zeroline=False)
    fig.update_yaxes(title_text="SOC (%)", secondary_y=True, range=[0, 100], showgrid=False, zeroline=False)
    fig.update_layout(
        height=570,
        paper_bgcolor=PANEL_2,
        plot_bgcolor=PANEL_2,
        font=dict(color=TEXT, size=12),
        hovermode="x unified",
        hoverlabel=dict(bgcolor="#202632", bordercolor="#354052", font=dict(color=TEXT)),
        legend=dict(orientation="h", y=1.11, x=0, font=dict(size=11), bgcolor="rgba(0,0,0,0)"),
        margin=dict(t=72, l=58, r=62, b=48),
        xaxis=dict(
            title=x_title,
            gridcolor=GRID,
            rangeslider=dict(visible=(mode in {"Jour", "Semaine"}), bgcolor="#171c25", thickness=.08),
        ),
    )
    return fig


def _flow_diagram(t: dict[str, float], soc: float, best) -> None:
    net_batt = t["charge"] - t["discharge"]
    batt_action = "chargée" if net_batt >= 0 else "déchargée"
    st.markdown(
        f"""
        <div class="em-flow-shell">
          <div class="em-flow-node"><span class="em-flow-icon">☀</span><b>Surplus solaire</b><strong class="green">{_fmt(t['exp_before'])} kWh</strong></div>
          <div class="em-flow-arrow">→</div>
          <div class="em-flow-node em-battery"><span class="em-flow-icon">▣</span><b>Batterie {float(best.Cap_kWh):.0f} kWh</b><strong class="blue">SOC {soc:.0f} %</strong><small>{_fmt(t['charge'])} kWh chargés · {_fmt(t['discharge'])} kWh restitués</small></div>
          <div class="em-flow-arrow">→</div>
          <div class="em-flow-node"><span class="em-flow-icon">⌂</span><b>Site</b><strong class="purple">{_fmt(t['discharge'])} kWh fournis</strong></div>
          <div class="em-flow-arrow">↔</div>
          <div class="em-flow-node"><span class="em-flow-icon">⚡</span><b>Réseau</b><strong class="orange">{_fmt(t['imp_after'])} kWh importés</strong><small>{_fmt(t['exp_after'])} kWh injectés</small></div>
        </div>
        <div class="em-flow-caption">Sur la période sélectionnée, la batterie a été globalement {batt_action} de {_fmt(abs(net_batt))} kWh.</div>
        """,
        unsafe_allow_html=True,
    )


def _statistics(t: dict[str, float]) -> None:
    captured = _ratio(t["charge"], t["exp_before"])
    covered = _ratio(t["discharge"], t["imp_before"])
    import_reduction = _ratio(t["imp_before"] - t["imp_after"], t["imp_before"])
    export_reduction = _ratio(t["exp_before"] - t["exp_after"], t["exp_before"])
    st.markdown(
        f"""
        <div class="em-kpi-grid">
          <div class="em-kpi"><span>Surplus solaire</span><strong class="green">{_fmt(t['exp_before'])} kWh</strong><small>Avant batterie</small></div>
          <div class="em-kpi"><span>Énergie stockée</span><strong class="blue">{_fmt(t['charge'])} kWh</strong><small>{captured:.0%} du surplus</small></div>
          <div class="em-kpi"><span>Énergie restituée</span><strong class="purple">{_fmt(t['discharge'])} kWh</strong><small>{covered:.0%} des besoins réseau initiaux</small></div>
          <div class="em-kpi"><span>Import après batterie</span><strong class="orange">{_fmt(t['imp_after'])} kWh</strong><small>-{import_reduction:.0%} par rapport à avant</small></div>
          <div class="em-kpi"><span>Injection après batterie</span><strong class="cyan">{_fmt(t['exp_after'])} kWh</strong><small>-{export_reduction:.0%} par rapport à avant</small></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_energy_dashboard(df: pd.DataFrame, sim, best) -> None:
    st.markdown(
        f"""
        <style>
        .em-head{{display:flex;justify-content:space-between;align-items:end;margin:1.5rem 0 .7rem}}
        .em-title{{font-size:1.75rem;font-weight:850;letter-spacing:-.02em;color:{TEXT}}}
        .em-subtitle{{color:{MUTED};font-size:.9rem;margin-top:.2rem}}
        .em-badge{{background:rgba(239,91,50,.13);border:1px solid rgba(239,91,50,.45);color:#ff9a7d;padding:.35rem .65rem;border-radius:999px;font-size:.78rem;font-weight:750}}
        .em-chart-shell{{background:{PANEL_2};border:1px solid rgba(148,163,184,.16);border-radius:18px;padding:4px 12px 2px;box-shadow:0 16px 42px rgba(0,0,0,.20)}}
        .em-flow-shell{{display:grid;grid-template-columns:1fr auto 1.25fr auto 1fr auto 1fr;align-items:stretch;gap:12px;margin:20px 0 8px}}
        .em-flow-node{{background:linear-gradient(180deg,#171c25,#12161e);border:1px solid rgba(148,163,184,.17);border-radius:16px;padding:18px;display:flex;flex-direction:column;gap:6px;min-height:120px;justify-content:center}}
        .em-flow-node b{{font-size:.9rem;color:#e5e7eb}} .em-flow-node strong{{font-size:1.2rem}} .em-flow-node small{{color:{MUTED};font-size:.75rem}}
        .em-flow-icon{{font-size:1.45rem;color:#f8fafc}} .em-flow-arrow{{display:flex;align-items:center;color:#64748b;font-size:1.35rem}}
        .em-battery{{border-color:rgba(79,140,255,.38);box-shadow:inset 0 0 28px rgba(79,140,255,.05)}}
        .em-flow-caption{{color:{MUTED};font-size:.78rem;text-align:center;margin-bottom:18px}}
        .em-kpi-grid{{display:grid;grid-template-columns:repeat(5,minmax(150px,1fr));gap:12px;margin:16px 0 10px}}
        .em-kpi{{background:linear-gradient(180deg,#171c25,#12161e);border:1px solid rgba(148,163,184,.17);border-radius:16px;padding:17px 18px;min-height:118px}}
        .em-kpi span{{display:block;color:#dbe3ee;font-size:.82rem;font-weight:700;margin-bottom:12px}} .em-kpi strong{{display:block;font-size:1.42rem;white-space:nowrap}} .em-kpi small{{display:block;color:{MUTED};font-size:.75rem;margin-top:8px}}
        .green{{color:{GREEN}}}.blue{{color:{BLUE}}}.purple{{color:{PURPLE}}}.orange{{color:{SOLEOL}}}.cyan{{color:{CYAN}}}
        @media(max-width:1100px){{.em-flow-shell{{grid-template-columns:1fr}}.em-flow-arrow{{display:none}}.em-kpi-grid{{grid-template-columns:repeat(2,1fr)}}}}
        </style>
        <div class="em-head"><div><div class="em-title">Gestion de l'énergie</div><div class="em-subtitle">Comportement énergétique simulé avec la batterie recommandée</div></div><div class="em-badge">{float(best.Cap_kWh):.0f} kWh · {float(best.Power_kW):.0f} kW</div></div>
        """,
        unsafe_allow_html=True,
    )

    frame = build_energy_frame(df, sim)
    if frame.empty:
        st.warning("Aucune donnée disponible pour la visualisation énergétique.")
        return

    mode, selected, use_power, x_title = _controls(frame)
    if selected.empty:
        st.warning("Aucune mesure disponible sur la période sélectionnée.")
        return

    st.markdown('<div class="em-chart-shell">', unsafe_allow_html=True)
    st.plotly_chart(_chart(selected, mode, use_power, x_title), use_container_width=True, config={"displaylogo": False})
    st.markdown("</div>", unsafe_allow_html=True)

    t = _totals(selected)
    soc = float(selected["soc_pct"].iloc[-1]) if "soc_pct" in selected and not selected.empty else 0.0
    _flow_diagram(t, soc, best)
    _statistics(t)
    st.caption(
        "Les courbes sont calculées à partir des mesures d'import/export et de la simulation. "
        "Les séries 'besoin réseau avant batterie' et 'injection réseau' peuvent être activées dans la légende. "
        "Une courbe complète production PV / consommation totale nécessitera un profil PV quart-horaire."
    )
