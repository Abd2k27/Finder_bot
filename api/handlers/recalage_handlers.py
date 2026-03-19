"""
Gestionnaires de recalage de position.

Traite le recalage par route citée et par repère/landmark décrit.
"""

import re
import traceback
from typing import Dict, List, Optional, Tuple

from api.schemas import ChatResponse
from api.dependencies import (
    chat_state, geocoding_service, routing_service,
    CONFIDENCE_ROUTE, CONFIDENCE_LANDMARK
)


async def handle_route_recalage(
    routes: List[str],
    current_step: int,
    entities: Dict
) -> Tuple[bool, str, List[Dict]]:
    """
    Recalage par route citée par l'utilisateur.
    
    Cherche d'abord dans les instructions OSRM, puis via Overpass.
    
    Args:
        routes: Liste des noms de routes extraits
        current_step: Étape actuelle
        entities: Entités extraites
    
    Returns:
        Tuple (recalage_done, recalage_message, map_updates)
    """
    if not routes or not chat_state.has_trajet() or not chat_state.has_route_data():
        return False, "", []
    
    print(f"\n{'='*60}")
    print(f"🛣️ RECALAGE PAR ROUTE CITÉE: {routes}")
    print(f"{'='*60}")
    
    recalage_message = ""
    map_updates = []
    route_recalage_done = False
    distance_km = 0
    
    for route_name in routes:
        # ÉTAPE 1: Chercher dans les instructions OSRM d'abord
        found_in_instructions = False
        if 'instructions' in chat_state.route_data:
            for instr in chat_state.route_data['instructions']:
                instr_text = instr.get('name', '') + ' ' + instr.get('text', '')
                if route_name.lower() in instr_text.lower():
                    cumulative_dist = instr.get('cumulative_distance', 0)
                    print(f"✅ Route {route_name} trouvée dans instructions OSRM à {cumulative_dist/1000:.1f}km")
                    
                    position = routing_service.find_position_on_route(
                        chat_state.route_data, cumulative_dist
                    )
                    
                    if position:
                        chat_state.set_coordinates(position[0], position[1], CONFIDENCE_ROUTE)
                        
                        total_distance = chat_state.route_data['total_distance']
                        total_duration = chat_state.route_data['total_duration']
                        new_duration_min = int((cumulative_dist / total_distance) * total_duration / 60)
                        chat_state.context['duration'] = new_duration_min
                        distance_km = cumulative_dist / 1000
                        
                        chat_state.context['recalage_done'] = True
                        chat_state.context['awaiting_description'] = False
                        route_recalage_done = True
                        
                        map_updates.append({
                            'type': 'position_with_radius',
                            'lat': position[0],
                            'lon': position[1],
                            'radius': 500,
                            'confidence': CONFIDENCE_ROUTE,
                            'source': f'Route {route_name} (OSRM)'
                        })
                        
                        recalage_message = f"✅ **Bien reçu !** Je vous ai localisé sur la route **{route_name}**. Cela correspond à environ **{distance_km:.1f}km** de votre trajet.\n\n"
                        found_in_instructions = True
                        break
        
        # ÉTAPE 2: Si pas trouvé dans instructions, utiliser Overpass
        if not found_in_instructions:
            start_coords = await geocoding_service.get_coordinates_from_place(chat_state.context['start'])
            end_coords = await geocoding_service.get_coordinates_from_place(chat_state.context['end'])
            
            if start_coords and end_coords:
                route_coords = await geocoding_service.get_route_coordinates_on_path(
                    route_name, start_coords, end_coords
                )
                
                if route_coords:
                    print(f"✅ Route {route_name} trouvée via Overpass: {route_coords}")
                    
                    # Projeter sur la géométrie
                    if chat_state.route_data.get('geometry'):
                        geometry = chat_state.route_data['geometry']
                        best_distance = float('inf')
                        best_cumulative = 0
                        cumulative = 0
                        
                        for i in range(len(geometry) - 1):
                            p1 = geometry[i]
                            p2 = geometry[i + 1]
                            seg_dist = routing_service._haversine_distance(
                                route_coords[0], route_coords[1], p1[1], p1[0]
                            )
                            if seg_dist < best_distance:
                                best_distance = seg_dist
                                best_cumulative = cumulative
                            cumulative += routing_service._haversine_distance(p1[1], p1[0], p2[1], p2[0])
                    
                    chat_state.set_coordinates(route_coords[0], route_coords[1], CONFIDENCE_ROUTE)
                    
                    if best_cumulative > 0:
                        total_distance = chat_state.route_data['total_distance']
                        total_duration = chat_state.route_data['total_duration']
                        new_duration_min = int((best_cumulative / total_distance) * total_duration / 60)
                        chat_state.context['duration'] = new_duration_min
                        distance_km = best_cumulative / 1000
                    
                    chat_state.context['recalage_done'] = True
                    route_recalage_done = True
                    
                    map_updates.append({
                        'type': 'position_with_radius',
                        'lat': route_coords[0],
                        'lon': route_coords[1],
                        'radius': 500,
                        'confidence': CONFIDENCE_ROUTE,
                        'source': f'Route {route_name}'
                    })
                    
                    recalage_message = f"✅ **Bien reçu !** Je vous ai localisé sur la route **{route_name}**. Cela correspond à environ **{distance_km:.1f}km** de votre trajet.\n\n"
                else:
                    recalage_message = f"Je ne trouve pas la route **{route_name}** sur votre itinéraire. Voyez-vous un autre panneau ou un nom de ville proche ?\n\n"
        
        if route_recalage_done:
            break
    
    return route_recalage_done, recalage_message, map_updates


