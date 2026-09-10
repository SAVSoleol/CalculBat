"""Libellés français partagés par l'application et son rapport."""
LANGS = {"Français": "fr"}
ERROR_CODES = {"no_savings", "no_healthy", "negligible_gain"}

TEXT = {
    "title": "Calculateur de batterie",
    "caption": "Dimensionnement par simulation des flux import/export réseau et des tarifs renseignés.",
    "no_savings": "Aucune économie positive avec les hypothèses retenues. La configuration affichée sert uniquement à l'analyse.",
    "no_healthy": "Aucune configuration n'atteint le seuil interne de {cycles_low:.0f} cycles équivalents/an. Aucun dimensionnement validé.",
    "cycles_unavailable": "Période non annualisée : le seuil annuel de cycles n'est pas évalué. Dimensionnement provisoire.",
    "negligible_gain": "Économie annuelle inférieure au seuil de pertinence renseigné ({threshold:.0f} CHF/an). Aucune conclusion favorable à l'investissement.",
    "upper_bound": "Capacité à la limite haute étudiée : élargir la plage technique pour vérifier la saturation.",
    "lower_bound": "Capacité à la limite basse étudiée : une batterie plus petite peut convenir.",
    "non_monotone": "Le gain n'augmente pas partout avec la capacité. Le lissage sert au repérage ; les économies affichées restent celles réellement simulées.",
    "cycles_definition": "Cycles = énergie déchargée interne (DC) / capacité utile entre SOC minimum et 100 %. Seuil interne : {cycles_low:.0f}/an, à distinguer des cycles sur capacité nominale.",
    "heuristic": "Règle de dimensionnement : valeur marginale lissée sur {window:g} kWh, seuil à {floor:.0f} % de sa référence lissée ; plus petite puissance conservant {power_share:.0f} % du gain maximal à capacité donnée. Ce critère n'est pas un optimum de rentabilité.",
}


def t(lang, key, **fmt):
    if lang != "fr":
        raise ValueError("L'interface est disponible en français.")
    return TEXT[key].format(**fmt)


def msg(lang, code, params):
    return t(lang, code, **params)


def recommendation_messages(rec):
    return [msg("fr", code, params) for code, params in rec.warnings]


def study_assumptions(sim, meta, rec, *, tariff_profile, tariff_year, tariff_note,
                      tariff_import_ht, tariff_import_bt, tariff_export, periods,
                      weekend_low, tariff_schedule=None, capex_chf=None, seasonal_prices=None):
    """Même objet présenté à l'écran et transmis au PDF ; valeurs issues du moteur."""
    from simulation import simple_payback
    assumptions = {
        "Période analysée": f"{meta.start} au {meta.end} (fin exclue)",
        "Source": meta.source,
        "Pas de temps": f"{sim.dt_hours * 60:g} minutes",
        "Horodatages source": "Fin d'intervalle" if meta.timestamp_position == "end" else "Début d'intervalle",
        "Fuseau": "Europe/Zurich ; calcul chronologique en UTC",
        "Données exploitables": f"{meta.completeness:.2%} ; {meta.invalid_rows} valeurs invalides, {meta.absent_rows} intervalles absents",
        "Convention cellules vides": f"{meta.blank_zero_cells} cellule(s) vide(s) Groupe E supposée(s) nulles lorsque l’autre flux est mesuré" if meta.blank_zero_cells else "Aucune substitution de cellule vide",
        "Traitement des trous": {"block": "Aucun trou accepté", "segments": "Segments indépendants ; redémarrage au SOC minimum", "estimate": "Estimation explicite par jours comparables"}[meta.missing_policy],
        "Intervalles estimés": str(meta.estimated_rows),
        "Capacité nominale": f"{sim.capacity_kWh:g} kWh",
        "Capacité utile": f"{sim.usable_capacity_kWh:.2f} kWh",
        "Puissance AC de charge/décharge": f"{sim.power_kW:g} kW (budget de temps partagé)",
        "Plage SOC": f"{sim.soc_min_pct:g} % à 100 %",
        "SOC initial de chaque segment": f"{sim.soc_min_pct:g} % ; énergie utilisable initiale nulle",
        "Rendement aller-retour": f"{sim.roundtrip_eff:.1%} ; rendement symétrique charge/décharge",
        "Pilotage": "Autoconsommation immédiate ; " + ("décharge puis charge" if sim.dispatch_order == "discharge_first" else "charge puis décharge"),
        "Cycles": "Décharge DC / capacité utile ; critère interne, distinct d'une garantie constructeur",
        "Annualisation": f"Facteur {sim.annual_factor:.6f}, référence 365 jours" if sim.annual_factor is not None else "Désactivée ; résultats sur la période mesurée",
        "Profil tarifaire": tariff_profile,
        "Année tarifaire / scénario": str(tariff_year),
        "Application des tarifs": tariff_note,
        "Tarifs CHF/kWh": f"HT {tariff_import_ht:.4f} ; BT {tariff_import_bt:.4f} ; reprise {tariff_export:.4f}" if not tariff_schedule else "Calendrier détaillé ci-dessous",
        "Plages HT": "; ".join(f"{a:g}h-{b:g}h" for a, b in periods) or "Aucune plage HT (tarif unique)",
        "Week-end": "Entièrement BT" if weekend_low else "Mêmes plages que la semaine",
        "Coût installé renseigné": f"{capex_chf:,.0f} CHF" if capex_chf else "Non renseigné ; pas de retour sur investissement calculé",
        "Retour simple": f"{simple_payback(capex_chf, sim.gain_annual_chf):.1f} ans, hors actualisation" if simple_payback(capex_chf, sim.gain_annual_chf) is not None else "Non calculable",
        "Périmètre": "Pas de vieillissement ni de pertes auxiliaires ajoutées. Aucun gain de Peak Shaving ou d'arbitrage réseau.",
    }
    if seasonal_prices:
        assumptions["Tarifs CHF/kWh"] = (
            f"Été HP {seasonal_prices['summer_ht']:.4f} / HC {seasonal_prices['summer_bt']:.4f} ; "
            f"hiver HP {seasonal_prices['winter_ht']:.4f} / HC {seasonal_prices['winter_bt']:.4f} ; "
            f"reprise {tariff_export:.4f}"
        )
        assumptions["Week-end"] = "Samedi : HP 07h-23h, HC autrement ; dimanche entièrement HC"
        assumptions["Saisons tarifaires"] = "Été : 1er avril au 30 septembre ; hiver : 1er octobre au 31 mars"
        assumptions["Lecture HT/BT"] = "HT = HP, BT = HC ; tarifs du détail des gains pondérés par les kWh évités dans chaque saison"
    return assumptions
