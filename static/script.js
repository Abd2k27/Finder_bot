let step = 0;
let map = null;
let routeControl = null;
let markers = [];
let circles = [];
let confidenceCircle = null;  // Cercle de confiance actuel
let poiLayer = null;          // Layer groupe pour les POI candidats
let collectedInfo = {
    trajet: { start: null, end: null },
    transport: null,
    position_estimee: null,
    confiance: 0,
    route_data: null
};

// Initialiser la carte dès le chargement
function initMap() {
    // Centrer sur la France
    map = L.map("map").setView([46.603354, 1.888334], 6);

    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: "© OpenStreetMap contributors"
    }).addTo(map);

    // Initialiser le layer groupe pour les POI candidats
    poiLayer = L.layerGroup().addTo(map);

    updateMapStatus("Carte initialisée - Prête à recevoir vos informations");
}

function updateMapStatus(status) {
    const statusElement = document.getElementById("map-status");
    if (statusElement) {
        statusElement.textContent = status;
    }
}

function updateInfoPanel() {
    const updateElement = (id, value) => {
        const element = document.getElementById(id);
        if (element) {
            element.textContent = value;
            // Met à jour la classe pour feedback visuel si l'info est remplie
            if (value && value !== "Non défini" && value !== "En cours..." && value !== "-") {
                element.parentElement.classList.add("info-defined");
            } else {
                element.parentElement.classList.remove("info-defined");
            }
        }
    };

    updateElement("trajet-value",
        collectedInfo.trajet.start && collectedInfo.trajet.end
            ? `${collectedInfo.trajet.start} → ${collectedInfo.trajet.end}`
            : "Non défini");

    updateElement("transport-value", collectedInfo.transport || "Non défini");

    updateElement("position-value",
        collectedInfo.position_estimee
            ? `${collectedInfo.position_estimee.lat.toFixed(4)}°, ${collectedInfo.position_estimee.lon.toFixed(4)}°`
            : "En cours...");

    updateElement("confiance-value",
        collectedInfo.confiance > 0
            ? `${(collectedInfo.confiance * 100).toFixed(0)}%`
            : "-");
}

function clearMapElements() {
    // Supprimer les marqueurs existants
    markers.forEach(marker => {
        if (map.hasLayer(marker)) {
            map.removeLayer(marker);
        }
    });
    markers = [];

    // Supprimer les cercles existants
    circles.forEach(circle => {
        if (map.hasLayer(circle)) {
            map.removeLayer(circle);
        }
    });
    circles = [];

    // ✅ FIX: Nettoyer le layer groupe POI candidats
    if (poiLayer) {
        poiLayer.clearLayers();
    }

    // ✅ FIX: Supprimer le cercle de confiance
    if (confidenceCircle) {
        if (map.hasLayer(confidenceCircle)) {
            map.removeLayer(confidenceCircle);
        }
        confidenceCircle = null;
    }

    // Supprimer la route existante
    if (routeControl) {
        map.removeControl(routeControl);
        routeControl = null;
    }
}

