"""Profils tarifaires GRD pour Battery Sizer.

Important :
- Les horaires HT/BT sont structurés ici pour être utilisés automatiquement par l'app.
- Les tarifs HT/BT/rachat restent modifiables dans l'interface.
- Pour les GRD où les valeurs changent selon la commune, le produit tarifaire ou l'année,
  `needs_verification=True` force un avertissement dans la sidebar.
- Mettre à jour ce fichier chaque année avec les valeurs ElCom / VESE / contrat client.
"""

from __future__ import annotations

# Format d'une plage HT : (heure_debut, heure_fin), en heures décimales.
# Exemple : (17.0, 22.0) = 17h00 à 22h00.
#
# weekend_low=True signifie : samedi/dimanche entièrement en bas tarif.
# weekend_low=False signifie : les mêmes plages HT s'appliquent aussi le week-end.

GRD_PROFILES = {
    "Tarif unique 24h/24": {
        "ht": 0.21,
        "bt": 0.21,
        "export": 0.08,
        "periods": (),
        "weekend_low": False,
        "needs_verification": True,
        "single_tariff": True,
        "source": "Tarif unique saisi manuellement",
        "description": (
            "Un seul tarif d'achat est appliqué toute l'année, "
            "24h/24, sans distinction haut tarif / bas tarif."
        ),
    },
    "Groupe E": {
        "ht": 0.2932,
        "bt": 0.1927,
        "export": 0.0600,
        "periods": ((7.0, 12.0), (17.0, 23.0)),
        "weekend_low": False,
        "needs_verification": True,
        "source": "Horaires Groupe E 2026 ; montants hérités du simulateur, à vérifier sur le contrat client",
        "description": (
            "Tarifs variables 2026 utilisés par défaut. "
            "HT : 07h-12h et 17h-23h à 0.2932 CHF/kWh. "
            "BT : 00h-07h, 12h-17h, 23h-00h à 0.1927 CHF/kWh. "
            "Reprise PV : 0.0600 CHF/kWh. "
            "Les coûts fixes ne sont pas inclus dans le gain batterie."
        ),
    },
    "Spécial": {
        "seasonal": True,
        "revision": "2026-09-10-mivelaz-v1",
        "ht": 0.1688,
        "bt": 0.1426,
        "summer_ht": 0.1433,
        "summer_bt": 0.1213,
        "winter_ht": 0.1688,
        "winter_bt": 0.1426,
        "export": 0.0900,
        "periods": ((7.0, 23.0),),
        "saturday_periods": ((7.0, 13.5),),
        "weekend_low": False,
        "high_tariff_weekdays": (0, 1, 2, 3, 4, 5),
        "needs_verification": False,
        "source": (
            "Hypothèse Mivelaz Bois : fourniture négociée 2027-2029 "
            "(HP/HC été 8.21/6.01 ; hiver 10.76/8.14 ct/kWh) "
            "+ réseau BT Duo 2026 : distribution 1.95, Swissgrid 1.87 "
            "et taxe fédérale 2.30 ct/kWh, soit +6.12 ct/kWh. "
            "Prix hors TVA, hors taxes locales éventuelles, frais fixes et puissance. "
            "Reprise fixe supposée de 9 ct/kWh, arrondie à partir de la moyenne "
            "2025 de 8.98 ct/kWh. Le réseau 2026 est maintenu par hypothèse "
            "pour la projection ; ce profil ne reconstitue pas une facture historique."
        ),
        "export_note": (
            "Hypothèse de reprise fixe : 0.0900 CHF/kWh, fondée sur la moyenne "
            "des recettes d'injection 2025. Valeur modifiable."
        ),
        "description": (
            "Été du 1er avril au 30 septembre ; hiver du 1er octobre au 31 mars. "
            "HP du lundi au vendredi de 07h00 à 23h00 et le samedi de 07h00 à 13h30 ; "
            "HC le reste du temps, dimanche compris. "
            "Heure suisse, sans régime distinct pour les jours fériés."
        ),
    },
    "Romande Energie": {
        "ht": 0.31,
        "bt": 0.21,
        "export": 0.08,
        "periods": ((17.0, 22.0),),
        "weekend_low": True,
        "needs_verification": True,
        "source": "Profil heures pleines / heures creuses Romande Energie",
        "description": (
            "Heures pleines : lundi-vendredi de 17h00 à 22h00. "
            "Heures creuses : lundi-vendredi de 00h00 à 17h00 et de 22h00 à 24h00, "
            "ainsi que toute la journée le samedi et le dimanche."
        ),
    },
    "Yverdon Energies": {
        "ht": 0.31,
        "bt": 0.21,
        "export": 0.08,
        "periods": ((7.0, 12.0), (17.0, 22.0)),
        "weekend_low": True,
        "needs_verification": True,
        "source": "À vérifier selon tarif ElCom / contrat Yverdon Energies",
        "description": (
            "Profil prérempli à vérifier. "
            "HT proposée : lundi-vendredi 07h-12h et 17h-22h. "
            "BT : reste du temps et week-end."
        ),
    },
    "SIG": {
        "ht": 0.31,
        "bt": 0.21,
        "export": 0.08,
        "periods": ((7.0, 22.0),),
        "weekend_low": True,
        "needs_verification": True,
        "source": "À vérifier selon tarif SIG / commune / produit",
        "description": "Profil indicatif : HT en journée ouvrable, BT soir/nuit/week-end.",
    },
    "Viteos": {
        "ht": 0.31,
        "bt": 0.21,
        "export": 0.08,
        "periods": ((7.0, 12.0), (17.0, 22.0)),
        "weekend_low": True,
        "needs_verification": True,
        "source": "À vérifier selon tarif Viteos / commune / produit",
        "description": "Profil indicatif à corriger selon contrat client.",
    },
    "OIKEN": {
        "ht": 0.31,
        "bt": 0.21,
        "export": 0.08,
        "periods": ((7.0, 12.0), (17.0, 22.0)),
        "weekend_low": True,
        "needs_verification": True,
        "source": "À vérifier selon tarif OIKEN / commune / produit",
        "description": "Profil indicatif à corriger selon contrat client.",
    },
    "SIL Lausanne": {
        "ht": 0.31,
        "bt": 0.21,
        "export": 0.08,
        "periods": ((7.0, 22.0),),
        "weekend_low": True,
        "needs_verification": True,
        "source": "À vérifier selon tarif SIL / produit",
        "description": "Profil indicatif : HT journée ouvrable, BT nuit/week-end.",
    },
    "SIE SA": {
        "ht": 0.31,
        "bt": 0.21,
        "export": 0.08,
        "periods": ((7.0, 12.0), (17.0, 22.0)),
        "weekend_low": True,
        "needs_verification": True,
        "source": "À vérifier selon tarif SIE / commune / produit",
        "description": "Profil indicatif à corriger selon contrat client.",
    },
    "SEFA": {
        "ht": 0.31,
        "bt": 0.21,
        "export": 0.08,
        "periods": ((7.0, 12.0), (17.0, 22.0)),
        "weekend_low": True,
        "needs_verification": True,
        "source": "À vérifier selon tarif SEFA / commune / produit",
        "description": "Profil indicatif à corriger selon contrat client.",
    },
    "VOenergies": {
        "ht": 0.31,
        "bt": 0.21,
        "export": 0.08,
        "periods": ((7.0, 12.0), (17.0, 22.0)),
        "weekend_low": True,
        "needs_verification": True,
        "source": "À vérifier selon tarif VOénergies / commune / produit",
        "description": "Profil indicatif à corriger selon contrat client.",
    },
    "SEIC": {
        "ht": 0.31,
        "bt": 0.21,
        "export": 0.08,
        "periods": ((7.0, 12.0), (17.0, 22.0)),
        "weekend_low": True,
        "needs_verification": True,
        "source": "À vérifier selon tarif SEIC / commune / produit",
        "description": "Profil indicatif à corriger selon contrat client.",
    },
    "Gruyere Energie": {
        "ht": 0.31,
        "bt": 0.21,
        "export": 0.08,
        "periods": ((7.0, 12.0), (17.0, 23.0)),
        "weekend_low": False,
        "needs_verification": True,
        "source": "À vérifier selon tarif Gruyère Energie / commune / produit",
        "description": "Profil indicatif proche Groupe E, à vérifier.",
    },
    "BKW": {
        "ht": 0.31,
        "bt": 0.21,
        "export": 0.08,
        "periods": ((7.0, 20.0),),
        "weekend_low": True,
        "needs_verification": True,
        "source": "À vérifier selon tarif BKW / commune / produit",
        "description": "Profil indicatif : HT journée ouvrable, BT nuit/week-end.",
    },
    "Personnalise": {
        "ht": 0.31,
        "bt": 0.21,
        "export": 0.08,
        "periods": ((7.0, 12.0), (17.0, 23.0)),
        "weekend_low": False,
        "needs_verification": False,
        "source": "Saisi manuellement",
        "description": "Définir manuellement les plages haut tarif.",
    },
}


