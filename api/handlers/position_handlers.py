"""
Gestionnaires de calcul et estimation de position.

Traite le calcul de position basé sur durée/distance et les suggestions de POI.
"""

import traceback
from typing import Dict, List, Optional, Tuple

from api.schemas import ChatResponse
from api.dependencies import (
    chat_state, geocoding_service, routing_service,
    CONFIDENCE_HIGH, CONFIDENCE_LANDMARK
)


async def calculate_position_from_duration(
    duration_min: int,
    real_speed_kmh: float,
    route_data: Dict
) -> Tuple[Optional[Tuple[float, float]], int, float, List[Dict]]:
    """
    Calcule la position sur l'itinéraire en fonction de la durée écoulée.
    Utilise les vitesses OSRM par segment pour une zone d'incertitude dynamique.
    Renvoie: (position, distance_meters, progress_ratio, map_updates)
    """
    total_distance_m = route_data['total_distance']
    duration_seconds = duration_min * 60
    
    # Tenter le calcul dynamique par segment
    range_result = routing_service.find_position_range_on_route(
        route_data, duration_seconds
    )
    
    if range_result:
        # Utiliser la zone d'incertitude dynamique
        position = range_result['position_center']
        distance_meters = range_result['d_center']
        progress_ratio = range_result['progress_center']
        radius_meters = range_result['radius']
        
        print(f"\n⏱️  Durée écoulée: {duration_min} min")
        print(f"📊 Vitesse moyenne: {real_speed_kmh:.1f} km/h")
        print(f"📏 D_min: {range_result['d_min']}m | D_centre: {distance_meters}m | D_max: {range_result['d_max']}m")
        print(f"📐 Rayon dynamique: {radius_meters}m")
    else:
        # Fallback: calcul classique avec vitesse moyenne
        distance_meters = int((real_speed_kmh * 1000 / 60) * duration_min)
        progress_ratio = min(distance_meters / total_distance_m, 1.0)
        radius_meters = int(real_speed_kmh * 50)
        radius_meters = max(1000, min(radius_meters, 8000))
        
        print(f"\n⏱️  Durée écoulée: {duration_min} min (fallback vitesse moyenne)")
        print(f"📊 Vitesse: {real_speed_kmh:.1f} km/h")
        print(f"📏 Distance estimée: {distance_meters}m / {total_distance_m}m")
        
        position = routing_service.find_position_on_route(route_data, distance_meters)
        range_result = None
    
    map_updates = []
    if position:
        chat_state.set_coordinates(position[0], position[1], CONFIDENCE_HIGH)
        # Stocker le rayon et range_result pour réutilisation dans handle_show_all_pois
        chat_state.context['uncertainty_radius'] = radius_meters
        chat_state.context['range_result'] = range_result
        chat_state.context['estimated_distance'] = distance_meters
        chat_state.log_event('position_estimated', {
            'lat': position[0], 'lon': position[1], 'radius': radius_meters
        })
        
        map_updates.append({
            'type': 'position_with_radius',
            'lat': position[0],
            'lon': position[1],
            'radius': radius_meters,
            'confidence': CONFIDENCE_HIGH,
            'source': f'Durée: {duration_min}min'
        })
    
    return position, distance_meters, progress_ratio, map_updates, range_result


async def calculate_position_from_distance(
    distance_km: float,
    real_speed_kmh: float,
    route_data: Dict
) -> Tuple[Optional[Tuple[float, float]], int, float, List[Dict]]:
    """
    Calcule la position sur l'itinéraire en fonction de la distance fournie.
    Renvoie: (position, distance_meters, progress_ratio, map_updates)
    """
    total_distance_m = route_data['total_distance']
    distance_meters = int(distance_km * 1000)
    progress_ratio = min(distance_meters / total_distance_m, 1.0)
    
    print(f"\n📏 Distance parcourue: {distance_km}km = {distance_meters}m")
    
    position = routing_service.find_position_on_route(route_data, distance_meters)
    
    map_updates = []
    if position:
        chat_state.set_coordinates(position[0], position[1], CONFIDENCE_HIGH)
        radius_meters = int(real_speed_kmh * 50)
        radius_meters = max(500, min(radius_meters, 5000))
        
        map_updates.append({
            'type': 'position_with_radius',
            'lat': position[0],
            'lon': position[1],
            'radius': radius_meters,
            'confidence': CONFIDENCE_HIGH,
            'source': f'Distance: {distance_km}km'
        })
    
    return position, distance_meters, progress_ratio, map_updates


