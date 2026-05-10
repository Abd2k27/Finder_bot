"""
Extracteur d'entités LLM asynchrone.

Utilise Ollama (local ou cloud) pour extraire des informations structurées
des messages utilisateur (trajet, transport, durée, repères).
"""

import asyncio
import json
import re
import httpx
from typing import Dict, List, Optional, Any

from config.settings import OLLAMA_MODEL, OLLAMA_URL, OLLAMA_TIMEOUT, OLLAMA_API_KEY


class LLMExtractor:
    """Extracteur d'entités utilisant un LLM (Ollama) - async"""
    
    def __init__(self):
        print(f"🤖 Initialisation LLM avec {OLLAMA_MODEL}...")
        self.model = OLLAMA_MODEL
        self.url = OLLAMA_URL
        self.timeout = OLLAMA_TIMEOUT
        self.api_key = OLLAMA_API_KEY
        print(f"✅ LLM {OLLAMA_MODEL} configuré (async)")
    
    async def _call_ollama(self, prompt_text: str, use_json: bool = False) -> Optional[Any]:
        """Appelle l'API Ollama de manière asynchrone avec httpx"""
        
        system_prompt = "Tu es un assistant d'extraction d'informations."
        
        if use_json:
            system_prompt = """Tu es un robot d'extraction JSON EXPERT.
RÈGLES:
1. Réponds SEULEMENT avec du JSON valide
2. Si une info n'existe pas: utilise null
3. Ne jamais inventer d'informations
4. Pour les durées, extrait TOUTES les unités (heures ET minutes)"""
        
        payload = {
            "model": self.model,
            "prompt": prompt_text,
            "stream": False,
            "system": system_prompt
        }
        
        if use_json:
            payload["format"] = "json"
        
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(self.url, json=payload, headers=headers)
                response.raise_for_status()
                
                response_data = response.json()
                raw_response = response_data.get('response', '{}' if use_json else '')
                
                if use_json:
                    # Nettoyage markdown
                    if raw_response.startswith("```json"):
                        raw_response = raw_response[7:].strip()
                    if raw_response.endswith("```"):
                        raw_response = raw_response[:-3].strip()
                    
                    # ROBUSTESSE: Extraire uniquement le bloc JSON même si texte superflu
                    json_match = re.search(r'\{.*\}', raw_response, re.DOTALL)
                    if json_match:
                        raw_response = json_match.group()
                    
                    return json.loads(raw_response)
                else:
                    return raw_response.strip()
                    
        except httpx.TimeoutException:
            print(f"⏱️  Timeout Ollama")
            return None
        except httpx.RequestError as e:
            print(f"❌ Erreur réseau Ollama: {e}")
            return None
        except json.JSONDecodeError as e:
            print(f"❌ JSON invalide: {e}")
            print(f"Réponse: {raw_response[:200] if 'raw_response' in dir() else 'N/A'}")
            return None
    
    def _extract_duration_manually(self, text: str) -> Optional[int]:
        """
        Extraction robuste de durée par regex.
        Gère: "2h", "2 h", "2heures", "2h30", "2h 30", "1h 41", "1h41min", etc.
        """
        text_lower = text.lower()
        
        # Pattern combiné: "1h30", "1h 30", "1 h 30", "1h 41", etc.
        pattern_combined = r'(\d+)\s*(?:h|heure|heures)\s*(\d+)(?:\s*(?:min|minute|minutes))?'
        match_combined = re.search(pattern_combined, text_lower)
        
        if match_combined:
            hours = int(match_combined.group(1))
            minutes = int(match_combined.group(2))
            total_minutes = hours * 60 + minutes
            print(f"  🕐 Regex détecté: {hours}h {minutes}min")
            print(f"  ✅ Durée extraite par regex: {total_minutes} minutes")
            return total_minutes
        
        # Pattern heures seules (pas suivi d'un chiffre)
        pattern_hours = r'(\d+)\s*(?:h|heure|heures)(?!\s*\d)'
        match_hours = re.search(pattern_hours, text_lower)
        
        # Pattern minutes seules (pas précédé d'heures)
        pattern_minutes = r'(?<!h\s)(?<!heure\s)(?<!heures\s)(\d+)\s*(?:min|minute|minutes)'
        match_minutes = re.search(pattern_minutes, text_lower)
        
        total_minutes = 0
        
        if match_hours:
            hours = int(match_hours.group(1))
            total_minutes += hours * 60
            print(f"  🕐 Regex détecté: {hours}h")
        
        if match_minutes:
            minutes = int(match_minutes.group(1))
            total_minutes += minutes
            print(f"  🕐 Regex détecté: {minutes}min")
        
        if total_minutes > 0:
            print(f"  ✅ Durée extraite par regex: {total_minutes} minutes")
            return total_minutes
        
        return None
    
    async def extract_entities(self, text: str, conversation_context: Dict = None) -> Dict[str, Any]:
        """Extrait les entités du texte utilisateur (async)"""
        
        print(f"\n{'='*60}")
        print(f"🔎 Extraction d'entités pour: '{text}'")
        print(f"{'='*60}")
        
        # Contexte existant
        existing_transport = None
        existing_start = None
        existing_end = None
        if conversation_context and 'current_context' in conversation_context:
            existing_transport = conversation_context['current_context'].get('transport')
            existing_start = conversation_context['current_context'].get('start')
            existing_end = conversation_context['current_context'].get('end')
            if existing_transport:
                print(f"📋 Transport déjà en contexte: {existing_transport}")
            if existing_start:
                print(f"📋 Départ déjà en contexte: {existing_start}")
            if existing_end:
                print(f"📋 Arrivée déjà en contexte: {existing_end}")
        
        # Extraction manuelle de durée
        manual_duration = self._extract_duration_manually(text)
        
        # Extraction manuelle des villes avec support noms composés
        manual_depart = None
        manual_fin = None
        
        # Pattern amélioré: supporte "Aix en Provence", "Saint-Étienne", etc.
        # On exige un 'De' ou 'Depuis' clair au début pour éviter de confondre avec une description
        city_pattern = r'^(?:je pars de|parti de|depuis|de)\s+([A-Za-zÀ-ÿ\-]+(?: [A-Za-zÀ-ÿ\-]+)*)\s+(?:à|vers|pour|en direction de)\s+([A-Za-zÀ-ÿ\-]+(?: [A-Za-zÀ-ÿ\-]+)*)'
        city_match = re.search(city_pattern, text, re.IGNORECASE)
        if city_match:
            manual_depart = city_match.group(1).strip().title()
            manual_fin = city_match.group(2).strip().title()
            print(f"  🏙️ Regex détecté: {manual_depart} → {manual_fin}")
        else:
            # Pattern alternatif sans préposition — limité à 1-3 mots pour éviter les faux positifs
            city_pattern2 = r'^([A-Za-zÀ-ÿ\-]{2,}(?:\s[A-Za-zÀ-ÿ\-]+){0,2})\s+(?:vers|pour)\s+([A-Za-zÀ-ÿ\-]{2,}(?:\s[A-Za-zÀ-ÿ\-]+){0,2})\s*$'
            city_match2 = re.search(city_pattern2, text, re.IGNORECASE)
            # Mots qui ne sont PAS des villes → rejeter le match
            non_city_words = {'il', 'je', 'un', 'une', 'le', 'la', 'les', 'des', 'du', 'au', 'y', 'a', 'est', 'vois', 'suis'}
            if city_match2:
                dep = city_match2.group(1).strip().lower()
                arr = city_match2.group(2).strip().lower()
                first_word_dep = dep.split()[0] if dep else ''
                if first_word_dep not in non_city_words and len(dep) > 2:
                    manual_depart = city_match2.group(1).strip().title()
                    manual_fin = city_match2.group(2).strip().title()
                    print(f"  🏙️ Regex détecté: {manual_depart} → {manual_fin}")
        
        # Bypass LLM pour messages courts
        if len(text.strip()) < 5:
            print(f"⚡ Message court ({len(text.strip())} chars) → bypass LLM")
            return {
                'lieux': [],
                'routes': [],
                'distances': [],
                'directions': [],
                'depart': None,
                'fin': None,
                'transport': existing_transport,
                'duree': manual_duration,
                'distance': None,
                'reperes': [],
                'reperes_depasses': []
            }
        
        # Extraction LLM
        extraction_prompt = f"""Extrais les entités de ce message de détresse.

MESSAGE: "{text}"

Format JSON:
{{
  "depart": null, "fin": null, "transport": null, "duree": null,
  "distance": null, "lieux": [], "routes": [], "reperes": [], "reperes_depasses": []
}}

RÈGLES CRITIQUES:
1. "reperes": Extrais TOUS les points de repère que l'appelant voit actuellement (ex: "Je vois un garage").
2. "reperes_depasses": Extrais TOUS les repères que l'appelant dit avoir DÉJÀ DÉPASSÉ (ex: "J'ai passé un pont", "je viens de dépasser l'arrêt de bus"). S'il dit "J'ai passé X", mets "X" dans cette liste, pas dans "reperes".
3. "routes": UNIQUEMENT si un numéro de route est ÉCRIT dans le message (ex: "N12", "D906").
4. Si une info est absente, utilise null ou [].
5. TRANSPORTS: voiture, bus, pied, moto, velo.
6. Chaque champ liste doit être un tableau [], pas une chaîne.
7. Corrige les fautes d'orthographe visibles avant d'extraire.
"""
        
        extracted = await self._call_ollama(extraction_prompt, use_json=True)
        
        if not extracted:
            print("⚠️  LLM échoué, utilisation résultats manuels uniquement")
            return {
                'lieux': [],
                'routes': [],
                'distances': [],
                'directions': [],
                'depart': manual_depart,
                'fin': manual_fin,
                'transport': existing_transport,
                'duree': manual_duration,
                'distance': None,
                'reperes': [],
                'reperes_depasses': []
            }
        
        # Normalisation
        result = {
            'lieux': extracted.get('lieux', []) or [],
            'routes': extracted.get('routes', []) or [],
            'distances': [extracted.get('distance')] if extracted.get('distance') else [],
            'directions': extracted.get('directions', []) or [],
            'depart': extracted.get('depart'),
            'fin': extracted.get('fin'),
            'transport': extracted.get('transport'),
            'duree': extracted.get('duree') or manual_duration,
            'distance': extracted.get('distance'),
            'reperes': extracted.get('reperes', []) or [],
            'reperes_depasses': extracted.get('reperes_depasses', []) or []
        }
        
        # Sécurisation: convertir strings en listes
        list_fields = ['lieux', 'routes', 'directions', 'reperes', 'distances']
        for field in list_fields:
            if field in result:
                if isinstance(result[field], str):
                    result[field] = [result[field]] if result[field] else []
                    print(f"  ⚠️  {field} était une chaîne → converti en liste")
                elif not isinstance(result[field], list):
                    result[field] = []
                    print(f"  ⚠️  {field} type invalide → remplacé par []")
        
        # Garder transport du contexte si LLM n'en extrait pas
        if not result['transport'] and existing_transport:
            print(f"  ✅ Transport non extrait → garde contexte: {existing_transport}")
            result['transport'] = existing_transport
        
        # Convertir durée LLM en int
        if result['duree'] is not None and isinstance(result['duree'], str):
            try:
                result['duree'] = int(result['duree'])
            except ValueError:
                print(f"  ⚠️  Durée LLM non parsable: '{result['duree']}' → None")
                result['duree'] = None
        
        # Regex a priorité sur LLM pour la durée
        if manual_duration is not None:
            if result['duree'] is not None and result['duree'] != manual_duration:
                print(f"  ⚠️  LLM ({result['duree']}min) vs Regex ({manual_duration}min) → priorité Regex")
            result['duree'] = manual_duration
            print(f"  ✅ Durée finale (regex): {manual_duration}min")
        elif result['duree'] is not None:
            print(f"  ✅ Durée finale (LLM): {result['duree']}min")
        
        # Nettoyer "null" string
        for key in ['depart', 'fin', 'transport', 'duree', 'distance']:
            if result[key] == 'null' or result[key] == '':
                result[key] = None
        
        # Valider transport
        valid_transports = ['voiture', 'bus', 'pied', 'moto', 'velo']
        if result['transport'] and result['transport'] not in valid_transports:
            print(f"  ⚠️  Transport '{result['transport']}' non valide → garde contexte")
            result['transport'] = existing_transport
        
        # Détecter hallucinations
        hallucination_patterns = [
            'ville_depart', 'ville_arrivee', 'ville_fin', 'nom_ville',
            'depart_ville', 'arrivee_ville', 'ville ou lieu', 'undefined'
        ]
        for key in ['depart', 'fin']:
            if result[key] and isinstance(result[key], str):
                result_lower = result[key].lower()
                if any(pattern.lower() in result_lower for pattern in hallucination_patterns):
                    print(f"  ⚠️  Hallucination détectée: {key}='{result[key]}' → None")
                    result[key] = None
        
        # Fallback regex pour villes
        if not result['depart'] and manual_depart:
            print(f"  ✅ LLM échoué → utilise regex départ: {manual_depart}")
            result['depart'] = manual_depart
        if not result['fin'] and manual_fin:
            print(f"  ✅ LLM échoué → utilise regex arrivée: {manual_fin}")
            result['fin'] = manual_fin
        
        # Préservation du contexte existant
        if not result['depart'] and existing_start:
            print(f"  ✅ Départ non extrait → garde contexte: {existing_start}")
        if not result['fin'] and existing_end:
            print(f"  ✅ Arrivée non extraite → garde contexte: {existing_end}")
        
        print(f"✅ Résultat final:")
        print(f"   - Départ: {result.get('depart')}")
        print(f"   - Fin: {result.get('fin')}")
        print(f"   - Transport: {result.get('transport')}")
        print(f"   - Durée: {result.get('duree')} min")
        print(f"   - Distance: {result.get('distance')} km")
        print(f"{'='*60}\n")
        
        return result
    
    async def generate_followup_question(self, missing_fields: List[str], context: Dict) -> str:
        """Génère une question de suivi"""
        
        if not missing_fields:
            return "Pouvez-vous me donner plus de détails ?"
        
        field_questions = {
            'start': "D'où êtes-vous parti(e) ?",
            'end': "Quelle est votre destination ?",
            'transport': "Comment vous déplacez-vous ?",
            'duration': "Depuis combien de temps êtes-vous en route ?",
            'distance': "Quelle distance avez-vous parcourue ?"
        }
        
        field = missing_fields[0]
        return field_questions.get(field, "Précisez votre situation ?")
    
    async def decide_action(self, user_message: str, state_dict: Dict) -> Dict:
        """
        Prompting Agentique: Le LLM décide de la prochaine action conversationnelle.
        """
        import json
        import re
        
        print(f"\n{'='*60}")
        print(f"🤖 DÉCISION AGENTIQUE pour: '{user_message}'")
        print(f"{'='*60}")
        
        # Contexte simplifié pour le prompt
        context_summary = {
            "trajet_defini": state_dict.get("has_trajet", False),
            "position_trouvee": state_dict.get("has_position", False),
            "confiance": state_dict.get("confidence", 0),
            "recalage_fait": state_dict.get("context", {}).get("recalage_done", False),
            "attente_choix_poi": state_dict.get("context", {}).get("awaiting_poi_selection", False),
            "attente_description": state_dict.get("context", {}).get("awaiting_description", False),
            "liste_poi_actuelle": state_dict.get("context", {}).get("current_poi_list", []),
            "transport": state_dict.get("context", {}).get("transport"),
            "depart": state_dict.get("context", {}).get("start"),
            "arrivee": state_dict.get("context", {}).get("end"),
            "historique_disponible": state_dict.get("history_size", 0) > 1
        }
        
        # Nombre de POI dans la liste actuelle
        nb_poi_liste = len(context_summary.get("liste_poi_actuelle", []))
        
        prompt = f"""Tu es un assistant de localisation. Tu dois décider la prochaine action.

ÉTAT CONVERSATION:
- Trajet: {context_summary['depart']} → {context_summary['arrivee']}
- En attente de choix parmi {nb_poi_liste} POI: {context_summary['attente_choix_poi']}
- Historique de recherche disponible: {context_summary['historique_disponible']}

MESSAGE UTILISATEUR: "{user_message}"

RÈGLES DE DÉCISION:
1. "ignore_previous_candidates": true si l'utilisateur rejette les points proposés (ex: "aucun", "pas ça", "rien") même s'il donne un nouvel indice après.
2. "target_keyword": Si l'utilisateur veut revenir à une étape précise, extrais le nom du lieu demandé (ex: "Carrefour", "cabinet", "boulangerie").
3. "action": 
   - "finish": remerciements ou fin.
   - "show_previous_list": l'utilisateur veut revenir en arrière ou réafficher une recherche passée (ex: "reviens aux Carrefour").
   - "show_all_pois": demande d'affichage global/cercle.
   - "confirm_choice": choix d'un numéro ou nom de la liste.
   - "recalage": description d'un lieu précis.
   - "reject_pois": refus simple.
   - "continue": infos de trajet/temps.

Réponds UNIQUEMENT en JSON:
{{
    "action": "finish|recalage|confirm_choice|clarify|continue|reject_pois|show_all_pois|show_previous_list",
    "ignore_previous_candidates": boolean,
    "target_keyword": "nom du lieu à retrouver ou null",
    "response": "Message court",
    "extract_entities": true ou false,
    "poi_index": numéro ou null,
    "reason": "Explication"
}}
"""

        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "system": "Tu es un agent décisionnel strict. Tu comprends les intentions derrière les fautes de frappe."
        }
        
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(self.url, json=payload, headers=headers)
                response.raise_for_status()
                
                result = response.json()
                raw_response = result.get('response', '{}')
                
                # Parser le JSON
                json_match = re.search(r'\{.*\}', raw_response, re.DOTALL)
                if json_match:
                    decision = json.loads(json_match.group())
                    
                    # Normalisation
                    decision.setdefault("action", "continue")
                    decision.setdefault("response", "Pouvez-vous préciser ?")
                    decision.setdefault("extract_entities", False)
                    decision.setdefault("poi_index", None)
                    decision.setdefault("reason", "")
                    
                    # Convertir poi_index en int si string
                    if decision["poi_index"] is not None:
                        try:
                            decision["poi_index"] = int(decision["poi_index"])
                        except (ValueError, TypeError):
                            decision["poi_index"] = None
                    
                    print(f"✅ DÉCISION: {decision['action']}")
                    print(f"   Réponse: {decision['response'][:80]}...")
                    print(f"   Raison: {decision['reason']}")
                    print(f"   extract_entities: {decision['extract_entities']}")
                    if decision['poi_index']:
                        print(f"   poi_index: {decision['poi_index']}")
                    
                    return decision
                else:
                    print(f"❌ JSON invalide: {raw_response[:200]}")
                    
        except httpx.TimeoutException:
            print(f"⏱️  Timeout décision agentique")
        except Exception as e:
            print(f"❌ Erreur décision agentique: {e}")
        
        # Fallback: continuer le flow normal
        return {
            "action": "continue",
            "response": None,
            "extract_entities": True,
            "poi_index": None,
            "reason": "Fallback - erreur LLM"
        }