def get_profile(name: str, year: int) -> dict:
    """Copie d'un préremplissage ; les prix ne valent jamais validation de contrat."""
    if name not in GRD_PROFILES:
        raise ValueError("Profil tarifaire inconnu.")
    profile = dict(GRD_PROFILES[name])
    profile["reference_year"] = int(year)
    profile["needs_verification"] = True
    profile["price_note"] = "Prix indicatifs hérités : vérifier achat, reprise, taxes variables et produit du client."
    if name == "Groupe E":
        if year == 2025:
            profile["periods"] = ((7., 21.),)
        elif year == 2026:
            profile["periods"] = ((7., 12.), (17., 23.))
        else:
            profile["source"] = "Horaires non vérifiés pour cette année ; renseigner le contrat."
        profile["schedule_source"] = "https://www.groupe-e.ch/fr/decouvrir-groupe-e/medias/communiques-de-presse/tarifs-en-baisse"
        profile["description"] = "Plages HT proposées : " + "; ".join(f"{a:g}h-{b:g}h" for a, b in profile["periods"]) + ". Prix à vérifier."
    elif name == "Romande Energie" and year in {2025, 2026}:
        profile["schedule_source"] = "https://www.romande-energie.ch/espace-presse/communiques-de-presse/des-changements-en-2025-romande-energie-propose-des-tarifs-la"
    elif name == "Spécial":
        profile["needs_verification"] = False
        profile["price_note"] = (
            "Hypothèses d'achat hors TVA : fourniture négociée + 6.12 ct/kWh "
            "de réseau, Swissgrid et taxe fédérale. Quatre prix saisonniers "
            "modifiables ; frais fixes et puissance exclus."
        )
    return profile


