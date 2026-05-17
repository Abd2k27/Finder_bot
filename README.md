# Finder Bot — Assistant de géolocalisation SAMU

**Finder Bot** est un outil intelligent d'aide à la localisation pour les Assistants de Régulation Médicale (ARM) dans le cadre du projet **HéliSMUR**.

Il permet de transformer les descriptions orales de trajets et d'environnement fournies par les appelants (au 15) en coordonnées géographiques précises grâce à une approche hybride (Chat + Formulaire) et une base de données locale exhaustive.

## 🚀 Fonctionnalités Clés

- **Interface Hybride** : Saisie structurée par formulaire synchronisée avec un chatbot NLP.
- **Orchestration Agentique** : Analyse automatique des intentions et extraction d'entités (LLM local).
- **Base de Données Locale** : Plus de 12 millions de points d'intérêt (POI) français extraits d'OpenStreetMap via un pipeline d'ingestion hybride (ingest_osm + ingest_complement), accessibles sans internet.
- **Moteur de Triangulation** : Croisement du trajet (OSRM), du temps de parcours et des repères visuels réels (Fuzzy Matching).
- **Validation Spatiale** : Filtrage automatique des faux positifs via la proximité à l'itinéraire.

## 🛠️ Installation

1. **Environnement** :
   ```bash
   pip install -r requirements.txt
   pip install osmium osmnx
   ```

2. **Données** :
   - Placer le fichier `france-latest.osm.pbf` dans le dossier `data/`.
   - Lancer l'ingestion de la base locale :
     ```bash
     python scripts/ingest_osm.py
     ```

3. **Lancement** :
   ```bash
   python main.py
   ```

## 📂 Structure du projet

- `/api` : Orchestrateur et gestionnaires d'actions.
- `/models` : État de la conversation et extraction NLP.
- `/services` : Moteurs de géocodage et de routage.
- `/static` : Interface utilisateur (HTML/CSS/JS).
- `/data` : Base SQLite locale et données source OSM.
- `/memoire` : Brouillons et rapports du mémoire M2 DSS.

---

  Contrairement à un RAG classique qui interroge une base de données vectorielle de documents, ce projet utilise une approche hybride pour
  la géolocalisation :

  1. Retrieval (Récupération)
  Au lieu d'utiliser des "embeddings" et une base vectorielle, le système récupère des données géospatiales structurées :
   * Base de connaissances : Une base SQLite locale (data/pois_local.db) contenant des Points d'Intérêt (POI) issus d'OpenStreetMap.
   * Moteurs de recherche : Le code (services/geocoding.py) effectue des recherches spatiales (autour d'un point ou le long d'un
     itinéraire) combinées à une recherche textuelle floue (fuzzy matching via difflib) pour retrouver des repères cités par l'appelant.

  2. Augmentation (Ancrage)
  Le LLM n'est pas utilisé pour "connaître" la carte (ce qui éviterait les hallucinations géographiques), mais pour extraire les intentions
  :
   * Extraction Sémantique : models/llm_extractor.py utilise GPT via Ollama pour extraire les repères visuels ("Je vois un garage"), les durées et
     les directions depuis le texte brut.
   * Ancrage Spatial : Ces entités extraites servent de filtres pour interroger la base OSM. Le résultat de cette recherche (les
     coordonnées réelles des POI) "augmente" le contexte du système pour recalculer la position probable.

  3. Raisonnement Agentique
  Le système utilise également le LLM comme un agent décisionnel (decide_action) qui, en fonction des POI récupérés et de l'état de la
  conversation, choisit la prochaine étape (recalage, confirmation, demande de précision).
