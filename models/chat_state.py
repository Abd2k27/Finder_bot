from typing import Optional, List, Dict  # Annotations de type pour clarté du code
from datetime import datetime

class ChatState:  # Classe de gestion de l'état conversationnel et données collectées
    """État de la conversation et des informations collectées"""
    
    def __init__(self):  # Constructeur: initialise tous les attributs à leur état vide
        self.responses: List[str] = []  # Historique des réponses textuelles de l'utilisateur (ordre chronologique)
        self.coordinates: Optional[tuple] = None  # Position estimée (lat, lon) ou None si pas encore trouvée
        self.confidence: float = 0.0  # Niveau de confiance de la position (0.0 à 1.0, 0=aucune, 1=certaine)
        self.poi_history: List[Dict] = [] # Historique des listes de POI proposées [{'query': str, 'list': [], 'map_updates': []}]
        self.session_log: List[Dict] = []  # Journal horodaté de la session
        self.session_start: str = datetime.now().isoformat()  # Heure de début de session
        self.context: Dict = {  # Dictionnaire du contexte conversationnel collecté
            'start': None,  # Ville de départ (str ou None)
            'end': None,  # Ville d'arrivée (str ou None)
            'transport': None,  # Mode de transport: 'voiture', 'bus', 'moto', 'velo', 'pied' (str ou None)
            'duration': None,  # Durée écoulée en minutes (int ou None)
            'last_landmarks': [],  # Liste des repères mentionnés (routes, villes, POI)
            'recalage_done': False,  # True si un recalage a été effectué sur un POI confirmé
            'rejected_pois': [],  # Liste des noms de POI que l'utilisateur a dit ne pas voir
            'current_poi_list': [],  # Liste des 5 POI proposés à l'utilisateur (pour sélection par numéro)
            'awaiting_poi_selection': False,  # True si on attend que l'utilisateur choisisse un POI
            'awaiting_description': False,  # True si on attend une description libre après "Aucun"
            'manual_zone': None # Zone dessinée par l'ARM [lat, lon, radius]
        }
        self.route_data: Optional[Dict] = None  # Données itinéraire OSRM complet (distances, instructions) ou None
        
    def reset(self):  # Réinitialise complètement l'état (nouvelle conversation)
        """Réinitialiser l'état"""
        self.__init__()  # Rappelle le constructeur pour remettre tous attributs à zéro
    
    def add_poi_to_history(self, query: str, poi_list: List[Dict], map_updates: List[Dict] = None):
        """Sauvegarde une liste de POI dans l'historique"""
        # Nettoyage de la query pour la comparaison
        q_clean = query.lower().strip()
        
        # Ne pas sauvegarder si la liste est identique à la dernière
        if self.poi_history and self.poi_history[-1]['query'].lower() == q_clean:
            return
            
        self.poi_history.append({
            'query': query,
            'list': poi_list.copy(),
            'map_updates': map_updates.copy() if map_updates else []
        })
        if len(self.poi_history) > 10: # Augmenté à 10 pour plus de confort
            self.poi_history.pop(0)

    def pop_previous_poi_list(self) -> Optional[Dict]:
        """Récupère la liste de POI précédente (Undo simple)"""
        if len(self.poi_history) < 2:
            return None
        self.poi_history.pop()
        return self.poi_history[-1]

    def find_specific_history(self, keyword: str) -> Optional[Dict]:
        """Cherche une étape précise dans l'historique par mot-clé"""
        if not keyword: return None
        keyword = keyword.lower()
        
        # Parcourir l'historique à l'envers
        for entry in reversed(self.poi_history[:-1]):
            if keyword in entry['query'].lower():
                # On tronque l'historique pour revenir à ce point
                while self.poi_history[-1] != entry:
                    self.poi_history.pop()
                return entry
        return None

    def add_response(self, response: str):  # Ajoute une réponse utilisateur à l'historique
        """Ajouter une réponse utilisateur"""
        self.responses.append(response.strip())  # .strip() supprime espaces début/fin avant ajout
    
    def set_trajet(self, start: str, end: str):  # Définit le trajet (départ → arrivée)
        """Définir le trajet"""
        self.context['start'] = start  # Stocke ville départ
        self.context['end'] = end  # Stocke ville arrivée
    
    def set_transport(self, transport: str):  # Enregistre le mode de transport
        """Définir le mode de transport"""
        self.context['transport'] = transport  # Stocke: 'voiture', 'bus', 'moto', 'velo', ou 'pied'
    
    def set_duration(self, duration: int):  # Enregistre la durée écoulée
        """Définir la durée en minutes"""
        self.context['duration'] = duration  # Stocke durée en minutes (int)
    
    def set_distance(self, distance: int):  # Enregistre la distance parcourue
        """Définir la distance parcourue en km"""
        self.context['distance'] = distance  # Stocke distance en kilomètres (int)
    
    def add_landmark(self, landmark: str):  # Ajoute un repère à la liste (sans doublon)
        """Ajouter un repère"""
        if landmark not in self.context['last_landmarks']:  # Vérifie si repère pas déjà présent
            self.context['last_landmarks'].append(landmark)  # Ajoute seulement si unique
    
    def set_coordinates(self, lat: float, lon: float, confidence: float):  # Définit position avec niveau confiance
        """Définir les coordonnées avec niveau de confiance"""
        self.coordinates = (lat, lon)  # Stocke tuple (latitude, longitude)
        self.confidence = confidence  # Stocke score confiance (0.0 à 1.0)
    
    def has_trajet(self) -> bool:  # Vérifie si trajet complet défini
        """Vérifier si le trajet est défini"""
        return self.context['start'] is not None and self.context['end'] is not None  # True si départ ET arrivée définis
    
    def has_position(self) -> bool:  # Vérifie si position estimée existe
        """Vérifier si une position est estimée"""
        return self.coordinates is not None  # True si coordinates non None
    
    def is_position_confident(self, threshold: float = 0.7) -> bool:  # Vérifie si position suffisamment fiable
        """Vérifier si la position est suffisamment fiable"""
        return self.has_position() and self.confidence >= threshold  # True si position existe ET confiance ≥ seuil (défaut 0.7)
    
    def get_step_count(self) -> int:  # Compte nombre d'étapes conversation effectuées
        """Obtenir le nombre d'étapes effectuées"""
        return len(self.responses)  # Nombre de réponses = nombre d'étapes
    
    def to_dict(self) -> Dict:  # Exporte l'état complet en dictionnaire (debug/API)
        """Convertir l'état en dictionnaire pour debug/API"""
        return {
            "responses_count": len(self.responses),  # Nombre total de réponses
            "coordinates": self.coordinates,  # Position actuelle (tuple ou None)
            "confidence": self.confidence,  # Score confiance position (0.0-1.0)
            "context": self.context.copy(),  # Copie du contexte (évite modification externe)
            "has_trajet": self.has_trajet(),  # Boolean: trajet défini?
            "has_position": self.has_position(),  # Boolean: position trouvée?
            "is_confident": self.is_position_confident(),  # Boolean: confiance ≥ 0.7?
            "history_size": len(self.poi_history)
        }
    
    def set_route_data(self, route_data: Dict):  # Stocke les données itinéraire OSRM complet
        """Stocker les données détaillées de l'itinéraire"""
        self.route_data = route_data  # Dict contenant: total_distance, total_duration, instructions[], geometry
    
    def has_route_data(self) -> bool:  # Vérifie si données itinéraire OSRM disponibles
        """Vérifier si on a les données d'itinéraire"""
        return self.route_data is not None  # True si itinéraire récupéré
    
    def get_route_instructions_summary(self) -> str:  # Génère résumé lisible de l'itinéraire (pour logs)
        """Résumé des instructions pour debug"""
        if not self.route_data:  # Si pas de données itinéraire
            return "Aucun itinéraire"  # Message par défaut
    
        total_km = self.route_data['total_distance'] / 1000  # Conversion mètres → kilomètres
        total_min = self.route_data['total_duration'] / 60  # Conversion secondes → minutes
        num_steps = len(self.route_data['instructions'])  # Nombre d'instructions turn-by-turn
    
        return f"{total_km:.1f}km, {total_min:.0f}min, {num_steps} étapes"  # Format: "450.2km, 270min, 87 étapes"
    
    def log_event(self, event_type: str, data: Dict = None):
        """Enregistre un événement horodaté dans le journal de session"""
        self.session_log.append({
            'time': datetime.now().strftime('%H:%M:%S'),
            'timestamp': datetime.now().isoformat(),
            'type': event_type,
            'data': data or {}
        })
    
    def generate_report(self) -> str:
        """Génère un rapport HTML complet de la session"""
        now = datetime.now()
        
        # En-tête
        html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<title>Rapport FindMe — {now.strftime('%d/%m/%Y %H:%M')}</title>