async def handle_landmark_recalage(
    landmarks_to_search: List[str],
    current_step: int,
    entities: Dict
) -> Optional[ChatResponse]:
    """
    Recalage par repères/lieux décrits par l'utilisateur.
    
    Utilise:
    1. Recherche dans le réseau routier OSMnx (pour les noms de rues/avenues/boulevards)
    2. Recherche floue dans le cache POI local
    3. Overpass en fallback
    
    Args:
        landmarks_to_search: Liste des repères à chercher
        current_step: Étape actuelle
        entities: Entités extraites
    
    Returns:
        ChatResponse si recalage réussi ou choix demandé, None sinon
    """
    if not landmarks_to_search or not chat_state.coordinates or not chat_state.has_route_data():
        return None
    
    print(f"\n{'='*60}")
    print(f"🏛️ RECALAGE PAR REPÈRES: {landmarks_to_search}")
    print(f"{'='*60}")
    
    # Reset awaiting_description après utilisation
    chat_state.context['awaiting_description'] = False
    
    # Mots-clés indiquant un nom de voie
    road_keywords = ['rue', 'avenue', 'boulevard', 'chemin', 'allée', 'impasse', 'place', 'route', 'voie', 'passage']
    
    # FILTRAGE INTELLIGENT: Ne chercher les génériques que si AUCUN nom propre n'existe
    generic_words = ['garage', 'église', 'mairie', 'école', 'château', 'restaurant', 'station', 'supermarché', 'commerce', 'magasin']
    
    specific_names = [l for l in landmarks_to_search if l.lower() not in generic_words]
    generic_names = [l for l in landmarks_to_search if l.lower() in generic_words]
    
    if specific_names:
        filtered_landmarks = list(dict.fromkeys(specific_names))  # Dédoublonner
        if generic_names:
            print(f"⚡ Ignoré génériques {generic_names}, priorité aux noms propres: {filtered_landmarks}")
    else:
        filtered_landmarks = list(dict.fromkeys(generic_names))  # Dédoublonner
    
    print(f"🔍 Landmarks à chercher (dédoublonnés): {filtered_landmarks}")
    
    map_updates = []
    last_searched = None
    
    for landmark_desc in filtered_landmarks:
        last_searched = landmark_desc
        print(f"\n🔎 Recherche de '{landmark_desc}'...")
        
        # ========== ÉTAPE 0: RECHERCHE DE VOIE DANS LE TRAJET OSRM ==========
        # Vérifier si c'est probablement un nom de voie
        landmark_lower = landmark_desc.lower()
        is_road_name = any(keyword in landmark_lower for keyword in road_keywords)
        
        if is_road_name and chat_state.has_route_data() and 'instructions' in chat_state.route_data:
            print(f"🛣️  Détecté comme nom de voie, recherche dans les instructions OSRM du trajet...")
            
            from difflib import SequenceMatcher
            
            best_match = None
            best_score = 0
            best_instruction = None
            is_exact_match = False
            
            # Extraire les mots-clés significatifs (> 3 caractères, sans les mots génériques)
            generic_words = {'rue', 'avenue', 'boulevard', 'place', 'chemin', 'route', 'allée', 'voie', 'passage', 'impasse', 'de', 'du', 'la', 'le', 'les', 'des', 'au', 'aux'}
            query_keywords = [w for w in landmark_lower.split() if len(w) > 2 and w not in generic_words]
            
            # Parcourir toutes les instructions du trajet
            for instr in chat_state.route_data['instructions']:
                road_name = instr.get('name', '')
                if not road_name or road_name == 'Route sans nom':
                    continue
                
                road_name_lower = road_name.lower()
                road_keywords_in_name = [w for w in road_name_lower.split() if len(w) > 2 and w not in generic_words]
                
                # Match exact (un mot-clé important doit être présent)
                keyword_match = any(kw in road_name_lower for kw in query_keywords)
                
                # Calcul de similarité
                similarity = SequenceMatcher(None, landmark_lower, road_name_lower).ratio()
                
                # Score: on exige soit un match de mot-clé, soit une très haute similarité
                if keyword_match:
                    # Match de mot-clé trouvé → score élevé
                    score = max(similarity, 0.8)
                    if score > best_score:
                        best_score = score
                        best_match = road_name
                        best_instruction = instr
                        is_exact_match = True
                        print(f"   🎯 Match mot-clé: '{road_name}' (score: {score:.2f})")
                elif similarity >= 0.7:
                    # Haute similarité même sans mot-clé exact
                    score = similarity
                    if score > best_score and not is_exact_match:
                        best_score = score
                        best_match = road_name
                        best_instruction = instr
                        print(f"   📊 Match similarité: '{road_name}' (score: {score:.2f})")
            
            # Valider le match trouvé
            if best_match and best_instruction and best_score >= 0.7:
                cumulative_dist = best_instruction.get('cumulative_distance', 0)
                print(f"✅ Voie '{best_match}' trouvée dans le trajet à {cumulative_dist/1000:.1f}km (score: {best_score:.2f})")
                
                # Trouver la position exacte sur le trajet
                position = routing_service.find_position_on_route(
                    chat_state.route_data, cumulative_dist
                )
                
                if position:
                    chat_state.set_coordinates(position[0], position[1], CONFIDENCE_LANDMARK)
                    
                    # Mettre à jour la durée estimée
                    total_distance = chat_state.route_data['total_distance']
                    total_duration = chat_state.route_data['total_duration']
                    new_duration_min = int((cumulative_dist / total_distance) * total_duration / 60)
                    chat_state.context['duration'] = new_duration_min
                    distance_km = cumulative_dist / 1000
                    
                    chat_state.context['recalage_done'] = True
                    chat_state.context['awaiting_description'] = False
                    
                    recalage_message = f"✅ J'ai trouvé **{best_match}** sur votre trajet !\n"
                    recalage_message += f"📍 Cela correspond à environ **{distance_km:.1f}km** depuis le départ.\n"
                    recalage_message += f"⏱️ Temps de trajet recalculé: **{new_duration_min}min**.\n\n"
                    recalage_message += "Votre position a été recalée sur la carte.\n"
                    
                    map_updates = [{
                        'type': 'position_with_radius',
                        'lat': position[0],
                        'lon': position[1],
                        'radius': 500,
                        'confidence': CONFIDENCE_LANDMARK,
                        'source': f"Voie {best_match}",
                        'road_name': best_match
                    }]
                    
                    print(f"🚩 RECALAGE PAR VOIE RÉUSSI - {best_match} à {distance_km:.1f}km")
                    return ChatResponse(
                        message=recalage_message,
                        step=current_step + 1,
                        entities=entities,
                        map_updates=map_updates
                    )
            else:
                if best_match:
                    print(f"⚠️  Match faible rejeté: '{best_match}' (score: {best_score:.2f} < 0.7)")
                print(f"⚠️  Aucune voie correspondant précisément à '{landmark_desc}' trouvée dans le trajet OSRM")
                # Continuer avec la recherche locale
        
        # ========== ÉTAPE 0.5: RECHERCHE DANS LE CERCLE LOCAL ==========
        # Si c'est un nom de voie et pas trouvé dans OSRM, chercher dans le cercle autour de la position
        if is_road_name and chat_state.coordinates:
            print(f"🔍 Recherche de '{landmark_desc}' dans le cercle local...")
            
            local_road = await geocoding_service.find_road_in_area(
                landmark_desc,
                chat_state.coordinates[0],
                chat_state.coordinates[1],
                radius=3000  # Rayon de recherche 3km
            )
            
            if local_road:
                # Voie trouvée dans le cercle local !
                # On confirme la position actuelle comme étant sur cette voie
                lat, lon = chat_state.coordinates
                chat_state.set_coordinates(lat, lon, CONFIDENCE_LANDMARK)
                chat_state.context['recalage_done'] = True
                chat_state.context['awaiting_description'] = False
                
                recalage_message = f"✅ J'ai trouvé **{local_road['name']}** ({local_road['type_label']}) dans votre zone !\n"
                recalage_message += f"📍 Votre position a été confirmée.\n\n"
                
                map_updates = [{
                    'type': 'position_confirmed',
                    'lat': lat,
                    'lon': lon,
                    'radius': 500,
                    'confidence': CONFIDENCE_LANDMARK,
                    'source': f"Voie locale {local_road['name']}",
                    'road_name': local_road['name'],
                    'road_type': local_road['type_label']
                }]
                
                print(f"🚩 RECALAGE PAR VOIE LOCALE RÉUSSI - {local_road['name']}")
                return ChatResponse(
                    message=recalage_message,
                    step=current_step + 1,
                    entities=entities,
                    map_updates=map_updates
                )
        
        # ========== ÉTAPE 1: RECHERCHE FLOUE dans le cache POI ==========
        fuzzy_matches = geocoding_service.find_landmarks_fuzzy(landmark_desc, cutoff=0.4, max_results=5)
        
        if fuzzy_matches:
            nb_matches = len(fuzzy_matches)
            print(f"✅ {nb_matches} match(s) fuzzy trouvé(s) pour '{landmark_desc}'")
            
            if nb_matches == 1:
                # UN SEUL RÉSULTAT: Recalage définitif
                return await _recalage_single_match(fuzzy_matches[0], current_step, entities)
            else:
                # PLUSIEURS RÉSULTATS: Demander choix
                return await _build_choice_response(fuzzy_matches, landmark_desc, current_step, entities)
        
        # ========== ÉTAPE 2: Fallback Overpass ==========
        found_landmarks = await geocoding_service.search_landmarks_near_point(
            landmark_desc,
            chat_state.coordinates[0],
            chat_state.coordinates[1],
            radius=2000
        )
        
        if found_landmarks:
            best_landmark = found_landmarks[0]
            print(f"✅ Repère Overpass '{best_landmark['name']}' trouvé")
            return await _recalage_overpass_match(best_landmark, current_step, entities)
    
    # Aucun match trouvé
    if last_searched:
        chat_state.context['awaiting_description'] = True
        print(f"\n⚠️  RECALAGE ÉCHOUÉ pour '{last_searched}' - Demande description")
        return ChatResponse(
            message=f"Je ne trouve aucun point correspondant à **{last_searched}** dans cette zone. Avez-vous une autre description de ce que vous voyez ?",
            step=current_step + 1,
            entities=dict(entities) if entities else None,
            map_updates=None
        )
    
    print("⚠️  Aucun landmark à chercher - retour None")
    return None


