"""
Service de géocodage asynchrone avec cache local OSMnx et recherche floue.

Utilise:
- Nominatim (via geopy) pour le géocodage de lieux
- OSMnx pour charger les POI locaux en cache
- difflib pour la recherche floue (fuzzy matching)
- Overpass API en fallback avec rotation de miroirs
"""

import asyncio
import math
import httpx
from difflib import get_close_matches
from typing import Optional, Tuple, List, Dict
from geopy.geocoders import Nominatim

from config.settings import (
    NOMINATIM_USER_AGENT,
    NOMINATIM_TIMEOUT,
    GEOCODING_SLEEP,
    OVERPASS_TIMEOUT,
    FRANCE_AREA_ID,
    OVERPASS_MIRRORS,
    OVERPASS_MAX_RETRIES,
    OVERPASS_RETRY_BASE_DELAY,
)


class GeocodingService:
    """Service de géocodage avec cache local OSMnx et fuzzy search"""
    
    def __init__(self):
        self.geolocator = Nominatim(user_agent=NOMINATIM_USER_AGENT)
        self.overpass_mirrors = OVERPASS_MIRRORS.copy()
        self.current_mirror_index = 0
        
        # Cache local pour les POI
        self.poi_cache: List[Dict] = []
        self.cache_center: Optional[Tuple[float, float]] = None
        self.cache_radius: int = 0
        
        # Cache pour le réseau routier (graphe OSMnx)
        self.road_graph = None
        self.road_cache_center: Optional[Tuple[float, float]] = None
        self.road_cache_radius: int = 0
        
        print("✅ Services de géocodage initialisés (OSMnx + fuzzy + roads)")
    
    # ==================== CACHE LOCAL OSMnx ====================
    
    async def fetch_local_pois(self, lat: float, lon: float, radius: int = 2000) -> List[Dict]:
        """
        Charge tous les POI nommés dans un rayon via OSMnx.
        Les résultats sont mis en cache pour éviter les appels répétés.
        
        Args:
            lat: Latitude du centre
            lon: Longitude du centre
            radius: Rayon en mètres (défaut: 2000m)
        
        Returns:
            Liste de POI avec name, type, lat, lon
        """
        # Vérifier si le cache est déjà valide pour cette zone
        if self._is_cache_valid(lat, lon, radius):
            print(f"📦 Cache POI valide ({len(self.poi_cache)} POI)")
            return self.poi_cache
        
        print(f"🌐 Chargement POI OSMnx autour de ({lat:.4f}, {lon:.4f}), rayon {radius}m...")
        
        try:
            # Import OSMnx ici pour éviter le chargement au démarrage
            import osmnx as ox
            
            # Tags pour les features à récupérer
            tags = {
                'amenity': True,  # restaurants, stations, etc.
                'shop': True,     # commerces
                'tourism': True,  # points touristiques
                'historic': True, # sites historiques
                'railway': ['station', 'halt'],  # gares
                'man_made': ['water_tower', 'tower', 'silo'],  # structures
                'leisure': ['stadium'],  # stades
            }
            
            # Récupérer les features via OSMnx (synchrone, exécuté en thread)
            gdf = await asyncio.to_thread(
                ox.features_from_point,
                (lat, lon),
                tags,
                dist=radius
            )
            
            # Convertir en liste de dictionnaires
            pois = []
            
            # Noms génériques/techniques à exclure (pas de vrais repères)
            excluded_names = [
                'vitesse', 'panneau', 'radar', 'signalisation', 
                'rocade', 'bretelle', 'échangeur', 'sortie',
                'stop', 'cédez', 'feu', 'borne'
            ]
            
            for idx, row in gdf.iterrows():
                name = row.get('name')
                if not name or (isinstance(name, float) and math.isnan(name)):
                    continue
                
                name_str = str(name).strip()
                name_lower = name_str.lower()
                
                # Filtrer les noms génériques/techniques
                if any(excl in name_lower for excl in excluded_names):
                    continue
                
                # Récupérer le centroïde de la géométrie
                try:
                    centroid = row.geometry.centroid
                    poi_lat, poi_lon = centroid.y, centroid.x
                except:
                    continue
                
                # Déterminer le type
                poi_type = self._get_osmnx_poi_type(row)
                
                pois.append({
                    'name': name_str,
                    'type': poi_type,
                    'lat': poi_lat,
                    'lon': poi_lon,
                    'name_lower': name_lower  # Pour fuzzy search
                })
            
            # Mettre en cache
            self.poi_cache = pois
            self.cache_center = (lat, lon)
            self.cache_radius = radius
            
            print(f"✅ {len(pois)} POI chargés en cache")
            for poi in pois[:5]:
                print(f"   📍 {poi['name']} ({poi['type']})")
            
            return pois
            
        except ImportError:
            print("⚠️  OSMnx non installé, fallback sur Overpass")
            return await self.get_pois_in_area(lat, lon, radius)
        except Exception as e:
            print(f"❌ Erreur OSMnx: {e}, fallback sur Overpass")
            return await self.get_pois_in_area(lat, lon, radius)
    
    def _is_cache_valid(self, lat: float, lon: float, radius: int) -> bool:
        """Vérifie si le cache actuel couvre la zone demandée"""
        if not self.cache_center or not self.poi_cache:
            return False
        
        # Distance entre le centre demandé et le centre du cache
        distance = self._haversine_distance(
            lat, lon, 
            self.cache_center[0], self.cache_center[1]
        )
        
        # Le cache est valide si on est à moins de 500m du centre
        # ET que le rayon du cache est suffisant
        return distance < 500 and self.cache_radius >= radius
    
    def _get_osmnx_poi_type(self, row) -> str:
        """Détermine le type de POI à partir des attributs OSMnx"""
        amenity = row.get('amenity', '')
        shop = row.get('shop', '')
        tourism = row.get('tourism', '')
        historic = row.get('historic', '')
        railway = row.get('railway', '')
        man_made = row.get('man_made', '')
        leisure = row.get('leisure', '')
        
        if amenity == 'fuel':
            return 'station-service'
        elif amenity == 'restaurant':
            return 'restaurant'
        elif amenity == 'fast_food':
            return 'fast-food'
        elif amenity == 'place_of_worship':
            return 'église'
        elif amenity == 'hospital':
            return 'hôpital'
        elif amenity == 'school':
            return 'école'
        elif amenity == 'townhall':
            return 'mairie'
        elif amenity == 'car_wash':
            return 'station de lavage'
        elif shop == 'supermarket':
            return 'supermarché'
        elif shop == 'car_repair':
            return 'garage'
        elif shop:
            return 'commerce'
        elif tourism == 'viewpoint':
            return 'point de vue'
        elif historic == 'castle':
            return 'château'
        elif railway in ['station', 'halt']:
            return 'gare'
        elif man_made == 'water_tower':
            return "château d'eau"
        elif man_made == 'tower':
            return 'tour/antenne'
        elif man_made == 'silo':
            return 'silo'
        elif leisure == 'stadium':
            return 'stade'
        else:
            return 'repère'
    
    # ==================== RECHERCHE FLOUE ====================
    
    def find_landmarks_fuzzy(self, query: str, cutoff: float = 0.5, max_results: int = 5) -> List[Dict]:
        """
        Recherche intelligente en 3 étapes:
        1. Correspondance exacte (nom complet)
        2. Correspondance substring (nom contient la requête ou inversement)
        3. Recherche floue (seulement si étapes 1-2 échouent)
        """
        if not self.poi_cache:
            return []
        
        query_lower = query.lower().strip()
        results = []
        
        # ==================== ÉTAPE 1: CORRESPONDANCE EXACTE ====================
        exact_matches = [poi for poi in self.poi_cache if poi['name_lower'] == query_lower]
        if exact_matches:
            print(f"✅ Correspondance EXACTE pour '{query}': {[p['name'] for p in exact_matches]}")
            return exact_matches[:max_results]
        
        # ==================== ÉTAPE 2: CORRESPONDANCE SUBSTRING ====================
        # Le nom du POI contient la requête OU la requête contient le nom du POI
        substring_matches = []
        for poi in self.poi_cache:
            poi_name = poi['name_lower']
            # Requête dans le nom du POI (ex: "autosur" dans "garage autosur rennes")
            if query_lower in poi_name:
                substring_matches.append(poi)
            # Nom du POI dans la requête (ex: "autosur" contient "auto")
            elif poi_name in query_lower and len(poi_name) >= 3:
                substring_matches.append(poi)
        
        if substring_matches:
            print(f"✅ Correspondance SUBSTRING pour '{query}': {[p['name'] for p in substring_matches]}")
            return substring_matches[:max_results]
        
        # ==================== ÉTAPE 3: RECHERCHE FLOUE (fallback) ====================
        # Seulement si aucune correspondance exacte/substring trouvée
        # Cutoff plus élevé (0.6) pour éviter les faux positifs
        poi_names = [poi['name_lower'] for poi in self.poi_cache]
        fuzzy_matches = get_close_matches(query_lower, poi_names, n=max_results, cutoff=max(cutoff, 0.6))
        
        for match_name in fuzzy_matches:
            for poi in self.poi_cache:
                if poi['name_lower'] == match_name and poi not in results:
                    results.append(poi)
                    break
        
        if results:
            print(f"🔍 {len(results)} match(s) FUZZY pour '{query}':")
            for r in results:
                print(f"   📍 {r['name']} ({r['type']})")
        else:
            print(f"❌ Aucun match pour '{query}' (exact/substring/fuzzy)")
        
        return results
    
    def get_cached_pois(self) -> List[Dict]:
        """Retourne les POI actuellement en cache"""
        return self.poi_cache
    
    def clear_cache(self):
        """Vide le cache POI"""
        self.poi_cache = []
        self.cache_center = None
        self.cache_radius = 0
        print("🗑️  Cache POI vidé")
    
    # ==================== RÉSEAU ROUTIER OSMnx ====================
    
    async def fetch_road_network(self, lat: float, lon: float, radius: int = 2000) -> bool:
        """
        Charge le réseau routier dans un rayon via OSMnx.
        Les résultats sont mis en cache pour éviter les appels répétés.
        
        Args:
            lat: Latitude du centre
            lon: Longitude du centre
            radius: Rayon en mètres (défaut: 2000m)
        
        Returns:
            True si le graphe a été chargé avec succès
        """
        # Vérifier si le cache est déjà valide pour cette zone
        if self._is_road_cache_valid(lat, lon, radius):
            print(f"📦 Cache réseau routier valide")
            return True
        
        print(f"🛣️  Chargement réseau routier OSMnx autour de ({lat:.4f}, {lon:.4f}), rayon {radius}m...")
        
        try:
            import osmnx as ox
            
            # Télécharger le graphe routier (réseau "drive" pour les routes)
            self.road_graph = await asyncio.to_thread(
                ox.graph_from_point,
                (lat, lon),
                dist=radius,
                network_type='drive'
            )
            
            # Mettre en cache
            self.road_cache_center = (lat, lon)
            self.road_cache_radius = radius
            
            # Stats du graphe
            num_nodes = self.road_graph.number_of_nodes()
            num_edges = self.road_graph.number_of_edges()
            print(f"✅ Réseau routier chargé: {num_nodes} nœuds, {num_edges} segments")
            
            return True
            
        except ImportError:
            print("⚠️  OSMnx non installé, réseau routier indisponible")
            return False
        except Exception as e:
            print(f"❌ Erreur chargement réseau routier: {e}")
            return False
    
    def _is_road_cache_valid(self, lat: float, lon: float, radius: int) -> bool:
        """Vérifie si le cache réseau routier couvre la zone demandée"""
        if self.road_graph is None or self.road_cache_center is None:
            return False
        
        distance = self._haversine_distance(
            lat, lon, 
            self.road_cache_center[0], self.road_cache_center[1]
        )
        
        return distance < 500 and self.road_cache_radius >= radius
    
    async def get_road_info_at_position(self, lat: float, lon: float, radius: int = 2000) -> Optional[Dict]:
        """
        Trouve les informations de la voie la plus proche d'une position.
        
        Args:
            lat: Latitude de la position
            lon: Longitude de la position
            radius: Rayon pour le cache réseau routier
        
        Returns:
            Dict avec: road_name, highway_type, maxspeed, oneway, geometry
            None si aucune voie trouvée
        """
        # S'assurer que le réseau routier est en cache
        if not await self.fetch_road_network(lat, lon, radius):
            return None
        
        try:
            import osmnx as ox
            
            # Trouver l'edge le plus proche
            nearest_edge = ox.distance.nearest_edges(self.road_graph, X=lon, Y=lat)
            
            # Récupérer les données de l'edge
            u, v, key = nearest_edge
            edge_data = self.road_graph.get_edge_data(u, v, key)
            
            if not edge_data:
                print(f"⚠️  Pas de données pour l'edge ({u}, {v})")
                return None
            
            # Extraire les informations
            road_name = edge_data.get('name', 'Voie sans nom')
            if isinstance(road_name, list):
                road_name = road_name[0]  # Parfois c'est une liste
            
            highway_type = edge_data.get('highway', 'unknown')
            if isinstance(highway_type, list):
                highway_type = highway_type[0]
            
            result = {
                'road_name': road_name,
                'highway_type': highway_type,
                'highway_label': self._get_highway_label(highway_type),
                'maxspeed': edge_data.get('maxspeed'),
                'oneway': edge_data.get('oneway', False),
                'ref': edge_data.get('ref'),  # Numéro de route si disponible
                'length': edge_data.get('length', 0)
            }
            
            print(f"🛣️  Voie trouvée: {result['road_name']} ({result['highway_label']})")
            return result
            
        except Exception as e:
            print(f"❌ Erreur recherche voie: {e}")
            return None
    
    async def get_all_roads_in_area(self, lat: float, lon: float, radius: int = 2000) -> List[Dict]:
        """
        Récupère toutes les voies (rues, routes, autoroutes) dans un cercle.
        
        Args:
            lat: Latitude du centre
            lon: Longitude du centre
            radius: Rayon en mètres (défaut: 2000m)
        
        Returns:
            Liste de dictionnaires avec 'name', 'type', 'type_label' pour chaque voie unique
        """
        # S'assurer que le réseau routier est chargé
        if not await self.fetch_road_network(lat, lon, radius):
            print("⚠️  Impossible de charger le réseau routier")
            return []
        
        try:
            roads = {}  # Utiliser un dict pour dédoublonner par nom
            
            # Parcourir tous les edges du graphe
            for u, v, key, data in self.road_graph.edges(keys=True, data=True):
                road_name = data.get('name', '')
                
                # Ignorer les voies sans nom
                if not road_name or road_name == 'Route sans nom':
                    continue
                
                # Gérer les noms multiples (liste)
                if isinstance(road_name, list):
                    road_name = road_name[0]
                
                # Si ce nom n'a pas encore été ajouté
                if road_name not in roads:
                    highway_type = data.get('highway', 'unknown')
                    if isinstance(highway_type, list):
                        highway_type = highway_type[0]
                    
                    roads[road_name] = {
                        'name': road_name,
                        'type': highway_type,
                        'type_label': self._get_highway_label(highway_type),
                        'ref': data.get('ref'),  # Numéro de route (A6, N7, etc.)
                    }
            
            # Convertir en liste et trier par nom
            result = sorted(roads.values(), key=lambda x: x['name'])
            print(f"🛣️  {len(result)} voies uniques trouvées dans le cercle")
            
            return result
            
        except Exception as e:
            print(f"❌ Erreur extraction voies: {e}")
            return []
    
    async def find_road_in_area(
        self, 
        query: str, 
        lat: float, 
        lon: float, 
        radius: int = 2000
    ) -> Optional[Dict]:
        """
        Recherche une voie par nom dans le cercle autour d'une position.
        Utilise recherche exacte, substring, puis fuzzy.
        
        Args:
            query: Nom de la voie à chercher
            lat: Latitude du centre
            lon: Longitude du centre
            radius: Rayon en mètres
        
        Returns:
            Dictionnaire avec infos de la voie trouvée, ou None
        """
        # Récupérer toutes les voies du cercle
        all_roads = await self.get_all_roads_in_area(lat, lon, radius)
        
        if not all_roads:
            return None
        
        query_lower = query.lower().strip()
        
        # Extraire les mots-clés significatifs (ignorer mots génériques)
        generic_words = {'rue', 'avenue', 'boulevard', 'place', 'chemin', 'route', 
                         'allée', 'voie', 'passage', 'impasse', 'de', 'du', 'la', 
                         'le', 'les', 'des', 'au', 'aux', 'd', 'l'}
        query_keywords = [w for w in query_lower.split() if len(w) > 2 and w not in generic_words]
        
        from difflib import SequenceMatcher
        
        best_match = None
        best_score = 0
        
        for road in all_roads:
            road_name = road['name']
            road_name_lower = road_name.lower()
            
            # Match de mot-clé (plus fiable)
            keyword_match = any(kw in road_name_lower for kw in query_keywords)
            
            # Similarité globale
            similarity = SequenceMatcher(None, query_lower, road_name_lower).ratio()
            
            # Score combiné
            if keyword_match:
                score = max(similarity, 0.8)
                match_type = "mot-clé"
            else:
                score = similarity
                match_type = "similarité"
            
            if score > best_score and score >= 0.6:
                best_score = score
                best_match = {
                    **road,
                    'score': score,
                    'match_type': match_type
                }
        
        if best_match:
            print(f"✅ Voie '{best_match['name']}' trouvée dans le cercle (score: {best_score:.2f}, {best_match['match_type']})")
            return best_match
        else:
            print(f"⚠️  Aucune voie correspondant à '{query}' dans le cercle")
            return None
    
    def _get_highway_label(self, highway_type: str) -> str:
        """Convertit le type highway OSM en label lisible"""
        labels = {
            'motorway': 'autoroute',
            'trunk': 'route nationale',
            'primary': 'route principale',
            'secondary': 'route secondaire',
            'tertiary': 'route tertiaire',
            'residential': 'rue résidentielle',
            'unclassified': 'route non classée',
            'service': 'voie de service',
            'living_street': 'zone de rencontre',
            'pedestrian': 'rue piétonne',
            'motorway_link': 'bretelle autoroute',
            'trunk_link': 'bretelle nationale',
            'primary_link': 'bretelle principale',
        }
        return labels.get(highway_type, highway_type)
    
    async def enrich_candidates_with_nearby_pois(
        self, 
        candidates: List[Dict], 
        radius: int = 500,
        max_nearby: int = 3
    ) -> List[Dict]:
        """
        Enrichit chaque candidat POI avec les POI les plus proches autour.
        Utile pour la désambiguïsation: "Près du #1 il y a un Garage Autosur..."
        
        Args:
            candidates: Liste de POI candidats avec lat/lon
            radius: Rayon de recherche autour de chaque candidat (mètres)
            max_nearby: Nombre max de POI proches à inclure par candidat
        
        Returns:
            Liste de candidats enrichis avec champ 'nearby_pois'
        """
        print(f"🔍 Enrichissement de {len(candidates)} candidats avec POI proches...")
        enriched = []
        
        for i, candidate in enumerate(candidates):
            enriched_candidate = candidate.copy()
            nearby = []
            
            try:
                # Charger les POI autour de ce candidat
                pois = await self.fetch_local_pois(
                    candidate['lat'], 
                    candidate['lon'], 
                    radius=radius
                )
                
                if pois:
                    # Filtrer: exclure le candidat lui-même et les POI avec même nom
                    candidate_name = candidate.get('name', '').lower()
                    other_pois = [
                        p for p in pois 
                        if p.get('name', '').lower() != candidate_name
                    ]
                    
                    # Trier par distance et prendre les N plus proches
                    for poi in other_pois:
                        dist = self._haversine_distance(
                            candidate['lat'], candidate['lon'],
                            poi['lat'], poi['lon']
                        )
                        poi['distance_to_candidate'] = int(dist)
                    
                    other_pois.sort(key=lambda p: p.get('distance_to_candidate', 9999))
                    nearby = other_pois[:max_nearby]
                    
                    if nearby:
                        nearby_names = [p['name'] for p in nearby]
                        print(f"   #{i+1} {candidate.get('name', 'POI')}: {', '.join(nearby_names)}")
                    
            except Exception as e:
                print(f"   ⚠️ Erreur enrichissement #{i+1}: {e}")
            
            enriched_candidate['nearby_pois'] = nearby
            enriched.append(enriched_candidate)
        
        print(f"✅ {len(enriched)} candidats enrichis")
        return enriched
    
    def filter_candidates_by_nearby(
        self, 
        candidates: List[Dict], 
        nearby_query: str
    ) -> List[Dict]:
        """
        Filtre les candidats en gardant ceux qui ont un POI proche correspondant à la requête.
        
        Args:
            candidates: Liste de candidats enrichis (avec nearby_pois)
            nearby_query: Nom du POI proche mentionné par l'utilisateur
        
        Returns:
            Liste filtrée de candidats
        """
        from difflib import SequenceMatcher
        
        query_lower = nearby_query.lower().strip()
        filtered = []
        
        for candidate in candidates:
            nearby_pois = candidate.get('nearby_pois', [])
            
            for poi in nearby_pois:
                poi_name = poi.get('name', '').lower()
                
                # Match exact ou substring
                if query_lower in poi_name or poi_name in query_lower:
                    filtered.append(candidate)
                    print(f"   ✅ Match: '{nearby_query}' ↔ '{poi['name']}' près de {candidate.get('name', 'POI')}")
                    break
                
                # Match fuzzy
                score = SequenceMatcher(None, query_lower, poi_name).ratio()
                if score >= 0.6:
                    filtered.append(candidate)
                    print(f"   ✅ Match fuzzy: '{nearby_query}' ↔ '{poi['name']}' (score: {score:.2f})")
                    break
        
        print(f"🔍 Filtrage: {len(candidates)} → {len(filtered)} candidats pour '{nearby_query}'")
        return filtered
    
    def find_road_on_route(self, route_segments: List[Dict], query: str) -> Optional[Dict]:
        """
        Recherche une voie par nom parmi les segments d'un trajet.
        Utilise recherche exacte, substring, puis fuzzy.
        
        Args:
            route_segments: Liste de segments avec 'name', 'start_distance', 'end_distance'
            query: Nom de voie à chercher
        
        Returns:
            Segment correspondant avec cumulative_distance au milieu, ou None
        """
        if not route_segments or not query:
            return None
        
        query_lower = query.lower().strip()
        
        # Étape 1: Correspondance exacte
        for seg in route_segments:
            if seg.get('name', '').lower() == query_lower:
                mid = (seg['start_distance'] + seg['end_distance']) / 2
                print(f"✅ Match EXACT pour '{query}': {seg['name']}")
                return {
                    'name': seg['name'],
                    'cumulative_distance': int(mid),
                    'start_distance': seg['start_distance'],
                    'end_distance': seg['end_distance'],
                    'confidence': 1.0
                }
        
        # Étape 2: Correspondance substring
        for seg in route_segments:
            seg_name = seg.get('name', '').lower()
            if query_lower in seg_name or seg_name in query_lower:
                mid = (seg['start_distance'] + seg['end_distance']) / 2
                print(f"✅ Match SUBSTRING pour '{query}': {seg['name']}")
                return {
                    'name': seg['name'],
                    'cumulative_distance': int(mid),
                    'start_distance': seg['start_distance'],
                    'end_distance': seg['end_distance'],
                    'confidence': 0.9
                }
        
        # Étape 3: Recherche fuzzy
        from difflib import SequenceMatcher
        
        best_match = None
        best_score = 0
        
        for seg in route_segments:
            seg_name = seg.get('name', '').lower()
            if not seg_name:
                continue
            score = SequenceMatcher(None, query_lower, seg_name).ratio()
            if score > best_score and score > 0.5:
                best_score = score
                best_match = seg
        
        if best_match:
            mid = (best_match['start_distance'] + best_match['end_distance']) / 2
            print(f"🔍 Match FUZZY pour '{query}': {best_match['name']} (score: {best_score:.2f})")
            return {
                'name': best_match['name'],
                'cumulative_distance': int(mid),
                'start_distance': best_match['start_distance'],
                'end_distance': best_match['end_distance'],
                'confidence': best_score
            }
        
        print(f"❌ Aucune voie trouvée pour '{query}'")
        return None
    
    async def get_pois_along_route_buffer(
        self, 
        route_geometry: List[Tuple[float, float]], 
        buffer_meters: int = 100
    ) -> List[Dict]:
        """
        Cherche les POI le long d'un trajet avec un buffer (plus précis qu'un cercle).
        
        Args:
            route_geometry: Liste de coordonnées (lon, lat) du trajet
            buffer_meters: Largeur du buffer en mètres de chaque côté
        
        Returns:
            Liste de POI dans le buffer du trajet
        """
        if not route_geometry or len(route_geometry) < 2:
            return []
        
        try:
            from shapely.geometry import LineString, Point
            from shapely.ops import transform
            import pyproj
            
            # Créer la ligne du trajet
            route_line = LineString(route_geometry)
            
            # Projeter en mètres pour buffer précis (UTM zone approximative)
            center_lon = sum(p[0] for p in route_geometry) / len(route_geometry)
            center_lat = sum(p[1] for p in route_geometry) / len(route_geometry)
            utm_zone = int((center_lon + 180) / 6) + 1
            
            project_to_utm = pyproj.Transformer.from_crs(
                "EPSG:4326", f"EPSG:326{utm_zone:02d}", always_xy=True
            ).transform
            project_to_wgs = pyproj.Transformer.from_crs(
                f"EPSG:326{utm_zone:02d}", "EPSG:4326", always_xy=True
            ).transform
            
            # Buffer en mètres
            route_utm = transform(project_to_utm, route_line)
            buffer_utm = route_utm.buffer(buffer_meters)
            buffer_wgs = transform(project_to_wgs, buffer_utm)
            
            # Filtrer les POI en cache qui sont dans le buffer
            pois_in_buffer = []
            
            for poi in self.poi_cache:
                poi_point = Point(poi['lon'], poi['lat'])
                if buffer_wgs.contains(poi_point):
                    pois_in_buffer.append(poi)
            
            print(f"🛣️  {len(pois_in_buffer)} POI dans le buffer de {buffer_meters}m le long du trajet")
            return pois_in_buffer
            
        except ImportError as e:
            print(f"⚠️  Librairie manquante pour buffer: {e}")
            return []
        except Exception as e:
            print(f"❌ Erreur buffer trajet: {e}")
            return []
    
    # ==================== MÉTHODES EXISTANTES ====================
    
    def _get_next_mirror(self) -> str:
        """Retourne le prochain miroir Overpass (rotation circulaire)"""
        mirror = self.overpass_mirrors[self.current_mirror_index]
        self.current_mirror_index = (self.current_mirror_index + 1) % len(self.overpass_mirrors)
        return mirror
    
    async def _query_overpass_with_retry(self, query: str) -> Optional[dict]:
        """
        Exécute une requête Overpass avec rotation de miroirs et retry exponentiel.
        Gère les erreurs 429 (rate limit) et 504 (server overload).
        """
        last_error = None
        
        for attempt in range(OVERPASS_MAX_RETRIES):
            mirror = self._get_next_mirror()
            
            try:
                async with httpx.AsyncClient(timeout=OVERPASS_TIMEOUT) as client:
                    response = await client.post(
                        mirror,
                        data={"data": query},
                        headers={"Content-Type": "application/x-www-form-urlencoded"}
                    )
                    
                    if response.status_code == 200:
                        return response.json()
                    elif response.status_code in (429, 504):
                        delay = OVERPASS_RETRY_BASE_DELAY * (2 ** attempt)
                        print(f"⚠️  Overpass {response.status_code} sur {mirror}, retry dans {delay}s...")
                        await asyncio.sleep(delay)
                        continue
                    else:
                        print(f"❌ Overpass HTTP {response.status_code} sur {mirror}")
                        last_error = f"HTTP {response.status_code}"
                        
            except httpx.TimeoutException:
                print(f"⏱️  Timeout Overpass sur {mirror}")
                last_error = "Timeout"
            except Exception as e:
                print(f"❌ Erreur Overpass sur {mirror}: {e}")
                last_error = str(e)
            
            if attempt < OVERPASS_MAX_RETRIES - 1:
                delay = OVERPASS_RETRY_BASE_DELAY * (2 ** attempt)
                await asyncio.sleep(delay)
        
        print(f"❌ Échec Overpass après {OVERPASS_MAX_RETRIES} tentatives: {last_error}")
        return None
    
    def _haversine_distance(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calcul distance précise entre deux points GPS (formule de Haversine)"""
        R = 6371000
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        
        a = math.sin(dphi/2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda/2)**2
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    
    async def get_coordinates_from_place(self, place_name: str, context: str = "") -> Optional[Tuple[float, float]]:
        """Géocoder un lieu avec contexte pour disambiguation (async)"""
        try:
            search_queries = [
                f"{place_name}, France",
                f"{place_name}",
            ]
            
            if context:
                search_queries.insert(0, f"{place_name}, {context}, France")
            
            for query in search_queries:
                try:
                    location = await asyncio.to_thread(
                        self.geolocator.geocode, query, timeout=NOMINATIM_TIMEOUT
                    )
                    if location:
                        return (location.latitude, location.longitude)
                    await asyncio.sleep(GEOCODING_SLEEP)
                except Exception as e:
                    print(f"Erreur géocodage pour '{query}': {e}")
                    continue
                    
        except Exception as e:
            print(f"Erreur générale géocodage: {e}")
        return None
    
    async def get_route_coordinates_on_path(
        self, route_number: str, start_coords: tuple, end_coords: tuple
    ) -> Optional[Tuple[float, float]]:
        """Obtenir coordonnées d'une route sur un trajet spécifique"""
        clean_route = route_number.upper().replace(' ', '')
        
        lat_min = min(start_coords[0], end_coords[0]) - 0.2
        lat_max = max(start_coords[0], end_coords[0]) + 0.2
        lon_min = min(start_coords[1], end_coords[1]) - 0.2
        lon_max = max(start_coords[1], end_coords[1]) + 0.2
        
        bbox = f"{lat_min},{lon_min},{lat_max},{lon_max}"
        
        query = f"""
        [out:json][timeout:{OVERPASS_TIMEOUT}];
        (
            way["highway"]["ref"="{clean_route}"]({bbox});
        );
        out center 3;
        """
        
        result = await self._query_overpass_with_retry(query)
        if result and result.get('elements'):
            mid_lat = (start_coords[0] + end_coords[0]) / 2
            mid_lon = (start_coords[1] + end_coords[1]) / 2
            
            best_way = None
            min_distance = float('inf')
            
            for elem in result['elements']:
                if 'center' in elem:
                    way_lat = float(elem['center']['lat'])
                    way_lon = float(elem['center']['lon'])
                    distance = self._haversine_distance(way_lat, way_lon, mid_lat, mid_lon)
                    
                    if distance < min_distance:
                        min_distance = distance
                        best_way = elem
            
            if best_way and 'center' in best_way:
                return (float(best_way['center']['lat']), float(best_way['center']['lon']))
        
        return None
    
    def validate_coordinates(self, lat: float, lon: float) -> bool:
        """Vérifier si les coordonnées sont dans les limites de la France métropolitaine"""
        france_bounds = {
            'lat_min': 41.0,
            'lat_max': 51.5,
            'lon_min': -5.5,
            'lon_max': 9.5
        }
        
        return (france_bounds['lat_min'] <= lat <= france_bounds['lat_max'] and
                france_bounds['lon_min'] <= lon <= france_bounds['lon_max'])
    
    async def get_pois_in_area(self, lat: float, lon: float, radius_meters: int = 1000) -> List[Dict]:
        """
        Recherche des POI visuels via Overpass API (fallback si OSMnx échoue).
        """
        pois = []
        
        query = f"""
        [out:json][timeout:{OVERPASS_TIMEOUT}];
        (
          node["amenity"="fuel"](around:{radius_meters},{lat},{lon});
          node["amenity"="fast_food"](around:{radius_meters},{lat},{lon});
          node["amenity"="restaurant"](around:{radius_meters},{lat},{lon});
          node["shop"="car_repair"](around:{radius_meters},{lat},{lon});
          node["shop"="supermarket"](around:{radius_meters},{lat},{lon});
          way["shop"="supermarket"](around:{radius_meters},{lat},{lon});
          node["amenity"="place_of_worship"](around:{radius_meters},{lat},{lon});
          way["amenity"="place_of_worship"](around:{radius_meters},{lat},{lon});
          node["man_made"="water_tower"](around:{radius_meters},{lat},{lon});
          node["historic"="castle"](around:{radius_meters},{lat},{lon});
          node["railway"="station"](around:{radius_meters},{lat},{lon});
          node["amenity"="townhall"](around:{radius_meters},{lat},{lon});
          node["amenity"="hospital"](around:{radius_meters},{lat},{lon});
          node["leisure"="stadium"](around:{radius_meters},{lat},{lon});
        );
        out center 20;
        """
        
        print(f"🔍 Recherche POI Overpass autour de ({lat:.4f}, {lon:.4f}), rayon {radius_meters}m...")
        
        result = await self._query_overpass_with_retry(query)
        
        if not result or not result.get('elements'):
            print("⚠️  Aucun résultat Overpass")
            return []
        
        for elem in result['elements']:
            tags = elem.get('tags', {})
            name = tags.get('name', '')
            if not name:
                continue
            
            poi_type = self._get_poi_type_label(tags)
            
            if 'lat' in elem and 'lon' in elem:
                poi_lat, poi_lon = float(elem['lat']), float(elem['lon'])
            elif 'center' in elem:
                poi_lat = float(elem['center']['lat'])
                poi_lon = float(elem['center']['lon'])
            else:
                continue
            
            pois.append({
                'name': name,
                'type': poi_type,
                'lat': poi_lat,
                'lon': poi_lon,
                'name_lower': name.lower()
            })
        
        # Mettre aussi en cache les résultats Overpass
        if pois and not self.poi_cache:
            self.poi_cache = pois
            self.cache_center = (lat, lon)
            self.cache_radius = radius_meters
        
        print(f"✅ {len(pois)} POI trouvés")
        return pois
    
    def _get_poi_type_label(self, tags: Dict) -> str:
        """Convertit les tags OSM en label lisible"""
        if tags.get('amenity') == 'fuel':
            return 'station-service'
        elif tags.get('amenity') == 'place_of_worship':
            return 'église'
        elif tags.get('shop') == 'supermarket':
            return 'supermarché'
        elif tags.get('shop') == 'car_repair':
            return 'garage'
        elif tags.get('man_made') == 'water_tower':
            return "château d'eau"
        elif tags.get('historic') == 'castle':
            return 'château'
        elif tags.get('railway') == 'station':
            return 'gare'
        elif tags.get('amenity') == 'fast_food':
            return 'fast-food'
        elif tags.get('amenity') == 'restaurant':
            return 'restaurant'
        elif tags.get('amenity') == 'townhall':
            return 'mairie'
        elif tags.get('amenity') == 'hospital':
            return 'hôpital'
        elif tags.get('leisure') == 'stadium':
            return 'stade'
        else:
            return 'repère'
    
    async def search_landmarks_near_point(
        self, description: str, lat: float, lon: float, radius: int = 2000
    ) -> List[Dict]:
        """
        Cherche des repères par mot-clé. Utilise d'abord le cache fuzzy, puis Overpass en fallback.
        """
        # D'abord, essayer la recherche fuzzy dans le cache
        if self.poi_cache:
            fuzzy_results = self.find_landmarks_fuzzy(description, cutoff=0.4, max_results=5)
            if fuzzy_results:
                print(f"✅ Résultats fuzzy depuis le cache pour '{description}'")
                return fuzzy_results
        
        # Fallback: Overpass avec regex
        clean_desc = description.strip().replace("'", ".").replace(" ", ".")
        
        print(f"🔍 Recherche Overpass pour '{description}'...")
        
        query = f"""
        [out:json][timeout:10];
        (
          node(around:{radius},{lat},{lon})["name"~"{clean_desc}",i];
          node(around:{radius},{lat},{lon})["brand"~"{clean_desc}",i];
          way(around:{radius},{lat},{lon})["name"~"{clean_desc}",i];
        );
        out center 10;
        """
        
        result = await self._query_overpass_with_retry(query)
        found = []
        
        if not result or not result.get('elements'):
            print(f"⚠️  Aucun repère trouvé pour '{description}'")
            return []
        
        for elem in result['elements']:
            tags = elem.get('tags', {})
            name = tags.get('name', tags.get('brand', 'Repère'))
            
            if 'lat' in elem and 'lon' in elem:
                l_lat, l_lon = float(elem['lat']), float(elem['lon'])
            elif 'center' in elem:
                l_lat = float(elem['center']['lat'])
                l_lon = float(elem['center']['lon'])
            else:
                continue
            
            found.append({
                'name': name,
                'lat': l_lat,
                'lon': l_lon,
                'type': 'repère décrit',
                'name_lower': name.lower()
            })
            print(f"   📍 Trouvé: {name}")
        
        return found