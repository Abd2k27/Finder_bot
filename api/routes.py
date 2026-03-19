"""
API Routes pour le bot de localisation.

Ce fichier ne contient que les endpoints HTTP et orchestre les appels
aux handlers spécialisés. La logique métier est dans le package handlers/.
"""

import re
import traceback

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from api.schemas import ChatMessage, ChatResponse, GeocodeRequest
from api.dependencies import (
    chat_state, llm_extractor, geocoding_service, routing_service,
    reset_chat_state, CONFIDENCE_HIGH
)
from api.handlers import (
    handle_finish,
    handle_clarify,
    handle_reject_pois,
    handle_show_all_pois,
    handle_confirm_choice,
    handle_route_recalage,
    handle_landmark_recalage,
    handle_disambiguation_refinement,
    calculate_position_from_duration,
    calculate_position_from_distance,
    suggest_nearby_pois
)


router = APIRouter()


# ============================================================
# ENDPOINT: Proxy Géocodage
# ============================================================

@router.post("/api/geocode")
async def geocode_proxy(request: GeocodeRequest):
    """Proxy géocodage pour éviter les appels Nominatim directs depuis le frontend"""
    try:
        coords = await geocoding_service.get_coordinates_from_place(request.query)
        if coords:
            return {"success": True, "lat": coords[0], "lon": coords[1]}
        return {"success": False, "error": "Lieu non trouvé"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================
# ENDPOINT: Chat Principal
# ============================================================

@router.post("/chat", response_model=ChatResponse)
async def chat(message: ChatMessage):
    """Endpoint principal du chatbot avec gestion d'erreurs robuste - VERSION AGENTIQUE"""
    
    try:
        user_response = message.response
        current_step = message.step
        
        print(f"\n{'='*80}")
        print(f"📨 ÉTAPE {current_step} : '{user_response}'")
        print(f"{'='*80}")
        
        # Ajouter la réponse
        chat_state.add_response(user_response)
        
        # Initialiser map_updates et recalage_message
        map_updates = []
        recalage_message = ""
        
        # ═══════════════════════════════════════════════════════════════
        # VÉRIFIER SI L'UTILISATEUR VEUT REVENIR EN ARRIÈRE (UNDO)
        # ═══════════════════════════════════════════════════════════════
        
        user_lower = user_response.lower().strip()
        undo_keywords = ['retour', 'revenir', 'arrière', 'précédent', 'annuler', 'undo', 'back', 'trompé', 'erreur']
        wants_undo = any(kw in user_lower for kw in undo_keywords)
        
        if wants_undo and not chat_state.is_in_disambiguation():
            # Vérifier s'il y a une désambiguïsation à restaurer
            if chat_state.can_restore_disambiguation():
                print(f"🔄 Restauration de la désambiguïsation précédente...")
                if chat_state.restore_disambiguation():
                    result = await handle_disambiguation_refinement(user_response, current_step, {})
                    if result:
                        return result
        
        # ═══════════════════════════════════════════════════════════════
        # VÉRIFIER SI ON EST EN MODE DÉSAMBIGUÏSATION
        # ═══════════════════════════════════════════════════════════════
        
        if chat_state.is_in_disambiguation():
            print(f"🔀 Mode désambiguïsation actif - traitement raffinement")
            result = await handle_disambiguation_refinement(user_response, current_step, {})
            if result:
                return result
        
        # 🤖 DÉCISION AGENTIQUE
        # Seulement skip si les infos de base sont vraiment manquantes ET pas une réponse spéciale
        has_basic_info = (
            chat_state.has_trajet() and
            chat_state.context.get('transport') and
            chat_state.context.get('duration')
        )
        
        # Réponses spéciales qui doivent toujours passer par decide_action
        special_responses = ['aucun', 'non', 'rien', 'pas vu', 'je ne vois pas', 'je vois pas']
        is_special_response = any(sr in user_lower for sr in special_responses)
        
        # MODIFIÉ: Ne skip pas si c'est awaiting_poi_selection ou une réponse spéciale
        awaiting_poi = chat_state.context.get('awaiting_poi_selection', False)
        
        if not has_basic_info and not awaiting_poi and not is_special_response:
            print(f"⚡ Skip decide_action (infos de base incomplètes)")
            decision = {"action": "continue", "response": None, "extract_entities": True}
        else:
            if awaiting_poi or is_special_response:
                print(f"🎯 Force decide_action (awaiting_poi={awaiting_poi}, special={is_special_response})")
            decision = await llm_extractor.decide_action(user_response, chat_state.to_dict())
        
        action = decision.get("action", "continue")
        llm_response = decision.get("response")
        
        # ═══════════════════════════════════════════════════════════════
        # DISPATCH DES ACTIONS AGENTIQUES
        # ═══════════════════════════════════════════════════════════════
        
        if action == "finish":
            return await handle_finish(llm_response, current_step)
        
        if action == "clarify":
            return await handle_clarify(llm_response, current_step)
        
        if action == "reject_pois":
            return await handle_reject_pois(llm_response, current_step)
        
        if action == "show_all_pois":
            return await handle_show_all_pois(current_step)
        
        if action == "confirm_choice" and chat_state.context.get('current_poi_list'):
            result, _ = await handle_confirm_choice(
                user_response, 
                decision.get("poi_index"),
                current_step
            )
            if result:
                return result
        
        # ═══════════════════════════════════════════════════════════════
        # EXTRACTION D'ENTITÉS
        # ═══════════════════════════════════════════════════════════════
        
        missing_fields = []
        if not chat_state.context['start']:
            missing_fields.append('start')
        if not chat_state.context['end']:
            missing_fields.append('end')
        if not chat_state.context['transport']:
            missing_fields.append('transport')
        if not chat_state.context['duration'] and not chat_state.context.get('distance'):
            missing_fields.append('duration')
        
        conversation_context = {
            'missing_fields': missing_fields,
            'current_context': chat_state.context
        }
        
        print("🤖 Extraction LLM...")
        try:
            entities = await llm_extractor.extract_entities(user_response, conversation_context)
            print(f"✅ Entités: {entities}")
        except Exception as e:
            print(f"❌ Erreur LLM: {e}")
            traceback.print_exc()
            entities = {
                'lieux': [], 'routes': [], 'distances': [], 'directions': [],
                'depart': None, 'fin': None, 'transport': None,
                'duree': None, 'distance': None, 'reperes': []
            }
        
        # ═══════════════════════════════════════════════════════════════
        # RECALAGE PAR ROUTE
        # ═══════════════════════════════════════════════════════════════
        
        route_recalage_done = False
        if entities.get('routes'):
            route_recalage_done, recalage_msg, route_map_updates = await handle_route_recalage(
                entities['routes'], current_step, entities
            )
            if recalage_msg:
                recalage_message = recalage_msg
            map_updates.extend(route_map_updates)
        
        # ═══════════════════════════════════════════════════════════════
        # RECALAGE PAR REPÈRES
        # ═══════════════════════════════════════════════════════════════
        
        if not route_recalage_done:
            reperes = entities.get('reperes') or []
            lieux = entities.get('lieux') or []
            if isinstance(reperes, str):
                reperes = [reperes]
            if isinstance(lieux, str):
                lieux = [lieux]
            landmarks_to_search = reperes + lieux
            
            # Fallback: description libre
            if not landmarks_to_search and chat_state.context.get('awaiting_description'):
                clean_text = user_response.lower()
                clean_text = re.sub(r'^(je vois|il y a|j\'aperçois|y a)\s*(une|un|des|le|la|les)?\s*', '', clean_text).strip()
                if clean_text and len(clean_text) > 2:
                    landmarks_to_search = [clean_text]
                    print(f"📝 Fallback description libre: '{clean_text}'")
            
            if landmarks_to_search and chat_state.coordinates and chat_state.has_route_data():
                result = await handle_landmark_recalage(landmarks_to_search, current_step, entities)
                if result:
                    print(f"\n💬 Réponse (recalage): {result.message[:100]}...")
                    return result
        
        # ═══════════════════════════════════════════════════════════════
        # MISE À JOUR TRANSPORT
        # ═══════════════════════════════════════════════════════════════
        
        transport_changed = False
        if entities.get('transport'):
            old_transport = chat_state.context.get('transport')
            new_transport = entities['transport']
            
            if old_transport != new_transport:
                print(f"\n🚗 CHANGEMENT DE TRANSPORT: {old_transport} → {new_transport}")
                transport_changed = True
            
            chat_state.set_transport(new_transport)
            map_updates.append({'type': 'transport', 'transport': new_transport})
        
        # Recalculer le trajet si transport a changé
        if transport_changed and chat_state.has_trajet():
            await _recalculate_route(map_updates)
        
        # ═══════════════════════════════════════════════════════════════
        # MISE À JOUR TRAJET
        # ═══════════════════════════════════════════════════════════════
        
        if entities.get('depart') and entities.get('fin'):
            print(f"\n🗺️  TRAJET: {entities['depart']} → {entities['fin']}")
            chat_state.set_trajet(entities['depart'], entities['fin'])
            
            try:
                start_coords = await geocoding_service.get_coordinates_from_place(entities['depart'])
                end_coords = await geocoding_service.get_coordinates_from_place(entities['fin'])
                
                if start_coords and end_coords:
                    transport = chat_state.context.get('transport', 'voiture')
                    route_data = await routing_service.get_detailed_route(
                        start_coords, end_coords, transport
                    )
                    
                    if route_data:
                        chat_state.set_route_data(route_data)
                        total_km = route_data['total_distance'] / 1000
                        total_min = route_data['total_duration'] / 60
                        print(f"✅ Itinéraire OSRM: {total_km:.1f}km, {total_min:.0f}min")
                        
                        map_updates.append({
                            'type': 'route',
                            'start': entities['depart'],
                            'end': entities['fin'],
                            'route_data': route_data
                        })
            except Exception as e:
                print(f"❌ Erreur trajet: {e}")
                traceback.print_exc()
        
        # Mise à jour durée et distance
        if entities.get('duree'):
            chat_state.set_duration(entities['duree'])
        if entities.get('distance'):
            chat_state.set_distance(entities['distance'])
        
        # Repères
        for lieu in entities.get('lieux', []):
            chat_state.add_landmark(lieu)
        for route in entities.get('routes', []):
            chat_state.add_landmark(route)
        
        # ═══════════════════════════════════════════════════════════════
        # CALCUL DE POSITION
        # ═══════════════════════════════════════════════════════════════
        
        next_message = ""
        
        if chat_state.has_trajet() and chat_state.has_route_data():
            next_message, pos_map_updates = await _calculate_and_suggest_position(
                entities, current_step
            )
            map_updates.extend(pos_map_updates)
        else:
            next_message = _get_missing_info_question()
        
        print(f"\n💬 Réponse: {next_message}")
        print(f"{'='*80}\n")
        
        final_message = recalage_message + next_message if recalage_message else next_message
        
        return ChatResponse(
            message=final_message,
            step=current_step + 1,
            entities=entities,
            map_updates=map_updates if map_updates else None
        )
    
    except Exception as e:
        print(f"\n{'='*80}")
        print(f"❌ ERREUR CRITIQUE DANS /chat")
        print(f"{'='*80}")
        print(f"Erreur: {e}")
        traceback.print_exc()
        
        return ChatResponse(
            message="Une erreur s'est produite. Pouvez-vous reformuler ?",
            step=message.step + 1,
            entities=None,
            map_updates=None
        )


# ============================================================
# HELPERS INTERNES
# ============================================================

async def _recalculate_route(map_updates: list):
    """Recalcule l'itinéraire après changement de transport."""
    print(f"\n🔄 RECALCUL DE L'ITINÉRAIRE avec nouveau transport...")
    try:
        start_coords = await geocoding_service.get_coordinates_from_place(chat_state.context['start'])
        end_coords = await geocoding_service.get_coordinates_from_place(chat_state.context['end'])
        
        if start_coords and end_coords:
            transport = chat_state.context.get('transport', 'voiture')
            route_data = await routing_service.get_detailed_route(
                start_coords, end_coords, transport
            )
            
            if route_data:
                chat_state.set_route_data(route_data)
                map_updates.append({
                    'type': 'route',
                    'start': chat_state.context['start'],
                    'end': chat_state.context['end'],
                    'route_data': route_data
                })
    except Exception as e:
        print(f"❌ Erreur recalcul trajet: {e}")
        traceback.print_exc()


async def _calculate_and_suggest_position(entities: dict, current_step: int) -> tuple:
    """Calcule la position et suggère des POI pour levée de doute."""
    print(f"\n{'='*80}")
    print("🎯 CALCUL DE POSITION AVEC VITESSE OSRM RÉELLE")
    print(f"{'='*80}")
    
    transport = chat_state.context.get('transport', 'voiture')
    route_data = chat_state.route_data
    total_distance_m = route_data['total_distance']
    total_duration_sec = route_data['total_duration']
    total_distance_km = total_distance_m / 1000
    
    if total_duration_sec <= 0:
        return "Erreur dans le calcul du trajet. Pouvez-vous reformuler ?", []
    
    real_speed_kmh = (total_distance_km / total_duration_sec) * 3600
    print(f"📊 Vitesse moyenne RÉELLE: {real_speed_kmh:.1f} km/h")
    
    map_updates = []
    next_message = ""
    
    if chat_state.context.get('duration'):
        duration_minutes = chat_state.context['duration']
        
        position, distance_meters, progress_ratio, pos_updates = await calculate_position_from_duration(
            duration_minutes, route_data, real_speed_kmh
        )
        map_updates.extend(pos_updates)
        
        if position:
            progress_pct = progress_ratio * 100
            
            if progress_ratio >= 1.0:
                next_message = "🏁 D'après mes calculs, vous devriez être arrivé(e) à destination. Êtes-vous bien arrivé(e) ou avez-vous rencontré un problème en chemin ?"
            else:
                next_message = f"📍 D'après mes calculs, vous devriez être dans cette zone (progression: {progress_pct:.0f}%).\n\n"
                
                # Suggérer des POI
                poi_message, poi_updates = await suggest_nearby_pois(
                    position, distance_meters, route_data
                )
                next_message += poi_message
                map_updates.extend(poi_updates)
        else:
            next_message = "Je n'arrive pas à calculer votre position précise. Pouvez-vous me donner plus de détails ?"
    
    elif chat_state.context.get('distance'):
        distance_km = chat_state.context['distance']
        position, pos_updates = await calculate_position_from_distance(
            distance_km, route_data, real_speed_kmh
        )
        map_updates.extend(pos_updates)
        
        if position:
            progress_pct = (distance_km * 1000 / total_distance_m) * 100
            next_message = f"✅ Position trouvée avec {int(CONFIDENCE_HIGH*100)}% confiance ! (progression: {progress_pct:.1f}%)"
        else:
            next_message = "Position non trouvée. Plus de détails ?"
    else:
        next_message = _get_missing_transport_or_duration_question()
    
    return next_message, map_updates


def _get_missing_info_question() -> str:
    """Retourne la question pour les informations manquantes."""
    if not chat_state.context['start'] or not chat_state.context['end']:
        return "D'où partez-vous et où allez-vous ? Par exemple : 'De Paris à Lyon'"
    elif not chat_state.context.get('transport'):
        return "Comment voyagez-vous ? En voiture, bus, moto, à pied, ou à vélo ?"
    else:
        return "Depuis combien de temps êtes-vous en route ?"


def _get_missing_transport_or_duration_question() -> str:
    """Retourne la question pour transport ou durée manquant."""
    if not chat_state.context.get('transport'):
        return "Comment voyagez-vous ? En voiture, bus, moto, à pied, ou à vélo ?"
    elif not chat_state.context.get('duration'):
        return "Depuis combien de temps êtes-vous en route ?"
    else:
        return "Je n'ai pas assez d'informations. Précisez votre position ?"


# ============================================================
# ENDPOINT: Reset
# ============================================================

@router.post("/reset")
async def reset():
    """Réinitialiser la conversation"""
    try:
        reset_chat_state()
        return {
            "message": "Bonjour ! Pour vous localiser, dites-moi d'où vous partez et où vous allez. Par exemple : 'De Paris à Lyon'",
            "step": 0
        }
    except Exception as e:
        print(f"❌ Erreur reset: {e}")
        traceback.print_exc()
        return {
            "message": "Bonjour ! D'où partez-vous et où allez-vous ?",
            "step": 0
        }


# ============================================================
# ENDPOINT: Page d'accueil
# ============================================================

@router.get("/")
async def root():
    """Page d'accueil"""
    try:
        with open("static/index.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except Exception as e:
        print(f"❌ Erreur chargement HTML: {e}")
        return {"error": "Impossible de charger l'interface"}