async def _recalage_single_match(match: Dict, current_step: int, entities: Dict) -> ChatResponse:
    """Recalage sur un seul match fuzzy."""
    chat_state.set_coordinates(match['lat'], match['lon'], CONFIDENCE_LANDMARK)
    
    # Calculer cumulative_distance via projection
    if chat_state.route_data:
        projected = routing_service.project_pois_on_route(
            chat_state.route_data,
            [match],
            max_distance_from_route=2000
        )
        if projected and projected[0].get('cumulative_distance'):
            cumulative_dist = projected[0]['cumulative_distance']
            total_distance = chat_state.route_data['total_distance']
            total_duration = chat_state.route_data['total_duration']
            new_duration_min = int((cumulative_dist / total_distance) * total_duration / 60)
            chat_state.context['duration'] = new_duration_min
            print(f"📍 Recalage: {cumulative_dist/1000:.1f}km parcourus, {new_duration_min}min")
    
    chat_state.context['recalage_done'] = True
    chat_state.context['awaiting_description'] = False
    
    recalage_message = f"✅ J'ai trouvé **{match['name']}** ({match['type']}).\n"
    recalage_message += f"📍 Coordonnées: {match['lat']:.5f}, {match['lon']:.5f}\n\n"
    recalage_message += "Votre position a été recalée sur la carte.\n\n"
    
    # Charger POI autour
    nearby_pois_list = []
    try:
        nearby_pois = await geocoding_service.fetch_local_pois(match['lat'], match['lon'], radius=1000)
        if nearby_pois:
            other_pois = [p for p in nearby_pois if p['name'] != match['name']]
            nearby_pois_list = other_pois
            if other_pois:
                recalage_message += f"**{len(other_pois)} POI autour de ce point (1km) :**\n"
                for poi in other_pois[:8]:
                    recalage_message += f"- {poi['name']} ({poi['type']})\n"
                print(f"✅ {len(other_pois)} POI trouvés autour du point recalé")
    except Exception as e:
        print(f"⚠️  Erreur recherche POI: {e}")
    
    map_updates = [{
        'type': 'search_area_circle',
        'lat': match['lat'],
        'lon': match['lon'],
        'radius': 1000,
        'confidence': CONFIDENCE_LANDMARK,
        'source': match['name'],
        'poi_type': match['type'],
        'nearby_pois': nearby_pois_list,
        'fitBounds': True
    }]
    
    print(f"\n🚩 RECALAGE RÉUSSI - Retour immédiat")
    return ChatResponse(
        message=recalage_message,
        step=current_step + 1,
        entities=entities,
        map_updates=map_updates
    )