def special_tariff_schedule(start, end, *, summer_ht, summer_bt, winter_ht, winter_bt,
                            tariff_export):
    """Calendrier Spécial sur les dates réelles, en heure suisse, fin exclue.

    Les saisons tarifaires changent à minuit le 1er avril et le 1er octobre,
    indépendamment des dates de changement d'heure. Tous les prix sont en CHF/kWh.

    Le moteur existant accepte une seule liste de plages HP par période.
    Les samedis sont donc isolés dans le calendrier, sans modifier le moteur.
    Les jours voisins ayant les mêmes règles sont regroupés. Les bornes de jours
    restent locales afin de respecter les journées de 23/25 heures.
    """
    import math
    import pandas as pd

    def local(value):
        timestamp = pd.Timestamp(value)
        if pd.isna(timestamp):
            raise ValueError("Date du calendrier Spécial invalide.")
        return (timestamp.tz_localize("Europe/Zurich") if timestamp.tzinfo is None
                else timestamp.tz_convert("Europe/Zurich"))

    start, end = local(start), local(end)
    if end <= start:
        raise ValueError("La fin du calendrier Spécial doit suivre son début.")
    summer_ht, summer_bt, winter_ht, winter_bt, tariff_export = map(
        float, (summer_ht, summer_bt, winter_ht, winter_bt, tariff_export))
    if not all(math.isfinite(p) for p in (summer_ht, summer_bt, winter_ht, winter_bt, tariff_export)):
        raise ValueError("Prix du calendrier Spécial invalide.")
    profile = GRD_PROFILES["Spécial"]
    schedule = []
    day = start.normalize()
    while day < end:
        next_day = day + pd.DateOffset(days=1)
        summer = 4 <= day.month <= 9
        season = "été" if summer else "hiver"
        ht, bt = (summer_ht, summer_bt) if summer else (winter_ht, winter_bt)
        periods = profile["saturday_periods"] if day.weekday() == 5 else profile["periods"]
        entry = dict(start=day.strftime("%Y-%m-%d"), end=next_day.strftime("%Y-%m-%d"),
                     season=season, ht=ht, bt=bt, export=tariff_export,
                     periods=periods, weekend_low=False,
                     high_tariff_weekdays=profile["high_tariff_weekdays"])
        same_rules = schedule and all(schedule[-1][key] == entry[key] for key in (
            "season", "ht", "bt", "export", "periods", "weekend_low", "high_tariff_weekdays"))
        if same_rules and schedule[-1]["end"] == entry["start"]:
            schedule[-1]["end"] = entry["end"]
        else:
            schedule.append(entry)
        day = next_day
    return schedule


def parse_periods(value: str) -> tuple:
    """Exemple : '7-12;17-23'. Un champ vide signifie aucune plage HT."""
    import math
    if not str(value).strip():
        return ()
    result = []
    try:
        for part in str(value).replace(",", ".").split(";"):
            start, end = (float(x.strip()) for x in part.split("-"))
            if not all(math.isfinite(x) and 0 <= x <= 24 for x in (start, end)) or start == end:
                raise ValueError
            result.append((start, end))
    except (TypeError, ValueError) as error:
        raise ValueError("Plages HT attendues au format 7-12;17-23, heures entre 0 et 24.") from error
    return tuple(result)
