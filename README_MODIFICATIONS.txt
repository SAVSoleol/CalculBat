Battery Sizer - version sans Peak Shaving

Architecture:
- Battery Sizer = dimensionnement autoconsommation / énergie uniquement.
- Peak Shaving Simulator = étude Peak Shaving, seuil, réserve, recharge réseau et économie de puissance.

Supprimé du Battery Sizer:
- section « Réserve Peak Shaving »;
- case « Protéger une réserve pour le Peak Shaving »;
- slider de réserve;
- option de maintien de réserve depuis le réseau;
- seuil interne de protection;
- messages et résultats Peak Shaving;
- anciens restes de configuration Sungrow/fixed config.

La simulation du Battery Sizer force maintenant tous les paramètres Peak Shaving à désactivés.
simulation.py conserve cependant l'API historique pour compatibilité technique.
