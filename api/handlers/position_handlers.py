"""
Gestionnaires de calcul et estimation de position.

Traite le calcul de position basé sur durée/distance et les suggestions de POI.
"""

import traceback
from typing import Dict, List, Optional, Tuple

from api.schemas import ChatResponse
from api.dependencies import (
    chat_state, geocoding_service, routing_service,
    CONFIDENCE_HIGH
)


async def calculate_position_from_duration(
    duration_minutes: int,
    route_data: Dict,
    real_speed_kmh: float
) -> Tuple[Optional[Tuple[float, float]], int, float, List[Dict]]:
    """
    Calcule la position sur l'itinéraire basée sur la durée écoulée.
    
    Args:
        duration_minutes: Durée écoulée en minutes
        route_data: Données d'itinéraire OSRM
        real_speed_kmh: Vitesse moyenne réelle calculée
    
    Returns:
        Tuple (position, distance_meters, progress_ratio, map_updates)
    """
    total_distance_m = route_data['total_distance']
    total_duration_sec = route_data['total_duration']
    
    duration_seconds = duration_minutes * 60
    print(f"\n⏱️  Durée écoulée: {duration_minutes} min ({duration_seconds} sec)")
    
    # Calculer le ratio de progression temporelle
    progress_ratio = duration_seconds / total_duration_sec
    
    # Si l'utilisateur a dépassé le temps total, il est arrivé
    if progress_ratio >= 1.0:
        print(f"🏁 ARRIVÉ! (durée écoulée ≥ durée totale)")
        progress_ratio = 1.0
        distance_meters = int(total_distance_m)
    else:
        distance_meters = int(progress_ratio * total_distance_m)
    
    distance_km = distance_meters / 1000
    progress_pct = progress_ratio * 100
    
    print(f"\n{'='*60}")
    print(f"📊 CALCUL BASÉ SUR LE TEMPS OSRM RÉEL")
    print(f"{'='*60}")
    print(f"⏱️  Temps écoulé: {duration_minutes} min / {total_duration_sec/60:.0f} min")
    print(f"📊 Ratio de progression: {progress_ratio:.2%}")
    print(f"📏 Distance parcourue: {distance_km:.1f} km / {total_distance_m/1000:.1f} km")
    print(f"📊 Progression: {progress_pct:.1f}%")
    print(f"{'='*60}\n")
    
    # Chercher position sur itinéraire
    print(f"🔍 Recherche position à {distance_meters}m...")
    position = routing_service.find_position_on_route(route_data, distance_meters)
    
    map_updates = []
    if position:
        chat_state.set_coordinates(position[0], position[1], CONFIDENCE_HIGH)
        
        # Rayon de confiance basé sur la vitesse réelle
        radius_meters = int(real_speed_kmh * 50)
        radius_meters = max(500, min(radius_meters, 5000))
        
        print(f"🎯 Rayon de confiance: {radius_meters}m (basé sur vitesse {real_speed_kmh:.1f}km/h)")
        
        map_updates.append({
            'type': 'position_with_radius',
            'lat': position[0],
            'lon': position[1],
            'radius': radius_meters,
            'confidence': CONFIDENCE_HIGH,
            'source': f'OSRM: {duration_minutes}min à {real_speed_kmh:.1f}km/h (vitesse réelle)'
        })
    
    return position, distance_meters, progress_ratio, map_updates


async def calculate_position_from_distance(
    distance_km: float,
    route_data: Dict,
    real_speed_kmh: float
) -> Tuple[Optional[Tuple[float, float]], List[Dict]]:
    """
    Calcule la position sur l'itinéraire basée sur la distance parcourue.
    
    Args:
        distance_km: Distance parcourue en km
        route_data: Données d'itinéraire OSRM
        real_speed_kmh: Vitesse moyenne réelle calculée
    
    Returns:
        Tuple (position, map_updates)
    """
    total_distance_m = route_data['total_distance']
    distance_meters = int(distance_km * 1000)
    
    print(f"\n📏 Distance parcourue: {distance_km}km = {distance_meters}m")
    progress_pct = (distance_meters / total_distance_m) * 100
    print(f"📊 Progression: {progress_pct:.1f}%")
    
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
    
    return position, map_updates