async def _build_choice_response(matches: List[Dict], query: str, current_step: int, entities: Dict) -> ChatResponse:
    """
    Construit une réponse demandant un choix parmi plusieurs matches.
    Enrichit les candidats avec les POI proches pour aider à la désambiguïsation.
    """
    chat_state.context['awaiting_poi_selection'] = True
    chat_state.context['current_poi_list'] = matches
    
    # Enrichir les candidats avec les POI proches
    print(f"\n🔍 DÉSAMBIGUÏSATION: {len(matches)} candidats pour '{query}'")
    enriched_matches = await geocoding_service.enrich_candidates_with_nearby_pois(
        matches, radius=500, max_nearby=3
    )
    
    # Démarrer le mode désambiguïsation
    chat_state.start_disambiguation(enriched_matches, query)
    chat_state.disambiguation['candidates_with_context'] = enriched_matches
    
    # Construire les updates pour la carte (cercles autour de chaque candidat)
    map_updates = []
    for i, match in enumerate(enriched_matches):
        map_updates.append({
            'type': 'candidate_circle',
            'lat': match['lat'],
            'lon': match['lon'],
            'radius': 500,  # Cercle de 500m autour de chaque candidat
            'name': match['name'],
            'poi_type': match['type'],
            'index': i + 1,
            'nearby_pois': match.get('nearby_pois', []),
            'fitBounds': True if i == 0 else False
        })
    
    # Construire le message avec contexte enrichi
    recalage_message = f"🔍 J'ai trouvé **{len(matches)} points** correspondant à \"**{query}**\":\n\n"
    
    for i, match in enumerate(enriched_matches):
        recalage_message += f"**{i+1}.** {match['name']} ({match['type']})\n"
        
        # Ajouter les POI proches pour ce candidat
        nearby = match.get('nearby_pois', [])
        if nearby:
            nearby_names = [f"{p['name']}" for p in nearby[:2]]
            recalage_message += f"   → À côté: {', '.join(nearby_names)}\n"
        else:
            recalage_message += f"   → 📍 {match['lat']:.5f}, {match['lon']:.5f}\n"
        recalage_message += "\n"
    
    recalage_message += "**Lequel voyez-vous ?** Répondez par le numéro, ou décrivez un lieu proche.\n"
    recalage_message += "_Dites 'retour' pour revenir en arrière._\n"
    
    print(f"🗺️ {len(matches)} CANDIDATS enrichis - Demande de choix")
    return ChatResponse(
        message=recalage_message,
        step=current_step + 1,
        entities=entities,
        map_updates=map_updates
    )


