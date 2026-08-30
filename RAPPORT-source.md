# EcoInsight — matière pour le rapport de stage

> Ce document n'est pas le rapport. C'est le dossier de faits, de chiffres et de
> raisonnements dans lequel puiser pour l'écrire, organisé selon le plan en sept
> parties.
>
> **Chaque chiffre indique sa source.** Ceux marqués ⚠️ sont incertains ou
> contestables — les citer sans leur réserve serait une faute, et les citer avec
> est un point fort.

---

## 1 · Introduction et Contexte

### Le cadre Green IT

Le Green IT ne consiste pas à utiliser le numérique pour verdir autre chose,
mais à **réduire l'empreinte du numérique lui-même**. Trois leviers :

1. **Fabriquer moins** — prolonger la durée de vie du matériel
2. **Consommer moins** — réduire l'énergie à l'usage
3. **Mesurer** — sans quoi les deux premiers relèvent de l'intuition

Le troisième conditionne les deux autres. Or l'effort d'instrumentation porte
massivement sur les datacenters : on sait mesurer finement un serveur, on est
incapable de dire ce que consomme le poste d'un employé.

### Le déséquilibre fabrication / usage

C'est le constat qui structure tout le projet. Pour un portable, l'essentiel du
carbone est émis **avant la mise en service**.

Mesuré sur la machine de référence :

| Grandeur | Valeur | Source |
|---|---|---|
| Émissions d'usage | **12,9 kg CO₂eq/an** | mesure extrapolée sur la fenêtre observée |
| Fabrication | **≈ 300 kg CO₂eq** | ⚠️ estimation de classe, pas une fiche constructeur |
| Équivalent | **≈ 23 ans d'usage** | rapport des deux |
| Part fabrication | **82 % du carbone de cycle de vie** | idem |
| Gain d'un an de plus | **≈ 50 kg CO₂eq**, soit **3,9 ans** de sa propre électricité | idem |

⚠️ **Le chiffre de fabrication est le plus mou du projet.** C'est une estimation
de classe, pas un PCF constructeur, et les PCF publiés portent eux-mêmes une
incertitude large. Le panneau de l'application affiche une fourchette 200–400 kg
et l'annonce comme telle. À citer avec cette réserve.

Point favorable à l'argument : les émissions d'usage sont extrapolées d'une
fenêtre partielle, donc **sous-estimées**. Le multiple de 23 ans est un plancher.

### L'utilisateur développeur

Dans une entreprise de services numériques, la majorité des postes sont des
postes de développement — et ce sont les plus énergivores du parc.

- Compilations et tests répétés : pics soutenus, plusieurs fois par jour
- Conteneurs et machines virtuelles : consommation continue, souvent la nuit
- Outils d'IA générative : ressources consommées ailleurs, aucun retour local
- Environnements démarrés une fois, jamais arrêtés

**La formule à retenir** : un développeur ne laisse pas tourner une machine
virtuelle par négligence, mais parce que rien ne lui indique que cela coûte
quelque chose. L'enjeu n'est pas de contrôler, mais de rendre visible.

### Contexte de déploiement

Sofrecom Tunisie (groupe Orange). Parc de postes standardisés.
Intensité carbone du réseau tunisien : **483 gCO₂eq/kWh**, réseau à plus de 98 %
gaz. Le facteur est injecté et non codé en dur, donc un déploiement dans une
autre région demande une valeur, pas une modification de code.

---

## 2 · Problématique et Objectifs

### La chaîne du problème

```
Pas de mesure → pas de visibilité → pas d'action → gaspillage persistant
```

### Objectifs et critères de réussite

| Objectif | Critère |
|---|---|
| Mesurer la consommation réelle | Sans matériel externe ni droits administrateur |
| Distinguer le gaspillage du travail | Ne signaler que ce qui est évitable |
| Sensibiliser sans culpabiliser | Objectif hebdomadaire choisi par l'utilisateur |
| Déployer à l'échelle d'un parc | Une calibration par modèle, pas par machine |
| Rester vérifiable | Toute valeur affichée indique son origine |

