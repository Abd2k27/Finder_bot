"""
Gestionnaires des actions agentiques.

Traite les décisions du LLM : finish, clarify, reject_pois, show_all_pois, confirm_choice.
"""

from typing import Dict, List, Optional, Tuple
from api.schemas import ChatResponse
from api.dependencies import (
    chat_state, geocoding_service, routing_service,
    CONFIDENCE_VERY_HIGH
)


async def handle_finish(llm_response: Optional[str], current_step: int) -> ChatResponse:
    """
    Action FINISH - L'utilisateur termine la conversation.
    
    Args:
        llm_response: Réponse générée par le LLM
        current_step: Étape actuelle de la conversation
    
    Returns:
        ChatResponse avec message de conclusion
    """
    print("🏁 Action FINISH - Fin de conversation")
    return ChatResponse(
        message=llm_response or "Avec plaisir ! Bon voyage !",
        step=current_step + 1,
        entities=None,
        map_updates=None
    )


async def handle_clarify(llm_response: Optional[str], current_step: int) -> ChatResponse:
    """
    Action CLARIFY - L'utilisateur pose une question ou est confus.
    
    Args:
        llm_response: Réponse explicative du LLM
        current_step: Étape actuelle
    
    Returns:
        ChatResponse avec explication
    """
    print("❓ Action CLARIFY - Question/confusion de l'utilisateur")
    return ChatResponse(
        message=llm_response or "Je suis là pour vous aider à vous localiser. Décrivez ce que vous voyez autour de vous.",
        step=current_step + 1,
        entities=None,
        map_updates=None
    )


async def handle_reject_pois(llm_response: Optional[str], current_step: int) -> ChatResponse:
    """
    Action REJECT_POIS - L'utilisateur ne voit aucun POI proposé.
    
    Sauvegarde les POI rejetés et demande une description libre.
    
    Args:
        llm_response: Message du LLM
        current_step: Étape actuelle
    
    Returns:
        ChatResponse demandant une description
    """
    print("🚫 Action REJECT_POIS - Utilisateur ne voit aucun POI")
    
    # Sauvegarder les POI rejetés
    if chat_state.context.get('current_poi_list'):
        for p in chat_state.context['current_poi_list']:
            if p['name'] not in chat_state.context['rejected_pois']:
                chat_state.context['rejected_pois'].append(p['name'])
        print(f"📝 POI rejetés ajoutés: {len(chat_state.context['current_poi_list'])} POI")
    
    # Réinitialiser l'état d'attente
    chat_state.context['awaiting_poi_selection'] = False
    chat_state.context['current_poi_list'] = []
    chat_state.context['awaiting_description'] = True
    
    return ChatResponse(
        message=llm_response or "D'accord, vous ne voyez aucun de ces points de repère. Pouvez-vous me décrire précisément ce que vous voyez autour de vous ?",
        step=current_step + 1,
        entities=None,
        map_updates=None
    )


async def handle_show_all_pois(current_step: int) -> ChatResponse:
    """
    Action SHOW_ALL_POIS - Afficher tous les POI autour de la position.
    
    Charge les POI dans un rayon de 5km et les affiche sur la carte.
    
    Args:
        current_step: Étape actuelle
    
    Returns:
        ChatResponse avec liste des POI et mises à jour carte
    """
    print("🗺️ Action SHOW_ALL_POIS - Affichage de tous les POI")
    
    if not chat_state.has_position():
        return ChatResponse(
            message="Je n'ai pas encore de position estimée. Pouvez-vous me donner plus d'informations sur votre trajet et le temps écoulé ?",
            step=current_step + 1,
            entities=None,
            map_updates=None
        )
    
    lat, lon = chat_state.coordinates
    map_updates = []
    
    try:
        # Charger tous les POI dans un rayon de 5km
        nearby_pois = await geocoding_service.fetch_local_pois(lat, lon, radius=5000)
        
        if not nearby_pois:
            return ChatResponse(
                message="Je n'ai pas trouvé de POI dans cette zone. Pouvez-vous me décrire ce que vous voyez ?",
                step=current_step + 1,
                entities=None,
                map_updates=None
            )
        
        print(f"✅ {len(nearby_pois)} POI chargés pour affichage")
        
        # Construire le message
        poi_message = f"🗺️ **Voici tous les points d'intérêt dans un rayon de 5km autour de votre position estimée :**\n\n"
        for i, poi in enumerate(nearby_pois[:15]):  # Max 15 dans le texte
            poi_message += f"**{i+1}.** {poi['name']} ({poi['type']})\n"
        if len(nearby_pois) > 15:
            poi_message += f"\n...et {len(nearby_pois) - 15} autres POI affichés sur la carte.\n"
        poi_message += "\n*Voyez-vous l'un de ces lieux ? Indiquez le numéro ou décrivez ce que vous voyez.*"
        
        # Stocker la liste pour sélection ultérieure
        chat_state.context['current_poi_list'] = nearby_pois
        chat_state.context['awaiting_poi_selection'] = True
        chat_state.context['awaiting_description'] = False
        
        # Envoyer search_area_circle avec tous les POI
        map_updates.append({
            'type': 'search_area_circle',
            'lat': lat,
            'lon': lon,
            'radius': 5000,
            'confidence': chat_state.confidence,
            'source': 'Position estimée',
            'poi_type': 'Zone de recherche',
            'nearby_pois': nearby_pois,
            'fitBounds': True
        })
        
        print(f"🔵 ENVOI search_area_circle: {len(nearby_pois)} POI verts")
        
        return ChatResponse(
            message=poi_message,
            step=current_step + 1,
            entities=None,
            map_updates=map_updates
        )
        
    except Exception as e:
        print(f"⚠️  Erreur chargement POI: {e}")
        return ChatResponse(
            message="Une erreur est survenue lors du chargement des POI. Pouvez-vous me décrire ce que vous voyez ?",
            step=current_step + 1,
            entities=None,
            map_updates=None
        )


