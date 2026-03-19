"""
Dépendances et services globaux pour l'API.

Centralise l'initialisation des services et l'état de conversation.
"""

import traceback

# Imports des modèles et services
try:
    from models.chat_state import ChatState
    from models.llm_extractor import LLMExtractor
    from services.geocoding import GeocodingService
    from services.routing import RoutingService
    from config.settings import (
        QUESTIONS, 
        CONFIDENCE_VERY_HIGH,
        CONFIDENCE_ROUTE,
        CONFIDENCE_LANDMARK,
        CONFIDENCE_HIGH, 
        CONFIDENCE_MEDIUM, 
        CONFIDENCE_LOW
    )
    print("✅ Imports réussis (dependencies)")
except Exception as e:
    print(f"❌ Erreur imports dependencies: {e}")
    traceback.print_exc()


# ============================================================
# Services Singleton
# ============================================================

try:
    llm_extractor = LLMExtractor()
    geocoding_service = GeocodingService()
    routing_service = RoutingService()
    print("✅ Services initialisés")
except Exception as e:
    print(f"❌ Erreur init services: {e}")
    traceback.print_exc()
    llm_extractor = None
    geocoding_service = None
    routing_service = None


# ============================================================
# État Global de Conversation
# ============================================================

chat_state = ChatState()


def get_chat_state() -> ChatState:
    """Retourne l'état de conversation actuel"""
    return chat_state


def reset_chat_state():
    """Réinitialise l'état de conversation et le cache POI"""
    global chat_state
    chat_state.reset()
    if geocoding_service:
        geocoding_service.clear_cache()
    print("🔄 Conversation réinitialisée (cache POI nettoyé)")


def get_services():
    """Retourne un tuple de tous les services"""
    return llm_extractor, geocoding_service, routing_service
