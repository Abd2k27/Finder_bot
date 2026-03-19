"""
Service de routage asynchrone via OSRM.

Fournit:
- Calcul d'itinéraire avec profil adapté au transport
- Localisation de position sur un itinéraire
- Projection de POI sur le tracé avec optimisation bounding box
"""

import asyncio
import math
import httpx
from typing import Dict, List, Optional, Tuple


class RoutingService:
    """Service pour obtenir les instructions détaillées d'un itinéraire via OSRM (async)"""
    
    def __init__(self):
        self.osrm_base_url = "http://router.project-osrm.org/route/v1"
        print("🗺️  Service OSRM initialisé (async)")
    
    def _get_osrm_profile(self, transport: str) -> str:
        """
        Retourne le profil OSRM approprié selon le transport
        
        OSRM supporte 3 profils:
        - driving: voiture, moto, bus
        - foot: marche à pied
        - bike: vélo (pas toujours disponible sur serveur public)
        """
        profile_mapping = {
            'voiture': 'driving',
            'moto': 'driving',
            'bus': 'driving',
            'pied': 'foot',
            'velo': 'bike'
        }
        
        profile = profile_mapping.get(transport, 'driving')
        print(f"🚗 Transport '{transport}' → Profil OSRM '{profile}'")
        return profile
    
    async def get_detailed_route(
        self, 
        start_coords: tuple, 
        end_coords: tuple, 
        transport: str = 'voiture',
        fallback_on_foot_failure: bool = True
    ) -> Optional[Dict]:
        """
        Récupérer l'itinéraire détaillé avec le profil adapté au transport.
        
        Args:
            start_coords: (lat, lon) du départ
            end_coords: (lat, lon) de l'arrivée
            transport: mode de transport ('voiture', 'pied', 'moto', 'bus', 'velo')
            fallback_on_foot_failure: Si True et profil 'foot' échoue, retry avec 'driving'
        """
        profile = self._get_osrm_profile(transport)
        
        route_data = await self._fetch_osrm_route(start_coords, end_coords, profile)
        
        # Fallback pour le mode piéton: utiliser driving si foot échoue
        if route_data is None and transport == 'pied' and fallback_on_foot_failure:
            print("⚠️  Profil 'foot' échoué, fallback sur 'driving' avec vitesse piéton...")
            route_data = await self._fetch_osrm_route(start_coords, end_coords, 'driving')
            
            if route_data:
                # Recalculer la durée avec une vitesse de marche (~5 km/h)
                walking_speed_mps = 5 * 1000 / 3600  # 5 km/h en m/s
                route_data['total_duration'] = route_data['total_distance'] / walking_speed_mps
                route_data['transport_fallback'] = 'driving_as_foot'
                print(f"✅ Fallback: durée recalculée à {route_data['total_duration']/60:.0f}min (vitesse piéton)")
        
        return route_data
    
    async def _fetch_osrm_route(
        self, start_coords: tuple, end_coords: tuple, profile: str
    ) -> Optional[Dict]:
        """Fetch OSRM route avec httpx async"""
        try:
            # OSRM utilise le format lon,lat (pas lat,lon!)
            coordinates = f"{start_coords[1]},{start_coords[0]};{end_coords[1]},{end_coords[0]}"
            
            url = f"{self.osrm_base_url}/{profile}/{coordinates}"
            params = {
                'overview': 'full',
                'steps': 'true',
                'geometries': 'geojson'
            }
            
            print(f"🌐 Requête OSRM [{profile}]: {url}")
            
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(url, params=params)
                
                if response.status_code == 200:
                    data = response.json()
                    if data['code'] == 'Ok' and data['routes']:
                        route = self._parse_route_instructions(data['routes'][0])
                        print(f"✅ Itinéraire récupéré: {route['total_distance']/1000:.1f}km, {len(route['instructions'])} instructions")
                        return route
                    else:
                        print(f"⚠️  OSRM code: {data.get('code')}")
                else:
                    print(f"⚠️  OSRM HTTP {response.status_code}")
                    
        except httpx.TimeoutException:
            print("⏱️  Timeout OSRM")
        except Exception as e:
            print(f"❌ Erreur récupération itinéraire: {e}")
        
        return None
    
    def _parse_route_instructions(self, route: Dict) -> Dict:
        """Parser les instructions pour extraire infos utiles"""
        instructions = []
        cumulative_distance = 0
        
        for leg in route['legs']:
            for step in leg['steps']:
                coords_geojson = step['geometry']['coordinates'][0] if step['geometry']['coordinates'] else None
                
                instruction = {
                    'instruction': step['maneuver']['type'],
                    'name': step.get('name', 'Route sans nom'),
                    'distance': step['distance'],
                    'duration': step['duration'],
                    'cumulative_distance': cumulative_distance,
                    'coordinates': coords_geojson
                }
                
                instructions.append(instruction)
                cumulative_distance += step['distance']
        
        return {
            'total_distance': route['distance'],
            'total_duration': route['duration'],
            'instructions': instructions,
            'geometry': route['geometry']['coordinates']
        }
    
    def find_position_on_route(self, route_data: Dict, distance_meters: int) -> Optional[Tuple[float, float]]:
        """
        Trouver la position exacte sur l'itinéraire selon la distance parcourue.
        Utilise la géométrie complète de l'itinéraire.
        """
        if not route_data or not route_data.get('geometry'):
            print("❌ Pas de géométrie d'itinéraire")
            return None
        
        total_distance = route_data['total_distance']
        geometry = route_data['geometry']
        
        print(f"\n{'='*60}")
        print(f"🔍 RECHERCHE POSITION SUR GÉOMÉTRIE COMPLÈTE")
        print(f"{'='*60}")
        print(f"Distance demandée: {distance_meters}m ({distance_meters/1000:.1f}km)")
        print(f"Distance totale: {total_distance}m ({total_distance/1000:.1f}km)")
        print(f"Points de géométrie: {len(geometry)}")
        
        if distance_meters >= total_distance:
            print(f"⚠️  Distance demandée ≥ distance totale → retour destination")
            last_point = geometry[-1]
            coords = (last_point[1], last_point[0])
            print(f"🏁 Destination: {coords[0]:.4f}°N, {coords[1]:.4f}°E")
            return coords
        
        # Calculer distances cumulées
        cumulative_distances = [0]
        
        for i in range(1, len(geometry)):
            prev_point = geometry[i-1]
            curr_point = geometry[i]
            
            lat1, lon1 = prev_point[1], prev_point[0]
            lat2, lon2 = curr_point[1], curr_point[0]
            
            segment_distance = self._haversine_distance(lat1, lon1, lat2, lon2)
            cumulative_distances.append(cumulative_distances[-1] + segment_distance)
        
        # Trouver le segment contenant la distance
        for i in range(len(cumulative_distances) - 1):
            dist_start = cumulative_distances[i]
            dist_end = cumulative_distances[i + 1]
            
            if dist_start <= distance_meters <= dist_end:
                segment_length = dist_end - dist_start
                distance_in_segment = distance_meters - dist_start
                ratio = distance_in_segment / segment_length if segment_length > 0 else 0
                
                point_start = geometry[i]
                point_end = geometry[i + 1]
                
                lon = point_start[0] + (point_end[0] - point_start[0]) * ratio
                lat = point_start[1] + (point_end[1] - point_start[1]) * ratio
                
                coords = (lat, lon)
                progress_pct = (distance_meters / total_distance) * 100
                
                print(f"\n✅ POSITION TROUVÉE SUR LA GÉOMÉTRIE!")
                print(f"   Segment #{i}/{len(geometry)-1}")
                print(f"   Distance segment: {dist_start:.0f}m → {dist_end:.0f}m")
                print(f"   Ratio dans segment: {ratio:.2%}")
                print(f"   Coordonnées: {coords[0]:.4f}°N, {coords[1]:.4f}°E")
                print(f"   Progression: {progress_pct:.1f}% du trajet")
                print(f"{'='*60}\n")
                
                return coords
        
        print(f"⚠️  Distance non trouvée dans géométrie, retour dernier point")
        last_point = geometry[-1]
        return (last_point[1], last_point[0])
    
    def project_pois_on_route(
        self, 
        route_data: Dict, 
        pois: List[Dict], 
        max_distance_from_route: int = 1000
    ) -> List[Dict]:
        """
        Pour chaque POI, calcule sa position relative sur l'itinéraire.
        
        OPTIMISATION: Utilise un filtrage par bounding box pour réduire la complexité.
        Au lieu de comparer chaque POI à tous les segments, on filtre d'abord
        les segments dans un rayon immédiat du POI.
        
        Args:
            route_data: Données d'itinéraire avec geometry
            pois: Liste de POI avec lat/lon
            max_distance_from_route: Distance max en mètres depuis le tracé
        
        Returns: 
            Liste de POI projetés avec cumulative_distance et distance_from_route
        """
        if not route_data or not route_data.get('geometry'):
            print("⚠️  Pas de géométrie pour projection POI")
            return []
        
        if not pois:
            return []
        
        geometry = route_data['geometry']
        
        print(f"\n🔗 Projection de {len(pois)} POI sur l'itinéraire (optimisé)...")
        
        # Pré-calculer les distances cumulées pour chaque point
        cumulative_distances = [0]
        for i in range(1, len(geometry)):
            prev_point = geometry[i-1]
            curr_point = geometry[i]
            
            segment_dist = self._haversine_distance(
                prev_point[1], prev_point[0],
                curr_point[1], curr_point[0]
            )
            cumulative_distances.append(cumulative_distances[-1] + segment_dist)
        
        projected_pois = []
        
        # Conversion degrés → mètres approximatif pour bounding box
        # 1° latitude ≈ 111km, 1° longitude ≈ 111km * cos(lat)
        bbox_margin_deg = max_distance_from_route / 111000 * 1.5  # Marge de 50%
        
        for poi in pois:
            poi_lat, poi_lon = poi['lat'], poi['lon']
            
            # OPTIMISATION: Créer bounding box autour du POI
            bbox_lat_min = poi_lat - bbox_margin_deg
            bbox_lat_max = poi_lat + bbox_margin_deg
            bbox_lon_min = poi_lon - bbox_margin_deg
            bbox_lon_max = poi_lon + bbox_margin_deg
            
            # Filtrer les points de géométrie dans la bounding box
            min_distance = float('inf')
            best_cumulative = 0
            points_checked = 0
            
            for i, point in enumerate(geometry):
                point_lat, point_lon = point[1], point[0]
                
                # Skip si le point est hors de la bounding box
                if not (bbox_lat_min <= point_lat <= bbox_lat_max and
                        bbox_lon_min <= point_lon <= bbox_lon_max):
                    continue
                
                points_checked += 1
                dist_to_poi = self._haversine_distance(poi_lat, poi_lon, point_lat, point_lon)
                
                if dist_to_poi < min_distance:
                    min_distance = dist_to_poi
                    best_cumulative = cumulative_distances[i]
            
            # Si aucun point dans bbox, on fait une recherche complète (rare)
            if points_checked == 0:
                for i, point in enumerate(geometry):
                    point_lat, point_lon = point[1], point[0]
                    dist_to_poi = self._haversine_distance(poi_lat, poi_lon, point_lat, point_lon)
                    
                    if dist_to_poi < min_distance:
                        min_distance = dist_to_poi
                        best_cumulative = cumulative_distances[i]
            
            # Filtrer si trop loin du tracé
            if min_distance <= max_distance_from_route:
                projected_pois.append({
                    'name': poi['name'],
                    'type': poi['type'],
                    'lat': poi_lat,
                    'lon': poi_lon,
                    'cumulative_distance': int(best_cumulative),
                    'distance_from_route': int(min_distance)
                })
                print(f"   ✅ {poi['name']}: à {int(best_cumulative)}m du départ, {int(min_distance)}m du tracé (bbox: {points_checked} pts)")
            else:
                print(f"   ❌ {poi['name']}: trop loin ({int(min_distance)}m > {max_distance_from_route}m)")
        
        # Trier par distance cumulative
        projected_pois.sort(key=lambda x: x['cumulative_distance'])
        
        print(f"✅ {len(projected_pois)} POI projetés sur l'itinéraire")
        return projected_pois
    
    def _haversine_distance(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calcule la distance en mètres entre deux points GPS (formule de Haversine)."""
        R = 6371000
        
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lon2 - lon1)
        
        a = math.sin(delta_phi/2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda/2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        
        return R * c