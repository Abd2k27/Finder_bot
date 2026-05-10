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
    """Recalage par route citée."""
    if not routes or not chat_state.has_trajet() or not chat_state.has_route_data():
        return False, "", []

    recalage_message = ""
    map_updates = []
    route_recalage_done = False

    for route_name in routes:
        found_in_instructions = False
        if 'instructions' in chat_state.route_data:
            for instr in chat_state.route_data['instructions']:
                instr_text = (instr.get('name', '') + ' ' + instr.get('text', '')).lower()
                if route_name.lower() in instr_text:
                    cumulative_dist = instr.get('cumulative_distance', 0)
                    position = routing_service.find_position_on_route(chat_state.route_data, cumulative_dist)

                    if position:
                        chat_state.set_coordinates(position[0], position[1], CONFIDENCE_ROUTE)
                        total_distance = chat_state.route_data['total_distance']
                        total_duration = chat_state.route_data['total_duration']
                        new_duration_min = int((cumulative_dist / total_distance) * total_duration / 60)
                        chat_state.context['duration'] = new_duration_min
                        chat_state.context['recalage_done'] = True
                        route_recalage_done = True

                        map_updates.append({
                            'type': 'position_with_radius',
                            'lat': position[0], 'lon': position[1],
                            'radius': 500, 'confidence': CONFIDENCE_ROUTE,
                            'source': f'Route {route_name}'
                        })
                        recalage_message = f"✅ Bien reçu ! Je vous ai localisé sur la route **{route_name}**.\n\n"
                        found_in_instructions = True
                        break

        if not found_in_instructions:
            # Fallback Overpass simplifié pour l'exemple
            pass

    return route_recalage_done, recalage_message, map_updates