<style>
body {{ font-family: 'Segoe UI', Arial, sans-serif; max-width: 900px; margin: 0 auto; padding: 20px; color: #333; background: #fafbfc; }}
h1 {{ color: #1a3a5c; border-bottom: 3px solid #2196F3; padding-bottom: 10px; }}
h2 {{ color: #1565c0; margin-top: 30px; border-left: 4px solid #2196F3; padding-left: 12px; }}
.meta {{ background: #e3f2fd; border-radius: 8px; padding: 15px; margin: 15px 0; }}
.meta table {{ width: 100%; border-collapse: collapse; }}
.meta td {{ padding: 6px 12px; }}
.meta td:first-child {{ font-weight: bold; width: 200px; color: #1565c0; }}
.timeline {{ position: relative; margin: 20px 0; }}
.event {{ border-left: 3px solid #2196F3; margin-left: 20px; padding: 10px 20px; margin-bottom: 8px; background: white; border-radius: 0 8px 8px 0; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
.event .time {{ color: #666; font-size: 0.85em; font-family: monospace; }}
.event.user {{ border-left-color: #4caf50; }}
.event.bot {{ border-left-color: #2196F3; }}
.event.system {{ border-left-color: #ff9800; background: #fff8e1; }}
.event.success {{ border-left-color: #4caf50; background: #e8f5e9; }}
.result-box {{ background: linear-gradient(135deg, #e8f5e9, #c8e6c9); border: 2px solid #4caf50; border-radius: 12px; padding: 20px; margin: 20px 0; }}
.result-box h3 {{ color: #2e7d32; margin-top: 0; }}
.no-result {{ background: #fce4ec; border-color: #e57373; }}
.no-result h3 {{ color: #c62828; }}
.footer {{ text-align: center; color: #999; font-size: 0.85em; margin-top: 40px; padding-top: 20px; border-top: 1px solid #ddd; }}
@media print {{ .action-bar {{ display: none !important; }} body {{ background: white; }} .event {{ box-shadow: none; border: 1px solid #ddd; }} }}
</style>
</head>
<body>
<div class="action-bar" style="position:sticky;top:0;background:#1a3a5c;padding:10px 20px;display:flex;gap:12px;justify-content:flex-end;z-index:100;border-radius:0 0 8px 8px;box-shadow:0 2px 8px rgba(0,0,0,0.2);">
  <button onclick="window.print()" style="background:#2196F3;color:white;border:none;padding:8px 20px;border-radius:8px;cursor:pointer;font-weight:600;font-size:0.9rem;">🖨️ Imprimer / PDF</button>
  <button onclick="downloadHTML()" style="background:#4caf50;color:white;border:none;padding:8px 20px;border-radius:8px;cursor:pointer;font-weight:600;font-size:0.9rem;">💾 Télécharger HTML</button>
</div>
<script>
function downloadHTML() {{
  const blob = new Blob([document.documentElement.outerHTML], {{type:'text/html'}});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'rapport_findme_{now.strftime("%Y%m%d_%H%M")}.html';
  a.click();
}}
</script>
<h1>📋 Rapport de Session — Finder Bot</h1>
"""
        
        # Métadonnées session
        html += '<div class="meta"><table>'
        html += f'<tr><td>📅 Date</td><td>{now.strftime("%d/%m/%Y")}</td></tr>'
        html += f'<tr><td>🕐 Début de session</td><td>{self.session_start[:19].replace("T", " ")}</td></tr>'
        html += f'<tr><td>🕐 Fin de session</td><td>{now.strftime("%H:%M:%S")}</td></tr>'
        html += f'<tr><td>📊 Nombre d\'échanges</td><td>{len(self.responses)}</td></tr>'
        
        if self.context.get('start') and self.context.get('end'):
            html += f'<tr><td>🚗 Trajet</td><td>{self.context["start"]} → {self.context["end"]}</td></tr>'
        if self.context.get('transport'):
            html += f'<tr><td>🚙 Transport</td><td>{self.context["transport"].capitalize()}</td></tr>'
        if self.context.get('duration'):
            html += f'<tr><td>⏱️ Durée déclarée</td><td>{self.context["duration"]} min</td></tr>'
        if self.route_data:
            total_km = self.route_data['total_distance'] / 1000
            total_min = self.route_data['total_duration'] / 60
            html += f'<tr><td>📏 Distance totale</td><td>{total_km:.1f} km</td></tr>'
            html += f'<tr><td>⏱️ Durée estimée trajet</td><td>{total_min:.0f} min</td></tr>'
        if self.context.get('uncertainty_radius'):
            html += f'<tr><td>📐 Rayon d\'incertitude</td><td>{self.context["uncertainty_radius"]} m</td></tr>'
        html += '</table></div>'
        
        # Chronologie
        html += '<h2>📜 Chronologie de la session</h2>'
        html += '<div class="timeline">'
        
        for event in self.session_log:
            etype = event['type']
            data = event['data']
            time_str = event['time']
            
            if etype == 'user_message':
                html += f'<div class="event user"><span class="time">{time_str}</span> 👤 <b>Appelant :</b> {data.get("message", "")}</div>'
            elif etype == 'bot_message':
                msg = data.get("message", "")
                # Tronquer les messages longs
                if len(msg) > 300:
                    msg = msg[:300] + "..."
                html += f'<div class="event bot"><span class="time">{time_str}</span> 🤖 <b>Finder Bot :</b> {msg}</div>'
            elif etype == 'form_update':
                fields = data.get("fields", {})
                details = ", ".join(f"{k}: {v}" for k, v in fields.items() if v)
                html += f'<div class="event system"><span class="time">{time_str}</span> 📝 <b>Formulaire :</b> {details}</div>'
            elif etype == 'position_estimated':
                lat = data.get("lat", "?")
                lon = data.get("lon", "?")
                radius = data.get("radius", "?")
                html += f'<div class="event system"><span class="time">{time_str}</span> 📍 <b>Position estimée :</b> {lat:.5f}, {lon:.5f} (rayon: {radius}m)</div>'
            elif etype == 'investigation_step':
                query = data.get("query", "?")
                candidates_before = data.get("candidates_before", "?")
                candidates_after = data.get("candidates_after", "?")
                html += f'<div class="event system"><span class="time">{time_str}</span> 🔍 <b>Enquête :</b> Recherche "{query}" — {candidates_before} → {candidates_after} candidats</div>'
            elif etype == 'location_confirmed':
                name = data.get("name", "?")
                lat = data.get("lat", "?")
                lon = data.get("lon", "?")
                evidence = data.get("evidence", [])
                html += f'<div class="event success"><span class="time">{time_str}</span> ✅ <b>Localisation confirmée :</b> {name} ({lat:.5f}, {lon:.5f})'
                if evidence:
                    html += f'<br>Preuves : {", ".join(evidence)}'
                html += '</div>'
        
        html += '</div>'
        
        # Résultat final
        html += '<h2>🎯 Résultat</h2>'
        if self.coordinates and self.confidence >= 0.7:
            html += '<div class="result-box">'
            html += f'<h3>✅ Position localisée</h3>'
            html += f'<p><b>Coordonnées :</b> {self.coordinates[0]:.5f}, {self.coordinates[1]:.5f}</p>'
            html += f'<p><b>Confiance :</b> {self.confidence*100:.0f}%</p>'
            if self.context.get('recalage_done'):
                html += '<p><b>Méthode :</b> Recalage par points de repère (mode enquête)</p>'
            html += '</div>'
        elif self.coordinates:
            html += '<div class="result-box no-result">'
            html += f'<h3>⚠️ Position estimée (confiance faible)</h3>'
            html += f'<p><b>Coordonnées :</b> {self.coordinates[0]:.5f}, {self.coordinates[1]:.5f}</p>'
            html += f'<p><b>Confiance :</b> {self.confidence*100:.0f}%</p>'
            html += '</div>'
        else:
            html += '<div class="result-box no-result">'
            html += '<h3>❌ Aucune position déterminée</h3>'
            html += '<p>La session n\'a pas permis de localiser l\'appelant.</p>'
            html += '</div>'
        
        html += f'<div class="footer">Rapport généré automatiquement par Finder Bot — {now.strftime("%d/%m/%Y %H:%M:%S")}</div>'
        html += '</body></html>'
        
        return html
