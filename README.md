# Iléo (MEL) pour Home Assistant

Intégration personnalisée [Home Assistant](https://www.home-assistant.io/) qui récupère la
consommation d'eau depuis l'espace client [Iléo](https://www.mel-ileo.fr), le service de
l'eau de la Métropole Européenne de Lille, pour les compteurs télérelevés.

> [!WARNING]
> **Statut : connexion Iléo à finaliser.**
> Le cadre de l'intégration est prêt et testé (configuration, capteurs, statistiques,
> lecture de l'export), mais la connexion au portail repose encore sur des **hypothèses** :
> les noms des champs du formulaire de connexion et l'adresse de l'export n'ont pas encore
> été relevés sur le vrai site. Tant que ce n'est pas fait, l'ajout de l'intégration
> échouera très probablement avec « Identifiants invalides » ou « Réponse inattendue ».
> Voir [Feuille de route](#feuille-de-route).

## Fonctionnalités

- Configuration depuis l'interface (adresse e-mail + mot de passe de l'espace client),
  avec ré-authentification quand le mot de passe change.
- Récupération de l'export des consommations (6 derniers mois) **toutes les 12 heures** :
  les données Iléo arrivent avec environ deux jours de retard, inutile d'interroger plus
  souvent.
- Capteurs :
  | Capteur | Unité | Détail |
  | --- | --- | --- |
  | Index du compteur | L | `device_class: water`, `state_class: total_increasing` |
  | Consommation du dernier jour | L | consommation du dernier jour présent dans l'export |
  | Date du dernier relevé | date | jour de consommation le plus récent |
- **Statistiques externes datées au jour réel de consommation**, utilisables dans le
  tableau de bord Énergie (section Eau) :
  - `ileo:<compte>_consommation` (litres) ;
  - `ileo:<compte>_cout` (euros), si un prix de l'eau est configuré.

### Comment sont calculées les statistiques

- Une ligne par jour, horodatée à 00:00 (heure locale) du **jour consommé**, et non du
  jour où Home Assistant a récupéré la donnée.
- La somme (`sum`) est le **cumul des écarts d'index** d'un jour sur l'autre, jamais l'index
  brut : pas de pic géant au premier import.
- Un index qui **recule** (remplacement de compteur, correction) compte pour 0 et sert de
  nouvelle base.
- Le premier jour importé vaut la consommation fournie par l'export si elle existe, sinon 0.
- L'import est **incrémental** : seuls les jours postérieurs à la dernière statistique
  enregistrée sont ajoutés, donc réinjecter le même export ne crée ni doublon ni décalage.
- Métadonnées conformes à Home Assistant 2026.11 : `mean_type: NONE`, `has_sum: true`,
  `unit_class: volume`.

> [!TIP]
> Dans le tableau de bord Énergie, choisissez la statistique **« … – consommation »**
> (source `ileo`) plutôt que le capteur « Index du compteur » : le capteur, lui, attribue la
> consommation au moment de la récupération, avec deux jours de décalage.

## Installation

### Via HACS (recommandé)

1. HACS → menu ⋮ → **Dépôts personnalisés**.
2. Ajoutez `https://github.com/guikbsx/ha-ileo` avec la catégorie **Intégration**.
3. Installez **Iléo (MEL)**, puis redémarrez Home Assistant.

### Manuellement

Copiez le dossier `custom_components/ileo` dans le dossier `custom_components` de votre
configuration Home Assistant, puis redémarrez.

Version minimale : Home Assistant 2026.10.

## Configuration

1. **Paramètres → Appareils et services → Ajouter une intégration → Iléo (MEL)**.
2. Saisissez l'adresse e-mail et le mot de passe de votre espace client mel-ileo.fr.

### Options : prix de l'eau

Dans les options de l'intégration, vous pouvez indiquer le prix de l'eau en **€/m³** pour
obtenir la statistique de coût :

- un **prix fixe** ;
- ou une **entité** (`sensor`, `input_number`, `number`) dont l'état est le prix en €/m³.
  Si les deux sont renseignés, l'entité est prioritaire. Si elle est indisponible, le coût
  n'est pas importé à ce cycle et sera rattrapé au suivant.

Le prix est appliqué au moment de l'import (il n'y a pas de recalcul rétroactif).

## Feuille de route

- [x] Cadre de l'intégration (config flow, options, coordinateur, capteurs, traductions).
- [x] Lecture de l'export CSV (format hypothétique, parseur tolérant).
- [x] Statistiques externes de consommation et de coût, sans pic ni doublon.
- [ ] **Rétro-ingénierie du portail** (site ASP.NET WebForms) :
  - relever les champs du formulaire de `connexion.aspx` (identifiant, mot de passe,
    bouton, champs cachés `__VIEWSTATE` / `__EVENTVALIDATION`) ;
  - relever comment `espaceperso/mes-consommations.aspx` déclenche l'export (contrôle de
    postback, champs de période) et le format exact du fichier (séparateur, colonnes,
    unités, date = jour consommé ou jour du relevé) ;
  - mettre à jour `IleoSiteConfig` dans `api.py`, le parseur si besoin, et remplacer les
    fixtures de test hypothétiques par des exemples réels anonymisés.
- [ ] Logo dans [home-assistant/brands](https://github.com/home-assistant/brands).

## Développement

```bash
uv venv -p 3.14 .venv
uv pip install -p .venv -r requirements_test.txt
.venv/bin/pytest
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

Organisation du code (`custom_components/ileo/`) :

| Fichier | Rôle |
| --- | --- |
| `api.py` | client du portail (connexion, export) — sans dépendance à Home Assistant |
| `parser.py` | lecture de l'export CSV |
| `statistics.py` | calcul des consommations journalières et import des statistiques |
| `coordinator.py` | mise à jour toutes les 12 h |
| `config_flow.py` | configuration, ré-authentification et options |
| `sensor.py` | capteurs |

Les fichiers de `tests/fixtures/` sont **inventés** (voir leur README) en attendant des
exemples réels.

## Remerciements et licence

Le principe (connexion à l'espace client puis export CSV) s'inspire de l'intégration
communautaire [hal01/ileo_direct](https://github.com/hal01/ileo_direct). Aucun code n'en a
été repris : ce projet est une réécriture indépendante.

Projet non officiel, sans lien avec Iléo ni la Métropole Européenne de Lille.

Distribué sous licence [MIT](LICENSE).
