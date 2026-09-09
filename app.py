"""Interface française du calculateur de batterie.

Lancement : python -m streamlit run app.py
Une grille physique en cache alimente tous les graphiques et le dimensionnement.
"""
from __future__ import annotations
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import tempfile
from zipfile import ZipFile

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from loaders import load_meter_files, prepare_simulation_data, UnsupportedFormatError
from simulation import grid_search, simulate, simple_payback, HAS_NUMBA
from recommend import MODE_SETTINGS, fixed_grid, recommend
from grd_profiles import GRD_PROFILES, get_profile, parse_periods
from i18n import t, msg, recommendation_messages, study_assumptions
from energy_dashboard import render_energy_dashboard
from report import generate_battery_report, SECTION_LABELS, monthly_before_after


ORIGINAL_CSS = """
    <style>
    :root {
        --card-bg: rgba(17, 24, 39, 0.72);
        --card-border: rgba(148, 163, 184, 0.20);
        --muted: #94a3b8;
        --blue: #3b82f6;
        --green: #4ade80;
        --orange: #fb923c;
        --purple: #a855f7;
    }
    .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
        max-width: 1500px;
    }
    section[data-testid="stSidebar"] {
        border-right: 1px solid rgba(148, 163, 184, 0.18);
    }
    .mar-summary-title {
        font-size: 1.65rem;
        font-weight: 800;
        letter-spacing: .02em;
        margin: 1.4rem 0 .8rem 0;
        text-transform: uppercase;
    }
    .mar-card-grid-5 {
        display: grid;
        grid-template-columns: repeat(5, minmax(150px, 1fr));
        gap: 14px;
        margin-bottom: 14px;
    }
    .mar-card-grid-2 {display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin-bottom:12px;}
.mar-card-grid-3 {
        display: grid;
        grid-template-columns: repeat(3, minmax(220px, 1fr));
        gap: 12px;
        margin-bottom: 14px;
    }
    .mar-card-grid-1of3 {
        display: grid;
        grid-template-columns: repeat(3, minmax(220px, 1fr));
        gap: 12px;
        margin-top: -2px;
        margin-bottom: 14px;
    }
    .mar-card {
        background: linear-gradient(180deg, rgba(15, 23, 42, 0.94), rgba(2, 6, 23, 0.88));
        border: 1px solid var(--card-border);
        border-radius: 14px;
        padding: 16px 18px;
        min-height: 128px;
        box-shadow: 0 14px 35px rgba(0,0,0,.22);
    }
    .mar-card.small {
        min-height: 118px;
        padding: 14px 16px;
    }
    .mar-label {
        color: #e5e7eb;
        font-size: .94rem;
        font-weight: 700;
        margin-bottom: 14px;
        display: flex;
        align-items: center;
        gap: 8px;
    }
    .mar-icon {
        font-size: 1.35rem;
        line-height: 1;
    }
    .mar-value {
        font-size: 2.05rem;
        font-weight: 800;
        line-height: 1.05;
        white-space: nowrap;
    }
    .mar-value.small {
        font-size: 1.8rem;
    }
    .mar-sub {
        color: var(--muted);
        font-size: .85rem;
        margin-top: 8px;
    }
    .mar-blue { color: var(--blue); }
    .mar-green { color: var(--green); }
    .mar-orange { color: var(--orange); }
    .mar-purple { color: var(--purple); }
    .mar-autoconso {
        background: linear-gradient(180deg, rgba(15, 23, 42, 0.96), rgba(2, 6, 23, 0.90));
        border: 1px solid var(--card-border);
        border-radius: 14px;
        padding: 18px 22px;
        margin: 8px 0 20px 0;
        box-shadow: 0 14px 35px rgba(0,0,0,.22);
    }
    .mar-autoconso-grid {
        display: grid;
        grid-template-columns: 1fr 1fr 1fr;
        gap: 18px;
        text-align: center;
        margin-top: 10px;
    }
    .mar-autoconso-cell {
        border-left: 1px solid rgba(148, 163, 184, 0.25);
    }
    .mar-autoconso-cell:first-child {
        border-left: none;
    }
    .mar-pill {
        display: inline-block;
        padding: 4px 9px;
        border-radius: 999px;
        font-size: .78rem;
        font-weight: 700;
        background: rgba(34, 197, 94, .15);
        color: #86efac;
        margin-top: 8px;
    }
    @media (max-width: 1100px) {
        .mar-card-grid-5, .mar-card-grid-3, .mar-card-grid-1of3 {
            grid-template-columns: repeat(2, minmax(160px, 1fr));
        }
        .mar-autoconso-grid {
            grid-template-columns: 1fr;
        }
        .mar-autoconso-cell {
            border-left: none;
            border-top: 1px solid rgba(148, 163, 184, 0.25);
            padding-top: 12px;
        }
        .mar-autoconso-cell:first-child {
            border-top: none;
        }
    }
    </style>
    """

@st.cache_data(show_spinner=False, max_entries=8)
def _load_cached(files, data_unit, position, ambiguous, minutes, same_meter, aggregate_devices=False, blank_policy="auto"):
    if sum(len(data) for _, data in files) > 100 * 1024**2:
        raise UnsupportedFormatError("Lot trop volumineux : maximum 100 Mo.")
    with tempfile.TemporaryDirectory() as directory:
        paths = []
        for index, (name, data) in enumerate(files):
            if len(data) > 30 * 1024**2:
                raise UnsupportedFormatError("Un fichier dépasse la limite de 30 Mo.")
            # User names never become filesystem paths.
            suffix = Path(name).suffix.lower()
            path = Path(directory) / f"mesures_{index:03d}{suffix}"
            path.write_bytes(data)
            if suffix == ".xlsx":
                with ZipFile(path) as archive:
                    if sum(z.file_size for z in archive.infolist()) > 250 * 1024**2:
                        raise UnsupportedFormatError("Classeur trop volumineux après décompression (250 Mo maximum).")
            paths.append(path)
        frame, meta = load_meter_files(paths, data_unit, timestamp_position=position,
            ambiguous_policy=ambiguous, interval_minutes=minutes, same_meter=same_meter,
            aggregate_devices=aggregate_devices, blank_policy=blank_policy)
    return frame, replace(meta, source="; ".join(name for name, _ in files))


@st.cache_data(show_spinner=False, max_entries=10)
def _grid_cached(imp, exp, caps, powers, options, max_c_rate):
    return grid_search(imp, exp, caps, powers, max_c_rate=max_c_rate, **options)


@st.cache_data(show_spinner=False, max_entries=16)
def _simulate_cached(imp, exp, capacity, power, options):
    return simulate(imp, exp, capacity, power, **options)


def _fmt(value, digits=0):
    return f"{float(value):,.{digits}f}".replace(",", " ")


