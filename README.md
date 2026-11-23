# Iléo (MEL) pour Home Assistant

Intégration personnalisée [Home Assistant](https://www.home-assistant.io/) qui récupère la
consommation d'eau depuis l'espace client [Iléo](https://www.mel-ileo.fr), le service de
l'eau de la Métropole Européenne de Lille, pour les compteurs télérelevés.

> [!NOTE]
> **Statut : connexion et export validés sur le vrai portail (novembre 2026).**
> La connexion et le format de l'export ont été relevés sur mel-ileo.fr avec un compte
> réel. L'intégration n'a pas encore tourné plusieurs jours dans une instance Home
> Assistant : signalez tout comportement inattendu dans les issues.

## Fonctionnalités

- Configuration depuis l'interface (adresse e-mail + mot de passe de l'espace client),
  avec ré-authentification quand le mot de passe change.
- Une entrée par **contrat d'eau** : si le compte en a plusieurs, l'intégration demande
  lequel suivre, et on l'ajoute une fois par contrat.
- Récupération de l'export des consommations (jusqu'à 6 mois) **toutes les 12 heures** :
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
  - `ileo:<contrat>_water_consumption` (litres) ;
  - `ileo:<contrat>_water_cost` (euros), si un prix de l'eau est configuré.

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
> Dans le tableau de bord Énergie, choisissez la statistique **« Iléo … – consommation d'eau »**
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
3. Si le compte a plusieurs contrats, choisissez celui à suivre. Pour en suivre un autre,
   ajoutez de nouveau l'intégration avec les mêmes identifiants.

### Options : prix de l'eau

Dans les options de l'intégration, vous pouvez indiquer le prix de l'eau en **€/m³** pour
obtenir la statistique de coût :

- un **prix fixe** ;
- ou une **entité** (`sensor`, `input_number`, `number`) dont l'état est le prix en €/m³.
  Si les deux sont renseignés, l'entité est prioritaire. Si elle est indisponible, le coût
  n'est pas importé à ce cycle et sera rattrapé au suivant.

Le prix est appliqué au moment de l'import (il n'y a pas de recalcul rétroactif).

## Sécurité et confidentialité

- **Destination unique.** L'intégration ne communique qu'avec `https://www.mel-ileo.fr`.
  Toute redirection vers une autre adresse est refusée, et le mot de passe n'est envoyé
  qu'au formulaire de connexion, jamais renvoyé lors d'une redirection.
- **Stockage des identifiants.** L'adresse e-mail et le mot de passe sont enregistrés par
  Home Assistant dans sa configuration (`.storage/core.config_entries`), **en clair**,
  comme pour toute intégration : protégez l'accès à votre instance et à ses sauvegardes.
- **Journaux et diagnostics.** Le mot de passe n'est jamais écrit dans les journaux. Le
  fichier de diagnostics (menu ⋮ de l'intégration) masque l'adresse e-mail, le mot de
  passe et le numéro de contrat, et ne contient aucun volume d'eau : il peut être joint à
  un rapport de bug.
- **Identifiant des statistiques.** Il contient le numéro de contrat
  (`ileo:1234567_water_consumption`), jamais l'adresse e-mail : pensez-y tout de même
  avant de partager une capture d'écran ou une configuration.
- **Rapports de bug.** Ne publiez jamais dans une issue un export CSV, une capture réseau
  (`.har`) ou une page de l'espace client : ils contiennent vos données personnelles.
- **Signaler une faille.** N'ouvrez pas d'issue publique : utilisez le
  [signalement privé de GitHub](https://github.com/guikbsx/ha-ileo/security/advisories/new)
  (onglet *Security* → *Report a vulnerability*).

## Feuille de route

- [x] Cadre de l'intégration (config flow, options, coordinateur, capteurs, traductions).
- [x] Lecture de l'export CSV (parseur tolérant aux variations de format).
- [x] Statistiques externes de consommation et de coût, sans pic ni doublon.
- [x] Rétro-ingénierie du portail : connexion (`email` / `password` sur `connexion.aspx`)
  et export CSV (`mes-consommations.aspx?ex=1&dateDebut=…&dateFin=…`).
- [ ] Vérifier que l'export respecte bien la période demandée sur un historique de
  plusieurs mois (le compte de test n'avait que quelques jours de télérelève).
- [x] Identification par numéro de contrat (statistiques, appareil, entrée).
- [ ] Valider le changement de contrat sur un vrai compte à plusieurs contrats : il est
  écrit d'après le sélecteur `switchAbt` du tableau de bord mais n'a pas pu être essayé.
  Tant que le portail ne confirme pas le bon contrat, aucune donnée n'est importée.
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
| `api.py` | client du portail (connexion, contrats, export) — sans dépendance à Home Assistant |
| `parser.py` | lecture de l'export CSV — sans dépendance à Home Assistant |
| `models.py` | contrat, relevé journalier et exceptions du client |
| `statistics.py` | calcul des consommations journalières et import des statistiques |
| `coordinator.py` | mise à jour toutes les 12 h |
| `config_flow.py` | configuration, choix du contrat, ré-authentification et options |
| `entity.py` | entité de base (appareil « Compteur d'eau ») |
| `sensor.py` | capteurs |
| `diagnostics.py` | diagnostics téléchargeables, données personnelles masquées |

Le code, ses commentaires et ses journaux sont en anglais, comme le veut l'usage dans
Home Assistant ; l'interface est traduite en français et en anglais.

Les fixtures `tests/fixtures/` mêlent extraits réels anonymisés et fichiers synthétiques
(voir leur README).

## Remerciements et licence

Le principe (connexion à l'espace client puis export CSV) s'inspire de l'intégration
communautaire [hal01/ileo_direct](https://github.com/hal01/ileo_direct). Aucun code n'en a
été repris : ce projet est une réécriture indépendante.

Projet non officiel, sans lien avec Iléo ni la Métropole Européenne de Lille.

Distribué sous licence [MIT](LICENSE).
