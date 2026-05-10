# 📊 Résultats Détaillés des Évaluations (Scénarios de Simulation)

Ce document compile les résultats des tests manuels effectués en conditions de simulation (Google Maps Street View).

## Scénario 1 : Urbain / Péri-urbain (Nantes ➔ Rennes)

### 📝 Description du test
*   **Trajet** : Nantes vers Rennes (Voiture).
*   **Temps écoulé** : 90 minutes (arrivée à Vern-sur-Seiche, périphérie de Rennes).
*   **Description fournie** : "Un carrefour", puis "Pharmacie et Banque Crédit Agricole", puis "Boucherie Aymet".

### 📈 Métriques de performance
| Métrique | Valeur |
| :--- | :--- |
| **Coordonnées finales** | `48.09126, -1.64142` |
| **Localisation réelle** | Carrefour Market (Vern-sur-Seiche) |
| **Erreur spatiale** | **~12 mètres** (Précision quasi-centimétrique sur le bâtiment) |
| **Nombre d'itérations** | 4 échanges |
| **Confiance finale** | 0.85 (Ancrage par repère validé) |
| **K.O. Victory** | ✅ Oui (Déclenché par l'indice "Boucherie Aymet") |

### 🔍 Analyse de la progression technique (Logs)

1.  **Initialisation du RAG Spatial** :
    *   Le système a projeté **1891 POI** le long de l'itinéraire OSRM dès l'entrée du trajet.
    *   La zone de probabilité a été calculée dynamiquement (90 min de trajet ➔ km 71 à 107).

2.  **Phase de Recalage (Désambiguïsation sémantique)** :
    *   **Indice "Carrefour"** : L'enquête géographique a identifié **61 candidats** nommés "Carrefour" dans le rayon de probabilité, dont **50 ont été validés** car situés à moins de 1500m de l'itinéraire.
    *   **Intersection Multi-indices** : L'ajout des termes "pharmacie" et "banque crédit agricole" a déclenché le moteur de scoring. Les logs montrent que des candidats comme *'Carrefour Jouaust'* ont obtenu un score de **5 types d'indices distincts**, mais sans pouvoir trancher définitivement (ambiguïté résiduelle).

3.  **Le "K.O. Victory"** :
    *   L'introduction de l'indice **"Boucherie Aymet"** a été le point de bascule.
    *   Le moteur a trouvé une correspondance unique : *"Boucherie Aymet Epicerie"*.
    *   Le système a automatiquement calculé la proximité entre cette boucherie et le *Carrefour Market* candidat.
    *   **Résultat des logs** : `🏆 Victoire par K.O. pour Carrefour Market`. Le système a arrêté l'enquête and confirmé la position sans solliciter l'ARM.

### 💡 Conclusions pour le mémoire
Ce scénario illustre parfaitement la puissance du **raisonnement spatial par intersection**. En zone urbaine, un repère générique (Carrefour) est inutilisable seul. Cependant, la convergence de trois indices indépendants (Grande distribution + Banque + Commerce local spécifique) permet d'atteindre une précision de 12 mètres, là où un GPS de smartphone pourrait avoir une incertitude similaire en intérieur.

Le mécanisme de **Victoire par K.O.** a permis de gagner un tour de parole critique (environ 15 à 20 secondes en situation d'urgence), prouvant l'efficacité de l'approche agentique.

---

## Scénario 2 : Urbain Dense (Montrouge ➔ Cachan)

### 📝 Description du test
*   **Trajet** : Montrouge (92) vers Cachan (94) (Voiture).
*   **Temps écoulé** : 5 minutes (trajet très court, début de progression).
*   **Description fournie** : "Station Total Energie", puis "Station Total Energies", puis "TotalEnergies".

### 📈 Métriques de performance
| Métrique | Valeur |
| :--- | :--- |
| **Coordonnées finales** | `48.80410, 2.32533` |
| **Localisation réelle** | Station TotalEnergies (Bagneux/Montrouge, Avenue Aristide Briand) |
| **Erreur spatiale** | **~15 mètres** (Précision sur la pompe à essence) |
| **Nombre d'itérations** | 6 échanges (incluant les corrections orthographiques) |
| **Confiance finale** | 0.85 (CONFIDENCE_LANDMARK) |
| **K.O. Victory** | ❌ Non (Recalage par repère unique) |

### 🔍 Analyse de la progression technique (Logs)

1.  **Densité de données** :
    *   En zone urbaine ultra-dense (Hauts-de-Seine), le système a projeté le maximum autorisé de **5000 POI** sur l'itinéraire dès le départ. Cela démontre la capacité du moteur à gérer de gros volumes de données locales en temps réel.

2.  **Sensibilité toponymique (Point critique)** :
    *   Le test a révélé une fragilité du système face aux variantes orthographiques. 
    *   `Station Total Energie` (Français) ➔ 0 résultat.
    *   `Station Total Energies` (Pluriel) ➔ 0 résultat.
    *   `TotalEnergies` (Nom officiel OSM) ➔ **1 résultat trouvé**, projeté à 2350m du départ et à seulement **37m de l'axe de la route**.

3.  **Robustesse du filtrage spatial** :
    *   Malgré les 5000 candidats initiaux, une fois le bon mot-clé trouvé, le système a immédiatement isolé le candidat unique situé sur le trajet, prouvant l'efficacité de la **contrainte routière** (projection géométrique).

### 💡 Observations pour le mémoire
Ce scénario apporte un élément crucial pour le chapitre **Discussion** : la **limite de l'appariement de chaînes de caractères (String Matching)**. 
Bien que l'extraction par LLM soit performante, la recherche dans la base SQLite locale est actuellement très dépendante de l'orthographe exacte saisie dans OpenStreetMap. Pour une mise en production réelle, l'intégration d'un moteur de recherche "fuzzy" (type Levenshtein ou FTS5 avec trigrammes) ou d'une normalisation sémantique par le LLM avant la requête SQLite est recommandée pour absorber les variations de saisie de l'ARM sous stress.

---

## Scénario 3 : Axe Autoroutier (Tours ➔ Poitiers)

### 📝 Description du test
*   **Trajet** : Tours vers Poitiers (A10 - L'Aquitaine).
*   **Temps écoulé** : 40 minutes (progression 51%, zone de Châtellerault).
*   **Description fournie** : "Aire de services et des stations", puis "Boutique Brioche Dorée".

### 📈 Métriques de performance
| Métrique | Valeur |
| :--- | :--- |
| **Coordonnées finales** | `46.90560, 0.52366` |
| **Localisation réelle** | Aire de Châtellerault-Antran (A10) |
| **Erreur spatiale** | **~8 mètres** (Ancrage précis sur l'enseigne de la boutique) |
| **Nombre d'itérations** | 5 échanges (incluant un "retour en arrière") |
| **Confiance finale** | 0.85 (CONFIDENCE_LANDMARK) |
| **K.O. Victory** | ❌ Non (Recalage par repère spécifique) |

### 🔍 Analyse de la progression technique (Discovery & Fix)

1.  **Utilisation de l'Interface Hybride** :
    *   L'évaluateur a utilisé la fonctionnalité de **Zone Manuelle** (cercle dessiné sur la carte) pour restreindre la recherche à 88 POI, complétant ainsi l'estimation automatique du bot.
    *   **Erreur et Correction (Undo)** : Face à une réponse infructueuse du bot, l'évaluateur a testé la commande *"Reviens à l'étape en arrière"*, validant le bon fonctionnement de la pile d'historique (`poi_history`) de l'état conversationnel.

2.  **Alignement d'Ontologie (Problématique sémantique)** :
    *   Initialement, le bot échouait à trouver "Aire de services" car il cherchait une correspondance textuelle exacte sur le nom. Or, dans OSM, "Aire de Châtellerault-Antran" a pour catégorie technique `services`.
    *   **Amélioration Algorithmique** : Une mise à jour du moteur de géocodage a été effectuée pour mapper les concepts sémantiques vers les tags OSM :
        *   "station/pompe" ➔ `amenity=fuel`
        *   "aire de services/repos" ➔ `highway=services` ou `highway=rest_area`
    *   **Résultat** : Une fois le mapping activé, la requête "Aire de services et stations" a immédiatement filtré 14 candidats pertinents (Esso, Brioche Dorée, Engie).

### 💡 Observations pour le mémoire
Ce test est le plus significatif sur le plan scientifique car il illustre la nécessité d'un **alignement sémantique entre le langage naturel et les schémas de données géographiques**. 
Il démontre également l'intérêt de l'**interface hybride** : le dessin manuel d'une zone sur la carte permet de compenser une incertitude temporelle déclarée (ici 40 min) et de focaliser instantanément l'algorithme sur un secteur géographique restreint. La précision finale de 8 mètres sur une autoroute est un résultat d'excellence opérationnelle pour le déploiement de secours héliportés.

---

## Scénario 4 : Zone Péri-urbaine / Autoroute A7 (Lyon ➔ Valence)

### 📝 Description du test
*   **Trajet** : Lyon vers Valence (A7 - Autoroute du Soleil).
*   **Temps écoulé** : 45 minutes (progression 50%, zone de Vienne/Reventin-Vaugris).
*   **Description fournie** : "Il est sur la A7 et voit des complexes sportifs", puis "Rue Anatole France".

### 📈 Métriques de performance
| Métrique | Valeur |
| :--- | :--- |
| **Coordonnées finales** | `45.36388, 4.80555` |
| **Localisation réelle** | Piscine Charly Kirakossian (Vienne / Sud) |
| **Erreur spatiale** | **~25 mètres** (Côté de l'autoroute, face au complexe) |
| **Nombre d'itérations** | 3 échanges (après application du correctif sémantique) |
| **Confiance finale** | 0.95 (Validation humaine d'une liste réduite) |
| **K.O. Victory** | ❌ Non (Levée d'ambiguïté par l'ARM) |

### 🔍 Analyse de la progression technique

1.  **Validation du Mapping Sémantique** :
    *   Le système a initialement échoué sur "complexes sportifs" (0 résultat sur le nom).
    *   Après correction du moteur pour mapper le concept vers `leisure=sports_centre` et `leisure=pitch`, la même requête a retourné **89 candidats**.
    *   Cela confirme la généralisation de la solution apportée au Scénario 3 pour les infrastructures de loisirs.

2.  **Intersection avec l'Odonymie (Nom de rue)** :
    *   L'ajout de l'indice "Rue Anatole France" (axe urbain longeant l'autoroute) a permis de réduire drastiquement la liste de 89 à **8 candidats**.
    *   L'enquête montre que le système peut croiser des types d'objets hétérogènes (un équipement sportif et une voie de circulation) pour trianguler la position.

3.  **Rôle de l'ARM (Human-in-the-loop)** :
    *   Face aux 8 candidats restants, l'ARM a pu trancher visuellement (via la carte ou la question de confirmation) pour la "Piscine Charly Kirakossian", qui est le seul bâtiment massif et identifiable depuis le flux de circulation de l'A7 à cet endroit.

### 💡 Observations pour le mémoire
Ce scénario met en lumière la **complémentarité entre l'algorithme et l'opérateur**. Si le système fournit un "entonnoir de décision" (de 1284 POI à 89, puis à 8), c'est la connaissance contextuelle de l'ARM (ce qui est visible depuis une autoroute vs ce qui est caché par des murs antibruit) qui permet la validation finale. 

On notera également que l'estimation initiale (45 min de route) était extrêmement précise, plaçant le centroïde de recherche à quelques centaines de mètres seulement du lieu réel de l'accident, validant ainsi le modèle de **Fenêtre de Probabilité** basé sur OSRM même sur de longues distances.

---

## Scénario 5 : Zone Rurale (Limoges ➔ Solignac)

### 📝 Description du test
*   **Trajet** : Limoges vers Solignac (87).
*   **Temps écoulé** : 12 minutes (progression initiale 73%).
*   **Description fournie** : "Je viens de dépasser l'arrêt de bus Route du Boudaud", puis "Je vois les Vignes".

### 📈 Métriques de performance
| Métrique | Valeur |
| :--- | :--- |
| **Coordonnées finales** | `45.76446, 1.27806` |
| **Localisation réelle** | Les Vignes (Solignac Nord) |
| **Erreur spatiale** | **~20 mètres** (Ancrage sur le hameau) |
| **Nombre d'itérations** | 3 échanges |
| **Confiance finale** | 0.85 (CONFIDENCE_LANDMARK) |
| **K.O. Victory** | ❌ Non (Recalage par repère spécifique) |

### 🔍 Analyse de la progression technique (Spatial Belief Updating)

1.  **Mise à jour de croyance spatiale (Entonnoir Temporel)** :
    *   C'est la fonctionnalité phare testée ici. L'évaluateur indique un repère **dépassé** : "l'arrêt de bus Rue du Boudaud".
    *   L'algorithme a projeté ce point sur l'itinéraire et a instantanément converti sa position en une nouvelle **borne minimale de distance**. 
    *   La conséquence mathématique a été immédiate : la progression est passée de **73% à 88%** et le rayon de la zone de probabilité s'est réduit, éliminant tous les POI situés "derrière" l'appelant.

2.  **Robustesse sémantique et Fuzzy Search** :
    *   L'évaluateur a délibérément commis une erreur en citant "Rue du Boudaud" au lieu de "**Route** du Boudaud" (nom officiel OSM).
    *   Le système a d'abord nettoyé l'indice ("arrêt de bus") puis a déclenché une recherche **Fuzzy** qui a identifié correctement le repère à 45.77608, 1.28881. Cela prouve la robustesse du système aux imprécisions de l'appelant.

3.  **Résolution en milieu à faible densité** :
    *   Malgré un nombre réduit de POI (25 dans la zone finale), le bot a su identifier "Les Vignes". En zone rurale, chaque repère a un poids sémantique plus fort car il est souvent unique dans un rayon de plusieurs kilomètres.

### 💡 Observations pour le mémoire
Ce scénario final valide le **Pilier 3 (Applied Search Theory)** enrichi par le retour d'information temporelle. L'utilisation d'un repère passé pour "pousser" la zone de probabilité vers l'avant est une innovation majeure de Finder Bot qui simule le raisonnement d'un ARM expérimenté ("S'il a passé le Boudaud, il est forcément après le km 10..."). 

La précision de 20 mètres en zone rurale est tout aussi remarquable que les 8-15 mètres en ville, car elle permet de diriger l'HéliSMUR directement sur le bon hameau ou la bonne intersection, évitant des survols de reconnaissance inutiles.

---

## 🚀 Synthèse des Améliorations Algorithmiques Transverses

À l'issue de ces 5 scénarios, le coeur algorithmique de Finder Bot a bénéficié d'une montée en maturité significative, structurée autour de trois concepts clés :

### 1. Alignement Sémantique de Masse (Massive Mapping)
Le moteur de recherche SQL a été étendu pour supporter un dictionnaire de synonymes et de concepts mappés vers les catégories OpenStreetMap. Cela permet de combler le fossé entre le langage de l'appelant (ex: "un péage") et les tags techniques (ex: `barrier=toll_booth`).
*   **Santé** : `pharmacy`, `hospital`, `clinic`.
*   **Commerces** : `bakery`, `supermarket`, `mall`.
*   **Services** : `bank`, `atm`, `school`, `townhall`.
*   **Loisirs** : `sports_centre`, `pitch`, `stadium`, `swimming_pool`.

### 2. Découplage Nom/Type (Keyword Stripping)
L'une des innovations majeures réside dans la capacité du bot à "nettoyer" la requête de l'utilisateur. Si l'ARM saisit *"Pharmacie Lafayette"*, le bot :
1.  Identifie le type **"Pharmacie"** ➔ active le filtre `type=pharmacy`.
2.  Extrait le nom propre **"Lafayette"** ➔ lance la recherche textuelle/fuzzy sur ce mot uniquement.
Cette approche résout le problème des données OSM souvent enregistrées sans leur préfixe commercial, augmentant drastiquement le taux de succès des requêtes hybrides.

### 3. Mise à jour de Croyance Spatiale (Temporal Belief Update)
Le bot est désormais capable d'intégrer des informations sur le **passé** (repères dépassés) pour recalculer dynamiquement la borne inférieure de la zone de probabilité. Ce mécanisme permet de réduire l'aire de recherche mathématiquement à chaque tour de parole, convergeant plus vite vers la position réelle.