def _tariff_settings():
    st.sidebar.markdown("**Tarifs énergie**")
    name = st.sidebar.selectbox("Profil tarifaire GRD", list(GRD_PROFILES),
        index=list(GRD_PROFILES).index("Groupe E"), key="tariff_profile")
    year = int(st.sidebar.number_input("Année du scénario tarifaire", min_value=2000, max_value=2100,
                                       value=2026, step=1, key="tariff_year"))
    profile = get_profile(name, year)
    token = f"{name}_{year}"
    st.sidebar.caption(profile["price_note"])
    unique = st.sidebar.checkbox("Tarif achat unique 24h/24", value=bool(profile.get("single_tariff", False)),
                                  key=f"unique_{token}")
    ht = st.sidebar.number_input("Tarif achat " + ("unique" if unique else "HT") + " (CHF/kWh)",
        value=float(profile["ht"]), step=.001, format="%.4f", key=f"ht_{token}")
    bt = ht if unique else st.sidebar.number_input("Tarif achat BT (CHF/kWh)",
        value=float(profile["bt"]), step=.001, format="%.4f", key=f"bt_{token}")
    export = st.sidebar.number_input("Tarif reprise (CHF/kWh)", value=float(profile["export"]),
                                     step=.001, format="%.4f", key=f"export_{token}")
    with st.sidebar.expander("Horaires et référence tarifaire"):
        period_text = st.text_input("Plages HT (ex. 7-12;17-23)",
            value=";".join(f"{a:g}-{b:g}" for a, b in profile["periods"]),
            key=f"periods_{token}", disabled=unique)
        weekend = st.checkbox("Week-end entièrement BT", value=bool(profile["weekend_low"]),
                              key=f"weekend_{token}", disabled=unique)
        st.caption(profile.get("source", "Contrat à vérifier"))
        note = st.text_input("Référence du contrat / produit", value="", key=f"contract_{token}")
    periods = () if unique else parse_periods(period_text)
    return dict(name=name, year=year, ht=float(ht), bt=float(bt), export=float(export),
                periods=periods, weekend=False if unique else weekend, note=note)


def _calendar(meta, tariffs):
    mode = st.selectbox("Application des tarifs", ["Scénario tarifaire unique", "Calendrier par période"], key="tariff_application")
    if mode == "Scénario tarifaire unique":
        note = (f"Tarifs du scénario {tariffs['year']} appliqués à tous les intervalles mesurés, "
                "aux jours et heures de la courbe source. Ce n'est pas une reconstitution des factures historiques.")
        st.caption(note)
        return None, note
    st.caption("Chaque période est définie par un début inclus et une fin exclue. Renseigner les prix et horaires du contrat ; aucun trou ni chevauchement n'est accepté.")
    first = pd.Timestamp(meta.start).year
    last = (pd.Timestamp(meta.end) - pd.Timedelta(seconds=1)).year
    defaults = []
    for year in range(first, last + 1):
        profile = get_profile(tariffs["name"], year)
        defaults.append({"Début": f"{year}-01-01", "Fin exclue": f"{year+1}-01-01",
                         "HT": tariffs["ht"], "BT": tariffs["bt"], "Reprise": tariffs["export"],
                         "Plages HT": ";".join(f"{a:g}-{b:g}" for a, b in profile["periods"]),
                         "Week-end BT": profile["weekend_low"]})
    table = st.data_editor(pd.DataFrame(defaults), num_rows="dynamic", hide_index=True,
        key=f"calendar_{meta.fingerprint}_{tariffs['name']}", width="stretch")
    table["Plages HT"] = table["Plages HT"].fillna("")
    if table.empty or table.isna().any().any():
        raise ValueError("Renseigner toutes les cellules du calendrier tarifaire.")
    schedule = []
    for _, row in table.iterrows():
        schedule.append(dict(start=str(row["Début"]), end=str(row["Fin exclue"]), ht=float(row.HT),
            bt=float(row.BT), export=float(row.Reprise), periods=parse_periods(row["Plages HT"]),
            weekend_low=bool(row["Week-end BT"])))
    return schedule, "Calendrier explicite de prix et horaires, appliqué aux dates réelles des mesures."