**Le dernier critère a structuré tous les autres.** Un outil dont la sortie est
un chiffre de gaspillage doit pouvoir dire d'où ce chiffre vient, sinon il n'est
ni contestable ni crédible.

---

## 3 · Étude de l'existant et Analyse des besoins

### Les approches existantes et leurs limites

| Approche | Apporte | Bloque |
|---|---|---|
| Prises connectées, wattmètres | Mesure physique fiable | Coût et logistique par poste |
| Utilitaires constructeur | Informations batterie | Ni historique exploitable, ni carbone |
| Estimation par TDP | Immédiate, sans mesure | Générique : deux machines identiques sur le papier ne consomment pas pareil |
| Outils orientés serveurs | Matures, précis | Conçus pour Linux et datacenter |

**La conclusion à formuler** : chacune résout une moitié du problème. Le
wattmètre mesure bien mais ne se déploie pas ; le TDP se déploie partout mais ne
mesure rien. Ce qui manque est le chaînon entre la mesure et la décision de
l'utilisateur.

### Pourquoi le TDP ne suffit pas — argument technique

Les watts par pourcent de CPU ne sont **pas une propriété du processeur**. Cela
dépend de la gestion d'énergie de la plateforme, de son refroidissement, et de
ce que Windows appelle « 100 % ». Tout chiffre publié est la régression de
quelqu'un d'autre sur le portable de quelqu'un d'autre.

Ce qui se transfère est un **rapport** : la machine de référence (i5-6300U,
TDP 15 W) donne 0,1053 W/%, soit 10,5 W à pleine charge — **70 % du TDP**. Le
repli utilisé pour les modèles non calibrés est donc `0,70 × TDP / 100`, avec le
TDP déduit du suffixe du processeur (U 15 W, P 28 W, H 45 W, HX 55 W).

⚠️ **Ce rapport repose sur UN point d'ancrage.** Il pourrait valoir 0,6 ou 0,85
ailleurs. C'est pourquoi les profils construits ainsi portent
`source="estimated"` et déclenchent un avertissement. Le système s'améliore de
lui-même : un deuxième modèle calibré permet de vérifier le rapport, un
troisième de l'ajuster.

### Besoins retenus

**Fonctionnels** — mesurer en continu, convertir en énergie puis en émissions,
détecter le gaspillage évitable, restituer par question, permettre à l'IT de
calibrer un modèle.

**Techniques** — agent local mono-processus, données stockées localement, aucune
sonde externe, aucun serveur central, aucun droit administrateur.

Ces contraintes ne sont pas des préférences : un outil qui exige du matériel ou
des droits administrateur ne sera jamais déployé sur un parc, et un outil qui
remonte l'activité détaillée d'un poste vers un serveur central pose un problème
que la mesure ne justifie pas.

---

## 4 · Choix techniques et Architecture

### Pile technique

| Couche | Technologies |
|---|---|
| Backend | Python 3.14, FastAPI, Uvicorn, SQLite |
| Collecte | psutil, WMI (pywin32), screen-brightness-control |
| Frontend | React 19, TypeScript, Vite, Recharts |
| Outils | Git, GitHub, VS Code |

### Architecture en cinq couches

```
collecteurs  →  modèles  ←  services  →  estimateurs  →  base
   (brut)      (contrats)   (orchestr.)  (calcul pur)   (SQLite)
```

**Règle de dépendance à sens unique.** Les estimateurs ne touchent jamais à la
base, à WMI ni à psutil : ce sont des fonctions pures d'un instantané et d'un
profil de calibration. C'est ce qui les rend testables et permet de changer les
données de calibration sans toucher à la logique.

### Le modèle de puissance

$$P_{\text{totale}} = P_{\text{base}} + \alpha_{\text{CPU}} \times \text{CPU\%} + \alpha_{\text{RAM}} \times \text{RAM}_{\text{GB}}$$

Un quatrième terme pour le disque a été **retiré** : le delta de puissance
mesurable se situait sous le plancher de bruit du capteur batterie.

### Décisions de conception à défendre

