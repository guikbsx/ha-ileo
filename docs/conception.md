# Conception et genèse

Pourquoi une intégration Iléo de plus ? La question est légitime : trois solutions
communautaires existaient déjà, et aucune n'était mauvaise. Voilà le raisonnement, et à
qui je dois quoi.

## Le problème

Iléo, le service de l'eau de la Métropole Européenne de Lille, n'expose aucune API. Pour un
compteur télérelevé, la consommation n'est visible que dans l'espace client, sous deux
formes : le tableau « Ma consommation » et un export CSV.

Deux contraintes en découlent. Il n'y a qu'une valeur par jour, jamais de débit instantané.
Et elle est publiée environ deux jours après la consommation réelle.

Conséquence : une intégration Iléo doit écrire aujourd'hui des données datées d'avant-hier.
Toute la difficulté est là, et elle n'a pas grand-chose à voir avec le scraping.

## Ce qui existait déjà

Le sujet est ouvert depuis mars 2025 dans le fil HACF
[Récupération conso d'eau chez ILEO](https://forum.hacf.fr/t/recuperation-conso-d-eau-chez-ileo/60013),
où trois approches se sont succédé.

D'abord une configuration `multiscrape`, partagée par beufanet en septembre 2025 : du YAML
et des sélecteurs CSS sur le tableau HTML du portail. Puis le
[scraper de pbranly](https://github.com/pbranly/ILEO-home-assistant-scraper), un conteneur
Docker qui remonte les valeurs par MQTT. Et en janvier 2026
[ileo_direct](https://github.com/hal01/ileo_direct) de hal01, la première vraie intégration
HACS, avec un capteur « ghost » pour les statistiques différées.

Les trois ont prouvé le point essentiel : la donnée est récupérable, en se connectant à
l'espace client puis en demandant l'export CSV. Je n'ai rien découvert sur ce terrain, j'en
ai hérité.

## Les deux problèmes qui restaient

Le fil, puis les issues, documentent deux symptômes tenaces.

### Le pic du premier import

À la première récupération, la première barre du tableau de bord Énergie vaut l'index entier
du compteur, plusieurs centaines de milliers de litres, au lieu de la consommation d'un
jour. Il faut aller corriger la statistique à la main dans *Paramètres → Outils →
Statistiques*, sans garantie que la valeur ne revienne pas le lendemain. Le cas est raconté
en détail dans le fil en octobre 2026.

### Les sommes négatives

Écrire une statistique dans le passé sur le `statistic_id` d'un capteur ne tient pas dans
le temps. Le `recorder` continue d'alimenter ce même identifiant avec l'état courant de
l'entité et recalcule la somme derrière vous, si bien qu'une valeur datée d'avant-hier
finit en écart négatif.

Le diagnostic n'est pas de moi : pbranly l'avait posé dès mai 2025 dans le fil
[AppDaemon et mise à jour d'un sensor dans le passé](https://forum.hacf.fr/t/appdaemon-et-mise-a-jour-dun-sensor-dans-le-passe/62907),
où llaumgui s'en sort en important explicitement `state` et `sum`.

S'y est ajouté un troisième caillou en novembre 2026 : depuis Home Assistant 2026.11, les
métadonnées de statistiques réclament `mean_type`, et un import qui ne le fournit pas est
refusé.

## Comment je m'y suis pris

Ce projet est une réécriture indépendante, aucun code n'a été repris. Les deux problèmes
ci-dessus sont traités dans la conception plutôt que rattrapés après coup, par deux choix.

### Des statistiques externes plutôt qu'un capteur

L'intégration ne touche pas aux statistiques d'une entité. Elle crée deux statistiques
externes :

```
ileo:<contrat>_water_consumption
ileo:<contrat>_water_cost
```

Un `statistic_id` préfixé par un domaine (`ileo:`) au lieu de `sensor.`, poussé avec
`async_add_external_statistics`. Personne d'autre n'écrit dedans, donc Home Assistant ne
recalcule rien, et poser une valeur vieille de deux jours n'a aucun effet de bord. Plus de
sommes négatives, et aucun capteur « ghost » à manipuler. C'est d'ailleurs la mécanique que
Home Assistant utilise lui-même pour les données venant de fournisseurs d'énergie.

### Une somme qui cumule les écarts d'index

La `sum` d'une statistique n'est pas l'index du compteur, c'est le cumul des écarts d'index
d'un jour sur l'autre.

```
consommation(J) = index(J) − index(J−1)
sum(J)          = sum(J−1) + consommation(J)
```

La première barre vaut donc la consommation d'une journée, et non l'historique du compteur.
Il n'y a rien à corriger à la main, ni au début ni plus tard. Si un index recule, par
exemple après un remplacement de compteur ou une correction du portail, le jour compte pour
0 et sert de nouvelle base.

### Ce qui en découle

- Chaque volume est horodaté au jour où l'eau a été consommée, pas au jour où Home
  Assistant l'a récupéré.
- L'import est incrémental : seuls les jours postérieurs à la dernière statistique
  enregistrée sont ajoutés. Réinjecter le même export ne crée ni doublon ni décalage, et un
  historique manquant après une coupure se rattrape tout seul.
- Le portail n'est interrogé qu'une fois toutes les 12 heures. Il publie avec deux jours de
  retard, le harceler n'apporterait rien.

Tout ça tient dans [`statistics.py`](../custom_components/ileo/statistics.py). La partie
portail est isolée dans [`api.py`](../custom_components/ileo/api.py) et
[`parser.py`](../custom_components/ileo/parser.py), sans dépendance à Home Assistant, donc
réutilisable pour une autre régie des eaux.

## Ce que ça ne résout pas

Ces limites viennent du portail, autant les dire franchement.

Quand Iléo ne fait pas bouger l'index pendant plusieurs jours, il n'y a rien à importer. Ces
jours valent 0 et le rattrapage tombe le jour où l'index bouge. Lisser reviendrait à
inventer des chiffres.

Le délai de deux jours est le rythme du portail, aucun réglage n'y change quoi que ce soit.
Cette intégration ne remplace pas un détecteur de fuite.

Les comptes à plusieurs contrats sont écrits d'après le sélecteur du tableau de bord, mais
je n'ai pas pu les essayer sur un vrai compte. Tant que le portail ne confirme pas le bon
contrat, rien n'est importé, ce qui vaut mieux qu'importer n'importe quoi.

Enfin, c'est de la lecture de site web. Si Iléo modifie son espace client, ça casse jusqu'à
une mise à jour.

## Remerciements

pbranly a ouvert le sujet en mars 2025, écrit son
[scraper Iléo](https://github.com/pbranly/ILEO-home-assistant-scraper), et surtout
diagnostiqué dès mai 2025 pourquoi les statistiques écrites dans le passé repartaient en
négatif. C'est ce diagnostic qui m'a orienté vers les statistiques externes.

hal01 a écrit [ileo_direct](https://github.com/hal01/ileo_direct), la première intégration
Iléo, celle qui a montré que ça pouvait vivre dans Home Assistant plutôt que dans un
conteneur à côté.

beufanet a partagé la configuration `multiscrape` qui prouvait que le formulaire de
connexion était franchissable.

llaumgui et bastgau, croisés dans le fil sur les statistiques dans le passé, ont documenté
le problème et ses contournements.

marc.vanee, RomainDph et miloumeeloo ont rapporté sur le forum des difficultés qui m'ont
servi de cahier des charges en creux.

Les deux fils qui tiennent lieu de mémoire collective sur le sujet :
[Récupération conso d'eau chez ILEO](https://forum.hacf.fr/t/recuperation-conso-d-eau-chez-ileo/60013)
et
[AppDaemon et mise à jour d'un sensor dans le passé](https://forum.hacf.fr/t/appdaemon-et-mise-a-jour-dun-sensor-dans-le-passe/62907).

## Pour aller plus loin

- Le [README](../README.md) pour l'installation, la configuration et le dépannage.
- [`quality_scale.yaml`](../custom_components/ileo/quality_scale.yaml) pour l'état de chaque
  règle de qualité Home Assistant.