async def handle_landmark_recalage(
    landmarks_to_search: List[str],
    current_step: int,
    entities: Dict,
    user_message: str = None,
    ignore_prev: bool = False
) -> Optional[ChatResponse]:
    """
    Recalage intelligent par repères avec système de scoring et filtrage strict (Mode Enquête).
    """
    # 1. DÉTECTION DU REFUS (priorité absolue)
    is_refusal = ignore_prev
    if user_message and not is_refusal:
        msg_lower = user_message.lower()
        if any(w in msg_lower for w in ["aucun", "auncun", "rien", "pas ça", "non plus", "pas ceux"]):
            is_refusal = True
            
    if is_refusal:
        print("🚫 Refus détecté (LLM ou regex). Suppression des anciens candidats.")
        chat_state.context['current_poi_list'] = []
        chat_state.context['awaiting_poi_selection'] = False

    # 2. NETTOYAGE DES MOTS DE BRUIT
    noise_words = ['un', 'une', 'le', 'la', 'les', 'des', 'lieu', 'aperçois', 'vois', 'je', 'aperçois', 'aucun', 'auncun']
    cleaned_landmarks = []

    targets = landmarks_to_search if landmarks_to_search else ([user_message] if user_message else [])
    for l in targets:
        words = str(l).lower().split()
        clean_words = [w for w in words if w not in noise_words]
        if clean_words: cleaned_landmarks.append(" ".join(clean_words))

    cleaned_landmarks = list(dict.fromkeys(cleaned_landmarks))
    if not cleaned_landmarks: return None

    print(f"\n🕵️ ENQUÊTE GÉOGRAPHIQUE : Recherche de {cleaned_landmarks}")

    # 3. LOGIQUE DE FILTRAGE
    # Seulement si la liste existante est un résultat d'enquête (< 200 candidats),
    # PAS si c'est la grosse liste de "Affiche les POI" (400+ items)
    MAX_REFINABLE = 200
    existing_candidates = chat_state.context.get('current_poi_list', [])
    if not is_refusal and existing_candidates and len(existing_candidates) <= MAX_REFINABLE and chat_state.context.get('awaiting_poi_selection'):
        print(f"📊 Filtrage de {len(existing_candidates)} candidats existants par nouveaux indices...")
        refined_list = []
        map_updates = []

        for i, cand in enumerate(existing_candidates):
            cand_supporting = []
            distinct_matches = 0
            for desc in cleaned_landmarks:
                matches = await geocoding_service.fetch_local_pois_sqlite(
                    cand['lat'], cand['lon'], radius_meters=250, query=desc
                )
                # Si la requête complète ne marche pas, essayer des sous-phrases
                # ex: "banque crédit agricole" → "crédit agricole" → "agricole"
                if not matches:
                    words = desc.split()
                    for start in range(1, len(words)):
                        sub_query = " ".join(words[start:])
                        if len(sub_query) >= 3:
                            matches = await geocoding_service.fetch_local_pois_sqlite(
                                cand['lat'], cand['lon'], radius_meters=250, query=sub_query
                            )
                            if matches:
                                break
                if matches:
                    cand_supporting.extend(matches)
                    distinct_matches += 1

            if cand_supporting:
                print(f"   ✅ Candidat '{cand['name']}' validé par {distinct_matches} types d'indices ({len(cand_supporting)} total)")
                cand['supporting_evidence'] = cand_supporting
                cand['score_distinct'] = distinct_matches
                refined_list.append(cand)

                map_updates.append({
                    'type': 'candidate_landmark',
                    'lat': cand['lat'], 'lon': cand['lon'],
                    'name': cand['name'], 'poi_type': cand.get('type', 'repère'),
                    'index': len(refined_list),
                    'fitBounds': (len(refined_list) == 1)
                })

        if refined_list:
            # TRIER PAR SCORE : Nombre d'indices distincts, puis nombre total
            refined_list.sort(key=lambda x: (x.get('score_distinct', 0), len(x.get('supporting_evidence', []))), reverse=True)
            
            chat_state.context['current_poi_list'] = refined_list
            chat_state.log_event('investigation_step', {
                'query': " + ".join(cleaned_landmarks),
                'candidates_before': len(existing_candidates),
                'candidates_after': len(refined_list)
            })
            
            # Collecter toutes les preuves pour affichage sur la carte
            all_evidence = []
            seen_evidence = set()
            for cand in refined_list:
                for ev in cand.get('supporting_evidence', []):
                    ev_key = f"{ev['lat']:.5f}_{ev['lon']:.5f}"
                    if ev_key not in seen_evidence:
                        seen_evidence.add(ev_key)
                        all_evidence.append(ev)
            
            if all_evidence:
                map_updates.append({
                    'type': 'evidence_pois',
                    'pois': all_evidence,
                    'label': " + ".join(cleaned_landmarks)
                })
            
            # --- LOGIQUE DE VICTOIRE PAR K.O. ---
            # Si le meilleur candidat a PLUS d'indices distincts que le deuxième, on valide DIRECTEMENT
            is_clearly_better = len(refined_list) == 1 or refined_list[0]['score_distinct'] > refined_list[1]['score_distinct']
            
            if is_clearly_better:
                print(f"🏆 Victoire par K.O. pour {refined_list[0]['name']}")
                response = await _recalage_single_match(refined_list[0], current_step, entities, evidence=refined_list[0].get('supporting_evidence'))
                response.map_updates = map_updates + (response.map_updates or [])
                # Sauvegarde même si c'est un match unique (pour pouvoir revenir au "K.O.")
                chat_state.add_poi_to_history(" ".join(cleaned_landmarks), refined_list, response.map_updates)
                return response
            else:
                # Plusieurs candidats ont le même nombre d'indices distincts, on demande de choisir
                response = _build_choice_response(refined_list, " ".join(cleaned_landmarks), current_step, entities, refined=True)
                response.map_updates = map_updates + (response.map_updates or [])
                # SAUVEGARDE DANS L'HISTORIQUE
                chat_state.add_poi_to_history(" ".join(cleaned_landmarks), refined_list, response.map_updates)
                return response

    # 4. RECHERCHE GLOBALE INITIALE (Support multi-indices simultanés)
    chat_state.context['awaiting_description'] = False
    cleaned_landmarks.sort(key=len, reverse=True)

    # Rayon du cercle d'incertitude actuel
    uncertainty_radius = chat_state.context.get('uncertainty_radius', 3000)
    center_lat, center_lon = chat_state.coordinates

    if len(cleaned_landmarks) > 1:
        print(f"🧩 Stratégie Multi-Indices : Recherche de l'intersection spatiale pour {cleaned_landmarks}")
        all_intersection_candidates = []
        
        for p_idx, pivot_desc in enumerate(cleaned_landmarks):
            other_indices = [l for i, l in enumerate(cleaned_landmarks) if i != p_idx]
            pivot_matches = await geocoding_service.fetch_local_pois_sqlite(
                center_lat, center_lon,
                radius_meters=uncertainty_radius + 500, query=pivot_desc
            )

            if pivot_matches:
                # Filtrer par distance au cercle (pas par distance à la route)
                projected_pivots = [p for p in pivot_matches 
                    if routing_service._haversine_distance(center_lat, center_lon, p['lat'], p['lon']) <= uncertainty_radius]

                for cand in projected_pivots:
                    cand_supporting = []
                    distinct_matches = 1 # Le pivot lui-même
                    for other_desc in other_indices:
                        matches = await geocoding_service.fetch_local_pois_sqlite(
                            cand['lat'], cand['lon'], radius_meters=400, query=other_desc
                        )
                        if matches: 
                            cand_supporting.extend(matches)
                            distinct_matches += 1

                    if cand_supporting:
                        cand['supporting_evidence'] = cand_supporting
                        cand['score_distinct'] = distinct_matches
                        all_intersection_candidates.append(cand)
        
        if all_intersection_candidates:
            # Nettoyer les doublons (si un point a été pivot puis cible)
            unique_candidates = {}
            for c in all_intersection_candidates:
                key = f"{c['lat']:.5f}_{c['lon']:.5f}"
                if key not in unique_candidates or c['score_distinct'] > unique_candidates[key]['score_distinct']:
                    unique_candidates[key] = c
            
            final_candidates = sorted(unique_candidates.values(), key=lambda x: (x.get('score_distinct', 0), len(x.get('supporting_evidence', []))), reverse=True)
            
            if final_candidates:
                is_clearly_better = len(final_candidates) == 1 or final_candidates[0]['score_distinct'] > final_candidates[1]['score_distinct']
                if is_clearly_better:
                    return await _recalage_single_match(final_candidates[0], current_step, entities, evidence=final_candidates[0].get('supporting_evidence'))
                else:
                    return _build_choice_response(final_candidates, " + ".join(cleaned_landmarks), current_step, entities, refined=True)

    # Recherche simple en 2 phases : cercle d'abord, puis trajet complet
    for landmark_desc in cleaned_landmarks:
        if landmark_desc in chat_state.context.get('rejected_pois', []): continue
        
        # PHASE 1 : Chercher dans le cercle d'incertitude
        print(f"🔎 Phase 1 — Recherche de '{landmark_desc}' dans le cercle ({uncertainty_radius}m)")
        matches = await geocoding_service.fetch_local_pois_sqlite(
            center_lat, center_lon,
            radius_meters=uncertainty_radius + 500, query=landmark_desc
        )

        if not matches:
            matches = geocoding_service.find_landmarks_fuzzy(landmark_desc, cutoff=0.6)

        if matches:
            # Filtrer par distance géographique au centre du cercle (pas par distance à la route)
            valid_matches = [m for m in matches 
                if routing_service._haversine_distance(center_lat, center_lon, m['lat'], m['lon']) <= uncertainty_radius]
            
            # Enrichir avec la projection sur la route (tri par position sur le trajet)
            if valid_matches and chat_state.has_route_data():
                projected = routing_service.project_pois_on_route(
                    chat_state.route_data, valid_matches, max_distance_from_route=5000
                )
                # Garder les projetés en priorité (triés par distance au trajet), ajouter les non-projetés à la fin
                projected_coords = {f"{p['lat']:.5f}_{p['lon']:.5f}" for p in projected}
                non_projected = [m for m in valid_matches 
                    if f"{m['lat']:.5f}_{m['lon']:.5f}" not in projected_coords]
                valid_matches = projected + non_projected

            if valid_matches:
                response = None
                if len(valid_matches) == 1:
                    response = await _recalage_single_match(valid_matches[0], current_step, entities)
                else:
                    response = _build_choice_response(valid_matches, landmark_desc, current_step, entities)

                # SAUVEGARDE DANS L'HISTORIQUE
                chat_state.add_poi_to_history(landmark_desc, valid_matches, response.map_updates)
                return response
        
        # PHASE 2 : Rien dans le cercle → proposer d'élargir
        # Vérifier d'abord s'il y en a sur le trajet complet
        print(f"🔎 Phase 2 — Aucun '{landmark_desc}' dans le cercle, vérification trajet complet...")
        wide_matches = await geocoding_service.fetch_local_pois_sqlite(
            center_lat, center_lon,
            radius_meters=10000, query=landmark_desc
        )
        if wide_matches:
            wide_valid = routing_service.project_pois_on_route(
                chat_state.route_data, wide_matches, max_distance_from_route=1200
            )
            if wide_valid:
                # Stocker pour utilisation si l'utilisateur accepte
                chat_state.context['pending_wide_search'] = {
                    'matches': wide_valid,
                    'query': landmark_desc,
                    'count': len(wide_valid)
                }
                return ChatResponse(
                    message=f"🔍 Je ne trouve pas de **{landmark_desc}** dans votre zone estimée.\n\n"
                            f"J'en ai trouvé **{len(wide_valid)}** sur l'ensemble du trajet. "
                            f"Voulez-vous que j'élargisse la recherche au trajet complet ?",
                    step=current_step + 1, entities=entities, map_updates=None
                )

    # FALLBACK OPENSTREETMAP
    for landmark_desc in cleaned_landmarks:
        found = await geocoding_service.search_landmarks_near_point(
            landmark_desc, center_lat, center_lon, radius=uncertainty_radius
        )
        if found:
            return await _recalage_overpass_match(found[0], current_step, entities)

    chat_state.context['awaiting_description'] = True
    return ChatResponse(
        message=f"Je ne trouve rien correspondant à '{cleaned_landmarks[0]}' dans votre zone ni sur votre route. Pouvez-vous me citer un autre repère ?",
        step=current_step + 1, entities=entities, map_updates=None
    )


