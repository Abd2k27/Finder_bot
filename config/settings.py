# Configuration et constantes du projet
import os
from dotenv import load_dotenv

# Charger les variables d'environnement depuis .env
load_dotenv()

# Questions hiérarchiques posées progressivement à l'utilisateur
QUESTIONS = [
    "Bonjour ! Pour vous localiser, dites-moi d'où vous partez et où vous allez. Par exemple : 'De Paris à Lyon'",  # Q0: Départ + Arrivée
    "Comment voyagez-vous ? En voiture, bus, moto, à pied, ou à vélo ?",  # Q1: Mode transport (influence calcul vitesse/distance)
    "Depuis combien de temps êtes-vous en route ? Ou quelle distance pensez-vous avoir parcourue ?",  # Q2: Durée/Distance (clé pour position sur itinéraire)
    "Quels ont été vos derniers points de repère ? Par exemple : sortie d'autoroute, gare, ville traversée...",  # Q3: Repères passés (triangulation)
    "Que voyez-vous actuellement autour de vous ? Panneaux de signalisation, bâtiments, commerces, paysages...",  # Q4: Environnement actuel (affine position)
    "Dans quelle direction vous dirigez-vous ? Nord, sud, est, ouest, ou vers un point visible ?",  # Q5: Direction (ajuste coords)
    "Pouvez-vous demander à quelqu'un le nom de cette ville/rue, ou voir un panneau d'entrée de ville ?"  # Q6: Confirmation locale (dernière tentative)
]

# Configuration LLM (remplace CamemBERT qui était utilisé avant)
# CAMEMBERT_MODEL = "Jean-Baptiste/camembert-ner"  # DEPRECATED
NER_CONFIDENCE_THRESHOLD = 0.7  # Gardé pour compatibilité

# Configuration Ollama Cloud (LLM pour extraction d'entités)
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gpt-oss:120b-cloud")
OLLAMA_URL = os.getenv("OLLAMA_URL", "https://ollama.com/api/generate")
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", "")
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "120"))

# Configuration géocodage Nominatim (OpenStreetMap)
NOMINATIM_USER_AGENT = "lost_person_bot_v1"
NOMINATIM_TIMEOUT = 10
GEOCODING_SLEEP = 1

# Configuration Overpass API (OpenStreetMap - routes et POI)
OVERPASS_TIMEOUT = 25
FRANCE_AREA_ID = "3600065637"

# Overpass API mirrors for resilience (rotation on failure)
OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://z.overpass-api.de/api/interpreter",
]

# Retry configuration for Overpass API
OVERPASS_MAX_RETRIES = 3
OVERPASS_RETRY_BASE_DELAY = 2  # Base delay in seconds for exponential backoff

# ✅ CORRECTION: Suppression complète du train
# Mots-clés pour détection mode de transport par NLP simple
TRANSPORT_KEYWORDS = {
    'voiture': ['voiture', 'auto', 'automobile', 'conduis', 'conduire', 'roule', 'rouler'],
    'bus': ['bus', 'car', 'autobus', 'autocar', 'transport en commun'],
    'pied': ['pied', 'pieds', 'marche', 'marcher', 'randonnée', 'marche à pied'],
    'moto': ['moto', 'motard', 'scooter', 'deux-roues'],
    'velo': ['vélo', 'velo', 'bicyclette', 'cycliste', 'bike']
}

# Seuils de confiance pour estimation position (0-1)
CONFIDENCE_VERY_HIGH = 0.95  # Position confirmée par POI
CONFIDENCE_ROUTE = 0.90  # Position confirmée par route
CONFIDENCE_LANDMARK = 0.85  # Position confirmée par repère
CONFIDENCE_HIGH = 0.7  # Position très fiable (route sur trajet, itinéraire OSRM)
CONFIDENCE_MEDIUM = 0.5  # Position moyennement fiable (lieu géocodé, route sans contexte)
CONFIDENCE_LOW = 0.3  # Position peu fiable (interpolation simple, peu de données)

# Configuration serveur FastAPI
SERVER_HOST = "0.0.0.0"
SERVER_PORT = 8000