async def _recalage_overpass_match(landmark: Dict, current_step: int, entities: Dict) -> ChatResponse:
    """Recalage sur un résultat Overpass."""
    chat_state.set_coordinates(landmark['lat'], landmark['lon'], CONFIDENCE_LANDMARK)
    chat_state.context['recalage_done'] = True
    chat_state.context['awaiting_description'] = False
    
    recalage_message = f"✅ J'ai identifié **{landmark['name']}**. Votre position a été recalée.\n\n"
    
    # Charger POI autour
    nearby_pois_list = []
    try:
        nearby_pois = await geocoding_service.fetch_local_pois(landmark['lat'], landmark['lon'], radius=1000)
        if nearby_pois:
            other_pois = [p for p in nearby_pois if p['name'] != landmark['name']]
            nearby_pois_list = other_pois
            if other_pois:
                recalage_message += f"**{len(other_pois)} POI autour de ce point (1km) :**\n"
                for poi in other_pois[:8]:
                    recalage_message += f"- {poi['name']} ({poi['type']})\n"
                print(f"✅ {len(other_pois)} POI trouvés autour du point recalé (Overpass)")
    except Exception as e:
        print(f"⚠️  Erreur recherche POI Overpass: {e}")
    
    map_updates = [{
        'type': 'search_area_circle',
        'lat': landmark['lat'],
        'lon': landmark['lon'],
        'radius': 1000,
        'confidence': CONFIDENCE_LANDMARK,
        'source': landmark['name'],
        'poi_type': landmark.get('type', 'Lieu'),
        'nearby_pois': nearby_pois_list,
        'fitBounds': True
    }]
    
    print(f"\n🚩 RECALAGE OVERPASS RÉUSSI - Retour immédiat")
    return ChatResponse(
        message=recalage_message,
        step=current_step + 1,
        entities=entities,
        map_updates=map_updates
    )