async def _recalage_single_match(match: Dict, current_step: int, entities: Dict, evidence: List[Dict] = None) -> ChatResponse:
    """Recalage sur un match unique avec preuves visuelles."""
    chat_state.set_coordinates(match['lat'], match['lon'], CONFIDENCE_LANDMARK)
    chat_state.context.update({
        'recalage_done': True, 'awaiting_description': False,
        'awaiting_poi_selection': False, 'current_poi_list': []
    })

    if chat_state.route_data:
        projected = routing_service.project_pois_on_route(chat_state.route_data, [match], max_distance_from_route=2000)
        if projected and projected[0].get('cumulative_distance'):
            dist = projected[0]['cumulative_distance']
            chat_state.context['duration'] = int((dist / chat_state.route_data['total_distance']) * chat_state.route_data['total_duration'] / 60)

    msg = f"✅ **Localisation confirmée !** Vous êtes à **{match['name']}**.\n"
    msg += f"📍 Coordonnées : `{match['lat']:.5f}, {match['lon']:.5f}`\n"
    evidence_names = []
    if evidence:
        unique_names = list(dict.fromkeys(e['name'] for e in evidence))
        evidence_names = unique_names[:3]
        msg += f"La présence de **{', '.join(evidence_names)}** à proximité confirme ce lieu.\n"
    
    chat_state.log_event('location_confirmed', {
        'name': match['name'], 'lat': match['lat'], 'lon': match['lon'],
        'evidence': evidence_names
    })

    return ChatResponse(message=msg, step=current_step + 1, entities=entities, map_updates=[{
        'type': 'position_recaled',
        'lat': match['lat'], 'lon': match['lon'],
        'confidence': CONFIDENCE_LANDMARK,
        'source': match['name'],
        'name': match['name']
    }])