| Décision | Raison |
|---|---|
| Un seul processus (agent) | Le collecteur mourait quand son terminal se fermait, et le tableau de bord servait des données périmées sans le signaler. Si l'agent tourne, la collecte tourne |
| SQLite en mode WAL | Une boucle écrit toutes les 1,5 s pendant que l'API lit en agrégeant : en mode journal par défaut, un lecteur bloque l'écrivain et la collecte est morte 14 heures sans que rien ne le signale |
| Deux cadences (1,5 s / 120 s) | Le tableau de bord doit paraître vivant ; la ligne de base statistique a besoin de jours, pas de résolution |
| Permission fichier comme contrôle d'accès | Un drapeau en ligne de commande n'est pas une permission : n'importe quel employé peut le passer |

---

## 5 · Réalisation et Démonstration

### Volumétrie collectée

Sur la machine de référence, du **10/08 au 30/08/2026** (20 jours) :

| Table | Lignes | Cadence |
|---|---|---|
| `measurements` | **279 389** | ~1,5 s |
| `process_samples` | 28 810 | 120 s |
| `telemetry_history` | 4 139 | 120 s |
| `workload_samples` | 1 770 | 120 s |
| `recommendations` | 99 | sur déclenchement |

### Le moteur de recommandations — et son réglage

C'est le meilleur récit d'ingénierie du projet, parce qu'il documente un échec
puis sa correction chiffrée.

**Version initiale — inutilisable.** Règle « moyenne + 1,5 σ ». Mesuré sur
1 258 lignes de télémétrie :

```
CPU  p50 = 20,6 %   p90 = 73,2 %
     moyenne 32,1 %, écart-type 24,8 %  →  1,5 σ déclenche au-dessus de 69,3 %
     part des échantillons qui déclencheraient : 11,3 %
```

À une cadence de 2 minutes, cela fait **une notification toutes les 18 minutes**.

**Trois corrections, et laquelle comptait vraiment :**

| Correction | Effet mesuré |
|---|---|
| Percentile p90 au lieu de σ | 16,2 notifications/jour — à peine mieux que 16,8 |
| **+ persistance (5 échantillons consécutifs)** | **0,6/jour** |
| + seuil d'impact énergétique | stabilise, ne réduit pas |

**Résultat final : 2,3 notifications/jour** (CPU 0,6 · RAM 1,6), mesuré en
rejouant six jours de télémétrie réelle.

**La leçon à écrire** : l'hypothèse gaussienne était fausse (« moyenne + 1,5 σ »
tombe vers le 88ᵉ percentile), mais la remplacer par un percentile ne réglait
rien — un percentile glissant déclenche sur (100−N) % des échantillons **par
construction**, sur n'importe quelle machine. Seule la persistance a compté.

**Un piège instructif** : le seuil d'impact, d'abord intégré à la condition de
déclenchement, a fait **augmenter** les notifications RAM de 2,3 à 5,7/jour. Une
puissance oscillant autour du seuil découpait un épisode unique en plusieurs,
chacun se ré-annonçant. Il ne devait pas conditionner l'appartenance à
l'épisode, seulement le fait de **parler**.

### Ce que l'outil a réellement trouvé

| Constat | Chiffre | Source |
|---|---|---|
| Énergie consommée machine inoccupée | **27 %** (14,3 Wh sur 96 min) | mesures propres |
| Énergie hors 08h–19h | **136 Wh sur 482 (28 %)** | horodatages |
| Dont week-end | **67 Wh** | idem |
| Chaque heure entre 00h et 02h | 16–18 Wh | idem |
| Coût d'une journée entière de Chrome | **1,27 Wh** | attribution par processus |
| Santé de la batterie | **46 %** | WMI `BatteryStaticData` |

**Le rapprochement qui porte l'argument** : 27 % de l'énergie part dans une
machine que personne n'utilise, quand la journée entière de Chrome coûte 1,27 Wh.
« Le CPU est anormalement élevé » décrit un ordinateur en train de faire son
travail ; aucune formulation ne rachète un événement sans action attachée.

⚠️ Ces pourcentages portent sur la fenêtre où le suivi d'inactivité fonctionnait,
pas sur les 20 jours. À formuler comme tel.

### La calibration en libre-service

