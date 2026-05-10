#!/usr/bin/env python3
"""
Evaluateur de Scénarios pour Finder Bot.
Simule des interactions ARM/Appelant pour valider la précision du système.
"""

import asyncio
import httpx
import json
import math
from typing import Dict, List

API_URL = "http://localhost:8000"

SCENARIOS = [
    # --- ZONE URBAINE (5) ---
    {
        "id": "SCN-URB-01", "name": "Urbain (Paris -> Versailles)", "start": "Paris", "end": "Versailles", "transport": "voiture", "duration": 15,
        "clues": ["Aucun", "Je vois le Pressing du Parc Heller", "Il y a la Ferme d'Antony pas loin", "Je suis devant Emilia Retouche", "Je suis à côté de la Pharmacie des Sources"],
        "truth": {"lat": 48.75126, "lon": 2.29007}
    },
    {
        "id": "SCN-URB-02", "name": "Urbain (Bagneux -> Antony)", "start": "Bagneux, Hauts-de-Seine", "end": "Antony, Hauts-de-Seine", "transport": "voiture", "duration": 8,
        "clues": ["Aucun", "Je vois le Marché Carnot", "Il y a la Rotisserie à 2 Patt'ates", "Je suis près du restaurant The One"],
        "truth": {"lat": 48.80075, "lon": 2.32392}
    },
    {
        "id": "SCN-URB-03", "name": "Urbain (Ivry -> Vitry)", "start": "Ivry-sur-Seine, Val-de-Marne", "end": "Vitry-sur-Seine, Val-de-Marne", "transport": "velo", "duration": 12,
        "clues": ["Aucun", "Je vois l'École primaire Marcel Cachin", "Je vois le bar La Kunda", "Je vois un distributeur CIC", "Je suis devant le Carrefour Market"],
        "truth": {"lat": 48.80137, "lon": 2.37967}
    },
    {
        "id": "SCN-URB-04", "name": "Urbain (Montrouge -> Cachan)", "start": "Montrouge, Hauts-de-Seine", "end": "Cachan, Val-de-Marne", "transport": "voiture", "duration": 10,
        "clues": ["Aucun", "Je vois l'atelier du brushing", "Il y a le Parking Léo Ferré", "Je vois le Centre Municipal de Santé Louis Pasteur", "C'est le Stade René-Rousseau"],
        "truth": {"lat": 48.80142, "lon": 2.31566}
    },
    {
        "id": "SCN-URB-05", "name": "Urbain (Boulogne -> Meudon)", "start": "Boulogne-Billancourt, Hauts-de-Seine", "end": "Meudon, Hauts-de-Seine", "transport": "voiture", "duration": 14,
        "clues": ["Aucun", "Je vois l'Allée Sainte Lucie", "Je vois le Restaurant Club Municipal Sainte-Lucie", "Je suis sur le Quai de Stalingrad"],
        "truth": {"lat": 48.825, "lon": 2.245}
    },

    # --- ZONE PÉRI-URBAINE (5) ---
    {
        "id": "SCN-PER-01", "name": "Péri-urbain (Nantes -> Angers)", "start": "Nantes", "end": "Angers", "transport": "voiture", "duration": 25,
        "clues": ["Aucun", "Je vois le Dolmen de la Pierre Couvretière", "Je vois le magasin Trésor du Maroc", "Il y a la Clinique Arcadia à côté"],
        "truth": {"lat": 47.373, "lon": -1.176}
    },
    {
        "id": "SCN-PER-02", "name": "Péri-urbain (Chartres -> Le Mans)", "start": "Chartres", "end": "Le Mans", "transport": "voiture", "duration": 35,
        "clues": ["Aucun", "Je vois un pylône électrique", "Je suis à une aire de repos"],
        "truth": {"lat": 48.245, "lon": 0.732}
    },
    {
        "id": "SCN-PER-03", "name": "Péri-urbain (Tours -> Tours)", "start": "Tours", "end": "Poitiers", "transport": "voiture", "duration": 40,
        "clues": ["Aucun", "Je vois La Boucaire", "Je vois La Plonnière", "C'est le Château de Ports"],
        "truth": {"lat": 47.012, "lon": 0.548}
    },
    {
        "id": "SCN-PER-04", "name": "Péri-urbain (Evry -> Fontainebleau)", "start": "Évry", "end": "Fontainebleau", "transport": "moto", "duration": 20,
        "clues": ["Aucun", "Je passe sous un pont"],
        "truth": {"lat": 48.452, "lon": 2.589}
    },
    {
        "id": "SCN-PER-05", "name": "Péri-urbain (Lyon -> Valence)", "start": "Lyon", "end": "Valence", "transport": "voiture", "duration": 45,
        "clues": ["Aucun", "Je vois l'hôtel Mercure", "Il y a un restaurant Courtepaille", "Je suis au Rond-Point de Chanas", "C'est le parking Chanas Auto"],
        "truth": {"lat": 45.321, "lon": 4.812}
    },

    # --- ZONE RURALE (5) ---
    {
        "id": "SCN-RUR-01", "name": "Rural (Guéret -> Limoges)", "start": "Guéret", "end": "Limoges", "transport": "voiture", "duration": 20,
        "clues": ["Aucun", "Je vois le Collège Pierre de Ronsard", "Il y a le Gymnase de la Brégère", "Je suis sur le Pont Alexandra David-Néel"],
        "truth": {"lat": 45.85346, "lon": 1.27626}
    },
    {
        "id": "SCN-RUR-02", "name": "Rural (Aubusson -> Felletin)", "start": "Aubusson, Creuse", "end": "Felletin, Creuse", "transport": "voiture", "duration": 15,
        "clues": ["Aucun", "Je vois Le Truguet", "Je vois un pylône électrique", "Je vois Le Trucq", "Je vois l'église Saint-Gilles"],
        "truth": {"lat": 45.73870, "lon": 2.22290}
    },
    {
        "id": "SCN-RUR-03", "name": "Rural (Ussel -> Egletons)", "start": "Ussel, Corrèze", "end": "Égletons, Corrèze", "transport": "voiture", "duration": 18,
        "clues": ["Aucun", "Je vois Le Moulin de Saleix", "Je vois La Clidane", "Je suis sur le Viaduc de la Clidane"],
        "truth": {"lat": 45.63000, "lon": 2.53179}
    },
    {
        "id": "SCN-RUR-04", "name": "Rural (Limoges -> Solignac)", "start": "Limoges", "end": "Solignac, Haute-Vienne", "transport": "velo", "duration": 30,
        "clues": ["Aucun", "Je vois Les Billanges", "Je vois Les Veyssières", "Je vois le Pont Rompu"],
        "truth": {"lat": 45.75587, "lon": 1.25183}
    },
    {
        "id": "SCN-RUR-05", "name": "Rural (Saint-Yrieix -> Lubersac)", "start": "Saint-Yrieix-la-Perche", "end": "Lubersac, Corrèze", "transport": "voiture", "duration": 12,
        "clues": ["Aucun", "Je vois un pylône électrique", "Je vois le Bief du Moulin", "Je vois La Tour", "Je suis au Pont dit Pont de la Tour sur la Rivière de l'Isle"],
        "truth": {"lat": 45.54098, "lon": 1.13185}
    }
]