def _render_original_summary(sim, rec, meta, mode):
    best = rec.best
    study_mode = mode
    soc_min_pct = sim.soc_min_pct
    TECHNICAL_SOC_MIN_PCT = reserve_boundary_pct = soc_min_pct
    technical_reserve_best_kwh = sim.capacity_kWh - sim.usable_capacity_kWh
    usable_capacity_best_kwh = sim.usable_capacity_kWh
    rec_range_label = f"{sim.capacity_kWh:g} kWh"
    import_before_total, import_after_total, import_avoided_total = sim.import_before, sim.import_after_total, sim.import_avoided
    export_before_total, export_after_total, export_avoided_total = sim.export_before, sim.export_after_total, sim.export_stored
    import_reduction_pct, export_reduction_pct = 100 * sim.import_reduction, 100 * sim.surplus_captured
    autoconso_gain_pct = sim.import_avoided / sim.export_before * 100 if sim.export_before > 0 else 0.
    days = sim.valid.sum() * sim.dt_hours / 24
    surplus_average_kwh_per_day = sim.export_before / days if days > 0 else 0.
    gain_label = "Économies annuelles" if sim.annual_factor is not None else "Économies sur la période"
    gain_value = sim.gain_annual_chf if sim.annual_factor is not None else sim.gain_chf
    gain_unit = "CHF/an" if sim.annual_factor is not None else "CHF"
    cycles_value = sim.cycles_per_year if sim.annual_factor is not None else sim.cycles_period
    cycles_unit = "/an" if sim.annual_factor is not None else ""
    cycle_verdict = "Utilisation correcte" if rec.recommended and sim.annual_factor is not None else "À confirmer"
    _fmt_kwh = _fmt_chf = _fmt
    st.markdown('<div class="mar-summary-title">Résumé de la simulation</div>', unsafe_allow_html=True)

    st.markdown(
        f"""
        <div class="mar-card-grid-5">
            <div class="mar-card">
                <div class="mar-label"><span class="mar-icon">🔋</span>Capacité batterie</div>
                <div class="mar-value mar-blue">{rec_range_label}</div>
                <div class="mar-sub">Valeur centrale simulée : {best.Cap_kWh:g} kWh</div>
            </div>
            <div class="mar-card">
                <div class="mar-label"><span class="mar-icon">⚡</span>Puissance batterie</div>
                <div class="mar-value mar-blue">{best.Power_kW:g} kW</div>
                <div class="mar-sub">Puissance de charge/décharge</div>
            </div>
            <div class="mar-card">
                <div class="mar-label"><span class="mar-icon">💰</span>{gain_label}</div>
                <div class="mar-value mar-green">{_fmt_chf(gain_value)} {gain_unit}</div>
                <div class="mar-sub">Gain net HT/BT/revente</div>
            </div>
            <div class="mar-card">
                <div class="mar-label"><span class="mar-icon">♻️</span>Cycles équivalents</div>
                <div class="mar-value mar-purple">{cycles_value:.0f}{cycles_unit}</div>
                <div class="mar-pill">{cycle_verdict}</div>
            </div>
            <div class="mar-card">
                <div class="mar-label"><span class="mar-icon">🟠</span>Surplus capté</div>
                <div class="mar-value mar-orange">{sim.surplus_captured:.0%}</div>
                <div class="mar-sub">du surplus solaire</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if study_mode == "ci":
        st.markdown(
            f"""
            <div class="mar-card-grid-3">
                <div class="mar-card">
                    <div class="mar-label"><span class="mar-icon">🔒</span>Capacité non utilisée</div>
                    <div class="mar-value mar-blue">{technical_reserve_best_kwh:,.0f} kWh</div>
                    <div class="mar-sub">Zone 0-{TECHNICAL_SOC_MIN_PCT:.0f} % · non utilisée</div>
                </div>
                <div class="mar-card">
                    <div class="mar-label"><span class="mar-icon">🛡️</span>SOC minimum</div>
                    <div class="mar-value mar-blue">{soc_min_pct:.0f} %</div>
                    <div class="mar-sub">Limite basse choisie</div>
                </div>
                <div class="mar-card">
                    <div class="mar-label"><span class="mar-icon">🔋</span>Capacité autoconsommation</div>
                    <div class="mar-value mar-blue">{usable_capacity_best_kwh:,.0f} kWh</div>
                    <div class="mar-sub">Zone {reserve_boundary_pct:.0f}-100 %</div>
                </div>
            </div>
            """.replace(",", " "),
            unsafe_allow_html=True,
        )

    st.markdown(
        f"""
        <div class="mar-card-grid-3">
            <div class="mar-card small">
                <div class="mar-label"><span class="mar-icon">🔌</span>Import avant</div>
                <div class="mar-value small mar-blue">{_fmt_kwh(import_before_total)} kWh</div>
                <div class="mar-sub">Depuis le réseau</div>
            </div>
            <div class="mar-card small">
                <div class="mar-label"><span class="mar-icon">🏠</span>Import après</div>
                <div class="mar-value small mar-blue">{_fmt_kwh(import_after_total)} kWh</div>
                <div class="mar-sub">Depuis le réseau</div>
            </div>
            <div class="mar-card small">
                <div class="mar-label"><span class="mar-icon">⬇️</span>Import évité</div>
                <div class="mar-value small mar-green">{_fmt_kwh(import_avoided_total)} kWh</div>
                <div class="mar-sub">-{import_reduction_pct:.0f} %</div>
            </div>
        </div>

        <div class="mar-card-grid-3">
            <div class="mar-card small">
                <div class="mar-label"><span class="mar-icon">🔆</span>Export avant</div>
                <div class="mar-value small mar-orange">{_fmt_kwh(export_before_total)} kWh</div>
                <div class="mar-sub">Vers le réseau</div>
            </div>
            <div class="mar-card small">
                <div class="mar-label"><span class="mar-icon">🏡</span>Export après</div>
                <div class="mar-value small mar-orange">{_fmt_kwh(export_after_total)} kWh</div>
                <div class="mar-sub">Vers le réseau</div>
            </div>
            <div class="mar-card small">
                <div class="mar-label"><span class="mar-icon">⬇️</span>Export évité</div>
                <div class="mar-value small mar-green">{_fmt_kwh(export_avoided_total)} kWh</div>
                <div class="mar-sub">-{export_reduction_pct:.0f} %</div>
            </div>
        </div>

        <div class="mar-card-grid-1of3">
            <div class="mar-card small">
                <div class="mar-label"><span class="mar-icon">📊</span>Surplus moyen</div>
                <div class="mar-value small mar-purple">{_fmt_kwh(surplus_average_kwh_per_day)} kWh/jour</div>
                <div class="mar-sub">Moyenne réinjectée sur la période analysée</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        f"""
        <div class="mar-autoconso">
            <div class="mar-label"><span class="mar-icon">☀️</span>Autoconsommation / valorisation du surplus solaire</div>
            <div class="mar-autoconso-grid">
                <div>
                    <div class="mar-sub">Surplus initial</div>
                    <div class="mar-value small mar-orange">{_fmt_kwh(export_before_total)} kWh</div>
                </div>
                <div class="mar-autoconso-cell">
                    <div class="mar-sub">Surplus stocké par la batterie</div>
                    <div class="mar-value small mar-green">{_fmt_kwh(export_avoided_total)} kWh</div>
                </div>
                <div class="mar-autoconso-cell">
                    <div class="mar-sub">Surplus restitué au site</div>
                    <div class="mar-value small mar-green">{autoconso_gain_pct:.0f} %</div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )





ORIGINAL_LABELS = {'uploader': 'Fichiers compteur (Huawei / Groupe E / SolarEdge, Excel ou CSV ; vous pouvez déposer les '
             "12 fichiers mensuels Huawei d'un coup)",
 'drop_prompt': "⬆️ Déposez un ou plusieurs fichiers pour lancer l'analyse.",
 'legend_gain': 'Gain sur la période (CHF)',
 'legend_cycles': 'Cycles/an',
 'legend_recommended': 'Recommandé',
 'legend_maxgain': 'Gain max',
 'axis_capacity': 'Capacité (kWh)',
 'axis_gain': 'Gain (CHF/an)',
 'axis_cycles': 'Cycles DC/an (capacité utile)',
 'col_pct_max': '% du gain max',
 'axis_soc': 'SOC (%)',
 'axis_date': 'Date',
 'soc_title': 'État de charge, {cap} kWh / {power} kW',
 'cyc_legend_cum': 'Cycles cumulés',
 'cyc_legend_steady': 'rythme constant (idéal)',
 'cyc_axis': 'Cycles équivalents cumulés',
 'cyc_title': 'Cycles cumulés sur la période simulée',
 'ba_axis': 'kWh / mois',
 'pay_earns_title': "Ce que chaque kWh ajouté RAPPORTE vs ce qu'il COÛTE à posséder",
 'pay_earns_axis': 'CHF/an gagnés par ce kWh',
 'pay_nth_axis': 'le N-ième kWh de capacité',
 'pay_own_band': 'coûte à posséder 1 kWh/an ({lo:.0f}-{hi:.0f} CHF)',
 'pay_kpi_rec': 'Taille recommandée',
 'pay_kpi_payback': 'Rentabilité à cette taille',
 'pay_kpi_best': 'Taille la plus rentable',
 'pay_yr_val': '{v} ans',
 'pay_verdict': 'Configuration étudiée : {rec} kWh ({cyc} cycles DC/an).',
 'pay_health_title': 'Économies selon la taille, prendre la plus haute barre **VERTE** (la plus grande '
                     'encore pleinement cyclée)',
 'pay_health_caption': 'Vert = cycle encore ≥ {low}/an (chaque kWh est utilisé). Gris = surdimensionné '
                       '(sous {low}/an, capacité qui dort). Les économies montent toujours avec la '
                       'taille, mais au-delà du vert vous payez de la capacité inutilisée : le meilleur '
                       'achat est donc la plus haute barre verte.',
 'pay_rec_star': '★ {cap} kWh',
 'pay_oversized_note': 'surdimensionné : capacité inutilisée',
 'pay_legend_healthy': 'pleinement cyclée (saine)',
 'pay_legend_oversized': 'surdimensionnée (capacité qui dort)',
 'pay_earns_caption': 'Chaque barre = ce que rapporte le **kWh suivant** par an ; la bande grise = ce '
                      "qu'un kWh **coûte à posséder** par an. Règle d'arrêt : ajouter des kWh tant que "
                      "les barres atteignent la bande, s'arrêter quand elles passent nettement en "
                      "dessous (vert = clairement rentable · orange = à l'équilibre · rouge = coûte "
                      "plus qu'il ne rapporte). Le 1er kWh rapporte en général le plus, c'est la courbe "
                      "qui s'aplatit, pas une raison de n'acheter qu'1 kWh.",
 'pay_status_green': "À vos prix, la taille recommandée **{rec} kWh** rapporte encore plus qu'elle ne "
                     'coûte (vert) : la vue monétaire et le choix par cycles concordent.',
 'pay_status_amber': "À vos prix, la taille recommandée **{rec} kWh** est à l'équilibre (orange) : "
                     'monétaire et choix par cycles concordent à peu près.',
 'pay_status_red': "À vos prix, la taille recommandée **{rec} kWh** coûte déjà plus par kWh qu'elle ne "
                   'rapporte (rouge). Elle est dimensionnée pour un **cyclage sain, pas pour la '
                   "rentabilité** : si l'argent prime, réduire vers **{pb} kWh** (le creux de "
                   'rentabilité) ou la dernière barre verte.',
 'pay_rec_line': 'Recommandé : {cap} kWh',
 'pay_rec_caption': 'La barre verte la plus haute est le **1er kWh**, pas le meilleur achat. La ligne '
                    'verticale marque la taille **recommandée ({cap} kWh)** : la plus grande qui reste '
                    'dans la bande de cycles saine.',
 'pay_pb_title': 'Rentabilité système (coût fixe + modules), en U : 1 kWh et 20 kWh perdent',
 'pay_pb_axis': 'Retour sur investissement (ans)',
 'pay_life_line': 'Horizon de comparaison : {life} ans',
 'pay_best_label': 'moins mauvais',
 'pay_pb_caption': "Le coût fixe d'installation se répartit sur la capacité, d'où un U : trop petit "
                   'gaspille les frais fixes, trop grand porte de la capacité inutilisée. Le creux '
                   '**{pb} kWh** est la taille au meilleur retour. Le choix affiché **{rec} kWh** est '
                   "décidé sur les cycles (sans prix) ; s'ils diffèrent, **{pb} kWh** est le choix "
                   'monétaire et **{rec} kWh** le mieux cyclé : choisir selon ce que le client '
                   'privilégie.',
 'pay_curve_marg': 'le N-ième kWh rapporte',
 'pay_curve_total': 'gain total (CHF/an)',
 'pay_curve_y_marg': 'CHF/an par kWh ajouté',
 'pay_curve_y_total': 'gain total (CHF/an)',
 'pay_curve_caption': 'Les économies totales montent toujours, mais chaque kWh ajouté rapporte moins '
                      "que le précédent (barres qui rétrécissent). La courbe s'aplatit car une batterie "
                      'se remplit de bas en haut, le 1er kWh capte le surplus de chaque jour, le '
                      'dernier seulement les rares gros jours. **Gain max** surdimensionne car il '
                      'chasse cette queue plate.',
 'pay_cycles_use': 'cycles/an (usage)',
 'pay_cycles_frac': 'capacité cyclée par jour',
 'pay_cycles_healthy': 'Seuil interne : {low}–{high} cycles DC/an',
 'pay_cycles_oversized': 'Repère de cycles : 150/an',
 'pay_cycles_y2': 'Cycles DC par jour',
 'pay_cycles_caption': "Les cycles/an mesurent l'intensité d'usage de chaque kWh. Au-dessus de {low} = "
                       'chaque kWh utilisé quotidiennement (bande verte) ; sous 150 = capacité inactive '
                       '(surdimensionné). La taille recommandée est la plus grande qui reste dans le '
                       'vert , un indicateur sans prix de **bien utilisée**.',
 'pay_best_annot_undersized': 'moins mauvais (optimum monétaire)<br>{cap} kWh · {pb} an<br>mais ~{gap} '
                              'CHF/an de moins<br>que {rec} kWh, encore bien cyclé →<br>pourquoi on '
                              'agrandit',
 'pay_best_annot_oversized': 'moins mauvais (optimum monétaire)<br>{cap} kWh · {pb} an<br>mais {cyc} '
                             'cycles/an &lt; {low} :<br>capacité sous-utilisée →<br>pourquoi on ne '
                             'choisit pas ça',
 'pay_best_annot_agree': 'optimum monétaire = recommandé<br>{cap} kWh · {pb} an<br>retour et cycles '
                         'concordent ici',
 'pay_rec_annot': 'recommandé : {cap} kWh (sain en cycles)',
 'pay_pb_hover': '{cap} kWh → retour {pb} an',
 'pay_cycles_hover': '{cap} kWh · {cyc} cycles/an',
 'pay_cycles_hover2': '{cap} kWh · {frac}× capacité/jour',
 'pdf_button': '⬇️ Télécharger le rapport PDF',
 'pdf_filename': 'bilan_batterie.pdf'}

def _original_label(key, **fmt):
    return ORIGINAL_LABELS[key].format(**fmt)

def _payback_reason(F, T, rec_cap, cycles_low):
    """Why the recommendation differs from the payback low-point (money optimum).

    The money optimum and the recommended (cycles-healthy) size can land on either side of
    each other, and the *reason* we don't pick the money optimum flips with it:
      - low-point SMALLER than recommended -> it's harder-cycled, but leaves savings on the
        table (the older text wrongly called this "under-used" — e.g. 291 cyc/yr is NOT < 250);
      - low-point LARGER -> genuinely under-cycled (capacity sits idle);
      - same capacity -> the two views agree, nothing to warn about.
    Returns (best_row, annotation_text)."""
    best = F.loc[F.payback_yr.idxmin()]
    best_cap = float(best.Cap_kWh)
    common = dict(cap=f"{best_cap:.0f}", pb=f"{best.payback_yr:.0f}")
    if abs(best_cap - rec_cap) < 0.5:
        text = T("pay_best_annot_agree", **common)
    elif best_cap < rec_cap:
        rec_row = F.loc[(F.Cap_kWh - rec_cap).abs() < 0.5]
        gap = float(rec_row.Gain_CHF.iloc[0]) - float(best.Gain_CHF) if not rec_row.empty else 0.0
        text = T("pay_best_annot_undersized", gap=f"{max(gap, 0):,.0f}",
                 rec=f"{rec_cap:.0f}", **common)
    else:
        text = T("pay_best_annot_oversized", cyc=f"{best.Cycles_per_year:.0f}",
                 low=int(cycles_low), **common)
    return best, text

def _fig_payback(F, T, life, rec_cap, cycles_low):
    """Lens 3 — whole-system payback (fixed install + modules). U-shaped: 1 kWh and 20 kWh
    both lose. The least-bad trough is the money-optimal size; the recommended vline is the
    cycles-healthy pick — the two annotations make the distinction explicit in the viz."""
    fig = go.Figure(go.Scatter(
        x=F.Cap_kWh, y=F.payback_yr, mode="lines+markers", line=dict(color="#7c3aed", width=3),
        hovertemplate=T("pay_pb_hover", cap="%{x:.0f}", pb="%{y:.1f}") + "<extra></extra>"))
    fig.add_hline(y=life, line_dash="dash", line_color="#dc2626",
                  annotation_text=T("pay_life_line", life=life),
                  annotation_position="bottom right")
    best, best_text = _payback_reason(F, T, rec_cap, cycles_low)
    # The orange box (money optimum) sits up-LEFT of the trough; the green recommended label
    # sits up-RIGHT of its line, so the two never overlap regardless of which side the
    # recommendation lands on.
    fig.add_annotation(
        x=float(best.Cap_kWh), y=float(best.payback_yr),
        text=best_text, xanchor="right",
        showarrow=True, arrowhead=2, ax=-50, ay=-55, bgcolor="#fff7ed", bordercolor="#f97316",
        borderwidth=1, borderpad=4, font=dict(color="black", size=11))
    fig.add_vline(x=rec_cap, line_color="#16a34a",
                  annotation_text=T("pay_rec_annot", cap=f"{rec_cap:.0f}"),
                  annotation_position="top right",
                  annotation_font=dict(color="black", size=11),
                  annotation_bgcolor="#dcfce7", annotation_bordercolor="#16a34a",
                  annotation_borderwidth=1, annotation_borderpad=3)
    fig.update_layout(title=T("pay_pb_title"), xaxis=dict(title=T("axis_capacity"), dtick=2),
                      yaxis_title=T("pay_pb_axis"), template="plotly_white",
                      hoverlabel=dict(bgcolor="#1f2937", font=dict(color="white", size=12),
                                      bordercolor="#7c3aed"),
                      height=380, margin=dict(t=60, r=50, l=60, b=50))
    return fig

def _fig_cycles(F, T, cycles_low, cycles_high, rec_cap):
    """Lens 4 — cycles/yr + capacity cycled per day, with the healthy band. The price-free
    proxy for 'is this capacity actually used?' — the floor recommend.py optimizes on."""
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Scatter(
        x=F.Cap_kWh, y=F.Cycles_per_year, name=T("pay_cycles_use"),
        mode="lines+markers", line=dict(color="#0891b2", width=3),
        hovertemplate=T("pay_cycles_hover", cap="%{x:.0f}", cyc="%{y:.0f}") + "<extra></extra>",
        cliponaxis=False), secondary_y=False)
    fig.add_trace(go.Scatter(
        x=F.Cap_kWh, y=F.frac_full_per_day, name=T("pay_cycles_frac"),
        mode="lines+markers", line=dict(color="#65a30d", width=2, dash="dot"),
        hovertemplate=T("pay_cycles_hover2", cap="%{x:.0f}", frac="%{y:.2f}") + "<extra></extra>",
        cliponaxis=False), secondary_y=True)
    fig.add_hrect(y0=cycles_low, y1=cycles_high, fillcolor="#86efac", opacity=0.25, line_width=0,
                  annotation_text=T("pay_cycles_healthy", low=int(cycles_low), high=int(cycles_high)),
                  annotation_position="top left", secondary_y=False)
    fig.add_hline(y=150, line_dash="dash", line_color="#dc2626",
                  annotation_text=T("pay_cycles_oversized"),
                  annotation_position="bottom left", secondary_y=False)
    fig.add_vline(x=rec_cap, line_color="#16a34a",
                  annotation_text=T("pay_rec_annot", cap=f"{rec_cap:.0f}"),
                  annotation_position="top right",
                  annotation_font=dict(color="black", size=11),
                  annotation_bgcolor="#dcfce7", annotation_bordercolor="#16a34a",
                  annotation_borderwidth=1, annotation_borderpad=3)
    fig.update_yaxes(title_text=T("axis_cycles"), secondary_y=False, color="#0891b2")
    fig.update_yaxes(title_text=T("pay_cycles_y2"), secondary_y=True, color="#65a30d")
    fig.update_layout(xaxis=dict(title=T("axis_capacity"), dtick=2), template="plotly_white",
                      hoverlabel=dict(bgcolor="#1f2937", font=dict(color="white", size=12),
                                      bordercolor="#0891b2"),
                      height=380, legend=dict(orientation="h", y=1.13),
                      margin=dict(t=60, r=70, l=60, b=50))
    return fig

def _render_original_tabs(frame, sim, rec, results, capex, mode, cap_min, cap_max, cycles_low):
    T = _original_label
    annual = sim.annual_factor is not None
    best, big = rec.best, rec.max_gain_pick
    cycles_col = "Cycles_per_year" if annual else "Cycles_period"
    cycles_axis = "Cycles DC/an" if annual else "Cycles DC sur la période"
    min_cycles_per_year, cycles_high = cycles_low, max(350., cycles_low + 100.)
    with st.sidebar.expander("Plage et pas d'affichage"):
        bounds = (float(rec.frontier.Cap_kWh.min()), float(rec.frontier.Cap_kWh.max()))
        if bounds[0] != bounds[1]:
            bounds = st.slider("Capacités affichées (kWh)", bounds[0], bounds[1], bounds, key=f"display_bounds_{mode}_{cap_min}_{cap_max}")
        stride = st.select_slider("Afficher un point sur", options=[1, 2, 5, 10], value=1, key="display_step")
        st.caption("Affichage uniquement ; la configuration étudiée reste identique.")
        st.download_button("Configurations simulées (CSV)", results.to_csv(index=False).encode("utf-8-sig"), "configurations_batterie.csv", "text/csv")
    f = rec.frontier.copy()
    f["Marginal_CHF_per_kWh"] = f.Gain_CHF.diff() / f.Cap_kWh.diff()
    display_frontier = f[f.Cap_kWh.between(*bounds)].iloc[::stride]
    tab_front, tab_pay, tab_soc, tab_cyc, tab_ba = st.tabs(
        ["📈 Gain vs capacité", "Rentabilité", "🔋 État de charge", "♻️ Cycles cumulés", "📊 Avant / Après"])
    with tab_front:
        f = display_frontier.copy()

        fig = go.Figure()
        if annual:
            fig.add_hrect(
            y0=min_cycles_per_year,
            y1=cycles_high,
            line_width=0,
            fillcolor="green",
            opacity=0.08,
            yref="y2",
            annotation_text="zone d'utilisation acceptable",
            annotation_position="top left",
        )
        fig.add_trace(go.Scatter(
            x=f.Cap_kWh,
            y=f.Gain_CHF,
            name=T("legend_gain"),
            mode="lines+markers",
            line=dict(color="#2563eb"),
        ))
        fig.add_trace(go.Scatter(
            x=f.Cap_kWh,
            y=f[cycles_col],
            name="Cycles DC/an" if annual else "Cycles DC sur la période",
            mode="lines+markers",
            line=dict(color="#16a34a", dash="dot"),
            yaxis="y2",
        ))
        fig.add_trace(go.Scatter(
            x=[best.Cap_kWh],
            y=[best.Gain_CHF],
            name=T("legend_recommended"),
            mode="markers",
            marker=dict(size=16, color="#2563eb", symbol="star"),
        ))
        fig.add_trace(go.Scatter(
            x=[big.Cap_kWh],
            y=[big.Gain_CHF],
            name=T("legend_maxgain"),
            mode="markers",
            marker=dict(size=12, color="#dc2626", symbol="x"),
        ))
        fig.update_layout(
            xaxis_title=T("axis_capacity"),
            yaxis_title="Économie sur la période (CHF)",
            yaxis2=dict(title=cycles_axis, overlaying="y", side="right"),
            legend=dict(orientation="h", y=1.12),
            height=450,
            margin=dict(t=40),
        )
        st.plotly_chart(fig, width="stretch")

        marginal_floor = float(getattr(rec, "marginal_floor_chf_per_kwh", 0.0) or 0.0)
        fig_marg = go.Figure()
        fig_marg.add_trace(go.Bar(
            x=f.Cap_kWh,
            y=f.Marginal_CHF_per_kWh.fillna(0.0),
            name="Gain du kWh ajouté",
            hovertemplate="Capacité %{x:.0f} kWh : +%{y:.1f} CHF sur la période par kWh ajouté<extra></extra>",
        ))
        fig_marg.add_hline(
            y=marginal_floor,
            line_dash="dash",
            line_color="#dc2626",
            annotation_text="Seuil relatif : 30% de la référence lissée",
            annotation_position="top right",
        )
        fig_marg.add_vline(
            x=float(best.Cap_kWh),
            line_color="#2563eb",
            annotation_text=f"Recommandé : {best.Cap_kWh:g} kWh",
            annotation_position="top left",
        )
        fig_marg.update_layout(
            title="Gain marginal de chaque kWh de batterie ajouté",
            xaxis_title="Capacité atteinte (kWh)",
            yaxis_title="CHF sur la période par kWh ajouté",
            height=330,
            margin=dict(t=55),
        )
        st.plotly_chart(fig_marg, width="stretch")
        st.caption(
            f"Le repérage utilise une fenêtre fixe de {MODE_SETTINGS[mode]['window']:g} kWh et un seuil de 30% de la référence marginale lissée. Les cycles DC restent un contrôle technique."
        )

        st.dataframe(
            f.assign(**{T("col_pct_max"): (f.Gain_CHF / rec.gain_max * 100).round(1) if rec.gain_max > 0 else np.nan})[
                ["Cap_kWh", "Power_kW", "Gain_CHF", T("col_pct_max"),
                 "Marginal_CHF_per_kWh", "Forward_marginal_CHF_per_kWh", cycles_col]
            ].round(3),
            width="stretch",
            hide_index=True,
        )

    with tab_pay:
        f = rec.frontier.copy()
        fixed = float(st.session_state.get("cost_fixed", 0.))
        module = float(st.session_state.get("cost_module", 0.))
        life = float(st.session_state.get("cost_life", 13.))
        has_cost_model = fixed > 0 or module > 0
        f["capex"] = fixed + module * f.Cap_kWh if has_cost_model else np.nan
        f["payback_yr"] = f.capex / f.Gain_annual_CHF.where(f.Gain_annual_CHF > 0)
        rec_pb = (fixed + module * sim.capacity_kWh) / sim.gain_annual_chf if has_cost_model and annual and sim.gain_annual_chf > 0 else simple_payback(capex, sim.gain_annual_chf)
        st.success(f"Configuration étudiée : {sim.capacity_kWh:g} kWh. Les coûts renseignés servent à comparer les retours simples.")
        m = st.columns(3)
        m[0].metric("Capacité recommandée" if rec.recommended else "Capacité étudiée", f"{sim.capacity_kWh:g} kWh")
        m[1].metric("Économies annuelles" if annual else "Économies sur la période", f"{_fmt(sim.gain_annual_chf if annual else sim.gain_chf)} CHF" + ("/an" if annual else ""))
        m[2].metric("Retour simple", f"{rec_pb:.1f} ans" if rec_pb is not None else "n/a")
        if f.payback_yr.notna().any():
            st.plotly_chart(_fig_payback(f, T, life, sim.capacity_kWh, cycles_low), width="stretch")
            st.caption("Comparaison avec le coût fixe et le prix par kWh renseignés, à profil et tarifs constants.")
        else:
            fig = go.Figure(go.Scatter(x=f.Cap_kWh, y=f.payback_yr, mode="lines+markers", line=dict(color="#7c3aed", width=3)))
            fig.add_annotation(text="Renseigner les coûts à gauche et disposer de gains annuels positifs", x=.5, y=.5, xref="paper", yref="paper", showarrow=False)
            fig.update_layout(title=T("pay_pb_title"), xaxis=dict(title=T("axis_capacity"), dtick=2), yaxis_title=T("pay_pb_axis"), template="plotly_white", height=380, margin=dict(t=60,r=50,l=60,b=50))
            st.plotly_chart(fig, width="stretch")
            st.caption("Aucun coût de batterie n'est présupposé. Un devis total ne suffit pas à comparer plusieurs capacités.")
        days = sim.valid.sum() * sim.dt_hours / 24
        f["frac_full_per_day"] = f.Cycles_period / days
        if annual:
            fig = _fig_cycles(f, T, cycles_low, cycles_high, sim.capacity_kWh)
        else:
            fig = make_subplots(specs=[[{"secondary_y": True}]])
            fig.add_trace(go.Scatter(x=f.Cap_kWh, y=f.Cycles_period, name="Cycles DC sur la période", mode="lines+markers", line=dict(color="#0891b2", width=3)), secondary_y=False)
            fig.add_trace(go.Scatter(x=f.Cap_kWh, y=f.frac_full_per_day, name="Cycles DC par jour simulé", mode="lines+markers", line=dict(color="#65a30d", width=2, dash="dot")), secondary_y=True)
            fig.add_vline(x=sim.capacity_kWh, line_color="#16a34a")
            fig.update_layout(xaxis=dict(title=T("axis_capacity"),dtick=2), template="plotly_white", height=380, legend=dict(orientation="h",y=1.13), margin=dict(t=60,r=70,l=60,b=50))
            fig.update_yaxes(title_text=cycles_axis, secondary_y=False, color="#0891b2")
            fig.update_yaxes(title_text="Cycles DC par jour simulé", secondary_y=True, color="#65a30d")
        st.plotly_chart(fig, width="stretch")
        st.caption("Cycles calculés à partir de la décharge interne DC et de la capacité utile. Le seuil annuel s'applique uniquement aux périodes annualisées.")
    df = frame
    ts = frame.timestamp.dt.tz_convert("Europe/Zurich")
    with tab_soc:
        usable_cap = getattr(sim, "usable_capacity_kWh", best.Cap_kWh)
        soc_min = getattr(sim, "soc_min_pct", 0.0)
        soc_pct = sim.soc_pct
        fig = go.Figure(go.Scatter(x=ts, y=soc_pct, mode="lines", line=dict(color="#7c3aed", width=1)))
        if sim.soc_min_pct > 0:
            fig.add_hline(
                y=sim.soc_min_pct,
                line_dash="dash",
                annotation_text=f"SOC minimum : {sim.soc_min_pct:g} %",
            )
        fig.update_layout(
            yaxis_title=T("axis_soc"),
            xaxis_title=T("axis_date"),
            yaxis=dict(range=[0, 100]),
            height=420,
            title=T("soc_title", cap=f"{best.Cap_kWh:.0f}", power=f"{best.Power_kW:.0f}"),
        )
        st.plotly_chart(fig, width="stretch")

    with tab_cyc:
        discharge = sim.discharge_by_interval / np.sqrt(sim.roundtrip_eff)
        usable_cap = getattr(sim, "usable_capacity_kWh", best.Cap_kWh)
        cum_cycles = np.nancumsum(discharge) / usable_cap if usable_cap > 0 else np.zeros_like(discharge)
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=ts, y=np.where(sim.valid, cum_cycles, np.nan), mode="lines", name=T("cyc_legend_cum"),
                                 line=dict(color="#16a34a")))
        # straight reference line = perfectly steady cycling
        fig.add_trace(go.Scatter(x=[ts.iloc[0], ts.iloc[-1]], y=[0, cum_cycles[-1]], mode="lines",
                                 name=T("cyc_legend_steady"), line=dict(color="#9ca3af", dash="dash")))
        fig.update_layout(yaxis_title="Cycles DC sur capacité utile", xaxis_title=T("axis_date"), height=420,
                          legend=dict(orientation="h", y=1.1), title=T("cyc_title"))
        st.plotly_chart(fig, width="stretch")

    with tab_ba:
        s = monthly_before_after(frame, sim).rename(columns={"Import avant":"import_kWh", "Export avant":"export_kWh", "Import après":"import_after", "Export après":"export_after"})
        months = s.index.astype(str)
        fig = go.Figure()
        fig.add_trace(go.Bar(x=months, y=s.import_kWh, name='Import avant', marker_color="#fca5a5"))
        fig.add_trace(go.Bar(x=months, y=s.import_after, name='Import après', marker_color="#dc2626"))
        fig.add_trace(go.Bar(x=months, y=s.export_kWh, name='Export avant', marker_color="#bfdbfe"))
        fig.add_trace(go.Bar(x=months, y=s.export_after, name='Export après', marker_color="#2563eb"))
        fig.update_layout(barmode="group", height=440, yaxis_title=T("ba_axis"),
                          xaxis=dict(type="category"), legend=dict(orientation="h", y=1.1))
        st.plotly_chart(fig, width="stretch")



def main():
    st.set_page_config(page_title="Calculateur de batterie", page_icon="🔋", layout="wide")
    st.markdown(ORIGINAL_CSS, unsafe_allow_html=True)
    st.title("🔋 Calculateur V2")
    st.caption(t("fr", "caption"))
    st.sidebar.header("⚙️ Paramètres")
    client = st.sidebar.text_input("Nom du client", placeholder="Ex. Jean Dupont", key="client_name")
    st.sidebar.markdown("**Données**")
    unit = st.sidebar.selectbox("Unité des données import/export", ["Automatique", "kWh", "kW", "Wh", "W"], key="data_unit")
    st.sidebar.caption("kW/W = puissance moyenne convertie en kWh avec le pas de temps détecté. kWh/Wh = énergie déjà mesurée par intervalle.")
    position = st.sidebar.selectbox("L'heure du fichier représente", ["Fin d'intervalle", "Début d'intervalle"],
        key="timestamp_position", help="À vérifier auprès de l'exporteur. Exemple : 00h15 en fin d'intervalle décrit 00h00-00h15. Les index cumulés sont toujours affectés à la fin.")
    with st.sidebar.expander("Horodatages et pas de mesure"):
        ambiguous_label = st.selectbox("Heure d'automne isolée",
            ["Automatique (heure suisse)", "Première occurrence (été)", "Seconde occurrence (hiver)", "Signaler l'ambiguïté"],
            key="autumn_hour_policy",
            help="Automatique : conserver les deux occurrences si elles sont fournies. Si une seule est présente sans offset, retenir la première (été) et signaler cette hypothèse à l'écran et dans le PDF.")
        minute_label = st.selectbox("Pas de mesure (minutes)", ["Automatique", "5", "10", "15", "30", "60"], key="interval_minutes")
        blank_label = st.selectbox("Cellules vides des exports Groupe E",
            ["Automatique (convention de l'export)", "Toujours inconnues"], key="groupe_e_blank_policy",
            help="Pour le modèle Excel Groupe E reconnu, une cellule vide est interprétée comme zéro si l'autre flux est mesuré. Les mentions Erroné/Manquant et les deux flux vides restent inconnus. Cette convention est signalée dans le rapport.")
        aggregate_devices = st.checkbox("Huawei : additionner des compteurs distincts du même site", value=False, key="aggregate_devices",
            help="À activer uniquement si les appareils mesurent des flux distincts à additionner. Ne pas additionner plusieurs appareils qui relisent le même compteur.")
        st.caption("Les changements d'heure sont traités automatiquement. Les offsets fournis sont conservés ; les deux occurrences d'automne correctement renseignées restent distinctes.")
    try:
        tariffs = _tariff_settings()
    except ValueError as error:
        st.error(str(error))
        return
    st.sidebar.markdown("**Type d'étude**")
    mode = st.sidebar.radio("Mode", list(MODE_SETTINGS), format_func=lambda m: MODE_SETTINGS[m]["label"], key="study_mode")
    defaults = MODE_SETTINGS[mode]
    show_financial = st.sidebar.checkbox("Afficher l'économie financière dans le PDF", value=mode == "ci", key=f"pdf_financial_{mode}")
    eff = st.sidebar.slider("Rendement aller-retour", .50, 1., defaults["efficiency"], .01, key=f"eff_{mode}")
    soc_min = st.sidebar.slider("SOC minimum (%)", 0, 95, int(defaults["soc_min"]), 1, key=f"soc_min_{mode}",
        help="Limite basse de l'autoconsommation, à respecter selon le matériel. La capacité située sous cette limite n'est pas utilisée dans cette simulation.")
    st.sidebar.caption(f"Plage utilisée : **{soc_min}-100 %**. Le SOC initial est fixé à {soc_min} %. Aucun gain de Peak Shaving n'est calculé.")
    st.sidebar.markdown("**Plage de recherche**")
    cl, ch, cs = defaults["capacity"]
    pl, ph, ps = defaults["power"]
    left, right = st.sidebar.columns(2)
    cap_min = left.number_input("Cap. min (kWh)", min_value=.1, max_value=5000., value=cl, step=cs, key=f"cap_min_{mode}")
    cap_max = right.number_input("Cap. max (kWh)", min_value=.1, max_value=5000., value=ch, step=cs, key=f"cap_max_{mode}")
    p_min = left.number_input("P. min (kW)", min_value=.1, max_value=2500., value=pl, step=ps, key=f"p_min_{mode}")
    p_max = right.number_input("P. max (kW)", min_value=.1, max_value=2500., value=ph, step=ps, key=f"p_max_{mode}")
    st.sidebar.caption(f"Pas de calcul : {cs:g} kWh et {ps:g} kW. Ces bornes limitent la recherche ; les réglages sous le graphique limitent seulement l'affichage.")
    if defaults["c_rate"] is not None:
        st.sidebar.caption(f"Contrainte {defaults['c_rate']:g}C : puissance ≤ capacité nominale × {defaults['c_rate']:g}.")
    with st.sidebar.expander("Critères et ordre des flux"):
        cycles_floor = st.number_input("Seuil interne de cycles DC/an", min_value=0., value=defaults["cycles"], step=10., key=f"cycles_{mode}")
        minimum_saving = st.number_input("Économie annuelle minimale pertinente (CHF/an)", min_value=0., value=10., step=10., key="minimum_saving")
        st.caption("Critères d'étude à ajuster au projet ; aucune garantie constructeur n'en est déduite. Sans annualisation, le contrôle annuel des cycles est désactivé.")
        order_label = st.selectbox("Ordre supposé dans un intervalle", ["Décharge puis charge", "Charge puis décharge"], key="dispatch_order")
        st.caption("L'ordre réel des flux n'est pas connu avec des mesures agrégées. Le budget de temps du convertisseur est commun aux deux sens.")
    try:
        caps = fixed_grid(cap_min, cap_max, cs, cl)
        powers = fixed_grid(p_min, p_max, ps, pl)
    except ValueError as error:
        st.error(str(error))
        st.stop()
    sections = ["frontier", "ba"]
    uploaded = st.file_uploader(_original_label("uploader"), type=["xlsx", "xls", "csv"],
                                accept_multiple_files=True, key="uploader")
    if not uploaded:
        st.info(_original_label("drop_prompt"))
        return
    options = list(range(len(uploaded))) + (["combine"] if len(uploaded) > 1 else [])
    chosen = st.sidebar.selectbox("Courbe à analyser", options, key="dataset",
        format_func=lambda i: "Combiner des périodes du même compteur" if i == "combine" else f"{i + 1}. {uploaded[i].name}")
    same_meter = False
    if chosen == "combine":
        same_meter = st.sidebar.checkbox("Ces fichiers décrivent des périodes du même point de mesure (et non des clients différents).", key="same_meter")
        if not same_meter:
            st.info("Choisir une courbe ou préciser que les fichiers appartiennent au même point de mesure.")
            return
        active = uploaded
    else:
        active = [uploaded[chosen]]
    files = tuple((f.name, f.getvalue()) for f in active)
    ambiguous = {"Automatique (heure suisse)": "auto", "Signaler l'ambiguïté": "raise",
                 "Première occurrence (été)": "daylight", "Seconde occurrence (hiver)": "standard"}[ambiguous_label]
    try:
        with st.spinner("Lecture et contrôle de la chronologie..."):
            raw, raw_meta = _load_cached(files, "auto" if unit == "Automatique" else unit,
                "end" if position == "Fin d'intervalle" else "start", ambiguous,
                None if minute_label == "Automatique" else float(minute_label), same_meter, aggregate_devices,
                "unknown" if blank_label == "Toujours inconnues" else "auto")
    except (ValueError, OSError, KeyError) as error:
        st.error(str(error))
        return
    st.caption(f"Jeu de données actif : **{raw_meta.source}**")
    st.caption(f"Unité appliquée aux données : **{raw_meta.data_unit}**")
    with st.sidebar.expander("📋 Qualité des données détectées", expanded=False):
        q1, q2, q3, q4 = st.columns(4)
        q1.metric("Période couverte", f"{raw_meta.coverage_days:.2f} jours")
        q2.metric("Intervalles exploitables", f"{raw_meta.completeness:.2%}")
        q3.metric("Intervalles invalides", raw_meta.invalid_rows)
        q4.metric("Intervalles absents", raw_meta.absent_rows)
        st.caption(f"Source : {raw_meta.source} | Unité source : {raw_meta.data_unit} | Pas : {raw_meta.dt_hours * 60:g} min | Données internes en kWh.")
        if raw_meta.missing_periods:
            with st.expander("Périodes manquantes (heures suisses)", expanded=False):
                st.dataframe(pd.DataFrame(raw_meta.missing_periods), hide_index=True, width="stretch")
        missing_policy = "block"
        if raw_meta.completeness < 1:
            with st.expander("Traitement avancé des données manquantes"):
                treatment = st.radio("Traitement des données manquantes",
                    ["Calculer les segments mesurés", "Estimer par jours comparables", "Attendre des données complètes"],
                    key="gap_treatment")
                st.caption("Par défaut, le calcul se poursuit sur les segments mesurés. Les trous restent inconnus et chaque reprise commence au SOC minimum.")
            missing_policy = {"Attendre des données complètes": "block", "Calculer les segments mesurés": "segments", "Estimer par jours comparables": "estimate"}[treatment]
        try:
            frame, meta = prepare_simulation_data(raw, raw_meta, missing_policy)
        except ValueError as error:
            st.warning(str(error))
            return
        for warning in meta.warnings:
            st.warning(warning)
        annualize = st.checkbox("Calculer aussi un équivalent annuel sur 365 jours", value=meta.complete_year,
            disabled=not meta.annualization_allowed, key=f"annualize_{meta.fingerprint}_{missing_policy}")
        if not meta.annualization_allowed:
            annualize = False
            st.caption("Annualisation indisponible : il faut au moins 330 jours, les 12 mois représentés, 98 % de mesures et au moins 90 % par mois présent.")
        elif annualize and not meta.complete_year:
            st.warning("L'équivalent annuel est une extrapolation d'une période incomplète. Il ne reconstitue pas les mesures manquantes ni les effets saisonniers absents.")
    with st.sidebar.expander("Tarifs appliqués à cette courbe", expanded=False):
        try:
            schedule, tariff_note = _calendar(meta, tariffs)
        except ValueError as error:
            st.error(str(error))
            return
    with st.sidebar.expander("Coût installé et retour simple (facultatif)"):
        capex_input = st.number_input("Coût total installé de la configuration étudiée (CHF)", min_value=0., value=0., step=100., key="capex",
            help="Zéro signifie non renseigné. Ce coût ne modifie pas le dimensionnement énergétique.")
        st.caption("Aucun prix batterie n'est présupposé. Le retour simple suppose des tarifs et un profil constants.")
        st.number_input("Coût fixe pour comparer les capacités (CHF)", min_value=0., value=0., step=100., key="cost_fixed")
        st.number_input("Prix installé par kWh pour la comparaison (CHF/kWh)", min_value=0., value=0., step=50., key="cost_module")
        st.number_input("Horizon de comparaison (ans)", min_value=1., value=13., step=1., key="cost_life")
    capex = float(capex_input) if capex_input > 0 else None
    options = dict(dt_hours=meta.dt_hours, roundtrip_eff=eff, tariff_import=tariffs["ht"],
        tariff_export=tariffs["export"], coverage_days=meta.coverage_days, soc_min_pct=float(soc_min),
        timestamps=frame.timestamp, tariff_import_ht=tariffs["ht"], tariff_import_bt=tariffs["bt"],
        high_tariff_periods=tariffs["periods"], weekend_low_tariff=tariffs["weekend"],
        valid_mask=frame.simulation_valid.to_numpy(bool), reset_before=frame.reset_before.to_numpy(bool),
        annualize=bool(annualize), dispatch_order="discharge_first" if order_label == "Décharge puis charge" else "charge_first",
        tariff_schedule=schedule)
    imp, exp = frame.import_kWh.to_numpy(float), frame.export_kWh.to_numpy(float)
    if not HAS_NUMBA:
        st.info("Le moteur fonctionne sans accélération Numba ; une grande grille peut prendre plusieurs minutes.")
    try:
        with st.spinner("Simulation des configurations et dimensionnement..."):
            results = _grid_cached(imp, exp, tuple(caps), tuple(powers), options, defaults["c_rate"])
            rec = recommend(results, study_mode=mode, min_cycles_per_year=cycles_floor,
                            minimum_annual_saving_chf=minimum_saving)
            sim = _simulate_cached(imp, exp, float(rec.best.Cap_kWh), float(rec.best.Power_kW), options)
    except ValueError as error:
        st.error(str(error))
        return
    _render_original_summary(sim, rec, meta, mode)
    if not rec.recommended:
        st.warning("Configuration d'analyse : les critères ne permettent pas de valider un dimensionnement.")
    for warning in recommendation_messages(rec):
        st.warning(warning)
    with st.sidebar.expander("Détail du dimensionnement et des hypothèses"):
        for code, params in rec.notes:
            st.caption(msg("fr", code, params))
    assumptions = study_assumptions(sim, meta, rec, tariff_profile=tariffs["name"], tariff_year=tariffs["year"],
        tariff_note=tariff_note + (" Référence : " + tariffs["note"] if tariffs["note"] else " Contrat non référencé."),
        tariff_import_ht=tariffs["ht"], tariff_import_bt=tariffs["bt"], tariff_export=tariffs["export"],
        periods=tariffs["periods"], weekend_low=tariffs["weekend"], tariff_schedule=schedule, capex_chf=capex)
    with st.sidebar.expander("Hypothèses et qualité de l'étude"):
        st.dataframe(pd.DataFrame(assumptions.items(), columns=["Paramètre", "Valeur"]), hide_index=True, width="stretch")
    with st.expander("Détail du gain tarifaire", expanded=False):
        st.dataframe(pd.DataFrame({
            "Poste": ["Import évité haut tarif", "Import évité bas tarif", "Valeur de revente perdue", "Gain net batterie"],
            "kWh sur la période": [sim.import_avoided_ht, sim.import_avoided_bt, sim.export_stored, np.nan],
            "Tarif CHF/kWh": [sim.gain_ht_chf / sim.import_avoided_ht if sim.import_avoided_ht else 0., sim.gain_bt_chf / sim.import_avoided_bt if sim.import_avoided_bt else 0., sim.export_value_lost_chf / sim.export_stored if sim.export_stored else 0., np.nan],
            "CHF sur la période": [sim.gain_ht_chf, sim.gain_bt_chf, -sim.export_value_lost_chf, sim.gain_chf],
        }), hide_index=True, width="stretch")
        st.caption(f"Formule : achats HT évités + achats BT évités - revente non perçue. Profil utilisé : {tariffs['name']}.")
    st.divider()
    render_energy_dashboard(frame, sim, rec.best)
    _render_original_tabs(frame, sim, rec, results, capex, mode, cap_min, cap_max, cycles_floor)
    st.divider()
    # Button controls report computation. Any changed study invalidates the prepared download.
    identity = sha256(repr((meta.fingerprint, assumptions, rec.best.to_dict(), meta.warnings,
                           tuple(caps), tuple(powers), defaults["c_rate"], rec.warnings, rec.notes,
                           sections, show_financial, client, schedule)).encode()).hexdigest()
    if st.session_state.get("report_identity") != identity:
        st.session_state.pop("report_bytes", None)
    if st.sidebar.button("Préparer le rapport PDF", key="prepare_pdf"):
        with st.spinner("Création du rapport..."):
            try:
                st.session_state["report_bytes"] = generate_battery_report(df=frame, meta=meta, rec=rec, sim=sim,
                    assumptions=assumptions, client_name=client, sections=sections, show_financial=show_financial,
                    capex_chf=capex, tariff_schedule=schedule)
                st.session_state["report_identity"] = identity
            except (ValueError, OSError) as error:
                st.error(f"Le PDF n'a pas pu être créé : {error}")
    st.download_button(_original_label("pdf_button"), st.session_state.get("report_bytes", b""),
                       _original_label("pdf_filename"), "application/pdf", key="download_pdf",
                       disabled=st.session_state.get("report_bytes") is None)
    st.sidebar.caption("Préparer le PDF pour activer son téléchargement en bas de page.")


if __name__ == "__main__":
    main()