async def suggest_nearby_pois(
    position: Tuple[float, float],
    distance_meters: int,
    route_data: Dict,
    range_result: Dict = None
) -> Tuple[str, List[Dict]]:
    """
    Suggère des POI proches pour la levée de doute, avec dédoublonnage et priorité à l'avant.
    """
    if chat_state.context.get('awaiting_poi_selection'):
        return "", []
    
    print(f"\n{'='*60}")
    print("🔍 LEVÉE DE DOUTE PAR POI")
    print(f"{'='*60}")
    
    next_message = ""
    map_updates = []
    
    try:
        # Déterminer la zone de recherche POI
        if range_result:
            # Recherche sur tout l'arc [D_min, D_max]
            search_d_min = range_result['d_min']
            search_d_max = range_result['d_max']
            # Trouver les positions extrêmes pour le rayon de recherche
            pos_min = range_result.get('position_min', position)
            pos_max = range_result.get('position_max', position)
            # Centrer la recherche sur le milieu de l'arc
            search_lat = (pos_min[0] + pos_max[0]) / 2
            search_lon = (pos_min[1] + pos_max[1]) / 2
            # Rayon = demi-distance entre min et max + marge
            search_radius = range_result['radius'] + 1500
            print(f"📍 Recherche POI sur l'arc [{search_d_min/1000:.1f}km - {search_d_max/1000:.1f}km], rayon {search_radius}m")
        else:
            search_lat, search_lon = position[0], position[1]
            search_radius = 3000
        
        pois = await geocoding_service.fetch_local_pois(
            search_lat, search_lon, radius=search_radius
        )
        
        if pois:
            # ✅ ÉLARGISSEMENT: Autoriser les POI jusqu'à 1.5 km de la route (visibilité réelle)
            projected_pois = routing_service.project_pois_on_route(
                route_data, pois, max_distance_from_route=1500
            )
            
            if projected_pois:
                # Filtrer les rejets et DÉDOUBLONNER par nom
                rejected_pois = chat_state.context.get('rejected_pois', [])
                vu_names = set(n.lower() for n in rejected_pois)
                
                selected_ahead = []
                selected_behind = []
                
                # Déterminer la zone de filtrage pour les POI sur l'arc
                if range_result:
                    filter_d_min = range_result['d_min']
                    filter_d_max = range_result['d_max']
                else:
                    filter_d_min = max(0, distance_meters - 3000)
                    filter_d_max = distance_meters + 3000
                
                # Trier par proximité absolue au point actuel
                projected_pois.sort(key=lambda x: abs(x['cumulative_distance'] - distance_meters))
                
                for p in projected_pois:
                    name_clean = p['name'].lower().strip()
                    if name_clean in vu_names or len(name_clean) < 3:
                        continue
                    
                    # Ignorer les noms de routes génériques dans les suggestions textuelles
                    if p.get('type') in ['primary', 'secondary', 'tertiary', 'unclassified', 'residential', 'service']:
                        continue
                    
                    # Filtrer: garder uniquement les POI dans l'arc [D_min, D_max] + marge
                    margin = 2000  # 2km de marge de chaque côté
                    if p['cumulative_distance'] < (filter_d_min - margin) or p['cumulative_distance'] > (filter_d_max + margin):
                        continue
                        
                    vu_names.add(name_clean)
                    if p['cumulative_distance'] > distance_meters:
                        selected_ahead.append({**p, 'direction': 'devant'})
                    else:
                        selected_behind.append({**p, 'direction': 'derrière'})
                
                # Sélection finale : Mix intelligent (Max 5 POI, priorité devant)
                final_selection = selected_ahead[:3]
                if len(final_selection) < 5:
                    final_selection += selected_behind[:(5 - len(final_selection))]
                
                # Trier pour l'affichage (du plus proche au plus loin)
                final_selection.sort(key=lambda x: abs(x['cumulative_distance'] - distance_meters))
                
                if final_selection:
                    next_message, map_updates = _build_poi_suggestion_message(
                        final_selection, distance_meters, position
                    )
                else:
                    print("⚠️  Liste POI vide après filtrage")
                    next_message = "\n\nJe ne vois pas d'autre point de repère connu près d'ici. Pouvez-vous me décrire un panneau ou un bâtiment particulier ?"
                    chat_state.context['awaiting_description'] = True
            else:
                next_message = "\n\nJe ne trouve pas de repère précis sur ce tronçon. Pouvez-vous décrire ce que vous voyez ?"
                chat_state.context['awaiting_description'] = True
        else:
            next_message = "\n\nJe ne trouve aucun repère dans cette zone. Pouvez-vous décrire précisément votre environnement ?"
            chat_state.context['awaiting_description'] = True
            
    except Exception as poi_error:
        print(f"⚠️  Erreur lors de la recherche POI: {poi_error}")
        traceback.print_exc()
    
    return next_message, map_updates


def _build_poi_suggestion_message(
    combined_pois: List[Dict],
    distance_meters: int,
    position: Tuple[float, float]
) -> Tuple[str, List[Dict]]:
    """Construit le message de suggestion de POI et les mises à jour carte."""
    
    poi_emojis = {
        'supermarché': '🛒', 'station-service': '⛽', 'église': '⛪',
        'gare': '🚉', 'mairie': '🏛️', 'école': '🏫', 'hôpital': '🏥',
        "château d'eau": '💧', 'éolienne': '🌬️', 'pont': '🌉', 'aire de repos': '🅿️'
    }
    
    poi_list_text = "\n\n👁️ **Voici des points de repère proches de votre position :**\n\n"
    
    for i, poi in enumerate(combined_pois, 1):
        dist_km = abs(poi['cumulative_distance'] - distance_meters) / 1000
        emoji = poi_emojis.get(poi.get('type', ''), '📍')
        direction = f"({poi['direction']} vous)"
        poi_list_text += f"{i}. {emoji} {poi['name']} — ~{dist_km:.1f}km {direction}\n"
    
    poi_list_text += "\nVoyez-vous l'un d'eux ? Répondez par le numéro, le nom, ou \"Aucun\"."
    
    chat_state.context['current_poi_list'] = combined_pois
    chat_state.context['awaiting_poi_selection'] = True
    
    # Préparer les mises à jour carte
    pois_with_index = []
    for i, poi in enumerate(combined_pois, 1):
        pois_with_index.append({**poi, 'index': i})
    
    map_updates = [{
        'type': 'pois',
        'pois': pois_with_index,
        'fitBounds': True,
        'estimated_position': {'lat': position[0], 'lon': position[1]}
    }]
    
    return poi_list_text, map_updates