async def suggest_nearby_pois(
    position: Tuple[float, float],
    distance_meters: int,
    route_data: Dict
) -> Tuple[str, List[Dict]]:
    """
    Suggère des POI proches pour la levée de doute.
    
    Args:
        position: Position estimée (lat, lon)
        distance_meters: Distance parcourue en mètres
        route_data: Données d'itinéraire OSRM
    
    Returns:
        Tuple (message_text, map_updates)
    """
    if chat_state.context.get('awaiting_poi_selection'):
        return "", []
    
    print(f"\n{'='*60}")
    print("🔍 LEVÉE DE DOUTE PAR POI")
    print(f"{'='*60}")
    
    next_message = ""
    map_updates = []
    
    try:
        # Pré-charger le cache OSMnx pour la zone
        poi_search_radius = 2000
        pois = await geocoding_service.fetch_local_pois(
            position[0], position[1], 
            radius=poi_search_radius
        )
        
        if not pois:
            # Élargissement dynamique
            print("⚠️  Aucun POI trouvé dans la zone, élargissement à 3000m...")
            pois = await geocoding_service.get_pois_in_area(
                position[0], position[1], 
                radius_meters=3000
            )
        
        if pois:
            # Projeter les POI sur l'itinéraire (300m strict pour suggestions)
            projected_pois = routing_service.project_pois_on_route(
                route_data,
                pois,
                max_distance_from_route=300
            )
            
            if projected_pois:
                # Filtrer les POI déjà refusés
                rejected_pois = chat_state.context.get('rejected_pois', [])
                print(f"📝 POI déjà rejetés: {rejected_pois}")
                available_pois = [p for p in projected_pois if p['name'] not in rejected_pois]
                
                # Séparer avant/après la position actuelle
                pois_behind = [p for p in available_pois if p['cumulative_distance'] < distance_meters]
                pois_ahead = [p for p in available_pois if p['cumulative_distance'] >= distance_meters]
                
                # Trier par proximité
                pois_behind.sort(key=lambda p: distance_meters - p['cumulative_distance'])
                pois_ahead.sort(key=lambda p: p['cumulative_distance'] - distance_meters)
                
                # Limiter à 4 derrière + 4 devant = 8 max
                selected_behind = pois_behind[:4]
                selected_ahead = pois_ahead[:4]
                
                # Combiner avec indicateur de direction
                combined_pois = []
                for poi in selected_behind:
                    combined_pois.append({**poi, 'direction': 'derrière'})
                for poi in selected_ahead:
                    combined_pois.append({**poi, 'direction': 'devant'})
                
                print(f"✅ {len(selected_behind)} POI derrière + {len(selected_ahead)} POI devant (max 8)")
                
                if combined_pois:
                    next_message, map_updates = _build_poi_suggestion_message(
                        combined_pois, distance_meters, position
                    )
                else:
                    print("⚠️  Liste POI vide après filtrage des rejets")
                    next_message = "\n\nJe ne vois pas d'autre point de repère connu près d'ici. Pouvez-vous me décrire un autre bâtiment, une enseigne différente ou un panneau de direction ?"
                    chat_state.context['awaiting_description'] = True
            else:
                print("⚠️  Aucun POI sur le tracé de l'itinéraire")
                next_message = "\n\nJe ne trouve pas de POI proche du tracé. Pouvez-vous décrire ce que vous voyez ?"
                chat_state.context['awaiting_description'] = True
        else:
            print("⚠️  Toujours aucun POI après élargissement")
            next_message = "\n\nJe ne trouve aucun repère dans cette zone. Pouvez-vous décrire précisément ce que vous voyez ?"
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
    
    # Emojis par type de POI
    poi_emojis = {
        'supermarché': '🛒', 'station-service': '⛽', 'église': '⛪',
        'gare': '🚉', 'mairie': '🏛️', 'école': '🏫', 'hôpital': '🏥',
        'stade': '🏟️', 'château': '🏰', 'tour/antenne': '📡',
        "château d'eau": '💧', 'éolienne': '🌬️', 'silo': '🌾',
        'pont': '🌉', 'aire de repos': '🅿️', 'aire de service': '⛽'
    }
    
    poi_list_text = "\n\n👁️ **Voici des points de repère proches de votre position. En voyez-vous un ?**\n\n"
    
    for i, poi in enumerate(combined_pois, 1):
        dist_km = abs(poi['cumulative_distance'] - distance_meters) / 1000
        emoji = poi_emojis.get(poi['type'], '📍')
        direction = f"({poi['direction']} vous)"
        poi_list_text += f"**{i}.** {emoji} {poi['name']} — ~{dist_km:.1f}km {direction}\n\n"
    
    poi_list_text += "*Répondez par le numéro, le nom du lieu, ou \"Aucun\".*"
    
    # Stocker la liste pour le prochain tour
    chat_state.context['current_poi_list'] = combined_pois
    chat_state.context['awaiting_poi_selection'] = True
    print(f"📌 Liste POI stockée: {[p['name'] for p in combined_pois]}")
    
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
    
    print(f"✅ {len(pois_with_index)} POI envoyés au frontend")
    
    return poi_list_text, map_updates