def _build_choice_response(matches: List[Dict], query: str, current_step: int, entities: Dict, refined: bool = False) -> ChatResponse:
    """Propose un choix avec marquage sur la carte."""
    chat_state.context.update({'awaiting_poi_selection': True, 'current_poi_list': matches})

    # Carte : si <= 10 → marqueurs orange numérotés, sinon → points orange sans numéros
    map_updates = []
    if len(matches) <= 10:
        for i, m in enumerate(matches):
            map_updates.append({
                'type': 'candidate_landmark', 'lat': m['lat'], 'lon': m['lon'],
                'name': m['name'], 'poi_type': m.get('type', 'repère'), 'index': i + 1,
                'fitBounds': (i == 0)
            })
    else:
        # Trop de candidats pour les numéroter → points orange
        map_updates.append({
            'type': 'candidates_all',
            'pois': matches,
            'fitBounds': True
        })

    # Chat : lister jusqu'à 10 pour la lisibilité
    display_count = min(len(matches), 10)
    if refined:
        msg = f"🔍 Grâce à vos précisions, j'ai réduit la liste à **{len(matches)} candidats** :\n\n"
    else:
        msg = f"🔍 J'ai trouvé **{len(matches)} lieux** pour \"**{query}**\" :\n\n"

    for i, m in enumerate(matches[:display_count]):
        msg += f"{i+1}. {m['name']} ({m.get('type', 'repère')})\n"
    
    if len(matches) > display_count:
        msg += f"\n_...et {len(matches) - display_count} autres affichés sur la carte._\n"

    msg += "\nLequel voyez-vous ? (ou donnez-moi un autre détail pour trancher)."
    return ChatResponse(message=msg, step=current_step + 1, entities=entities, map_updates=map_updates)


