<div align="center">

<img src="assets/logo.svg" width="96" height="96" alt="">

# Iléo pour Home Assistant

**La consommation d'eau de votre compteur télérelevé Iléo dans Home Assistant,<br>
jour par jour, jusque dans le tableau de bord Énergie.**

[![Tests](https://github.com/guikbsx/ha-ileo/actions/workflows/tests.yml/badge.svg)](https://github.com/guikbsx/ha-ileo/actions/workflows/tests.yml)
[![Validation](https://github.com/guikbsx/ha-ileo/actions/workflows/validate.yml/badge.svg)](https://github.com/guikbsx/ha-ileo/actions/workflows/validate.yml)
[![HACS](https://img.shields.io/badge/HACS-d%C3%A9p%C3%B4t_personnalis%C3%A9-41BDF5)](https://hacs.xyz)
[![Home Assistant](https://img.shields.io/badge/Home_Assistant-2026.10+-18BCF2?logo=homeassistant&logoColor=white)](https://www.home-assistant.io)
[![Licence MIT](https://img.shields.io/github/license/guikbsx/ha-ileo?label=licence)](LICENSE)

[**ha.ileo.guik.io**](https://ha.ileo.guik.io) ·
[Installation](#installation) ·
[Configuration](#configuration) ·
[Statistiques](#statistiques) ·
[Sécurité](#sécurité-et-confidentialité) ·
[Feuille de route](#feuille-de-route)

</div>

---

Intégration personnalisée [Home Assistant](https://www.home-assistant.io/) qui récupère la
consommation d'eau depuis l'espace client [Iléo](https://www.mel-ileo.fr), le service de
l'eau de la Métropole Européenne de Lille, pour les compteurs télérelevés.

> [!NOTE]
> **Statut : connexion et export validés sur le vrai portail (novembre 2026).**
> L'intégration n'a pas encore tourné plusieurs jours dans une instance Home Assistant :
> signalez tout comportement inattendu dans les
> [issues](https://github.com/guikbsx/ha-ileo/issues).

## En bref

<table>
<tr>
<td width="33%" valign="top">

### 💧 Au jour réel

Les données Iléo arrivent avec deux jours de retard. Chaque volume est rangé sur le
**jour où l'eau a été consommée**, pas sur celui où il a été récupéré.

</td>
<td width="33%" valign="top">

### 📊 Tableau de bord Énergie

Des statistiques prêtes pour la section **Eau** : pas de pic au premier import, pas de
doublon, même après une coupure.

</td>
<td width="33%" valign="top">

### 💶 Coût de l'eau

Indiquez un prix au m³, fixe ou fourni par une entité, pour obtenir aussi la
**dépense** jour par jour.

</td>
</tr>
<tr>
<td valign="top">

### 🧾 Un contrat, une entrée

Plusieurs contrats sur le même compte ? Choisissez lequel suivre, et ajoutez
l'intégration une fois par contrat.

</td>
<td valign="top">

### 🔒 Identifiants protégés

Ils ne partent que vers le portail Iléo, en HTTPS. Les diagnostics masquent e-mail, mot
de passe et numéro de contrat.

</td>
<td valign="top">

### 🕑 Discret

Une seule récupération **toutes les 12 heures** : inutile d'interroger plus souvent
des données qui arrivent avec deux jours de retard.

</td>
</tr>
</table>

### Capteurs

| Capteur | Unité | Détail |
| --- | :---: | --- |
| **Index du compteur** | L | `device_class: water`, `state_class: total_increasing` |
| **Consommation du dernier jour** | L | consommation du dernier jour présent dans l'export |
| **Date du dernier relevé** | date | jour de consommation le plus récent (entité de diagnostic) |

## Installation

Version minimale : **Home Assistant 2026.10**.

[![Ouvrir ce dépôt dans HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=guikbsx&repository=ha-ileo&category=integration)

Le bouton ajoute le dépôt à [HACS](https://hacs.xyz). Installez ensuite **Iléo (MEL)**,
puis redémarrez Home Assistant.

<details>
<summary><b>Sans le bouton : ajouter le dépôt à la main dans HACS</b></summary>

1. HACS → menu ⋮ → **Dépôts personnalisés**.
2. Ajoutez `https://github.com/guikbsx/ha-ileo` avec la catégorie **Intégration**.
3. Installez **Iléo (MEL)**, puis redémarrez Home Assistant.

</details>

<details>
<summary><b>Sans HACS : installation manuelle</b></summary>

Copiez le dossier `custom_components/ileo` dans le dossier `custom_components` de votre
configuration Home Assistant, puis redémarrez.

</details>

## Configuration

[![Ajouter l'intégration à Home Assistant](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=ileo)

1. **Paramètres → Appareils et services → Ajouter une intégration → Iléo (MEL)**, ou le
   bouton ci-dessus.
2. Saisissez l'adresse e-mail et le mot de passe de votre espace client mel-ileo.fr.
3. Si le compte a plusieurs contrats, choisissez celui à suivre. Pour en suivre un autre,
   ajoutez de nouveau l'intégration avec les mêmes identifiants.

Si vous changez de mot de passe chez Iléo, Home Assistant vous demandera le nouveau. Pour
changer d'adresse e-mail ou de mot de passe de vous-même, utilisez **Reconfigurer** dans
le menu ⋮ de l'intégration : vos statistiques et vos capteurs sont conservés, à condition
que le compte porte le même contrat.

### Prix de l'eau (facultatif)

Dans les options de l'intégration, indiquez le prix de l'eau en **€/m³** pour obtenir la
statistique de coût :

- un **prix fixe** ;
- ou une **entité** (`sensor`, `input_number`, `number`) dont l'état est le prix en €/m³.

Si les deux sont renseignés, l'entité est prioritaire. Si elle est indisponible, le coût
n'est pas importé à ce cycle et sera rattrapé au suivant. Le prix est appliqué au moment
de l'import : il n'y a pas de recalcul rétroactif.

## Statistiques

L'intégration alimente deux statistiques externes, utilisables dans le tableau de bord
Énergie (section Eau) :

| Statistique | Unité | Nom affiché |
| --- | :---: | --- |
| `ileo:<contrat>_water_consumption` | L | Iléo `<contrat>` – consommation d'eau |
| `ileo:<contrat>_water_cost` | € | Iléo `<contrat>` – coût de l'eau (si un prix est configuré) |

> [!TIP]
> Dans le tableau de bord Énergie, choisissez la statistique
> **« Iléo … – consommation d'eau »** plutôt que le capteur « Index du compteur » : le
> capteur, lui, attribue la consommation au moment de la récupération, avec deux jours
> de décalage.

<details>
<summary><b>Comment sont calculées les statistiques</b></summary>

- Une ligne par jour, horodatée à 00:00 (heure locale) du **jour consommé**, et non du
  jour où Home Assistant a récupéré la donnée.
- La somme (`sum`) est le **cumul des écarts d'index** d'un jour sur l'autre, jamais
  l'index brut : pas de pic géant au premier import.
- Un index qui **recule** (remplacement de compteur, correction) compte pour 0 et sert de
  nouvelle base.
- Le premier jour importé vaut la consommation fournie par l'export si elle existe,
  sinon 0.
- L'import est **incrémental** : seuls les jours postérieurs à la dernière statistique
  enregistrée sont ajoutés, donc réinjecter le même export ne crée ni doublon ni décalage.
- Les valeurs négatives ou non finies de l'export sont ignorées, comme les jours datés
  dans le futur.
- Métadonnées conformes à Home Assistant 2026.11 : `mean_type: NONE`, `has_sum: true`,
  `unit_class: volume`.

</details>

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

> [!CAUTION]
> Ne publiez jamais dans une issue un export CSV, une capture réseau (`.har`) ou une page
> de l'espace client : ils contiennent vos données personnelles.

**Signaler une faille.** N'ouvrez pas d'issue publique : utilisez le
[signalement privé de GitHub](https://github.com/guikbsx/ha-ileo/security/advisories/new)
(onglet *Security* → *Report a vulnerability*).

## Feuille de route

- [x] Cadre de l'intégration (config flow, options, coordinateur, capteurs, traductions).
- [x] Lecture de l'export CSV (parseur tolérant aux variations de format).
- [x] Statistiques externes de consommation et de coût, sans pic ni doublon.
- [x] Rétro-ingénierie du portail : connexion (`email` / `password` sur `connexion.aspx`)
  et export CSV (`mes-consommations.aspx?ex=1&dateDebut=…&dateFin=…`).
- [x] Identification par numéro de contrat (statistiques, appareil, entrée).
- [ ] Vérifier que l'export respecte bien la période demandée sur un historique de
  plusieurs mois (le compte de test n'avait que quelques jours de télérelève).
- [ ] Valider le changement de contrat sur un vrai compte à plusieurs contrats : il est
  écrit d'après le sélecteur `switchAbt` du tableau de bord mais n'a pas pu être essayé.
  Tant que le portail ne confirme pas le bon contrat, aucune donnée n'est importée.
- [x] Reconfiguration des identifiants sans supprimer l'intégration.
- [x] Icône de l'intégration dans Home Assistant (dossier `brand/`, Home Assistant 2026.3 ou
  ultérieur).

## Développement

```bash
uv venv -p 3.14 .venv
uv pip install -p .venv -r requirements_test.txt
.venv/bin/pytest
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/mypy
```

Le code, ses commentaires et ses journaux sont en anglais, comme le veut l'usage dans
Home Assistant ; l'interface est traduite en français et en anglais.

Pour publier une version : relever `version` dans `manifest.json` et `pyproject.toml`,
pousser, attendre la CI, puis créer la publication GitHub `vX.Y.Z` sur ce commit. HACS
propose alors ce numéro aux utilisateurs.

<details>
<summary><b>Organisation du code</b> (<code>custom_components/ileo/</code>)</summary>

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

Les fixtures `tests/fixtures/` mêlent extraits réels anonymisés et fichiers synthétiques
(voir leur README).

</details>

## Remerciements et licence

Le principe (connexion à l'espace client puis export CSV) s'inspire de l'intégration
communautaire [hal01/ileo_direct](https://github.com/hal01/ileo_direct). Aucun code n'en a
été repris : ce projet est une réécriture indépendante.

Distribué sous licence [MIT](LICENSE).

---

<div align="center">
<sub>Projet non officiel, sans lien avec Iléo ni la Métropole Européenne de Lille.</sub>
</div>