async def handle_disambiguation_refinement(
    user_input: str,
    current_step: int,
    entities: Dict
) -> Optional[ChatResponse]:
    """
    Gère le raffinement de la désambiguïsation quand l'utilisateur donne plus d'infos.
    
    - Si l'utilisateur dit "retour" → revient à l'étape précédente
    - Si l'utilisateur décrit un POI proche → filtre les candidats
    - Si un seul candidat reste → confirme la position
    """
    if not chat_state.is_in_disambiguation():
        return None
    
    print(f"\n{'='*60}")
    print(f"🔄 RAFFINEMENT DÉSAMBIGUÏSATION: '{user_input}'")
    print(f"{'='*60}")
    
    user_lower = user_input.lower().strip()
    
    # Commande "retour" / "précédent"
    if user_lower in ['retour', 'précédent', 'back', 'revenir', 'annuler']:
        if chat_state.go_back_disambiguation():
            candidates = chat_state.get_disambiguation_candidates()
            return await _build_choice_response(
                candidates, 
                chat_state.disambiguation['original_query'],
                current_step,
                entities
            )
        else:
            # Impossible de revenir (on est à l'étape 0)
            chat_state.end_disambiguation()
            return ChatResponse(
                message="Pas d'étape précédente. Que voyez-vous autour de vous ?",
                step=current_step + 1,
                entities=entities,
                map_updates=None
            )
    
    # Sélection par numéro
    try:
        choice = int(user_lower)
        candidates = chat_state.get_disambiguation_candidates()
        if 1 <= choice <= len(candidates):
            selected = candidates[choice - 1]
            chat_state.end_disambiguation()
            return await _recalage_single_match(selected, current_step, entities)
    except ValueError:
        pass
    
    # Raffinement par description de POI proche
    candidates = chat_state.disambiguation.get('candidates_with_context', [])
    if not candidates:
        candidates = chat_state.get_disambiguation_candidates()
    
    # Filtrer les candidats basés sur les POI proches
    filtered = geocoding_service.filter_candidates_by_nearby(candidates, user_input)
    
    if len(filtered) == 1:
        # Un seul candidat correspond → recalage réussi !
        chat_state.end_disambiguation()
        print(f"✅ Désambiguïsation résolue: {filtered[0].get('name', 'POI')}")
        return await _recalage_single_match(filtered[0], current_step, entities)
    
    elif len(filtered) > 1:
        # Plusieurs candidats correspondent encore → continuer le raffinement
        chat_state.refine_disambiguation(filtered, user_input)
        
        # Enrichir les nouveaux candidats
        enriched = await geocoding_service.enrich_candidates_with_nearby_pois(filtered, radius=500, max_nearby=3)
        chat_state.disambiguation['candidates_with_context'] = enriched
        
        # Construire le message de suivi
        recalage_message = f"🔍 Il reste **{len(filtered)} candidats** possibles:\n\n"
        
        for i, match in enumerate(enriched):
            recalage_message += f"**{i+1}.** {match['name']} ({match['type']})\n"
            nearby = match.get('nearby_pois', [])
            if nearby:
                nearby_names = [f"{p['name']}" for p in nearby[:2]]
                recalage_message += f"   → À côté: {', '.join(nearby_names)}\n"
            recalage_message += "\n"
        
        recalage_message += "**Pouvez-vous préciser ?** Décrivez un autre lieu proche.\n"
        recalage_message += "_Dites 'retour' pour revenir en arrière._\n"
        
        map_updates = []
        for i, match in enumerate(enriched):
            map_updates.append({
                'type': 'candidate_circle',
                'lat': match['lat'],
                'lon': match['lon'],
                'radius': 500,
                'name': match['name'],
                'poi_type': match['type'],
                'index': i + 1,
                'nearby_pois': match.get('nearby_pois', []),
                'fitBounds': True if i == 0 else False
            })
        
        return ChatResponse(
            message=recalage_message,
            step=current_step + 1,
            entities=entities,
            map_updates=map_updates
        )
    
    else:
        # Aucun candidat ne correspond → demander autre chose
        recalage_message = f"Je ne trouve pas de correspondance pour \"{user_input}\" parmi les candidats.\n\n"
        recalage_message += "Pouvez-vous décrire autre chose que vous voyez ?\n"
        recalage_message += "_Dites 'retour' pour revenir à la liste précédente._\n"
        
        return ChatResponse(
            message=recalage_message,
            step=current_step + 1,
            entities=entities,
            map_updates=None
        )
