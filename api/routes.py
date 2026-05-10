"""
API Routes pour le bot de localisation.

Ce fichier ne contient que les endpoints HTTP et orchestre les appels
aux handlers spécialisés. La logique métier est dans le package handlers/.
"""

import re
import traceback

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, Response

from api.schemas import ChatMessage, ChatResponse, GeocodeRequest, ContextUpdate, StateResponse
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
    handle_show_previous_list,
    handle_route_recalage,
    handle_landmark_recalage,
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


@router.get("/api/autocomplete")
async def autocomplete(query: str):
    """Endpoint pour l'autocomplétion d'adresses"""
    if not query or len(query) < 3:
        return []
    try:
        results = await geocoding_service.search_address_candidates(query)
        return results
    except Exception as e:
        print(f"Erreur API Autocomplete: {e}")
        return []


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
        
        # Logger le message utilisateur
        chat_state.log_event('user_message', {'message': user_response})
        
        # Ajouter la réponse
        chat_state.add_response(user_response)
        
        # Initialiser map_updates et recalage_message
        map_updates = []
        recalage_message = ""
        
        # Gérer la réponse à "Voulez-vous élargir la recherche ?"
        pending_wide = chat_state.context.get('pending_wide_search')
        if pending_wide:
            msg_lower = user_response.lower().strip()
            chat_state.context.pop('pending_wide_search', None)
            
            if any(w in msg_lower for w in ['oui', 'yes', 'ok', 'd\'accord', 'vas-y', 'élargis', 'élargi']):
                from api.handlers.recalage_handlers import _build_choice_response, _recalage_single_match
                wide_matches = pending_wide['matches']
                query = pending_wide['query']
                
                if len(wide_matches) == 1:
                    return await _recalage_single_match(wide_matches[0], current_step, {})
                else:
                    return _build_choice_response(wide_matches, query, current_step, {})
            else:
                chat_state.context['awaiting_description'] = True
                return ChatResponse(
                    message="D'accord. Pouvez-vous me donner un autre repère visible autour de vous ?",
                    step=current_step + 1
                )
        
        # 🤖 DÉCISION AGENTIQUE
        # On active la décision dès qu'un trajet et un transport sont définis, peu importe l'étape
        skip_agentic = (
            not chat_state.has_trajet() or
            not chat_state.context.get('transport')
        )
        
        if skip_agentic:
            print(f"⚡ Skip decide_action (infos de base Nantes/Angers/Voiture incomplètes)")
            decision = {"action": "continue", "response": None, "extract_entities": True}
        else:
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
        
        if action == "show_previous_list":
            # On utilise le mot-clé extrait par la décision du LLM lui-même (ex: Carrefour)
            target = decision.get("target_keyword")
            return await handle_show_previous_list(current_step, target_keyword=target)
        
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
        # MISE À JOUR DE CROYANCE (REPÈRES DÉPASSÉS)
        # ═══════════════════════════════════════════════════════════════
        reperes_depasses = entities.get('reperes_depasses') or []
        if isinstance(reperes_depasses, str):
            reperes_depasses = [reperes_depasses]
        
        if reperes_depasses and chat_state.has_route_data():
            from api.handlers.recalage_handlers import handle_passed_landmarks
            passed_result, passed_map_updates = await handle_passed_landmarks(reperes_depasses, current_step, entities)
            if passed_result:
                map_updates.extend(passed_map_updates)
                recalage_message = passed_result + "\n\n"
        
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
            
            # Fallback: description libre (UNIQUEMENT si aucune entité utile n'a été extraite)
            has_useful_entities = (
                entities.get('duree') is not None or 
                entities.get('distance') is not None or 
                entities.get('transport') is not None or
                (entities.get('depart') and entities.get('fin'))
            )
            
            if not landmarks_to_search and chat_state.context.get('awaiting_description') and not has_useful_entities:
                clean_text = user_response.lower()
                clean_text = re.sub(r'^(je vois|il y a|j\'aperçois|y a)\s*(une|un|des|le|la|les)?\s*', '', clean_text).strip()
                if clean_text and len(clean_text) > 2:
                    landmarks_to_search = [clean_text]
                    print(f"📝 Fallback description libre: '{clean_text}'")
            
            if landmarks_to_search and chat_state.coordinates and chat_state.has_route_data():
                # On récupère le flag d'ignorance du LLM
                ignore_prev = decision.get("ignore_previous_candidates", False)
                result = await handle_landmark_recalage(
                    landmarks_to_search, 
                    current_step, 
                    entities, 
                    user_message=user_response,
                    ignore_prev=ignore_prev
                )
                if result:
                    print(f"\n💬 Réponse (recalage): {result.message[:100]}...")
                    chat_state.log_event('bot_message', {'message': result.message})
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
                        
                        # Générer le buffer (2000m par défaut)
                        route_buffer = routing_service.get_route_buffer(route_data['geometry'], 2000)
                        
                        total_km = route_data['total_distance'] / 1000
                        total_min = route_data['total_duration'] / 60
                        print(f"✅ Itinéraire OSRM: {total_km:.1f}km, {total_min:.0f}min")
                        
                        # Exclure segment_annotations du payload frontend (trop volumineux)
                        frontend_route_data = {k: v for k, v in route_data.items() if k != 'segment_annotations'}
                        
                        map_updates.append({
                            'type': 'route',
                            'start': entities['depart'],
                            'end': entities['fin'],
                            'route_data': frontend_route_data,
                            'route_buffer': route_buffer
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
        chat_state.log_event('bot_message', {'message': final_message})
        
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
                
                # ✅ AJOUT DU BUFFER ICI AUSSI
                route_buffer = routing_service.get_route_buffer(route_data['geometry'], 2000)
                
                # Exclure segment_annotations du payload frontend
                frontend_route_data = {k: v for k, v in route_data.items() if k != 'segment_annotations'}
                
                map_updates.append({
                    'type': 'route',
                    'start': chat_state.context['start'],
                    'end': chat_state.context['end'],
                    'route_data': frontend_route_data,
                    'route_buffer': route_buffer
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
        
        position, distance_meters, progress_ratio, pos_updates, range_result = await calculate_position_from_duration(
            duration_minutes, real_speed_kmh, route_data
        )
        map_updates.extend(pos_updates)
        
        if position:
            progress_pct = min(progress_ratio * 100, 100)  # Cap l'affichage à 100%
            total_km = route_data['total_distance'] / 1000
            
            if range_result:
                d_min_km = range_result['d_min'] / 1000
                d_max_km = range_result['d_max'] / 1000
                
                if range_result['d_min'] >= route_data['total_distance']:
                    # D_min ET D_max dépassent la destination → l'appelant est AU-DELÀ
                    next_message = (
                        f"🏁 D'après mes calculs, avec {chat_state.context.get('duration')} min de trajet, "
                        f"vous devriez avoir **dépassé votre destination** ({total_km:.0f} km).\n\n"
                        f"📍 Vous êtes probablement dans un rayon de **{range_result['radius']/1000:.1f} km** "
                        f"autour de la zone d'arrivée.\n\n"
                    )
                elif range_result['d_max'] > route_data['total_distance']:
                    # D_max dépasse mais pas D_min → l'appelant est proche/au-delà de la destination
                    next_message = (
                        f"📍 D'après mes calculs, vous devriez être entre le **km {d_min_km:.0f}** "
                        f"et **au-delà de la destination** (trajet total: {total_km:.0f} km).\n\n"
                        f"⚠️ Vous avez possiblement dépassé le point d'arrivée.\n\n"
                    )
                else:
                    next_message = f"📍 D'après mes calculs, vous devriez être entre le **km {d_min_km:.0f}** et le **km {d_max_km:.0f}** du trajet (progression: ~{progress_pct:.0f}%).\n\n"
            else:
                if progress_ratio >= 1.0:
                    next_message = "🏁 D'après mes calculs, vous devriez être arrivé(e) à destination. Êtes-vous bien arrivé(e) ou avez-vous rencontré un problème en chemin ?\n\n"
                else:
                    next_message = f"📍 D'après mes calculs, vous devriez être dans cette zone (progression: {progress_pct:.0f}%).\n\n"
                
            # Suggérer des POI (sur tout l'arc si range_result disponible)
            poi_message, poi_updates = await suggest_nearby_pois(
                position, distance_meters, route_data, range_result
            )
            next_message += poi_message
            map_updates.extend(poi_updates)
        else:
            next_message = "Je n'arrive pas à calculer votre position précise. Pouvez-vous me donner plus de détails ?"
    
    elif chat_state.context.get('distance'):
        distance_km = chat_state.context['distance']
        position, distance_meters, progress_ratio, pos_updates = await calculate_position_from_distance(
            distance_km, real_speed_kmh, route_data
        )
        map_updates.extend(pos_updates)
        
        if position:
            progress_pct = progress_ratio * 100
            next_message = f"✅ Position trouvée avec {int(CONFIDENCE_HIGH*100)}% de confiance ! (progression: {progress_pct:.1f}%)"
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
# ENDPOINT: Rapport de session
# ============================================================

@router.get("/api/report")
async def generate_report():
    """Génère et télécharge le rapport de session au format HTML"""
    try:
        html = chat_state.generate_report()
        return Response(
            content=html,
            media_type='text/html'
        )
    except Exception as e:
        print(f"❌ Erreur génération rapport: {e}")
        return Response(content=f"Erreur: {e}", status_code=500)


# ============================================================
# ENDPOINT: Reset
# ============================================================

@router.post("/reset")
async def reset():
    """Réinitialiser la conversation"""
    try:
        reset_chat_state()
        return {
            "message": "Bonjour ! Je suis **Finder Bot**. Pour vous localiser, dites-moi d'où vous partez et où vous allez. Par exemple : 'De Paris à Lyon'",
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


# ============================================================
# ENDPOINTS SYNCHRONISATION FORMULAIRE
# ============================================================

@router.get("/api/state", response_model=StateResponse)
async def get_state():
    """Récupère l'état actuel pour synchroniser le formulaire"""
    ctx = chat_state.context
    pos = None
    if chat_state.coordinates:
        pos = {"lat": chat_state.coordinates[0], "lon": chat_state.coordinates[1]}

    return StateResponse(
        start=ctx.get('start'),
        end=ctx.get('end'),
        transport=ctx.get('transport'),
        duration=ctx.get('duration'),
        confidence=chat_state.confidence,
        position_estimee=pos
    )


@router.post("/api/update_context", response_model=ChatResponse)
async def update_context(update: ContextUpdate):
    """Mise à jour manuelle via le formulaire ou zone de dessin"""
    try:
        print(f"\n📝 MISE À JOUR CONTEXTE: {update}")

        # Gérer le dessin manuel en priorité
        if update.type == 'manual_zone_update':
            chat_state.context['manual_zone'] = {
                'lat': update.lat,
                'lon': update.lon,
                'radius': update.radius
            }
            print(f"📍 Zone manuelle enregistrée: {chat_state.context['manual_zone']}")
            return ChatResponse(message="Zone manuelle enregistrée", step=update.step)
            
        if update.type == 'manual_zone_delete':
            chat_state.context['manual_zone'] = None
            print("🗑️ Zone manuelle supprimée")
            return ChatResponse(message="Zone manuelle supprimée", step=update.step)

        map_updates = []
        changes = []

        # Détecter les changements pour le message de confirmation
        if update.start != chat_state.context.get('start'):
            chat_state.context['start'] = update.start
            changes.append(f"départ: {update.start}")

        if update.end != chat_state.context.get('end'):
            chat_state.context['end'] = update.end
            changes.append(f"arrivée: {update.end}")

        if update.transport != chat_state.context.get('transport'):
            chat_state.set_transport(update.transport)
            changes.append(f"transport: {update.transport}")
            map_updates.append({'type': 'transport', 'transport': update.transport})

        if update.duration != chat_state.context.get('duration'):
            chat_state.set_duration(update.duration)
            changes.append(f"durée: {update.duration}min")

        # Recalculer l'itinéraire si besoin
        if chat_state.has_trajet():
            # Forcer le recalcul si trajet ou transport a changé
            await _recalculate_route(map_updates)

        # Calculer la position
        next_message = ""
        if chat_state.has_trajet() and chat_state.has_route_data():
            # On simule des entités vides car on a déjà mis à jour le state
            next_message, pos_map_updates = await _calculate_and_suggest_position(update.step, {})
            map_updates.extend(pos_map_updates)
        else:
            next_message = _get_missing_info_question()

        # Message de confirmation
        if changes:
            confirm_msg = f"🔄 **Informations mises à jour via le formulaire :** {', '.join(changes)}.\n\n"
            chat_state.log_event('form_update', {'fields': {
                'départ': update.start, 'arrivée': update.end,
                'transport': update.transport, 'durée': f'{update.duration}min' if update.duration else None
            }})
        else:
            confirm_msg = "🔄 **Formulaire appliqué (aucune modification détectée).**\n\n"

        return ChatResponse(
            message=confirm_msg + next_message,
            step=update.step + 1,
            entities=None,
            map_updates=map_updates if map_updates else None
        )

    except Exception as e:
        print(f"❌ Erreur update_context: {e}")
        traceback.print_exc()
        return ChatResponse(
            message="Une erreur s'est produite lors de la mise à jour du formulaire.",
            step=update.step,
            entities=None,
            map_updates=None
        )