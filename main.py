#!/usr/bin/env python3
"""
Bot de localisation pour personnes perdues en France
Utilise Ollama/Gemma pour l'extraction d'entités et les APIs OpenStreetMap pour la géolocalisation
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from api.routes import router
from config.settings import SERVER_HOST, SERVER_PORT, OLLAMA_MODEL


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gestionnaire de cycle de vie FastAPI (remplace @app.on_event)"""
    # === STARTUP ===
    print("🚀 Démarrage du Bot de Localisation...")
    print("📡 Chargement des modèles en cours...")
    print("🗺️  Interface disponible sur http://localhost:8000")
    
    yield  # L'application s'exécute ici
    
    # === SHUTDOWN ===
    print("🔴 Arrêt du Bot de Localisation")


def create_app() -> FastAPI:
    """Créer et configurer l'application FastAPI"""
    app = FastAPI(
        title="Bot de Localisation",
        description="Assistant intelligent pour aider les personnes perdues en France à se géolocaliser",
        version="1.0.0",
        lifespan=lifespan  # Utilise le nouveau gestionnaire de contexte
    )
    
    # Monter les fichiers statiques
    app.mount("/static", StaticFiles(directory="static"), name="static")
    
    # Inclure les routes
    app.include_router(router)
    
    return app


# Créer l'instance de l'application
app = create_app()


if __name__ == "__main__":
    import uvicorn
    
    print("=" * 60)
    print("🧭 BOT DE LOCALISATION - DÉMARRAGE")
    print("=" * 60)
    print(f"🌐 Serveur: http://{SERVER_HOST}:{SERVER_PORT}")
    print(f"📱 Interface: http://localhost:{SERVER_PORT}")
    print(f"🤖 LLM: Ollama/{OLLAMA_MODEL}")
    print("🗺️  OpenStreetMap: Nominatim + Overpass")
    print("=" * 60)
    
    uvicorn.run(
        "main:app", 
        host=SERVER_HOST, 
        port=SERVER_PORT, 
        reload=True,
        log_level="info"
    )