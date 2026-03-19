"""
Package des gestionnaires de requêtes pour l'API.
"""

from .action_handlers import (
    handle_finish,
    handle_clarify,
    handle_reject_pois,
    handle_show_all_pois,
    handle_confirm_choice
)

from .recalage_handlers import (
    handle_route_recalage,
    handle_landmark_recalage,
    handle_disambiguation_refinement
)

from .position_handlers import (
    calculate_position_from_duration,
    calculate_position_from_distance,
    suggest_nearby_pois
)

__all__ = [
    'handle_finish',
    'handle_clarify', 
    'handle_reject_pois',
    'handle_show_all_pois',
    'handle_confirm_choice',
    'handle_route_recalage',
    'handle_landmark_recalage',
    'handle_disambiguation_refinement',
    'calculate_position_from_duration',
    'calculate_position_from_distance',
    'suggest_nearby_pois'
]
