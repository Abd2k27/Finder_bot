import asyncio
import httpx

API_URL = "http://localhost:8000"

async def main():
    async with httpx.AsyncClient(timeout=60.0) as client:
        # Reset
        await client.post(f"{API_URL}/reset")
        
        # Route
        ctx_payload = {
            "start": "Montrouge",
            "end": "Cachan",
            "transport": "voiture",
            "duration": 10,
            "step": 1
        }
        await client.post(f"{API_URL}/api/update_context", json=ctx_payload)
        
        # Clues
        clues = ["Aucun", "Il y a un grand stade", "C'est le Stade René-Rousseau"]
        step = 2
        
        for clue in clues:
            print(f"\n🗣️ APPELANT : {clue}")
            r = await client.post(f"{API_URL}/chat", json={"response": clue, "step": step})
            print(f"🤖 BOT : {r.json()['message']}")
            step += 1

if __name__ == "__main__":
    asyncio.run(main())