def haversine(lat1, lon1, lat2, lon2):
    R = 6371000  # Rayon de la Terre en mètres
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1-a))

async def run_scenario(client, scenario):
    print(f"\n🚀 Exécution : {scenario['name']}")
    
    # 1. Reset
    await client.post(f"{API_URL}/reset")
    
    # 2. Envoi du trajet via formulaire (comme l'ARM)
    ctx_payload = {
        "start": scenario['start'],
        "end": scenario['end'],
        "transport": scenario['transport'],
        "duration": scenario['duration'],
        "step": 1
    }
    r1 = await client.post(f"{API_URL}/api/update_context", json=ctx_payload)
    
    # 3. Échange interactif (Indices séquentiels)
    clues = scenario.get('clues')
    if not clues:
        # Fallback si ancien format
        clues = ["Aucun", scenario.get('landmark_query', '')]
        
    step = 2
    ko_victory = False
    
    for clue in clues:
        print(f"   🗣️ Appelant : {clue}")
        r = await client.post(f"{API_URL}/chat", json={"response": clue, "step": step}, timeout=60.0)
        data = r.json()
        msg_preview = data['message'].replace('\n', ' ')[:80]
        print(f"   🤖 Bot      : {msg_preview}...")
        
        if "Localisation confirmée" in data['message']:
            ko_victory = True
            break # K.O. Victory ! On arrête l'enquête
        step += 1
    
    # 4. Analyse finale
    r_state = await client.get(f"{API_URL}/api/state")
    state = r_state.json()
    
    # Correction: l'API renvoie 'position_estimee' et non 'coordinates'
    pos = state.get('position_estimee') or {}
    final_lat = pos.get('lat', 0.0)
    final_lon = pos.get('lon', 0.0)
    confidence = state.get('confidence', 0)
    
    # Si pos non trouvée, erreur MAX
    if final_lat == 0.0 and final_lon == 0.0:
        error = 999999.0
    else:
        error = haversine(final_lat, final_lon, scenario['truth']['lat'], scenario['truth']['lon'])
    
    return {
        "id": scenario['id'],
        "error": round(error, 1),
        "confidence": confidence,
        "success": error < 1000,
        "ko_victory": ko_victory
    }

async def main():
    results = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        for scn in SCENARIOS:
            try:
                res = await run_scenario(client, scn)
                results.append(res)
            except Exception as e:
                print(f"❌ Erreur sur {scn['id']}: {e}")
    
    # Génération du tableau Markdown
    print("\n\n" + "="*50)
    print("📊 TABLEAU DES RÉSULTATS (POUR LE MÉMOIRE)")
    print("="*50)
    print("| Scénario ID | Environnement | Erreur (m) | Confiance | Succès | K.O. Victory |")
    print("|-------------|---------------|------------|-----------|--------|--------------|")
    for r, scn in zip(results, SCENARIOS):
        env = scn['name'].split(' (')[0]
        succes = "✅" if r['success'] else "❌"
        ko = "🎯 Oui" if r['ko_victory'] else "👤 Manuel"
        print(f"| {r['id']} | {env} | {r['error']}m | {r['confidence']*100:.0f}% | {succes} | {ko} |")

if __name__ == "__main__":
    asyncio.run(main())