Livré du 24 au 30/08. L'argument : l'équipe IT calibre un modèle et toutes les
machines identiques le récupèrent — mais jusque-là, le faire supposait d'éditer
la base à la main, ce qui mettait la calibration hors de portée de ceux qui
gèrent le parc.

- Assistant en 5 étapes à la première ouverture
- Tableau des profils : ajout, import, export, suppression
- Le sweep derrière un bouton, sans ligne de commande
- Mode IT réversible, avec trois sorties possibles
- Synchronisation entre sessions sans redémarrage

---

## 6 · Tests et Validation

**C'est la section qui donne sa crédibilité au rapport. Ne pas l'abréger.**

### Validation croisée du modèle

$$R^2 = 1 - \frac{SS_{\text{res}}}{SS_{\text{tot}}}$$

45 mesures, 9 campagnes, 3 sessions. Machine : Dell Latitude 7480.

| Modèle | MAE | MAPE | R² |
|---|---:|---:|---:|
| **En échantillon** — `4,69 + 0,1053 × cpu%` | 0,89 W | 8,0 % | **0,869** |
| **Hors échantillon** — une campagne retirée | 0,95 W | 8,5 % | **0,852** |
| **Hors échantillon** — une session retirée | 0,95 W | 8,7 % | **0,861** |
| **Modèle nul** — prédit la moyenne | 2,92 W | 28,8 % | **−0,014** |
| **Coefficients livrés** — avec le terme RAM | 1,40 W | 15,3 % | 0,707 |

Plage de puissance observée : 6,83–17,08 W (moyenne 10,69, écart-type 3,36).

**Les trois conclusions à écrire :**

1. **Le modèle généralise.** L'erreur hors échantillon est à peine supérieure à
   l'erreur en échantillon (0,95 contre 0,89 W) : il n'est pas surajusté.
2. **Il bat le modèle nul d'un facteur trois.** C'est la comparaison que le R²
   effectue silencieusement et que personne ne vérifie. Un R² hors échantillon
   **peut être négatif** ; celui en échantillon ne le peut jamais, et ne peut
   donc jamais alerter.
3. **La relation est stable entre les jours** : leave-one-session-out donne le
   même résultat que leave-one-sweep-out.

**Un détail méthodologique qui vaut d'être mentionné** : les découpages sont
**groupés, pas aléatoires**. Les lignes d'une même campagne partagent un état de
charge et un état thermique ; un découpage aléatoire évaluerait de
l'interpolation entre quasi-doublons et rapporterait un chiffre optimiste. À
noter aussi que `run_id` repart à 1 à chaque session, donc la clé de groupement
doit être (date, run_id) — grouper sur `run_id` seul fait fuiter l'information
d'un côté à l'autre du découpage.

### La consommation de base n'est pas l'ordonnée à l'origine

Point subtil et défendable :

```
4,69 W   ordonnée à l'origine de la régression
−2,78 W  contribution RAM pendant le sweep (0,375 W/GB × 7,4 GB)
=1,92 W  consommation de base mesurée séparément au repos
```

L'ordonnée à l'origine est une **extrapolation hors de la plage mesurée** — les
mesures ne descendent jamais sous 22 % de CPU. La consommation de base est donc
mesurée séparément (moyenne de 5 relevés, écart-type 0,702 W).

### Le sweep mémoire — un résultat nul, correctement établi

360 échantillons, 6 niveaux d'allocation, ordre aléatoire sur 6 rounds.

```
watts = 5,67 + 0,1345 × cpu%  − 0,0899 × ram_gb        (n = 360)
  coefficient RAM   −0,090 ± 0,215 W/GB
  intervalle 95 %   [−0,305 ; +0,126]
  ajout de la RAM au modèle CPU seul : R² 0,563 → 0,564, F = 0,67 (seuil 3,9)
```