async def _recalage_overpass_match(landmark: Dict, current_step: int, entities: Dict) -> ChatResponse:
    """Recalage via Overpass."""
    chat_state.set_coordinates(landmark['lat'], landmark['lon'], CONFIDENCE_LANDMARK)
    chat_state.context.update({'recalage_done': True, 'awaiting_description': False,
                               'awaiting_poi_selection': False, 'current_poi_list': []})
    
    chat_state.log_event('location_confirmed', {
        'name': landmark['name'], 'lat': landmark['lat'], 'lon': landmark['lon'],
        'evidence': []
    })
    
    msg = f"✅ **Localisation confirmée !** Vous êtes à **{landmark['name']}**.\n"
    msg += f"📍 Coordonnées : `{landmark['lat']:.5f}, {landmark['lon']:.5f}`\n"
    
    return ChatResponse(
        message=msg,
        step=current_step + 1, entities=entities, map_updates=[{
            'type': 'position_recaled',
            'lat': landmark['lat'], 'lon': landmark['lon'],
            'confidence': CONFIDENCE_LANDMARK,
            'source': landmark['name'],
            'name': landmark['name']
        }]
    )

async def handle_passed_landmarks(
    passed_landmarks: List[str],
    current_step: int,
    entities: Dict
) -> Tuple[str, List[Dict]]:
    """
    Met à jour la progression sur la route en fonction des repères dépassés.
    Projette le repère sur la route pour définir la nouvelle distance minimale parcourue.
    """
    map_updates = []
    messages = []
    
    if not chat_state.route_data:
        return "", []
        
    for desc in passed_landmarks:
        # Chercher le repère globalement autour de la zone incertaine
        center_lat, center_lon = chat_state.coordinates
        radius = chat_state.context.get('uncertainty_radius', 15000)
        
        matches = await geocoding_service.fetch_local_pois_sqlite(
            center_lat, center_lon, radius_meters=radius, query=desc
        )
        
        if not matches:
            # Assure que le cache est chargé avec les POI de la zone
            await geocoding_service.fetch_local_pois_sqlite(center_lat, center_lon, radius_meters=radius)
            
            # Extraire le nom pur (enlever les mots génériques comme 'arrêt de bus')
            name_query = desc.lower().strip()
            generic_keywords = [
                'arrêt de bus', 'arret de bus', 'abribus', 'abris bus',
                'station service', 'station-service', 'station', 'pompe',
                'aire de repos', 'aire de services', "aire d'autoroute", 'aire',
                'complexe sportif', 'complexes sportifs', 'terrain de sport',
                'boulangerie', 'pharmacie', 'banque', 'restaurant', 'bar', 'café', 'cafe',
                'supermarché', 'supermarche', 'hypermarché', 'hypermarche', 'magasin', 'boutique',
                'hôtel', 'hotel', 'camping', 'mairie', 'hôpital', 'hopital', 'clinique',
                'école', 'ecole', 'collège', 'college', 'lycée', 'lycee',
                'gare', 'aéroport', 'aeroport', 'cimetière', 'cimetiere', 'parc', 'parking',
                'pont', 'pylône', 'pylone', 'éolienne', 'eolienne', 'péage', 'peage', 'carrefour', 'croisement'
            ]
            for kw in generic_keywords:
                if name_query.startswith(kw + ' ') or name_query.endswith(' ' + kw):
                    name_query = name_query.replace(kw, '').strip()
            
            if not name_query:
                name_query = desc
                
            matches = geocoding_service.find_landmarks_fuzzy(name_query, cutoff=0.55)
            
        if matches:
            # On prend le meilleur match
            best_match = matches[0]
            
            # On le projette sur la route
            projected = routing_service.project_pois_on_route(chat_state.route_data, [best_match], max_distance_from_route=2000)
            if projected and projected[0].get('cumulative_distance'):
                distance_X = projected[0]['cumulative_distance']
                
                # Mise à jour de la croyance spatiale (Spatial Belief Updating)
                old_dist_min = chat_state.route_data.get('distance_min', 0)
                old_dist_max = chat_state.route_data.get('distance_max', chat_state.route_data['total_distance'])
                
                if distance_X > old_dist_min:
                    chat_state.route_data['distance_min'] = distance_X
                    
                    # Si on a dépassé le point max estimé, on pousse le max
                    if distance_X > old_dist_max:
                        # On donne une marge de 5km devant
                        chat_state.route_data['distance_max'] = min(distance_X + 5000, chat_state.route_data['total_distance'])
                        old_dist_max = chat_state.route_data['distance_max']
                        
                    # Recalcul des nouvelles coordonnées et incertitude
                    new_center_dist = (distance_X + old_dist_max) / 2
                    new_radius = max((old_dist_max - distance_X) / 2, 500) # Minimum 500m
                    
                    # Trouver les coordonnées de ce nouveau centre
                    position = routing_service.find_position_on_route(chat_state.route_data, new_center_dist)
                    if position:
                        chat_state.set_coordinates(position[0], position[1], confidence=0.7)
                        chat_state.context['uncertainty_radius'] = new_radius
                        # Clean existing candidates
                        chat_state.context['current_poi_list'] = []
                        chat_state.context['awaiting_poi_selection'] = False
                        
                        map_updates.append({
                            'type': 'position_with_radius',
                            'lat': position[0], 'lon': position[1],
                            'radius': new_radius, 'confidence': 0.7,
                            'source': f'Après {best_match["name"]}'
                        })
                        messages.append(f"✅ J'ai noté que vous avez dépassé **{best_match['name']}** (`{best_match['lat']:.5f}, {best_match['lon']:.5f}`). La zone de recherche a été resserrée devant ce point.")
                        
                        chat_state.log_event('belief_updated', {
                            'passed_landmark': best_match['name'],
                            'new_distance_min': distance_X,
                            'new_radius': new_radius
                        })
                        
    return "\n".join(messages), map_updates
