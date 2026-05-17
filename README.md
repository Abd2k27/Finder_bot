# Finder_bot


  Contrairement à un RAG classique qui interroge une base de données vectorielle de documents, ce projet utilise une approche hybride pour
  la géolocalisation :

  1. Retrieval (Récupération)
  Au lieu d'utiliser des "embeddings" et une base vectorielle, le système récupère des données géospatiales structurées :
   * Base de connaissances : Une base SQLite locale (data/pois_local.db) contenant des Points d'Intérêt (POI) issus d'OpenStreetMap.
   * Moteurs de recherche : Le code (services/geocoding.py) effectue des recherches spatiales (autour d'un point ou le long d'un
     itinéraire) combinées à une recherche textuelle floue (fuzzy matching via difflib) pour retrouver des repères cités par l'appelant.

  2. Augmentation (Ancrage)
  Le LLM n'est pas utilisé pour "connaître" la carte (ce qui éviterait les hallucinations géographiques), mais pour extraire les intentions
  :
   * Extraction Sémantique : models/llm_extractor.py utilise GPT via Ollama pour extraire les repères visuels ("Je vois un garage"), les durées et
     les directions depuis le texte brut.
   * Ancrage Spatial : Ces entités extraites servent de filtres pour interroger la base OSM. Le résultat de cette recherche (les
     coordonnées réelles des POI) "augmente" le contexte du système pour recalculer la position probable.

  3. Raisonnement Agentique
  Le système utilise également le LLM comme un agent décisionnel (decide_action) qui, en fonction des POI récupérés et de l'état de la
  conversation, choisit la prochaine étape (recalage, confirmation, demande de précision).

  C'est ce que tes documents de recherche (memoire/draft_memoire_fr.txt) appellent le "Raisonnement Spatial Assisté par la Génération",
  validant l'utilisation du LLM comme extracteur et du moteur spatial comme source de vérité déterministe.