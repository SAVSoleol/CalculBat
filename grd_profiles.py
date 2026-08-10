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
        "needs_verification": False,
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
        "needs_verification": False,
        "source": "Groupe E 2026 - PLUS tarif double, selon facture client",
        "description": (
            "Tarifs variables 2026 utilisés par défaut. "
            "HT : 07h-12h et 17h-23h à 0.2932 CHF/kWh. "
            "BT : 00h-07h, 12h-17h, 23h-00h à 0.1927 CHF/kWh. "
            "Reprise PV : 0.0600 CHF/kWh. "
            "Les coûts fixes ne sont pas inclus dans le gain batterie."
        ),
    },
    "Romande Energie": {
        "ht": 0.31,
        "bt": 0.21,
        "export": 0.08,
        "periods": ((17.0, 22.0),),
        "weekend_low": True,
        "needs_verification": False,
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
