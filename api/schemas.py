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


class ContextUpdate(BaseModel):
    """Mise à jour du contexte via le formulaire ou zone manuelle"""
    start: Optional[str] = None
    end: Optional[str] = None
    transport: Optional[str] = None
    duration: Optional[int] = None
    step: int
    # Champs pour la zone manuelle (dessin ARM)
    lat: Optional[float] = None
    lon: Optional[float] = None
    radius: Optional[int] = None
    type: Optional[str] = None


class StateResponse(BaseModel):
    """Réponse contenant l'état actuel du contexte"""
    start: Optional[str] = None
    end: Optional[str] = None
    transport: Optional[str] = None
    duration: Optional[int] = None
    confidence: float
    position_estimee: Optional[Dict] = None