async function showRoute(startPlace, endPlace, routeData = null) {
    try {
        updateMapStatus("Recherche des coordonnées et calcul de l'itinéraire...");

        const startCoords = await geocodePlace(startPlace);
        const endCoords = await geocodePlace(endPlace);

        if (!startCoords || !endCoords) {
            updateMapStatus("Impossible de localiser l'un des lieux du trajet");
            return;
        }

        clearMapElements();

        const startMarker = L.marker([startCoords.lat, startCoords.lon], {
            icon: L.divIcon({
                className: 'route-marker',
                html: '🟢',
                iconSize: [25, 25]
            })
        })
            .bindPopup(`🟢 Départ: ${startPlace}`)
            .addTo(map);

        const endMarker = L.marker([endCoords.lat, endCoords.lon], {
            icon: L.divIcon({
                className: 'route-marker',
                html: '🔴',
                iconSize: [25, 25]
            })
        })
            .bindPopup(`🔴 Arrivée: ${endPlace}`)
            .addTo(map);

        markers.push(startMarker, endMarker);

        routeControl = L.Routing.control({
            waypoints: [
                L.latLng(startCoords.lat, startCoords.lon),
                L.latLng(endCoords.lat, endCoords.lon)
            ],
            routeWhileDragging: false,
            addWaypoints: false,
            createMarker: () => null,
            lineOptions: {
                styles: [{
                    color: '#667eea',
                    weight: 6,
                    opacity: 0.8
                }]
            },
            show: true,
            collapsible: true
        }).addTo(map);

        routeControl.on('routesfound', function (e) {
            const routes = e.routes;
            const summary = routes[0].summary;

            if (!collectedInfo.route_data && routes[0].instructions) {
                collectedInfo.route_data = {
                    total_distance: summary.totalDistance,
                    total_duration: summary.totalTime,
                    instructions: routes[0].instructions
                };
            }

            updateMapStatus(`Itinéraire calculé: ${(summary.totalDistance / 1000).toFixed(1)}km, ${Math.round(summary.totalTime / 60)}min`);
        });

        const group = new L.featureGroup([startMarker, endMarker]);
        map.fitBounds(group.getBounds().pad(0.1));

    } catch (error) {
        console.error("Erreur lors du tracé de l'itinéraire:", error);
        updateMapStatus("Erreur lors du calcul de l'itinéraire");
    }
}

async function geocodePlace(placeName) {
    // ✅ SÉCURITÉ: Utilise le proxy interne au lieu d'appeler Nominatim directement
    try {
        const response = await fetch('/api/geocode', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query: placeName + ", France" })
        });
        const data = await response.json();

        if (data.success) {
            return {
                lat: data.lat,
                lon: data.lon
            };
        }
    } catch (error) {
        console.error("Erreur géocodage:", error);
    }
    return null;
}

function addEstimatedPosition(lat, lon, confidence, source = "") {
    const marker = L.marker([lat, lon], {
        icon: L.divIcon({
            className: 'estimated-marker',
            html: '📍',
            iconSize: [30, 30]
        })
    })
        .bindPopup(`Position estimée<br>Confiance: ${(confidence * 100).toFixed(0)}%<br>${source}`)
        .addTo(map);

    markers.push(marker);
    map.setView([lat, lon], 13);

    collectedInfo.position_estimee = { lat, lon };
    collectedInfo.confiance = confidence;

    updateMapStatus(`Position estimée avec ${(confidence * 100).toFixed(0)}% de confiance`);
}

function addPositionWithRadius(lat, lon, radius, confidence, source = "") {
    // ✅ SUPPRIMER TOUS LES ANCIENS MARQUEURS DE POSITION
    const positionClasses = ['estimated-marker', 'route-position-marker', 'poi-marker-numbered'];
    markers = markers.filter(marker => {
        const el = marker.getElement ? marker.getElement() : marker._icon;
        if (el && el.classList) {
            for (const cls of positionClasses) {
                if (el.classList.contains(cls)) {
                    marker.remove();
                    return false;
                }
            }
        }
        return true;
    });
    circles.forEach(circle => circle.remove());
    circles = [];
    console.log('[Debug JS] Tous les anciens marqueurs de position supprimés');

    // ✅ COULEUR DYNAMIQUE: vert/orange pour recalage précis
    let circleColor = '#667eea'; // Bleu par défaut
    let fillOpacity = 0.2;

    if (radius <= 250) {
        circleColor = '#28a745'; // Vert pour position précise
        fillOpacity = 0.3;
        console.log('[Debug JS] Cercle VERT (recalage précis)');
    } else if (radius <= 500) {
        circleColor = '#fd7e14'; // Orange pour position assez précise
        fillOpacity = 0.25;
        console.log('[Debug JS] Cercle ORANGE (position assez précise)');
    }

    const marker = L.marker([lat, lon], {
        icon: L.divIcon({
            className: 'estimated-marker',
            html: '🎯',
            iconSize: [30, 30]
        })
    })
        .bindPopup(`Position estimée<br>Zone: ${radius}m<br>${source}`)
        .addTo(map);

    const circle = L.circle([lat, lon], {
        radius: radius,
        color: circleColor,
        fillColor: circleColor,
        fillOpacity: fillOpacity,
        weight: 2,
        dashArray: '5, 5'
    }).addTo(map).bindPopup(`Zone d'incertitude: ${radius}m de rayon`);

    markers.push(marker);
    circles.push(circle);

    // Zoom intelligent pour voir le cercle
    const zoomLevel = map.getBoundsZoom(circle.getBounds());
    map.setView([lat, lon], zoomLevel);

    collectedInfo.position_estimee = { lat, lon };
    collectedInfo.confiance = confidence;

    updateMapStatus(`Position estimée (zone de ${radius}m)`);
}

