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
        # Autorise espaces et tirets dans les noms de ville
        city_pattern = r'(?:de|depuis)\s+([A-Za-zÀ-ÿ\-]+(?: [A-Za-zÀ-ÿ\-]+)*)\s+(?:à|vers|pour)\s+([A-Za-zÀ-ÿ\-]+(?: [A-Za-zÀ-ÿ\-]+)*)'
        city_match = re.search(city_pattern, text, re.IGNORECASE)
        if city_match:
            manual_depart = city_match.group(1).strip().title()
            manual_fin = city_match.group(2).strip().title()
            print(f"  🏙️ Regex détecté: {manual_depart} → {manual_fin}")
        else:
            # Pattern alternatif sans préposition
            city_pattern2 = r'^([A-Za-zÀ-ÿ\-]+(?: [A-Za-zÀ-ÿ\-]+)*)\s+(?:vers|à|pour)\s+([A-Za-zÀ-ÿ\-]+(?: [A-Za-zÀ-ÿ\-]+)*)'
            city_match2 = re.search(city_pattern2, text, re.IGNORECASE)
            if city_match2:
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
                'reperes': []
            }
        
        # Extraction LLM
        extraction_prompt = f"""Extrais les entités de ce message de détresse.

MESSAGE: "{text}"

Format JSON:
{{
  "depart": null, "fin": null, "transport": null, "duree": null,
  "distance": null, "lieux": [], "routes": [], "reperes": []
}}

RÈGLES CRITIQUES:
1. "reperes": Extrais TOUS les noms propres ou enseignes (ex: garage, McDo, Super U).
2. "routes": UNIQUEMENT si un numéro de route est ÉCRIT dans le message.
3. Si une info est absente, utilise null ou [].
4. TRANSPORTS: voiture, bus, pied, moto, velo.
5. Chaque champ liste doit être un tableau [], pas une chaîne.
6. Si l'utilisateur fait une faute d'orthographe visible sur un nom de lieu ou commerce, corrige-la avant de l'extraire dans "reperes".
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
                'reperes': []
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
            'duree': extracted.get('duree'),
            'distance': extracted.get('distance'),
            'reperes': extracted.get('reperes', []) or []
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
        
        Args:
            user_message: Message de l'utilisateur
            state_dict: État complet de la conversation (ChatState.to_dict())
        
        Returns:
            {
                "action": "continue|finish|clarify|recalage|confirm_choice",
                "response": "Message à afficher à l'utilisateur",
                "extract_entities": bool,
                "poi_index": int (si action=confirm_choice),
                "reason": "Explication de la décision"
            }
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
        }
        
        # Nombre de POI dans la liste actuelle
        nb_poi_liste = len(context_summary.get("liste_poi_actuelle", []))
        
        prompt = f"""Tu es un assistant de localisation pour personnes perdues. Tu dois décider la prochaine action.

ÉTAT CONVERSATION:
- Trajet défini: {context_summary['trajet_defini']} ({context_summary['depart']} → {context_summary['arrivee']})
- Position trouvée: {context_summary['position_trouvee']} (confiance: {context_summary['confiance']:.0%})
- Recalage effectué: {context_summary['recalage_fait']}
- En attente de choix POI: {context_summary['attente_choix_poi']} ({nb_poi_liste} POI proposés)
- En attente de description: {context_summary['attente_description']}

MESSAGE UTILISATEUR: "{user_message}"

ACTIONS POSSIBLES:
- "finish": L'utilisateur termine (merci, ok, c'est bon, au revoir, parfait) → répondre poliment
- "recalage": L'utilisateur décrit un lieu/commerce/panneau → chercher pour recaler position
- "confirm_choice": L'utilisateur répond par un numéro (1-{nb_poi_liste}) ou nom de POI → sélectionner ce POI
- "clarify": L'utilisateur pose une question ou est confus → expliquer
- "continue": L'utilisateur donne des infos utiles (durée, trajet) → continuer extraction normale
- "reject_pois": L'utilisateur dit "aucun", "rien", "pas ceux-là" → demander description libre
- "show_all_pois": L'utilisateur demande à voir tous les POI/points, la carte, ou la zone → afficher tous les POI sur la carte

Réponds UNIQUEMENT en JSON valide:
{{
    "action": "finish|recalage|confirm_choice|clarify|continue|reject_pois|show_all_pois",
    "response": "Message naturel à afficher",
    "extract_entities": true ou false,
    "poi_index": null ou numéro 1-{nb_poi_liste},
    "reason": "Explication courte"
}}
"""

        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "system": "Tu es un agent décisionnel. Réponds uniquement en JSON valide."
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