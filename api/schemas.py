"""
Schémas Pydantic pour l'API du bot de localisation.
"""

from pydantic import BaseModel
from typing import Dict, List, Optional


class ChatMessage(BaseModel):
    """Message entrant de l'utilisateur"""
    response: str
    step: int


class ChatResponse(BaseModel):
    """Réponse du bot vers le frontend"""
    message: str
    step: int
    entities: Optional[Dict] = None
    map_updates: Optional[List[Dict]] = None


class GeocodeRequest(BaseModel):
    """Requête de géocodage"""
    query: str
