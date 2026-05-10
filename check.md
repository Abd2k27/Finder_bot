# 🚀 Finder Bot - État du Projet (Session du 25 Avril 2026)

## 📋 Résumé des interventions
Cette session a porté sur la navigation temporelle (historique), la stabilisation du nettoyage sélectif de la carte et l'amélioration de la précision décisionnelle du LLM.

## 🏗️ Architecture du Projet
Le projet est structuré de manière modulaire :

### Frontend (`/static`)
- **`script.js`** : Point d'entrée, variables globales et protection du `progressCircle`.
- **`js/map_engine.js`** : Moteur Leaflet avec gestion de calques isolés (`confirmedPositionLayer`, `manualPoiLayer`, etc.) et nettoyage chirurgical via `keep_structure`.
- **`js/chat_engine.js`** : Gestion de la conversation.
- **`js/ui_engine.js`** : Contrôles d'interface et autocomplétion.

### Backend (`/api`)
- **`handlers/recalage_handlers.py`** : Intersection spatiale (multi-indices) et scoring par types d'indices distincts.
- **`handlers/action_handlers.py`** : Gestionnaire de l'historique et des retours en arrière (Undo/Jump).
- **`models/chat_state.py`** : Gestion de la pile `poi_history` (limite : 10 étapes) avec recherche par mot-clé.
- **`models/llm_extractor.py`** : Cerveau agentique extrayant désormais le `target_keyword` pour les retours en arrière précis.

## ✨ Fonctionnalités Clés Implémentées

### 1. Navigation dans l'Historique (Back/Jump)
- **Retour Arrière simple** : *"Reviens en arrière"* annule la dernière action et restaure la liste précédente.
- **Saut par mot-clé (Jump)** : *"Reviens à l'étape du Carrefour"* identifie la recherche spécifique dans l'historique et y retourne directement, peu importe le nombre d'étapes intermédiaires.
- **Persistance Textuelle** : Le chat réaffiche le titre exact de la recherche restaurée (ex: *"Retour à la recherche : Carrefour"*).

### 2. Nettoyage Chirurgical de la Carte
- **Protection de Structure** : L'itinéraire (bleu) et le cercle de progression théorique (orange/bleu large) sont protégés lors des retours en arrière.
- **Effacement des Indices** : Seuls les "indices de recherche" (points orange, points de preuve verts, étoile ⭐) sont nettoyés pour laisser place aux marqueurs de l'étape restaurée.
- **Signal `clear_map`** : Intégration d'un flag `keep_structure` permettant au serveur d'ordonner un nettoyage total ou partiel de la vue.

### 3. Logiciel de Décision "K.O. Victory"
- Le bot valide automatiquement une position si un candidat possède strictement plus de types d'indices confirmés (ex: Carrefour + Cabinet Infirmier) que tous ses concurrents.

## 🧪 Scénarios de Test Validés

### ✅ Scénario 1 : Recherche Multi-étapes et Filtrage
1. **User** : "Aucun, je vois un Carrefour" -> *Bot affiche 17 Carrefour.*
2. **User** : "Je vois un Cabinet Infirmier" -> *Bot filtre à 4 candidats (Carrefour ayant un Cabinet à <250m).*
3. **User** : "Je vois une Place Ney" -> *Bot confirme la localisation à Carrefour City ( ⭐ ).*

### ✅ Scénario 2 : Saut temporel (Jump)
1. **User** : "Cherche Carrefour" -> *Liste A affichée.*
2. **ARM** : Dessine un cercle sur la carte.
3. **ARM** : "Affiche les POI du cercle" -> *Liste B (400+ points) affichée.*
4. **ARM** : "Reviens à l'étape Carrefour" -> *Nettoyage de la map + Restauration immédiate de la Liste A.*

### ✅ Scénario 3 : Protection de l'Itinéraire
1. L'itinéraire Nantes-Angers est calculé.
2. Après plusieurs recherches et un retour en arrière au début de la conversation, **la ligne bleue et le cercle de progression restent affichés**, garantissant le maintien du contexte global pour l'ARM.

## 🛠️ Points de Vigilance (Known Issues)
- **Sensibilité orthographique** : Le saut dans l'historique est sensible aux pluriels (ex: "Carrefours" vs "Carrefour"). Le LLM tente de normaliser mais une correspondance exacte sur la racine est préférable.
- **Nettoyage ConfirmedLayer** : Bien s'assurer que `confirmedPositionLayer.clearLayers()` est appelé avant de ré-afficher des candidats pour éviter la superposition de l'étoile ⭐ et des marqueurs orange.

## 🚦 État Technique
- **Serveur** : FastAPI (Port 8000)
- **Cartographie** : Leaflet + OSRM
- **LLM** : Ollama (Decision Agentic + Entity Extraction)