function addRoutePosition(lat, lon, confidence, routeName, source = "") {
    const marker = L.marker([lat, lon], {
        icon: L.divIcon({
            className: 'route-position-marker',
            html: '🛣️',
            iconSize: [30, 30]
        })
    })
        .bindPopup(`Position sur ${routeName}<br>Confiance: ${(confidence * 100).toFixed(0)}%<br>${source}`)
        .addTo(map);

    markers.push(marker);
    map.setView([lat, lon], 13);

    collectedInfo.position_estimee = { lat, lon };
    collectedInfo.confiance = confidence;

    updateMapStatus(`Position trouvée sur ${routeName}`);
}

function addPOIMarkers(data) {
    const pois = data.pois || data;
    const shouldFitBounds = data.fitBounds || false;
    const estimatedPos = data.estimated_position;

    console.log(`[Debug JS] Ajout de ${pois.length} marqueurs POI numérotés`);

    // ✅ SUPPRIMER LES ANCIENS MARQUEURS POI (garde la position estimée 🎯)
    markers = markers.filter(marker => {
        const el = marker.getElement ? marker.getElement() : marker._icon;
        if (el && el.classList && el.classList.contains('poi-marker-numbered')) {
            marker.remove();
            return false; // Supprimer du tableau
        }
        return true; // Garder les autres marqueurs
    });
    console.log('[Debug JS] Anciens marqueurs POI supprimés');

    // Groupe pour le zoom automatique
    const boundsGroup = L.featureGroup();

    pois.forEach(poi => {
        // Afficher le numéro d'index si disponible, sinon l'emoji
        const displayLabel = poi.index ? `<b>${poi.index}</b>` : '👁️';

        const marker = L.marker([poi.lat, poi.lon], {
            icon: L.divIcon({
                className: 'poi-marker-numbered',
                html: displayLabel,
                iconSize: [30, 30]
            })
        })
            .bindPopup(`
            <b>${poi.index ? poi.index + '. ' : ''}${poi.name}</b><br>
            ${poi.type}<br>
            ${poi.cumulative_distance ? `À ${(poi.cumulative_distance / 1000).toFixed(1)}km du départ` : ''}
        `)
            .addTo(map);

        markers.push(marker);
        boundsGroup.addLayer(marker);
    });

    // Ajouter la position estimée au groupe si disponible
    if (estimatedPos) {
        const posMarker = L.marker([estimatedPos.lat, estimatedPos.lon]);
        boundsGroup.addLayer(posMarker);
    }

    // Zoom automatique pour voir tous les POI
    if (shouldFitBounds && boundsGroup.getLayers().length > 0) {
        map.fitBounds(boundsGroup.getBounds(), { padding: [50, 50], maxZoom: 14 });
        console.log('[Debug JS] Zoom ajusté pour afficher tous les POI');
    }

    updateMapStatus(`${pois.length} repères visuels numérotés affichés`);
}