**`0,375 W/GB de mémoire UTILISÉE est rejeté pour cette machine.** La valeur est
hors intervalle ; zéro est dedans.

**Ce n'est pas une expérience ratée mais un vrai résultat nul** : la manipulation
est vérifiée — l'allocation a fait monter `ram_used` de 10,88 à 13,48 GB de façon
monotone, écart-type 0,16–0,28 par niveau.

**Et cela n'invalide pas la littérature.** Les 3 W / 8 GB de CodeCarbon modélisent
la puissance de rafraîchissement DRAM, qui existe que l'OS ait distribué les
pages ou non — c'est une propriété de la capacité **installée**, donc une
constante, et une constante est exactement ce que l'expérience observe, absorbée
dans l'ordonnée à l'origine. L'erreur était d'appliquer par octet résident un
chiffre de capacité installée.

### ⚠️ Le désaccord non résolu — à assumer dans le rapport

Ce même sweep place le terme CPU à **0,1345 ± 0,0123 W/%**, intervalle
[0,122 ; 0,147], qui **exclut** le 0,1053 calibré. Deux expériences sur le même
portable, à douze jours d'écart, divergent d'environ **28 %**.

La colinéarité avec la RAM n'était que de +0,09, donc les estimations sont
proprement séparées : ce n'est pas un artefact d'ajustement.

Causes candidates : charge synthétique contre charge réelle mixte, fenêtres
d'échantillonnage du pourcentage CPU différentes, ou état thermique / turbo.

**C'est un point fort du rapport, pas une faiblesse** — à condition de le
présenter comme une question ouverte identifiée et bornée, avec l'expérience qui
la trancherait (un sweep sous les deux types de charge dans une même session).

### Ce que le système refuse de faire

| Garde-fou | Ce qu'il empêche |
|---|---|
| Bornes physiques à la saisie (CPU 0,02–0,60) | Une virgule mal placée devient un coefficient plausible et faux pour toujours |
| Provenance non requalifiable | Des valeurs saisies enregistrées comme mesurées |
| R² croisé sous seuil → refus d'écrire | Un mauvais profil « mesuré » héritant de l'autorité d'un sweep |
| Contrôle de l'agitation avant le sweep | Une régression sur une plage de 15 points |
| Comparaison retenue si historique insuffisant | Une variation spectaculaire calculée sur dix minutes |
| Comparaison retenue si la calibration a bougé | Un changement de modèle rapporté comme un changement de comportement |
| Trous affichés comme trous | Combler une absence de mesure par une valeur inventée |

---

## 7 · Bilan et Perspectives

### Difficultés rencontrées

**À raconter, ce sont les meilleures pages d'un rapport de stage.**

| Difficulté | Résolution |
|---|---|
| Mesurer la puissance sans matériel | LibreHardwareMonitor testé — les capteurs exposés ne donnent pas la puissance totale sur ce modèle. Repli sur le taux de décharge batterie via WMI |
| **L'instrument faussait sa propre mesure** | Ouvrir la connexion WMI à chaque lecture consommait assez de CPU pour être visible dans la mesure. Connexion mise en cache |
| Énergie fantôme au réveil | L'estimateur intégrait la puissance à travers la mise en veille : un réveil après 38 h a enregistré **641 Wh en un tick**. Plafond à 60 s. Migration corrective : **1 273,8 Wh retirés, soit 77,2 % du total enregistré** — le vrai chiffre était 376 Wh |
| La collecte mourait en silence | Base verrouillée → exception dans le thread démon → tableau de bord sain servant des données figées 14 h. Passage en WAL |
| L'agent mourait au démarrage automatique | Sous `pythonw` il n'y a pas de console : `sys.stdout` est `None`, le premier `print()` levait dans le thread de collecte, dont le gestionnaire d'erreur rapporte en imprimant, et levait à nouveau. Redirection vers un fichier de log |
| Un rapport d'état vide et rassurant | `schtasks /Query /FO LIST` renvoie des noms de champs **traduits** : sur un Windows français, chercher « Task To Run » ne trouvait rien. Lecture du XML de la tâche, non traduit |
| `requirements.txt` illisible | Encodé en **UTF-16 sans BOM** : une première réparation a échoué en silence, le décodage UTF-8 « réussissant » sur des octets nuls entrelacés |
| Le sweep de calibration inutilisable depuis l'interface | Imports non qualifiés (échec à l'import) et `input()` à chaque palier. Réécrit avec génération de charge programmatique |
| Modification invisible dans le navigateur | L'agent sert `frontend/dist`, pas les sources : il faut `npm run build` **et** redémarrer l'agent. Le symptôme ressemble exactement à un bug de la fonctionnalité |

**Le fil conducteur à formuler** : la plupart de ces défaillances étaient
**silencieuses**. Le code d'erreur disait « succès », le tableau de bord avait
l'air normal, le rapport d'état était vert. Ce qui les a révélées est d'avoir
regardé la donnée elle-même plutôt que le statut de l'opération.

### Acquis

**Techniques**
- Chaîne complète : collecte système → modèle physique → validation statistique → restitution
- Instrumentation Windows bas niveau (WMI, COM, DDC/CI, Task Scheduler)
- Régression et validation croisée appliquées à un cas réel
- Conception d'interface pilotée par la question posée

**Méthodologiques**
- Ne rien affirmer que la mesure ne soutient pas
- Traiter une absence comme une information, pas comme un vide à combler
- Concevoir les refus du système autant que ses fonctions

**La phrase de conclusion** : sur un outil dont toute la sortie est un chiffre de
gaspillage, la tentation permanente est de produire un chiffre même quand la
donnée ne le permet pas. Apprendre à afficher « je ne sais pas » a été le choix
de conception le plus structurant du projet.

### Limites, à énoncer sans les diluer

1. **La décomposition par composant n'est pas physique.** Le total est
   défendable ; la répartition CPU / RAM / base ne l'est pas.
2. **Deux estimations du coefficient CPU divergent de 28 %**, avec des
   intervalles disjoints. Non résolu.
3. **L'écran n'est pas dans le modèle**, alors que la dalle est un des plus gros
   consommateurs d'un portable.
4. **Un seul modèle de machine est calibré.** La prémisse est un parc
   standardisé ; n = 1 ne la teste pas.
5. **La calibration exige une batterie** — un poste fixe est hors de portée de
   cette méthode.
6. **Le carbone de fabrication est une estimation de classe.**

### Perspectives

**Court terme**
- Calibrer un deuxième modèle : valide le rapport de 70 % et transforme le repli
  d'expédient en premier point d'un modèle de parc
- Trancher le désaccord sur le coefficient CPU par une expérience dédiée
- Obtenir le PCF constructeur du Latitude 7480

**Moyen terme**
- Intégrer la luminosité au modèle de puissance : mécanisme clair, protocole
  connu (sweep de luminosité à CPU fixe, même dessin que le sweep mémoire)
- Notifications système, **une fois seulement** le signal assez rare — pousser
  le signal actuel apprendrait à l'utilisateur à l'ignorer
- Digest hebdomadaire : l'endroit où un modèle génératif gagnerait son coût, une
  inférence, latence sans importance, et aucune alerte en direct à corrompre

**Long terme**
- Consolidation à l'échelle d'une équipe, sans identifier les individus
- Intégration au pilotage du renouvellement du parc — la décision la plus
  importante n'est pas de réduire la consommation d'un poste, mais de décider
  s'il faut le remplacer

---

## Annexe · Chiffres de performance

| Optimisation | Avant | Après |
|---|---|---|
| `/api/history` sur 7 jours | 18,7 Mo | **63 Ko** (agrégation SQL) |
| Digest sur 145 000 lignes | 2,2 s par appel | mis en cache 60 s |
| Lecture de luminosité | 170 ms, soit 11 % d'un cycle de 1,5 s | échantillonnée toutes les 120 s |
| Minuteries de réveil | 3 s | cache 30 min |
| Réglages d'alimentation | 310 ms | cache 60 s |

---

## Annexe · Coefficients livrés

| Coefficient | Valeur | Origine |
|---|---|---|
| `cpu_watts_per_percent_usage` | **0,10532 W/%** | régression sur décharge batterie, 45 mesures |
| `ram_watts_per_gb_used` | 0,375 W/GB | ⚠️ valeur de littérature, **rejetée par la mesure** sur cette machine |
| `baseline_watts` | **1,9193 W** | moyenne de 5 mesures directes, σ = 0,702 W |
| Intensité carbone | 483 gCO₂eq/kWh | réseau tunisien |

Machine de référence : **Dell Inc. Latitude 7480**, Intel i5-6300U (TDP 15 W).