async def handle_confirm_choice(
    user_response: str, 
    poi_index: Optional[int], 
    current_step: int
) -> Tuple[Optional[ChatResponse], List[Dict]]:
    """
    Action CONFIRM_CHOICE - L'utilisateur choisit un POI par numéro/nom.
    
    Effectue le recalage sur le POI sélectionné.
    
    Args:
        user_response: Message brut de l'utilisateur
        poi_index: Index du POI extrait par le LLM (1-indexed)
        current_step: Étape actuelle
    
    Returns:
        Tuple (ChatResponse si succès, map_updates)
        Si None en premier élément, le choix n'a pas été confirmé
    """
    current_list = chat_state.context.get('current_poi_list', [])
    
    if not current_list:
        return None, []
    
    selected_poi = None
    map_updates = []
    
    print(f"✅ Action CONFIRM_CHOICE - Index demandé: {poi_index}")
    
    # Sélection par index (LLM a extrait le numéro)
    if poi_index and 1 <= poi_index <= len(current_list):
        selected_poi = current_list[poi_index - 1]
        print(f"✅ POI sélectionné par numéro {poi_index}: {selected_poi['name']}")
    
    # Fallback: Détection par nom si LLM n'a pas trouvé l'index
    if not selected_poi:
        user_lower = user_response.lower().strip()
        for poi in current_list:
            if poi['name'].lower() in user_lower or user_lower in poi['name'].lower():
                selected_poi = poi
                print(f"✅ POI sélectionné par nom (fallback): {poi['name']}")
                break
    
    if not selected_poi:
        return None, []
    
    # === RECALAGE SUR LE POI CONFIRMÉ ===
    print(f"\n{'='*60}")
    print(f"🎯 RECALAGE POI CONFIRMÉ: {selected_poi['name']}")
    print(f"{'='*60}")
    
    poi_lat = selected_poi['lat']
    poi_lon = selected_poi['lon']
    chat_state.set_coordinates(poi_lat, poi_lon, CONFIDENCE_VERY_HIGH)
    
    # Calculer la nouvelle durée depuis ce point
    if chat_state.has_route_data() and 'cumulative_distance' in selected_poi:
        poi_distance = selected_poi['cumulative_distance']
        total_distance = chat_state.route_data['total_distance']
        total_duration = chat_state.route_data['total_duration']
        
        new_duration_sec = (poi_distance / total_distance) * total_duration
        new_duration_min = int(new_duration_sec / 60)
        
        chat_state.context['duration'] = new_duration_min
        print(f"⏱️  Durée recalée: {new_duration_min} min")
    
    chat_state.context['recalage_done'] = True
    chat_state.context['awaiting_poi_selection'] = False
    chat_state.context['current_poi_list'] = []
    
    recalage_message = f"✅ **Position recalée !** Vous êtes à **{selected_poi['name']}** ({selected_poi['type']}).\n\n"
    recalage_message += f"📍 Coordonnées: {poi_lat:.5f}, {poi_lon:.5f}\n\n"
    
    print(f"📍 Nouvelle position: {poi_lat:.4f}°N, {poi_lon:.4f}°E")
    
    # Charger les POI autour du point recalé (1km)
    nearby_pois_list = []
    try:
        nearby_pois = await geocoding_service.fetch_local_pois(poi_lat, poi_lon, radius=1000)
        if nearby_pois:
            other_pois = [p for p in nearby_pois if p['name'] != selected_poi['name']]
            nearby_pois_list = other_pois
            if other_pois:
                recalage_message += f"**{len(other_pois)} POI autour de ce point (1km) :**\n"
                for poi in other_pois[:8]:
                    recalage_message += f"- {poi['name']} ({poi['type']})\n"
                print(f"✅ {len(other_pois)} POI trouvés autour du point recalé")
    except Exception as e:
        print(f"⚠️  Erreur recherche POI: {e}")
    
    # Cercle 1km + POI verts
    map_updates.append({
        'type': 'search_area_circle',
        'lat': poi_lat,
        'lon': poi_lon,
        'radius': 1000,
        'confidence': CONFIDENCE_VERY_HIGH,
        'source': selected_poi['name'],
        'poi_type': selected_poi['type'],
        'nearby_pois': nearby_pois_list,
        'fitBounds': True
    })
    
    print(f"\n🔵 ENVOI search_area_circle: {len(nearby_pois_list)} POI verts")
    
    return ChatResponse(
        message=recalage_message,
        step=current_step + 1,
        entities=None,
        map_updates=map_updates
    ), map_updates