function addMessage(content, isUser = false) {
    const chatBox = document.getElementById("chat-box");
    const messageDiv = document.createElement("div");
    messageDiv.className = isUser ? "user-message" : "bot-message";
    messageDiv.innerHTML = `<strong>${isUser ? 'Vous' : 'Assistant'}:</strong> ${content}`;
    chatBox.appendChild(messageDiv);
    chatBox.scrollTop = chatBox.scrollHeight;
}

// ✅ FONCTION CORRIGÉE AVEC LOADING STATE
async function sendMessage() {
    const input = document.getElementById("user-input");
    const sendBtn = document.getElementById("send-btn");
    const message = input.value.trim();

    if (!message) return;

    addMessage(message, true);
    input.value = "";

    // ✅ LOADING STATE: Désactiver input et bouton, afficher spinner
    input.disabled = true;
    sendBtn.disabled = true;
    const originalBtnText = sendBtn.innerHTML;
    sendBtn.innerHTML = '<span class="spinner"></span>';

    try {
        // ✅ TIMEOUT: 60s pour le premier chargement OSMnx
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 60000);

        const response = await fetch("/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ response: message, step: step }),
            signal: controller.signal
        });

        clearTimeout(timeoutId);

        const data = await response.json();

        console.log("Données reçues du backend:", data);

        addMessage(data.message);
        step = data.step;

        // ✅ Gestion de "map_updates" (pluriel)
        if (data.map_updates && Array.isArray(data.map_updates)) {

            console.log(`[Debug JS] ${data.map_updates.length} action(s) reçue(s)`);

            for (const update of data.map_updates) {
                console.log("[Debug JS] Exécution action:", update.type);
                switch (update.type) {
                    case 'route':
                        collectedInfo.trajet.start = update.start;
                        collectedInfo.trajet.end = update.end;
                        if (update.route_data) {
                            collectedInfo.route_data = update.route_data;
                        }
                        await showRoute(update.start, update.end, update.route_data);
                        break;

                    case 'position':
                        addEstimatedPosition(
                            update.lat,
                            update.lon,
                            update.confidence || 0.5,
                            update.source || ""
                        );
                        break;

                    case 'position_with_radius':
                        addPositionWithRadius(
                            update.lat,
                            update.lon,
                            update.radius || 500,
                            update.confidence || 0.5,
                            update.source || ""
                        );
                        break;

                    case 'route_position':
                        addRoutePosition(
                            update.lat,
                            update.lon,
                            update.confidence || 0.5,
                            update.route_name || "Route",
                            update.source || ""
                        );
                        break;

                    case 'transport':
                        collectedInfo.transport = update.transport;
                        break;

                    case 'pois':
                        addPOIMarkers(update.pois);
                        break;

                    case 'position_recaled':
                        // ✅ NETTOYER TOUS LES CERCLES (y compris la liste circles)
                        circles.forEach(c => {
                            if (map.hasLayer(c)) map.removeLayer(c);
                        });
                        circles = [];
                        if (confidenceCircle) {
                            map.removeLayer(confidenceCircle);
                            confidenceCircle = null;
                        }

                        // ✅ NETTOYER LES ANCIENS MARQUEURS DE POSITION (🎯, 📍)
                        markers = markers.filter(marker => {
                            const el = marker.getElement ? marker.getElement() : marker._icon;
                            if (el && el.classList && (
                                el.classList.contains('estimated-marker') ||
                                el.classList.contains('poi-marker-numbered')
                            )) {
                                marker.remove();
                                return false;
                            }
                            return true;
                        });

                        // ✅ Nettoyer les anciens marqueurs candidats
                        if (poiLayer) poiLayer.clearLayers();

                        // Creer icone drapeau rouge
                        const recaledIcon = L.divIcon({
                            className: 'recaled-marker',
                            html: '<div style="font-size:28px;">🚩</div>',
                            iconSize: [32, 32],
                            iconAnchor: [16, 32]
                        });

                        // Ajouter marqueur drapeau
                        const recaledMarker = L.marker([update.lat, update.lon], { icon: recaledIcon })
                            .addTo(map)
                            .bindPopup(`<b>${update.source || update.name || 'Position recalée'}</b><br>📍 ${update.lat.toFixed(5)}, ${update.lon.toFixed(5)}`)
                            .openPopup();

                        // ✅ Ajouter à la liste des marqueurs pour tracking
                        markers.push(recaledMarker);

                        // Centrer la vue zoom 16
                        map.setView([update.lat, update.lon], 16);

                        // Mettre à jour les infos collectées
                        collectedInfo.position_estimee = { lat: update.lat, lon: update.lon };
                        collectedInfo.confiance = update.confidence || 0.95;

                        console.log("[Debug JS] Position recalee avec drapeau 🚩");
                        break;

                    case 'candidate_landmark':
                        // Nettoyer avant le premier candidat
                        if (update.index === 1 && poiLayer) {
                            poiLayer.clearLayers();
                        }
                        // Creer icone orange numerotee
                        const candidateIcon = L.divIcon({
                            className: 'candidate-marker',
                            html: `<div style="background:#ff9800;color:white;border-radius:50%;width:28px;height:28px;display:flex;align-items:center;justify-content:center;font-weight:bold;font-size:14px;border:2px solid #e65100;">${update.index}</div>`,
                            iconSize: [28, 28],
                            iconAnchor: [14, 14]
                        });
                        // Ajouter marqueur candidat
                        const candidateMarker = L.marker([update.lat, update.lon], { icon: candidateIcon })
                            .bindPopup(`<b>${update.index}. ${update.name}</b><br>${update.poi_type}<br>📍 ${update.lat.toFixed(5)}, ${update.lon.toFixed(5)}`);
                        if (poiLayer) {
                            poiLayer.addLayer(candidateMarker);
                        } else {
                            candidateMarker.addTo(map);
                        }
                        // Centrer sur le premier marqueur
                        if (update.fitBounds) {
                            map.setView([update.lat, update.lon], 14);
                        }
                        console.log(`[Debug JS] Marqueur candidat #${update.index}: ${update.name}`);
                        break;

                    case 'candidate_circle':
                        // ✅ NOUVEAU: Cercle de désambiguïsation avec POI proches
                        console.log(`[Debug JS] Affichage cercle candidat #${update.index}: ${update.name}`);

                        // Nettoyer avant le premier candidat
                        if (update.index === 1) {
                            if (poiLayer) poiLayer.clearLayers();
                            circles.forEach(c => { if (map.hasLayer(c)) map.removeLayer(c); });
                            circles = [];
                            // Supprimer les anciens marqueurs de position
                            markers = markers.filter(marker => {
                                const el = marker.getElement ? marker.getElement() : marker._icon;
                                if (el && el.classList && (
                                    el.classList.contains('estimated-marker') ||
                                    el.classList.contains('poi-marker-numbered') ||
                                    el.classList.contains('candidate-marker')
                                )) {
                                    marker.remove();
                                    return false;
                                }
                                return true;
                            });
                        }

                        // Couleurs pour différencier les candidats
                        const candidateColors = ['#e74c3c', '#3498db', '#2ecc71', '#9b59b6', '#f39c12', '#1abc9c', '#e91e63', '#00bcd4'];
                        const circleColor = candidateColors[(update.index - 1) % candidateColors.length];

                        // 1. Cercle autour du candidat
                        const disambigCircle = L.circle([update.lat, update.lon], {
                            radius: update.radius || 500,
                            color: circleColor,
                            fillColor: circleColor,
                            fillOpacity: 0.15,
                            weight: 2,
                            dashArray: '5, 5'
                        }).addTo(map).bindPopup(`Candidat #${update.index}: ${update.name}`);
                        circles.push(disambigCircle);

                        // 2. Marqueur numéroté au centre
                        const disambigIcon = L.divIcon({
                            className: 'candidate-marker',
                            html: `<div style="background:${circleColor};color:white;border-radius:50%;width:32px;height:32px;display:flex;align-items:center;justify-content:center;font-weight:bold;font-size:16px;border:3px solid white;box-shadow:0 2px 6px rgba(0,0,0,0.3);">${update.index}</div>`,
                            iconSize: [32, 32],
                            iconAnchor: [16, 16]
                        });

                        // Construire popup avec POI proches
                        let popupContent = `<b>${update.index}. ${update.name}</b><br><i>${update.poi_type}</i>`;
                        if (update.nearby_pois && update.nearby_pois.length > 0) {
                            popupContent += `<br><br><b>À côté:</b><ul style="margin:5px 0;padding-left:15px;">`;
                            update.nearby_pois.forEach(poi => {
                                popupContent += `<li>${poi.name} (${poi.type})</li>`;
                            });
                            popupContent += `</ul>`;
                        }

                        const disambigMarker = L.marker([update.lat, update.lon], { icon: disambigIcon })
                            .bindPopup(popupContent);
                        if (poiLayer) {
                            poiLayer.addLayer(disambigMarker);
                        } else {
                            disambigMarker.addTo(map);
                        }

                        // 3. Ajouter les POI proches comme petits cercles
                        if (update.nearby_pois && Array.isArray(update.nearby_pois)) {
                            update.nearby_pois.forEach(poi => {
                                const nearbyCircle = L.circleMarker([poi.lat, poi.lon], {
                                    radius: 6,
                                    color: circleColor,
                                    fillColor: circleColor,
                                    fillOpacity: 0.7,
                                    weight: 1
                                }).bindPopup(`<b>${poi.name}</b><br>${poi.type}<br><i>Près de candidat #${update.index}</i>`);
                                if (poiLayer) {
                                    poiLayer.addLayer(nearbyCircle);
                                }
                            });
                        }

                        // Zoom pour voir tous les candidats
                        if (update.fitBounds) {
                            map.fitBounds(disambigCircle.getBounds().pad(0.2));
                        }

                        updateMapStatus(`${update.index} candidat(s) affichés - Choisissez ou décrivez un lieu proche`);
                        console.log(`[Debug JS] ⭕ Cercle candidat #${update.index} avec ${update.nearby_pois?.length || 0} POI proches`);
                        break;

                    case 'search_area_circle':
                        // ✅ NOUVEAU: Cercle 1km + étoile violette + POI verts (style map_rennes_osm)
                        console.log('[Debug JS] Affichage cercle de recherche 1km style OSM');

                        // Nettoyer les anciens éléments
                        if (poiLayer) poiLayer.clearLayers();
                        circles.forEach(c => { if (map.hasLayer(c)) map.removeLayer(c); });
                        circles = [];
                        markers = markers.filter(marker => {
                            const el = marker.getElement ? marker.getElement() : marker._icon;
                            if (el && el.classList && (
                                el.classList.contains('estimated-marker') ||
                                el.classList.contains('poi-marker-numbered') ||
                                el.classList.contains('search-star-marker')
                            )) {
                                marker.remove();
                                return false;
                            }
                            return true;
                        });

                        // 1. Cercle bleu de recherche 1km
                        const searchCircle = L.circle([update.lat, update.lon], {
                            radius: update.radius || 1000,
                            color: 'blue',
                            fillColor: 'blue',
                            fillOpacity: 0.1,
                            weight: 2
                        }).addTo(map).bindPopup(`Zone de recherche (${update.radius || 1000}m)`);
                        circles.push(searchCircle);

                        // 2. Étoile violette pour le POI trouvé (style map_rennes_osm)
                        const starIcon = L.divIcon({
                            className: 'search-star-marker',
                            html: '<div style="font-size:28px;text-shadow:2px 2px 4px rgba(0,0,0,0.5);">⭐</div>',
                            iconSize: [32, 32],
                            iconAnchor: [16, 16]
                        });
                        const starMarker = L.marker([update.lat, update.lon], { icon: starIcon })
                            .addTo(map)
                            .bindPopup(`<b>📍 ${update.source || 'Position recalée'}</b><br>${update.poi_type || ''}<br>Coordonnées: ${update.lat.toFixed(5)}, ${update.lon.toFixed(5)}`)
                            .openPopup();
                        markers.push(starMarker);

                        // 3. POI environnants comme petits cercles verts
                        if (update.nearby_pois && Array.isArray(update.nearby_pois)) {
                            console.log(`[Debug JS] Ajout de ${update.nearby_pois.length} POI verts`);
                            update.nearby_pois.forEach(poi => {
                                const poiCircle = L.circleMarker([poi.lat, poi.lon], {
                                    radius: 5,
                                    color: 'green',
                                    fillColor: 'green',
                                    fillOpacity: 0.6,
                                    weight: 2
                                }).bindPopup(`<b>${poi.name}</b><br>${poi.type}`);
                                poiLayer.addLayer(poiCircle);
                            });
                        }

                        // Zoom pour voir le cercle entier
                        if (update.fitBounds) {
                            map.fitBounds(searchCircle.getBounds().pad(0.1));
                        }

                        // Mettre à jour infos
                        collectedInfo.position_estimee = { lat: update.lat, lon: update.lon };
                        collectedInfo.confiance = update.confidence || 0.85;
                        updateMapStatus(`Position recalée: ${update.source || 'POI trouvé'} (zone 1km)`);

                        console.log(`[Debug JS] ⭐ Cercle 1km affiché avec ${update.nearby_pois?.length || 0} POI verts`);
                        break;
                }
            }

            // Mettre à jour le panneau d'info UNE SEULE FOIS
            updateInfoPanel();
        } else {
            console.log("[Debug JS] Aucune action 'map_updates' trouvée.");
        }

        if (data.entities && Object.keys(data.entities).some(key => data.entities[key].length > 0)) {
            console.log("Entités LLM extraites:", data.entities);
        }

    } catch (error) {
        // Erreur console uniquement, pas de message dans le chat
        console.error("Erreur fetch /chat:", error);
    } finally {
        // ✅ RÉACTIVER les éléments après la réponse
        input.disabled = false;
        sendBtn.disabled = false;
        sendBtn.innerHTML = originalBtnText;
        input.focus();
    }
}

