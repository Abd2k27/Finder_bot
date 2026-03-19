from typing import Optional, List, Dict  # Annotations de type pour clarté du code

class ChatState:  # Classe de gestion de l'état conversationnel et données collectées
    """État de la conversation et des informations collectées"""
    
    def __init__(self):  # Constructeur: initialise tous les attributs à leur état vide
        self.responses: List[str] = []  # Historique des réponses textuelles de l'utilisateur (ordre chronologique)
        self.coordinates: Optional[tuple] = None  # Position estimée (lat, lon) ou None si pas encore trouvée
        self.confidence: float = 0.0  # Niveau de confiance de la position (0.0 à 1.0, 0=aucune, 1=certaine)
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
            'awaiting_description': False  # True si on attend une description libre après "Aucun"
        }
        self.route_data: Optional[Dict] = None  # Données itinéraire OSRM complet (distances, instructions) ou None
        
        # État de désambiguïsation itérative (quand plusieurs POI candidats)
        self.disambiguation: Dict = {
            'active': False,            # True si en mode désambiguïsation
            'candidates': [],           # Liste des candidats POI restants
            'candidates_with_context': [],  # Candidats enrichis avec POI proches
            'history': [],              # Fil d'Ariane: [{step, candidates, user_input, query}]
            'current_step': 0,          # Étape actuelle dans la désambiguïsation
            'original_query': ''        # Recherche initiale de l'utilisateur
        }
        
    def reset(self):  # Réinitialise complètement l'état (nouvelle conversation)
        """Réinitialiser l'état"""
        self.__init__()  # Rappelle le constructeur pour remettre tous attributs à zéro
    
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
            "is_confident": self.is_position_confident()  # Boolean: confiance ≥ 0.7?
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
    
    # ==================== MÉTHODES DE DÉSAMBIGUÏSATION ====================
    
    def start_disambiguation(self, candidates: List[Dict], query: str):
        """Démarre le mode désambiguïsation avec une liste de candidats."""
        self.disambiguation = {
            'active': True,
            'candidates': candidates.copy(),
            'candidates_with_context': [],
            'history': [{
                'step': 0,
                'candidates': candidates.copy(),
                'user_input': query,
                'query': query
            }],
            'current_step': 0,
            'original_query': query
        }
        print(f"🔀 Désambiguïsation démarrée: {len(candidates)} candidats pour '{query}'")
    
    def refine_disambiguation(self, new_candidates: List[Dict], user_input: str):
        """Affine la désambiguïsation avec de nouveaux candidats filtrés."""
        if not self.disambiguation['active']:
            return
        
        # Sauvegarder l'état actuel dans l'historique
        self.disambiguation['current_step'] += 1
        self.disambiguation['history'].append({
            'step': self.disambiguation['current_step'],
            'candidates': new_candidates.copy(),
            'user_input': user_input,
            'query': self.disambiguation['original_query']
        })
        self.disambiguation['candidates'] = new_candidates.copy()
        
        print(f"🔄 Désambiguïsation affinée: {len(new_candidates)} candidats restants (étape {self.disambiguation['current_step']})")
    
    def go_back_disambiguation(self) -> bool:
        """Retourne à l'étape précédente. Retourne True si possible, False sinon."""
        if not self.disambiguation['active'] or self.disambiguation['current_step'] <= 0:
            return False
        
        # Retour à l'étape précédente
        self.disambiguation['current_step'] -= 1
        previous_state = self.disambiguation['history'][self.disambiguation['current_step']]
        self.disambiguation['candidates'] = previous_state['candidates'].copy()
        
        # Retirer le dernier élément de l'historique
        self.disambiguation['history'] = self.disambiguation['history'][:self.disambiguation['current_step'] + 1]
        
        print(f"⏪ Retour à l'étape {self.disambiguation['current_step']}: {len(self.disambiguation['candidates'])} candidats")
        return True
    
    def end_disambiguation(self, save_for_undo: bool = True):
        """
        Termine le mode désambiguïsation.
        
        Args:
            save_for_undo: Si True, sauvegarde l'état pour permettre un retour
        """
        was_active = self.disambiguation['active']
        
        if save_for_undo and was_active:
            # Sauvegarder pour permettre un "undo"
            self.disambiguation['last_completed'] = {
                'candidates': self.disambiguation.get('candidates_with_context', []).copy() or self.disambiguation.get('candidates', []).copy(),
                'original_query': self.disambiguation.get('original_query', ''),
                'history': self.disambiguation.get('history', []).copy()
            }
        
        self.disambiguation['active'] = False
        self.disambiguation['candidates'] = []
        self.disambiguation['candidates_with_context'] = []
        self.disambiguation['history'] = []
        self.disambiguation['current_step'] = 0
        self.disambiguation['original_query'] = ''
        
        if was_active:
            print("✅ Désambiguïsation terminée (historique sauvegardé pour undo)")
    
    def restore_disambiguation(self) -> bool:
        """
        Restaure la dernière désambiguïsation terminée (undo).
        
        Returns:
            True si restauration réussie, False sinon
        """
        last = self.disambiguation.get('last_completed')
        if not last or not last.get('candidates'):
            return False
        
        # Restaurer l'état
        self.disambiguation = {
            'active': True,
            'candidates': last['candidates'].copy(),
            'candidates_with_context': last['candidates'].copy(),
            'history': last.get('history', []).copy(),
            'current_step': 0,
            'original_query': last.get('original_query', ''),
            'last_completed': None  # Effacer pour éviter double undo
        }
        
        print(f"🔄 Désambiguïsation restaurée: {len(self.disambiguation['candidates'])} candidats")
        return True
    
    def can_restore_disambiguation(self) -> bool:
        """Vérifie si une désambiguïsation peut être restaurée."""
        last = self.disambiguation.get('last_completed')
        return last is not None and len(last.get('candidates', [])) > 0
    
    def is_in_disambiguation(self) -> bool:
        """Vérifie si on est en mode désambiguïsation."""
        return self.disambiguation.get('active', False)
    
    def get_disambiguation_candidates(self) -> List[Dict]:
        """Retourne les candidats actuels."""
        return self.disambiguation.get('candidates', [])