# 🤖 Rapport de Fonctionnement du Bot FindMe

## Vue d'ensemble

Le bot est un **chatbot de géolocalisation** qui aide un utilisateur en déplacement à retrouver sa position. Il utilise une architecture modulaire en 5 couches :

```
┌─────────────────────────────────────────────────────────────────┐
│                      Frontend (static/index.html)               │
│                              ↓ /chat                            │
├─────────────────────────────────────────────────────────────────┤
│                      API Routes (api/routes.py)                 │
│                              ↓                                  │
├─────────────────────────────────────────────────────────────────┤
│                      Handlers (api/handlers/)                   │
│  • action_handlers.py    (finish, clarify, reject, confirm)    │
│  • recalage_handlers.py  (route, landmark recalibration)       │
│  • position_handlers.py  (position calculation, POI suggest)   │
├─────────────────────────────────────────────────────────────────┤
│     Models                    │         Services                │
│  • ChatState                  │  • GeocodingService             │
│  • LLMExtractor               │  • RoutingService               │
├─────────────────────────────────────────────────────────────────┤
│  Config (config/settings.py)  │  Schemas (api/schemas.py)       │
│  • Variables d'environnement  │  • ChatMessage, ChatResponse    │
│  • Constantes de confiance    │  • GeocodeRequest               │
└─────────────────────────────────────────────────────────────────┘
```

---

## 📁 Structure du Projet

```
poc_bot_map/
├── main.py                  # Point d'entrée FastAPI
├── .env                     # Variables d'environnement (API keys)
├── .env.example             # Template sans secrets
├── requirements.txt         # Dépendances Python
│
├── api/
│   ├── routes.py            # Endpoints HTTP (~350 lignes)
│   ├── schemas.py           # Modèles Pydantic
│   ├── dependencies.py      # Services singleton + état global
│   └── handlers/
│       ├── __init__.py
│       ├── action_handlers.py     # Actions agentiques (5 fonctions)
│       ├── recalage_handlers.py   # Recalage position (5 fonctions)
│       └── position_handlers.py   # Calcul position (4 fonctions)
│
├── config/
│   └── settings.py          # Configuration (env vars + constantes)
│
├── models/
│   ├── chat_state.py        # État de conversation
│   └── llm_extractor.py     # Extraction LLM (Ollama)
│
├── services/
│   ├── geocoding.py         # Nominatim + OSMnx + Overpass
│   └── routing.py           # OSRM + calcul position
│
└── static/
    └── index.html           # Interface utilisateur
```

---

## 🔄 Flux Principal (`/chat`)

L'endpoint principal orchestre les appels via les handlers modulaires :

| Étape | Handler/Fonction | Module | Rôle |
|-------|------------------|--------|------|
| 1 | `llm_extractor.decide_action()` | LLMExtractor | Décision agentique |
| 2 | `handle_finish/clarify/reject_pois/...` | action_handlers | Dispatch des actions |
| 3 | `llm_extractor.extract_entities()` | LLMExtractor | Extraction entités |
| 4 | `handle_route_recalage()` | recalage_handlers | Recalage par route |
| 5 | `handle_landmark_recalage()` | recalage_handlers | Recalage par repère |
| 6 | `calculate_position_from_duration()` | position_handlers | Calcul position OSRM |
| 7 | `suggest_nearby_pois()` | position_handlers | Suggestion POI |

---

## 📞 Graphe des Appels de Fonctions

```
chat() ─── api/routes.py ───────────────────────────────────────────
   │
   ├── 🤖 LLMExtractor.decide_action(user_message, state_dict)
   │      └── Retourne: {action, response, poi_index}
   │
   ├── 🎯 DISPATCH ACTIONS (api/handlers/action_handlers.py)
   │      ├── handle_finish() → Fin conversation
   │      ├── handle_clarify() → Réponse à question
   │      ├── handle_reject_pois() → Demande description libre
   │      ├── handle_show_all_pois() → Affiche tous les POI
   │      └── handle_confirm_choice() → Recalage sur POI choisi
   │
   ├── 🤖 LLMExtractor.extract_entities(text, context)
   │      └── Retourne: {depart, fin, transport, duree, routes, reperes}
   │
   ├── 🛣️ RECALAGE (api/handlers/recalage_handlers.py)
   │      ├── handle_route_recalage() → Recalage par route citée
   │      └── handle_landmark_recalage() → Recalage par repère
   │
   └── 📍 POSITION (api/handlers/position_handlers.py)
          ├── calculate_position_from_duration() → Position OSRM
          ├── calculate_position_from_distance() → Position par km
          └── suggest_nearby_pois() → Projection POI sur tracé
```

---

## 🎯 Actions Agentiques (LLM)

Le LLM peut décider de 6 actions via `decide_action()` :

| Action | Déclencheur | Handler |
|--------|-------------|---------|
| `continue` | Par défaut | Extraction normale |
| `finish` | "Merci", "Ok c'est bon" | `handle_finish()` |
| `clarify` | "Comment ça marche?" | `handle_clarify()` |
| `reject_pois` | "Je vois aucun de ces lieux" | `handle_reject_pois()` |
| `confirm_choice` | "Le numéro 3" | `handle_confirm_choice()` |
| `show_all_pois` | "Montre-moi tout" | `handle_show_all_pois()` |

---

## 🏛️ Recalage de Position

Trois méthodes de recalage dans `recalage_handlers.py` :

| Type | Fonction | Source | Confiance |
|------|----------|--------|-----------|
| **Par Route** | `handle_route_recalage()` | Instructions OSRM + Overpass | `CONFIDENCE_ROUTE` |
| **Par Repère** | `handle_landmark_recalage()` | Cache OSMnx + fuzzy match | `CONFIDENCE_LANDMARK` |
| **Par Choix POI** | `handle_confirm_choice()` | Sélection utilisateur | `CONFIDENCE_VERY_HIGH` |

---

## 🔐 Sécurité

La clé API Ollama est stockée dans les variables d'environnement :

```bash
# .env (gitignored)
OLLAMA_API_KEY=votre_clé_ici
OLLAMA_MODEL=gpt-oss:120b-cloud
```

**Ne jamais committer le fichier `.env` !** Utiliser `.env.example` comme template.

---

## 📈 Services Externes Appelés

| API | Fonction | Usage |
|-----|----------|-------|
| **Ollama LLM** | `_call_ollama()` | Extraction entités + décision agentique |
| **Nominatim** | `geolocator.geocode()` | Géocodage villes/lieux |
| **OSRM** | `router.project-osrm.org` | Calcul itinéraire |
| **Overpass** | `_query_overpass_with_retry()` | Fallback POI + recherche routes |
| **OSMnx** | `features_from_point()` | Cache POI local |

---

## 🚀 Lancement

```bash
cd poc_bot_map
pip install -r requirements.txt
cp .env.example .env  # Puis remplir la clé API
python main.py
```

Serveur accessible sur `http://localhost:8000`
