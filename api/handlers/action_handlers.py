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
    """
    print("🚫 Action REJECT_POIS - Utilisateur ne voit aucun POI")
    
    if chat_state.context.get('current_poi_list'):
        if 'rejected_pois' not in chat_state.context:
            chat_state.context['rejected_pois'] = []
        for p in chat_state.context['current_poi_list']:
            if p['name'] not in chat_state.context['rejected_pois']:
                chat_state.context['rejected_pois'].append(p['name'])
    
    chat_state.context['awaiting_poi_selection'] = False
    chat_state.context['current_poi_list'] = []
    chat_state.context['awaiting_description'] = True
    
    question = "Pouvez-vous me décrire précisément ce que vous voyez autour de vous (un commerce, un panneau, un carrefour, etc.) pour m'aider à vous situer ?"
    message = llm_response if llm_response else "D'accord, aucun de ces lieux ne correspond."
    if "décrire" not in message.lower() and "voyez" not in message.lower():
        message = f"{message}\n\n{question}"
    
    return ChatResponse(message=message, step=current_step + 1)


async def handle_show_all_pois(current_step: int) -> ChatResponse:
    """
    Action SHOW_ALL_POIS - Afficher tous les POI autour de la position (ou zone manuelle).
    Ne redessine pas de cercle si un cercle d'incertitude existe déjà.
    Quand la route est disponible, distribue les POI le long du tracé.
    """
    print("🗺️ Action SHOW_ALL_POIS - Affichage de tous les POI")
    
    manual_zone = chat_state.context.get('manual_zone')
    is_manual = False
    if manual_zone:
        lat, lon, radius = manual_zone['lat'], manual_zone['lon'], manual_zone['radius']
        source_label = "Zone manuelle"
        is_manual = True
    elif chat_state.has_position():
        lat, lon = chat_state.coordinates
        # Utiliser le rayon d'incertitude réel (stocké lors du calcul de position)
        uncertainty_radius = chat_state.context.get('uncertainty_radius', 3000)
        radius = uncertainty_radius + 500  # Petite marge pour la recherche
        source_label = "Position estimée"
    else:
        return ChatResponse(message="Aucune zone à explorer. Tracez un cercle sur la carte.", step=current_step + 1)
    
    try:
        # Types de routes génériques à filtrer
        generic_types = {'primary', 'secondary', 'tertiary', 'unclassified', 'residential', 'service', 'living_street', 'trunk'}
        
        # Rayon max pour garder les POI dans le cercle visible
        max_geo_distance = chat_state.context.get('uncertainty_radius', 3000)
        
        # Récupérer les POI — multi-points le long de la route pour couvrir tout le cercle
        nearby_pois = []
        if not is_manual and chat_state.has_route_data():
            route_data = chat_state.route_data
            range_info = chat_state.context.get('range_result')
            
            # Déterminer les points d'échantillonnage le long de la route
            if range_info:
                d_min = range_info.get('d_min', 0)
                d_max = range_info.get('d_max', route_data['total_distance'])
            else:
                # Estimer à partir du centre ± rayon
                total_dist = route_data['total_distance']
                estimated_dist = chat_state.context.get('estimated_distance', total_dist / 2)
                d_min = max(0, estimated_dist - max_geo_distance)
                d_max = min(total_dist * 1.3, estimated_dist + max_geo_distance)
            
            # Échantillonner N points le long de [D_min, D_max]
            n_samples = max(3, min(7, int((d_max - d_min) / 5000)))  # 1 point tous les 5km, min 3, max 7
            sample_distances = [d_min + i * (d_max - d_min) / (n_samples - 1) for i in range(n_samples)]
            
            seen_coords = set()
            fetch_radius = max(3000, int((d_max - d_min) / n_samples) + 1000)
            
            for sample_dist in sample_distances:
                sample_pos = routing_service.find_position_on_route(route_data, int(sample_dist))
                if not sample_pos:
                    continue
                pois_chunk = await geocoding_service.fetch_local_pois(
                    sample_pos[0], sample_pos[1], radius=fetch_radius
                )
                for p in pois_chunk:
                    coord_key = f"{p['lat']:.5f}_{p['lon']:.5f}"
                    if coord_key not in seen_coords:
                        seen_coords.add(coord_key)
                        nearby_pois.append(p)
            
            print(f"📡 {len(nearby_pois)} POI uniques récupérés depuis {n_samples} points d'échantillonnage")
        
        # Fallback: fetch depuis le centre seul
        if not nearby_pois:
            nearby_pois = await geocoding_service.fetch_local_pois(lat, lon, radius=radius)
        
        if not nearby_pois:
            return ChatResponse(message=f"Aucun point trouvé dans cette zone ({source_label}).", step=current_step + 1)
        
        # Filtrer les POI : types génériques, doublons, distance géographique
        all_filtered_pois = []
        if not is_manual and chat_state.has_route_data():
            projected = routing_service.project_pois_on_route(
                route_data, nearby_pois, max_distance_from_route=1500
            )
            
            if projected:
                vu_names = set()
                for p in projected:
                    name_clean = p['name'].lower().strip()
                    if name_clean in vu_names or len(name_clean) < 3:
                        continue
                    if p.get('type') in generic_types:
                        continue
                    geo_dist = routing_service._haversine_distance(lat, lon, p['lat'], p['lon'])
                    if geo_dist > max_geo_distance:
                        continue
                    vu_names.add(name_clean)
                    all_filtered_pois.append(p)
                
                print(f"🗺️ {len(all_filtered_pois)} POI dans le cercle (rayon {max_geo_distance}m)")
        
        # Fallback: pas de route data → filtrer par distance + doublons
        if not all_filtered_pois:
            vu_names = set()
            for p in nearby_pois:
                name_clean = p['name'].lower().strip()
                if name_clean in vu_names or len(name_clean) < 3:
                    continue
                if p.get('type') in generic_types:
                    continue
                vu_names.add(name_clean)
                all_filtered_pois.append(p)
        
        # Texte : lister les 15 premiers pour la lisibilité du chat
        text_pois = all_filtered_pois[:15]
        poi_message = f"🗺️ **Voici les points d'intérêt trouvés dans la zone ({source_label}) — {len(all_filtered_pois)} au total :**\n\n"
        for i, poi in enumerate(text_pois, 1):
            poi_message += f"{i}. {poi['name']} ({poi['type']})\n"
        if len(all_filtered_pois) > 15:
            poi_message += f"\n_...et {len(all_filtered_pois) - 15} autres affichés sur la carte._\n"
        
        chat_state.context['current_poi_list'] = all_filtered_pois
        chat_state.context['awaiting_poi_selection'] = True
        
        # Carte : afficher TOUS les POI
        if is_manual:
            map_updates = [{
                'type': 'search_area_circle', 'lat': lat, 'lon': lon, 'radius': radius,
                'confidence': 0.8, 'source': source_label, 'nearby_pois': all_filtered_pois,
                'fitBounds': True, 'clear': False
            }]
        else:
            # Envoyer tous les POI comme petits points verts (pas numérotés)
            map_updates = [{
                'type': 'pois_all',
                'pois': all_filtered_pois,
                'fitBounds': False,
                'estimated_position': {'lat': lat, 'lon': lon}
            }]
        
        # SAUVEGARDE HISTORIQUE
        chat_state.add_poi_to_history(f"Tous les POI ({source_label})", all_filtered_pois, map_updates)
        
        return ChatResponse(message=poi_message + "\nL'appelant en voit-il un parmi eux ?", step=current_step + 1, map_updates=map_updates)
    except Exception as e:
        print(f"Error handle_show_all_pois: {e}")
        return ChatResponse(message="Erreur lors du chargement des POI.", step=current_step + 1)


async def handle_show_previous_list(current_step: int, target_keyword: str = None) -> ChatResponse:
    """
    Action SHOW_PREVIOUS_LIST - Restaurer une recherche précédente par mot-clé ou par défaut (undo).
    """
    if target_keyword:
        print(f"🔙 Action SHOW_PREVIOUS_LIST - Recherche du mot-clé: {target_keyword}")
        prev = chat_state.find_specific_history(target_keyword)
    else:
        print("🔙 Action SHOW_PREVIOUS_LIST - Restauration (undo simple)")
        prev = chat_state.pop_previous_poi_list()
    
    if not prev:
        return ChatResponse(
            message="Je n'ai pas trouvé cette étape dans mon historique. Pouvez-vous me décrire où vous êtes ?",
            step=current_step + 1
        )
    
    # Restaurer dans le contexte
    chat_state.context['current_poi_list'] = prev['list']
    chat_state.context['awaiting_poi_selection'] = True
    chat_state.context['awaiting_description'] = False
    
    # Message de restauration
    msg = f"🔙 **Retour à la recherche : \"{prev['query']}\"**\n\n"
    for i, poi in enumerate(prev['list'][:10]):
        msg += f"{i+1}. {poi['name']} ({poi.get('type', 'repère')})\n"
    
    # FORCER LE NETTOYAGE CARTE SÉLECTIF (on garde la structure : trajet et progression)
    map_updates = [{'type': 'clear_map', 'keep_structure': True}] + prev['map_updates']
    
    return ChatResponse(
        message=msg + "\nLequel voyez-vous ?",
        step=current_step + 1,
        map_updates=map_updates
    )


async def handle_confirm_choice(user_response: str, poi_index: Optional[int], current_step: int) -> Tuple[Optional[ChatResponse], List[Dict]]:
    """
    Action CONFIRM_CHOICE - Validation d'un POI.
    """
    current_list = chat_state.context.get('current_poi_list', [])
    if not current_list: return None, []
    
    selected_poi = None
    if poi_index and 1 <= poi_index <= len(current_list):
        selected_poi = current_list[poi_index - 1]
    
    if not selected_poi:
        user_lower = user_response.lower().strip()
        for poi in current_list:
            if poi['name'].lower() in user_lower:
                selected_poi = poi
                break
    
    if not selected_poi: return None, []
    
    poi_lat, poi_lon = selected_poi['lat'], selected_poi['lon']
    chat_state.set_coordinates(poi_lat, poi_lon, CONFIDENCE_VERY_HIGH)
    chat_state.context.update({'recalage_done': True, 'awaiting_poi_selection': False, 'current_poi_list': []})
    
    recalage_message = f"✅ **Position recalée !** Vous êtes à **{selected_poi['name']}**.\n📍 Coordonnées: {poi_lat:.5f}, {poi_lon:.5f}\n"
    
    nearby_pois = []
    try:
        nearby_pois = await geocoding_service.fetch_local_pois(poi_lat, poi_lon, radius=1000)
    except: pass
    
    map_updates = [{
        'type': 'position_recaled',
        'lat': poi_lat, 'lon': poi_lon,
        'confidence': CONFIDENCE_VERY_HIGH,
        'source': selected_poi['name'],
        'name': selected_poi['name']
    }]
    
    return ChatResponse(message=recalage_message, step=current_step + 1, map_updates=map_updates), map_updates
