Battery Sizer - Peak Shaving générique

Architecture :
1. grid_search + recommend dimensionnent la batterie sur la valeur énergétique uniquement.
2. La capacité et la puissance recommandées sont conservées.
3. Si Peak Shaving est activé en C&I, une seconde simulation utilise cette batterie.
4. Le seuil proposé = pointe réseau mesurée - puissance batterie recommandée.
5. Le seuil reste modifiable dans l'interface.
6. La pointe réellement obtenue tient compte du SOC, de la capacité utile et de la puissance.
7. Le gain Peak Shaving est ajouté au gain financier total, mais ne modifie pas le dimensionnement.
8. Aucun modèle ou fabricant de batterie n'est imposé.

Groupe E :
- Le tarif Peak Shaving est prérempli à 5.10 CHF/kW/mois lorsque le profil Groupe E est sélectionné.
- Cette valeur reste modifiable selon le contrat du client.
