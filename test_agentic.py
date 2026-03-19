#!/usr/bin/env python3
"""
Test du prompting agentique pour le bot de localisation.
Teste si le LLM peut prendre des décisions conversationnelles intelligentes.
"""

import asyncio
import json
import httpx

# Configuration LLM
OLLAMA_URL = "https://ollama.com/api/generate"
OLLAMA_MODEL = "gpt-oss:120b-cloud"
OLLAMA_API_KEY = "a3ca171fcd3243d0b63b54d89927b1e3.5XGiOny1RLsLw1t2jUeFTXr5"
OLLAMA_TIMEOUT = 120

async def test_agentic_decision(user_message: str, state_dict: dict):
    """
    Test: Passer l'état complet au LLM et lui demander de décider la prochaine action.
    """
    
    prompt = f"""Tu es un assistant de localisation pour personnes perdues. Tu dois décider de la prochaine action.

ÉTAT ACTUEL DE LA CONVERSATION:
{json.dumps(state_dict, indent=2, ensure_ascii=False)}

MESSAGE DE L'UTILISATEUR: "{user_message}"

ACTIONS POSSIBLES:
- "continue": L'utilisateur donne des infos utiles → continuer le processus normal (extraction d'entités, affiner position)
- "finish": L'utilisateur termine la conversation (merci, ok, c'est bon, au revoir, etc.) → répondre poliment et clore
- "clarify": L'utilisateur est confus, pose une question, ou dit quelque chose d'incompréhensible → demander clarification
- "recalage": L'utilisateur décrit un lieu visuel → chercher le POI pour recaler sa position

Réponds UNIQUEMENT en JSON valide:
{{
    "action": "continue|finish|clarify|recalage",
    "response": "Message naturel à afficher à l'utilisateur",
    "reason": "Explication courte de ta décision"
}}
"""

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "system": "Tu es un agent décisionnel. Réponds uniquement en JSON valide."
    }
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OLLAMA_API_KEY}"
    }
    
    print(f"\n{'='*60}")
    print(f"🧪 TEST: Message utilisateur = '{user_message}'")
    print(f"{'='*60}")
    
    try:
        async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as client:
            response = await client.post(OLLAMA_URL, json=payload, headers=headers)
            response.raise_for_status()
            
            result = response.json()
            raw_response = result.get('response', '{}')
            
            # Parser le JSON
            import re
            json_match = re.search(r'\{.*\}', raw_response, re.DOTALL)
            if json_match:
                decision = json.loads(json_match.group())
                print(f"✅ DÉCISION LLM:")
                print(f"   Action: {decision.get('action')}")
                print(f"   Réponse: {decision.get('response')}")
                print(f"   Raison: {decision.get('reason')}")
                return decision
            else:
                print(f"❌ Pas de JSON valide dans: {raw_response[:200]}")
                return None
                
    except Exception as e:
        print(f"❌ Erreur: {e}")
        return None


async def main():
    # Simuler un état de conversation après recalage réussi
    state_dict = {
        "responses_count": 3,
        "coordinates": (46.6446, 4.8563),
        "confidence": 0.85,
        "context": {
            "start": "Paris",
            "end": "Lyon",
            "transport": "voiture",
            "duration": 226,
            "recalage_done": True,
            "last_landmarks": ["Chapelle St Martin"]
        },
        "has_trajet": True,
        "has_position": True,
        "is_confident": True
    }
    
    # Tests à effectuer
    test_messages = [
        "Merci",
        "Ok c'est bon",
        "Je vois une pharmacie",
        "Aucun de ces points",
        "Comment ça marche ?",
        "Au revoir",
        "Je suis perdu"
    ]
    
    print("🚀 Tests de prompting agentique\n")
    
    for msg in test_messages:
        await test_agentic_decision(msg, state_dict)
        await asyncio.sleep(1)  # Pause entre les appels
    
    print(f"\n{'='*60}")
    print("✅ Tests terminés!")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
