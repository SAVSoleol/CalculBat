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
import streamlit as st

from loaders import load_meter_files, prepare_simulation_data, UnsupportedFormatError
from simulation import grid_search, simulate, simple_payback, HAS_NUMBA
from recommend import MODE_SETTINGS, fixed_grid, recommend
from grd_profiles import GRD_PROFILES, get_profile, parse_periods
from i18n import t, msg, recommendation_messages, study_assumptions
from energy_dashboard import render_energy_dashboard
from report import generate_battery_report, SECTION_LABELS, monthly_before_after


@st.cache_data(show_spinner=False, max_entries=8)
def _load_cached(files, data_unit, position, ambiguous, minutes, same_meter, aggregate_devices=False):
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
            ambiguous_policy=ambiguous, interval_minutes=minutes, same_meter=same_meter, aggregate_devices=aggregate_devices)
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


def _line_chart(frame, column, title, selected, display_bounds, step):
    lo, hi = display_bounds
    shown = frame[(frame.Cap_kWh >= lo) & (frame.Cap_kWh <= hi)].iloc[::step]
    fig = go.Figure(go.Scatter(x=shown.Cap_kWh, y=shown[column], mode="lines+markers", name="Configurations simulées"))
    if lo <= float(selected.Cap_kWh) <= hi:
        fig.add_trace(go.Scatter(x=[selected.Cap_kWh], y=[selected[column]], mode="markers",
            marker=dict(size=12, color="#ef5b32"), name="Configuration étudiée"))
    fig.update_layout(xaxis_title="Capacité nominale (kWh)", yaxis_title=title, height=430,
                      margin=dict(l=30, r=20, t=25, b=40), legend=dict(orientation="h"))
    st.plotly_chart(fig, width="stretch")