async function resetChat() {
    try {
        const response = await fetch("/reset", { method: "POST" });
        const data = await response.json();

        document.getElementById("chat-box").innerHTML =
            `<div class="bot-message"><strong>Assistant:</strong> ${data.message}</div>`;

        clearMapElements();
        map.setView([46.603354, 1.888334], 6);

        collectedInfo = {
            trajet: { start: null, end: null },
            transport: null,
            position_estimee: null,
            confiance: 0,
            route_data: null
        };

        updateInfoPanel();
        updateMapStatus("Carte réinitialisée - En attente d'informations");
        step = 0;

    } catch (error) {
        console.error("Erreur lors du reset:", error);
        addMessage("Erreur lors de la réinitialisation", false);
    }
}

function debugRouteData() {
    if (collectedInfo.route_data) {
        console.log("Données de route disponibles:", collectedInfo.route_data);
        console.log(`Distance totale: ${collectedInfo.route_data.total_distance}m`);
        console.log(`Durée totale: ${collectedInfo.route_data.total_duration}s`);
        console.log(`Nombre d'instructions: ${collectedInfo.route_data.instructions?.length || 0}`);
    } else {
        console.log("Aucune donnée de route disponible");
    }
}

document.getElementById("user-input").addEventListener("keypress", function (e) {
    if (e.key === "Enter") {
        sendMessage();
    }
});

document.addEventListener('keydown', function (e) {
    if (e.ctrlKey && e.key === 'd') {
        e.preventDefault();
        debugRouteData();
    }
});

document.addEventListener('DOMContentLoaded', function () {
    console.log("🗺️ Initialisation de l'interface de localisation");
    initMap();
    resetChat();

    console.log("🤖 Bot de Localisation v3.0 - Multi-transport Fix");
    console.log("🔧 Raccourcis: Ctrl+D pour debug route. Vérifiez la console (F12) !");
});