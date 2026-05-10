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
import sqlite3
import os
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
        self.db_path = "data/pois_local.db"
        
        print(f"✅ Services de géocodage initialisés (Base locale: {os.path.exists(self.db_path)})")
    
    # ==================== SOURCE LOCALE SQLITE ====================
    
    async def fetch_local_pois_sqlite(self, lat: float, lon: float, radius_meters: int = 3000, query: str = None) -> List[Dict]:
        """
        Recherche des POI dans la base SQLite locale.
        Si query est fourni, cherche par nom dans la bounding box.
        """
        if not os.path.exists(self.db_path):
            return []

        lat_delta = radius_meters / 111000
        lon_delta = radius_meters / (111000 * math.cos(math.radians(lat)))
        
        lat_min, lat_max = lat - lat_delta, lat + lat_delta
        lon_min, lon_max = lon - lon_delta, lon + lon_delta
        
        try:
            conn = sqlite3.connect(self.db_path, timeout=20)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            if query:
                # 1. ANALYSE DU TERME (Magasin vs Infrastructure)
                query_clean = query.lower().strip()
                
                # Nettoyage des mots-clés génériques pour la recherche du nom
                name_query = query_clean
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
                    name_query = query_clean
                
                # Utilisation du rayon demandé (converti en degrés)
                q_lat_delta = radius_meters / 111000
                q_lon_delta = radius_meters / (111000 * math.cos(math.radians(lat)))

                # RECHERCHE HYBRIDE: Nom LIKE ou Catégorie match
                cursor.execute("""
                    SELECT name, type, lat, lon, category FROM pois 
                    WHERE (
                        name LIKE ? 
                        OR (category = 'shop' AND name LIKE ?)
                        OR (category = 'amenity' AND type = ?)
                        OR (category = 'highway' AND type = 'junction' AND ? IN ('carrefour', 'croisement'))
                        OR (category = 'highway' AND type IN ('services', 'rest_area') AND ? IN ('aire de repos', 'aire de services', 'aire d''autoroute', 'aire'))
                        OR (category = 'highway' AND type = 'bus_stop' AND ? IN ('arrêt de bus', 'arret de bus', 'abribus', 'abris bus', 'arrêt', 'arret'))
                        OR (category = 'amenity' AND type = 'fuel' AND ? IN ('station', 'station service', 'station-service', 'pompe'))
                        OR (category = 'leisure' AND type IN ('sports_centre', 'stadium', 'pitch', 'sports_hall', 'swimming_pool') AND ? IN ('complexe sportif', 'complexes sportifs', 'stade', 'gymnase', 'piscine', 'terrain de sport'))
                        OR (category = 'man_made' AND type = 'bridge' AND ? = 'pont')
                        OR (category = 'power' AND ? IN ('pylône', 'pylone', 'éolienne', 'eolienne', 'ligne haute tension'))
                        OR (category = 'barrier' AND ? IN ('péage', 'peage'))
                        OR (category = 'amenity' AND type = 'pharmacy' AND ? = 'pharmacie')
                        OR (category = 'shop' AND type = 'bakery' AND ? = 'boulangerie')
                        OR (category = 'amenity' AND type IN ('bank', 'atm') AND ? IN ('banque', 'distributeur', 'distributeur de billets', 'guichet'))
                        OR (category = 'amenity' AND type = 'hospital' AND ? IN ('hôpital', 'hopital', 'clinique', 'centre hospitalier'))
                        OR (category = 'shop' AND type IN ('supermarket', 'mall') AND ? IN ('supermarché', 'supermarche', 'hypermarché', 'hypermarche', 'centre commercial'))
                        OR (category = 'tourism' AND type = 'hotel' AND ? IN ('hôtel', 'hotel'))
                        OR (category = 'amenity' AND type = 'school' AND ? IN ('école', 'ecole', 'collège', 'college', 'lycée', 'lycee'))
                        OR (category = 'amenity' AND type = 'townhall' AND ? = 'mairie')
                        OR (category = 'amenity' AND type = 'parking' AND ? = 'parking')
                        OR (category = 'tourism' AND type = 'camp_site' AND ? = 'camping')
                        OR (category = 'amenity' AND type = 'graveyard' AND ? IN ('cimetière', 'cimetiere'))
                        OR (category = 'landuse' AND type = ? )
                    )
                    AND lat BETWEEN ? AND ? 
                    AND lon BETWEEN ? AND ?
                    ORDER BY 
                        (CASE WHEN name LIKE ? THEN 0 ELSE 1 END),
                        ((lat - ?) * (lat - ?)) + ((lon - ?) * (lon - ?)) ASC
                    LIMIT 100
                """, (
                    f"%{name_query}%", f"%{name_query}%", query_clean, query_clean, query_clean,
                    query_clean, query_clean, query_clean, query_clean, query_clean,
                    query_clean, query_clean, query_clean, query_clean, query_clean,
                    query_clean, query_clean, query_clean, query_clean, query_clean,
                    query_clean, query_clean, query_clean,
                    lat - q_lat_delta, lat + q_lat_delta, lon - q_lon_delta, lon + q_lon_delta,
                    f"{name_query}%", lat, lat, lon, lon
                ))
                rows = cursor.fetchall()
            else:
                # Recherche par proximité dans la zone (triée du plus proche au plus loin)
                cursor.execute("""
                    SELECT name, type, lat, lon, category FROM pois 
                    WHERE lat BETWEEN ? AND ? 
                    AND lon BETWEEN ? AND ?
                    ORDER BY ((lat - ?) * (lat - ?)) + ((lon - ?) * (lon - ?)) ASC
                    LIMIT 5000
                """, (lat_min, lat_max, lon_min, lon_max, lat, lat, lon, lon))
                rows = cursor.fetchall()

            conn.close()
            
            results = []
            for row in rows:
                results.append({
                    'name': row['name'],
                    'type': row['type'],
                    'category': row['category'],
                    'lat': row['lat'],
                    'lon': row['lon']
                })
            
            print(f"✅ {len(results)} POI trouvés (query='{query}')")
            return results
            
        except Exception as e:
            print(f"❌ Erreur lecture SQLite: {e}")
            return []

    def _update_cache(self, lat: float, lon: float, radius: int, pois: List[Dict]):
        """Met à jour le cache local des POI en assurant la présence de name_lower"""
        for poi in pois:
            if 'name_lower' not in poi and 'name' in poi:
                poi['name_lower'] = poi['name'].lower().strip()
                
        self.poi_cache = pois
        self.cache_center = (lat, lon)
        self.cache_radius = radius
        print(f"✅ {len(pois)} POI mis en cache (centre: {lat:.4f}, {lon:.4f})")

    # ==================== CACHE LOCAL OSMnx ====================
    
    async def fetch_local_pois(self, lat: float, lon: float, radius: int = 2000) -> List[Dict]:
        """
        Charge les POI via Base Locale SQLite (Priorité absolue).
        Si 0 résultats, tente un élargissement local avant tout fallback internet.
        """
        # 1. Vérifier cache mémoire
        if self._is_cache_valid(lat, lon, radius):
            print(f"📦 Cache mémoire valide ({len(self.poi_cache)} POI)")
            # ✅ FIX: Filtrage strict par distance même en utilisant le cache
            # Évite de renvoyer 5km de points quand on en demande 1km
            filtered_pois = []
            for poi in self.poi_cache:
                dist = self._haversine_distance(lat, lon, poi['lat'], poi['lon'])
                if dist <= radius:
                    if 'name_lower' not in poi:
                        poi['name_lower'] = poi['name'].lower().strip()
                    poi['_distance'] = dist
                    filtered_pois.append(poi)
            
            # Trier par distance géographique (plus proche d'abord)
            filtered_pois.sort(key=lambda p: p['_distance'])
            
            print(f"🎯 {len(filtered_pois)} POI conservés après filtrage par rayon ({radius}m)")
            return filtered_pois
        
        # 2. Tenter Base SQLite locale (Rayon demandé)
        local_pois = await self.fetch_local_pois_sqlite(lat, lon, radius)
        
        # 3. Si vide, tenter un élargissement local (ex: 10km) car c'est gratuit en temps
        if not local_pois and radius < 10000:
            print(f"🔍 Aucun POI à {radius}m, tentative élargissement à 10km en local...")
            local_pois = await self.fetch_local_pois_sqlite(lat, lon, 10000)

        if local_pois:
            self._update_cache(lat, lon, radius, local_pois)
            return local_pois

        # 4. Fallback internet (OSMnx/Overpass) si la base locale est absente ou vide
        print(f"🌐 Chargement POI OSMnx (Fallback) autour de ({lat:.4f}, {lon:.4f})...")
        
        try:
            # Import OSMnx ici pour éviter le chargement au démarrage
            import osmnx as ox
            
            # Tags pour les features à récupérer
            tags = {
                'amenity': True,  'shop': True, 'tourism': True, 'historic': True,
                'railway': ['station', 'halt'], 'man_made': ['water_tower', 'tower', 'silo'],
                'leisure': ['stadium'],
            }
            
            # Récupérer les features via OSMnx (synchrone, exécuté en thread)
            gdf = await asyncio.to_thread(
                ox.features_from_point, (lat, lon), tags, dist=radius
            )
            
            pois = []
            for idx, row in gdf.iterrows():
                try:
                    name_str = str(row.get('name', ''))
                    if not name_str or name_str == 'nan': continue
                    
                    if hasattr(row.geometry, 'x'):
                        poi_lat, poi_lon = row.geometry.y, row.geometry.x
                    else:
                        centroid = row.geometry.centroid
                        poi_lat, poi_lon = centroid.y, centroid.x
                    
                    pois.append({
                        'name': name_str,
                        'type': self._get_osmnx_poi_type(row),
                        'lat': poi_lat, 'lon': poi_lon
                    })
                except: continue
            
            self._update_cache(lat, lon, radius, pois)
            return pois
            
        except Exception as e:
            print(f"❌ Erreur Fallback OSMnx: {e}")
            return []
            
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
            self._update_cache(lat, lon, radius, pois)
            
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
        # Cutoff plus élevé (0.75) pour éviter les faux positifs (ex: "grand stade" = "grand optical")
        poi_names = [poi['name_lower'] for poi in self.poi_cache]
        fuzzy_matches = get_close_matches(query_lower, poi_names, n=max_results, cutoff=max(cutoff, 0.75))
        
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
                        headers={
                            "Content-Type": "application/x-www-form-urlencoded",
                            "User-Agent": NOMINATIM_USER_AGENT
                        }
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

    async def search_address_candidates(self, query: str, limit: int = 5) -> List[Dict]:
        """Recherche plusieurs candidats pour l'autocomplétion (async)"""
        try:
            # On force la recherche en France pour la pertinence
            full_query = f"{query}, France"
            
            locations = await asyncio.to_thread(
                self.geolocator.geocode, 
                full_query, 
                exactly_one=False, 
                limit=limit, 
                timeout=NOMINATIM_TIMEOUT
            )
            
            if not locations:
                return []
                
            results = []
            for loc in locations:
                results.append({
                    "display_name": loc.address,
                    "lat": loc.latitude,
                    "lon": loc.longitude
                })
            return results
        except Exception as e:
            print(f"Erreur autocomplétion pour '{query}': {e}")
            return []
    
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