def main():
    st.set_page_config(page_title="Calculateur de batterie", page_icon="🔋", layout="wide")
    st.markdown("<style>.block-container{max-width:1500px;padding-top:2rem} "
                "section[data-testid='stSidebar']{border-right:1px solid #334155} "
                "[data-testid='stMetric']{border:1px solid #64748b44;border-radius:12px;padding:14px}</style>", unsafe_allow_html=True)
    st.title("🔋 " + t("fr", "title"))
    st.caption(t("fr", "caption"))
    st.sidebar.header("Paramètres")
    client = st.sidebar.text_input("Nom du client", placeholder="Ex. Jean Dupont", key="client_name")
    st.sidebar.markdown("**Données**")
    unit = st.sidebar.selectbox("Unité import/export", ["Automatique", "kWh", "kW", "Wh", "W"], key="data_unit")
    position = st.sidebar.selectbox("L'heure du fichier représente", ["Fin d'intervalle", "Début d'intervalle"],
        key="timestamp_position", help="À vérifier auprès de l'exporteur. Exemple : 00h15 en fin d'intervalle décrit 00h00-00h15. Les index cumulés sont toujours affectés à la fin.")
    with st.sidebar.expander("Horodatages et pas de mesure"):
        ambiguous_label = st.selectbox("Heure d'automne isolée", ["Signaler l'ambiguïté", "Première occurrence (été)", "Seconde occurrence (hiver)"], key="ambiguous")
        minute_label = st.selectbox("Pas de mesure (minutes)", ["Automatique", "5", "10", "15", "30", "60"], key="interval_minutes")
        aggregate_devices = st.checkbox("Huawei : additionner des compteurs distincts du même site", value=False, key="aggregate_devices",
            help="À activer uniquement si les appareils mesurent des flux distincts à additionner. Ne pas additionner plusieurs appareils qui relisent le même compteur.")
        st.caption("Les heures avec offset sont conservées. Les heures sans offset sont interprétées en heure suisse. Les deux occurrences correctement renseignées en automne restent distinctes.")
    st.sidebar.markdown("**Type d'étude et batterie**")
    mode = st.sidebar.radio("Mode", list(MODE_SETTINGS), format_func=lambda m: MODE_SETTINGS[m]["label"], key="study_mode")
    defaults = MODE_SETTINGS[mode]
    eff = st.sidebar.slider("Rendement aller-retour", .50, 1., defaults["efficiency"], .01, key=f"eff_{mode}")
    soc_min = st.sidebar.slider("SOC minimum (%)", 0, 95, int(defaults["soc_min"]), 1, key=f"soc_min_{mode}",
        help="Limite basse de l'autoconsommation, à respecter selon le matériel. La capacité située sous cette limite n'est pas utilisée dans cette simulation.")
    st.sidebar.caption(f"Plage utilisée : **{soc_min}-100 %**. Le SOC initial est fixé à {soc_min} %. Aucun gain de Peak Shaving n'est calculé.")
    with st.sidebar.expander("Limites techniques de recherche"):
        cl, ch, cs = defaults["capacity"]
        pl, ph, ps = defaults["power"]
        cap_min = st.number_input("Capacité minimale (kWh)", min_value=.1, max_value=5000., value=cl, step=cs, key=f"cap_min_{mode}")
        cap_max = st.number_input("Capacité maximale (kWh)", min_value=.1, max_value=5000., value=ch, step=cs, key=f"cap_max_{mode}")
        p_min = st.number_input("Puissance minimale (kW)", min_value=.1, max_value=2500., value=pl, step=ps, key=f"p_min_{mode}")
        p_max = st.number_input("Puissance maximale (kW)", min_value=.1, max_value=2500., value=ph, step=ps, key=f"p_max_{mode}")
        st.caption(f"Ces limites contraignent le dimensionnement. Pas de calcul fixe : {cs:g} kWh et {ps:g} kW ; les bornes exactes de puissance sont incluses.")
        if defaults["c_rate"] is not None:
            st.caption(f"Contrainte {defaults['c_rate']:g}C : puissance ≤ capacité nominale × {defaults['c_rate']:g}.")
    with st.sidebar.expander("Critères et ordre des flux"):
        cycles_floor = st.number_input("Seuil interne de cycles DC/an", min_value=0., value=defaults["cycles"], step=10., key=f"cycles_{mode}")
        minimum_saving = st.number_input("Économie annuelle minimale pertinente (CHF/an)", min_value=0., value=10., step=10., key="minimum_saving")
        st.caption("Critères d'étude à ajuster au projet ; aucune garantie constructeur n'en est déduite. Sans annualisation, le contrôle annuel des cycles est désactivé.")
        order_label = st.selectbox("Ordre supposé dans un intervalle", ["Décharge puis charge", "Charge puis décharge"], key="dispatch_order")
        st.caption("L'ordre réel des flux n'est pas connu avec des mesures agrégées. Le budget de temps du convertisseur est commun aux deux sens.")
    try:
        tariffs = _tariff_settings()
        caps = fixed_grid(cap_min, cap_max, cs, cl)
        powers = fixed_grid(p_min, p_max, ps, pl)
    except ValueError as error:
        st.error(str(error))
        st.stop()
    show_financial = st.sidebar.checkbox("Afficher l'économie financière dans le PDF", value=mode == "ci", key=f"pdf_financial_{mode}")
    with st.sidebar.expander("Sections du PDF"):
        sections = st.multiselect("Graphiques inclus", list(SECTION_LABELS), default=["frontier", "soc", "ba"],
                                  format_func=lambda s: SECTION_LABELS[s], key="pdf_sections")
        st.caption("La synthèse, les hypothèses et les réserves sont toujours incluses.")
    uploaded = st.file_uploader("Courbes import/export réseau (Excel ou CSV)", type=["xlsx", "xls", "csv"],
                                accept_multiple_files=True, key="uploader")
    if not uploaded:
        st.info("Déposer une courbe de charge pour commencer. Pour deux clients différents, sélectionner leurs fichiers séparément.")
        return
    options = list(range(len(uploaded))) + (["combine"] if len(uploaded) > 1 else [])
    chosen = st.selectbox("Courbe à analyser", options, key="dataset",
        format_func=lambda i: "Combiner des périodes du même compteur" if i == "combine" else f"{i + 1}. {uploaded[i].name}")
    same_meter = False
    if chosen == "combine":
        same_meter = st.checkbox("Ces fichiers décrivent des périodes du même point de mesure (et non des clients différents).", key="same_meter")
        if not same_meter:
            st.info("Choisir une courbe ou préciser que les fichiers appartiennent au même point de mesure.")
            return
        active = uploaded
    else:
        active = [uploaded[chosen]]
    files = tuple((f.name, f.getvalue()) for f in active)
    ambiguous = {"Signaler l'ambiguïté": "raise", "Première occurrence (été)": "daylight", "Seconde occurrence (hiver)": "standard"}[ambiguous_label]
    try:
        with st.spinner("Lecture et contrôle de la chronologie..."):
            raw, raw_meta = _load_cached(files, "auto" if unit == "Automatique" else unit,
                "end" if position == "Fin d'intervalle" else "start", ambiguous,
                None if minute_label == "Automatique" else float(minute_label), same_meter, aggregate_devices)
    except (ValueError, OSError, KeyError) as error:
        st.error(str(error))
        return
    st.subheader("Qualité des données")
    q1, q2, q3, q4 = st.columns(4)
    q1.metric("Période couverte", f"{raw_meta.coverage_days:.2f} jours")
    q2.metric("Intervalles mesurés", f"{raw_meta.completeness:.2%}")
    q3.metric("Intervalles invalides", raw_meta.invalid_rows)
    q4.metric("Intervalles absents", raw_meta.absent_rows)
    st.caption(f"Source : {raw_meta.source} | Unité source : {raw_meta.data_unit} | Pas : {raw_meta.dt_hours * 60:g} min | Données internes en kWh.")
    if raw_meta.missing_periods:
        with st.expander("Périodes manquantes (heures suisses)", expanded=True):
            st.dataframe(pd.DataFrame(raw_meta.missing_periods), hide_index=True, width="stretch")
    missing_policy = "block"
    if raw_meta.completeness < 1:
        treatment = st.radio("Traitement des données manquantes", ["Attendre des données complètes", "Calculer les segments mesurés", "Estimer par jours comparables"], key="missing_policy")
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
    with st.expander("Tarifs appliqués à cette courbe", expanded=False):
        try:
            schedule, tariff_note = _calendar(meta, tariffs)
        except ValueError as error:
            st.error(str(error))
            return
    with st.expander("Coût installé et retour simple (facultatif)"):
        capex_input = st.number_input("Coût total installé de la configuration étudiée (CHF)", min_value=0., value=0., step=100., key="capex",
            help="Zéro signifie non renseigné. Ce coût ne modifie pas le dimensionnement énergétique.")
        st.caption("Aucun prix batterie n'est présupposé. Le retour simple suppose des tarifs et un profil constants.")
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
    st.subheader("Résumé de la simulation")
    summary = st.columns(4)
    summary[0].metric("Capacité nominale étudiée", f"{sim.capacity_kWh:g} kWh")
    summary[1].metric("Capacité utile", f"{sim.usable_capacity_kWh:g} kWh")
    summary[2].metric("Puissance AC", f"{sim.power_kW:g} kW")
    summary[3].metric("SOC minimum", f"{sim.soc_min_pct:g} %")
    kpis = st.columns(3)
    kpis[0].metric("Économie sur la période", f"{_fmt(sim.gain_chf, 2)} CHF")
    kpis[1].metric("Cycles DC sur la période", _fmt(sim.cycles_period, 1))
    kpis[2].metric("Part du surplus solaire captée", f"{sim.surplus_captured:.1%}")
    if sim.annual_factor is not None:
        st.caption(f"Équivalent sur 365 jours : {_fmt(sim.gain_annual_chf, 2)} CHF/an et {sim.cycles_per_year:.1f} cycles DC/an. Facteur appliqué : {sim.annual_factor:.6f}.")
    if rec.recommended and not rec.warnings and meta.completeness == 1:
        st.success("Dimensionnement énergétique cohérent avec les critères renseignés ; à rapprocher d'un matériel et d'un devis réels.")
    else:
        st.info("Configuration indicative à examiner avec les réserves ci-dessous." if rec.recommended else "Configuration d'analyse : les critères ne permettent pas de valider un dimensionnement.")
    for warning in recommendation_messages(rec):
        st.warning(warning)
    for code, params in rec.notes:
        st.caption(msg("fr", code, params))
    assumptions = study_assumptions(sim, meta, rec, tariff_profile=tariffs["name"], tariff_year=tariffs["year"],
        tariff_note=tariff_note + (" Référence : " + tariffs["note"] if tariffs["note"] else " Contrat non référencé."),
        tariff_import_ht=tariffs["ht"], tariff_import_bt=tariffs["bt"], tariff_export=tariffs["export"],
        periods=tariffs["periods"], weekend_low=tariffs["weekend"], tariff_schedule=schedule, capex_chf=capex)
    with st.expander("Hypothèses communes à l'écran et au PDF"):
        st.dataframe(pd.DataFrame(assumptions.items(), columns=["Paramètre", "Valeur"]), hide_index=True, width="stretch")
    view = st.radio("Vue", ["Gestion de l'énergie", "Dimensionnement", "Retour simple", "Cycles", "SOC", "Avant / après"], horizontal=True, key="view")
    if view == "Gestion de l'énergie":
        render_energy_dashboard(frame, sim, rec.best)
    elif view in {"Dimensionnement", "Cycles"}:
        st.caption("Les réglages ci-dessous modifient uniquement l'affichage. La grille simulée et la configuration étudiée restent identiques.")
        bounds = (float(rec.frontier.Cap_kWh.min()), float(rec.frontier.Cap_kWh.max()))
        if bounds[0] != bounds[1]:
            bounds = st.slider("Capacités affichées (kWh)", bounds[0], bounds[1], bounds, key=f"display_bounds_{mode}_{cap_min}_{cap_max}")
        display_step = st.select_slider("Afficher un point sur", options=[1, 2, 5, 10], value=1, key="display_step")
        column = "Gain_CHF" if view == "Dimensionnement" else ("Cycles_per_year" if annualize else "Cycles_period")
        title = "Économie sur la période (CHF)" if view == "Dimensionnement" else ("Cycles DC/an (365 jours)" if annualize else "Cycles DC sur la période")
        _line_chart(rec.frontier, column, title, rec.best, bounds, display_step)
        st.dataframe(rec.frontier, hide_index=True, width="stretch")
        st.download_button("Télécharger toutes les configurations (CSV)", results.to_csv(index=False).encode("utf-8-sig"), "configurations_batterie.csv", "text/csv")
    elif view == "Retour simple":
        payback = simple_payback(capex, sim.gain_annual_chf)
        if payback is None:
            st.info("Retour simple non calculable : renseigner un coût installé et disposer d'une économie annuelle positive.")
        else:
            st.metric("Retour simple", f"{payback:.1f} ans")
            years = np.arange(0., max(11., min(51., np.ceil(payback) + 3)))
            st.line_chart(pd.DataFrame({"Années": years, "Solde cumulé (CHF)": years * sim.gain_annual_chf - capex}).set_index("Années"))
    elif view == "SOC":
        st.line_chart(pd.DataFrame({"Heure suisse": frame.timestamp.dt.tz_convert("Europe/Zurich"), "SOC (%)": sim.soc_pct}).set_index("Heure suisse"))
        st.caption(f"Limite basse : {soc_min} %. Les périodes non simulées restent vides.")
    else:
        monthly = monthly_before_after(frame, sim)
        display = monthly.copy()
        display.index = display.index.astype(str)
        st.bar_chart(display[["Import avant", "Import après", "Export avant", "Export après"]], stack=False)
        st.dataframe(display, width="stretch")
    st.divider()
    st.subheader("Rapport PDF")
    # Button controls report computation. Any changed study invalidates the prepared download.
    identity = sha256(repr((meta.fingerprint, assumptions, rec.best.to_dict(), meta.warnings,
                           tuple(caps), tuple(powers), defaults["c_rate"], rec.warnings, rec.notes,
                           sections, show_financial, client, schedule)).encode()).hexdigest()
    if st.session_state.get("report_identity") != identity:
        st.session_state.pop("report_bytes", None)
    if st.button("Préparer le rapport PDF", key="prepare_pdf"):
        with st.spinner("Création du rapport..."):
            try:
                st.session_state["report_bytes"] = generate_battery_report(df=frame, meta=meta, rec=rec, sim=sim,
                    assumptions=assumptions, client_name=client, sections=sections, show_financial=show_financial,
                    capex_chf=capex, tariff_schedule=schedule)
                st.session_state["report_identity"] = identity
            except (ValueError, OSError) as error:
                st.error(f"Le PDF n'a pas pu être créé : {error}")
    if st.session_state.get("report_bytes") is not None:
        st.download_button("Télécharger le rapport PDF", st.session_state["report_bytes"],
                           "rapport_batterie.pdf", "application/pdf", key="download_pdf")


if __name__ == "__main__":
    main()
