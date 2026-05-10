/**
 * MAIN ENTRY POINT - Variables globales et initialisation
 */

// --- Variables Globales ---
let step = 0;
let map = null;
let routeControl = null;
let markers = [];
let circles = [];
let progressCircle = null; // Cercle de progression théorique (bleu clair)
let routeBufferLayer = null;
let confidenceCircle = null;
let poiLayer = null;
let evidenceLayer = null;

// Nouvelles variables pour le dessin manuel
let userDrawnCircle = null;
let manualCircleLayer = null; // Calque pour le cercle de recherche du bot (basé sur zone manuelle)
let manualPoiLayer = null;    // Calque pour les POI trouvés (basé sur zone manuelle)
let isDrawingMode = false;
let isDrawing = false;
let drawStartLatLng = null;

let collectedInfo = {
    trajet: { start: null, end: null },
    transport: null,
    position_estimee: null,
    confiance: 0,
    route_data: null,
    manual_zone: null // Pour stocker les infos du cercle [lat, lon, radius]
};

// --- Initialisation ---
document.addEventListener('DOMContentLoaded', function () {
    console.log("🗺️ Initialisation de l'interface de localisation");
    
    // Initialiser les composants (définis dans les autres fichiers js/)
    initMap();
    resetChat();

    // Listeners Recherche Adresse
    const searchInput = document.getElementById("address-search");
    if (searchInput) {
        searchInput.addEventListener("keypress", function (e) {
            if (e.key === "Enter") searchAddress();
        });
        searchInput.addEventListener("input", handleAutocomplete);
    }

    // Listeners Chat
    const userInput = document.getElementById("user-input");
    if (userInput) {
        userInput.addEventListener("keypress", function (e) {
            if (e.key === "Enter") sendMessage();
        });
    }

    // Cacher l'autocomplétion si on clique ailleurs
    document.addEventListener("click", function(e) {
        if (!e.target.closest(".map-search-container")) {
            hideAutocomplete();
        }
    });

    // Debug Route (Ctrl+D)
    document.addEventListener('keydown', function (e) {
        if (e.ctrlKey && e.key === 'd') {
            e.preventDefault();
            if (typeof debugRouteData === 'function') debugRouteData();
        }
    });

    console.log("🤖 Bot de Localisation v3.1 - Architecture modulaire");
});

function debugRouteData() {
    if (collectedInfo.route_data) {
        console.log("Données de route disponibles:", collectedInfo.route_data);
    } else {
        console.log("Aucune donnée de route disponible");
    }
}
