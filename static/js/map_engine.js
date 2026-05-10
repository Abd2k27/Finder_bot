/**
 * MAP ENGINE - Gestion de la carte Leaflet et des couches géographiques
 */

function initMap() {
    map = L.map("map").setView([46.603354, 1.888334], 6);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: "© OpenStreetMap contributors"
    }).addTo(map);
    
    // Layers BOT standards
    poiLayer = L.layerGroup().addTo(map);
    evidenceLayer = L.layerGroup().addTo(map);
    
    // Layers ZONE MANUELLE (isolés)
    manualCircleLayer = L.layerGroup().addTo(map);
    manualPoiLayer = L.layerGroup().addTo(map);
    
    // Layer POSITION CONFIRMÉE (toujours au-dessus)
    confirmedPositionLayer = L.layerGroup().addTo(map);
    
    // Setup listeners pour le dessin
    setupMapDrawEvents();
    
    updateMapStatus("Carte initialisée - Prête à recevoir vos informations");
}

function setupMapDrawEvents() {
    map.on('mousedown', function(e) {
        if (!isDrawingMode) return;
        isDrawing = true;
        drawStartLatLng = e.latlng;
        
        if (userDrawnCircle) {
            map.removeLayer(userDrawnCircle);
        }
        
        userDrawnCircle = L.circle(drawStartLatLng, {
            radius: 0,
            color: '#ff4d4d',
            fillColor: '#ff4d4d',
            fillOpacity: 0.2,
            weight: 3,
            dashArray: '5, 10'
        }).addTo(map);
        
        map.dragging.disable(); 
    });

    map.on('mousemove', function(e) {
        if (!isDrawing || !userDrawnCircle) return;
        const radius = map.distance(drawStartLatLng, e.latlng);
        userDrawnCircle.setRadius(radius);
        updateMapStatus(`Dessin zone : ${Math.round(radius)}m`);
    });

    map.on('mouseup', function() {
        if (!isDrawing) return;
        isDrawing = false;
        map.dragging.enable();
        
        const finalRadius = userDrawnCircle.getRadius();
        if (finalRadius < 10) {
            map.removeLayer(userDrawnCircle);
            userDrawnCircle = null;
            updateMapStatus("Zone trop petite ignorée");
        } else {
            updateMapStatus(`Zone manuelle définie : ${Math.round(finalRadius)}m`);
            showManualControls();
            
            collectedInfo.manual_zone = {
                lat: drawStartLatLng.lat,
                lon: drawStartLatLng.lng,
                radius: Math.round(finalRadius)
            };
            
            updateManualZoneContext();
        }
        toggleDrawMode(false);
    });
}

function toggleDrawMode(forceState = null) {
    const btn = document.getElementById('draw-tool-btn');
    isDrawingMode = (forceState !== null) ? forceState : !isDrawingMode;
    
    if (isDrawingMode) {
        btn.classList.add('active');
        btn.innerHTML = '🛑 Annuler Dessin';
        document.getElementById('map').classList.add('drawing-mode');
        updateMapStatus("Cliquez et glissez pour dessiner un cercle");
    } else {
        btn.classList.remove('active');
        btn.innerHTML = '⭕ Outil Dessin';
        document.getElementById('map').classList.remove('drawing-mode');
        isDrawing = false;
        map.dragging.enable();
    }
}

async function updateManualZoneContext() {
    if (!collectedInfo.manual_zone) return;
    
    try {
        await fetch("/api/update_context", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                ...collectedInfo.manual_zone,
                type: 'manual_zone_update',
                step: step
            })
        });
    } catch (e) {
        console.error("Erreur synchro zone manuelle:", e);
    }
}

function showManualControls() {
    const controls = document.getElementById('manual-circle-controls');
    if (controls) controls.style.display = 'block';
}

async function handleMapUpdates(updates) {
    console.log(`[Debug JS] Traitement de ${updates.length} mise(s) à jour carte`);
    for (const update of updates) {
        console.log("[Debug JS] Exécution action:", update.type);
        switch (update.type) {
            case 'clear_map':
                clearMapElements(update.keep_structure);
                break;
            case 'route':
                collectedInfo.trajet.start = update.start;
                collectedInfo.trajet.end = update.end;
                if (update.route_data) collectedInfo.route_data = update.route_data;
                await showRoute(update.start, update.end, update.route_data, update.route_buffer);
                break;
            case 'position':
                addEstimatedPosition(update.lat, update.lon, update.confidence || 0.5, update.source || "");
                break;
            case 'position_with_radius':
                addPositionWithRadius(update.lat, update.lon, update.radius || 500, update.confidence || 0.5, update.source || "");
                break;
            case 'route_position':
                addRoutePosition(update.lat, update.lon, update.confidence || 0.5, update.route_name || "Route", update.source || "");
                break;
            case 'transport':
                collectedInfo.transport = update.transport;
                break;
            case 'pois':
                addPOIMarkers(update.pois);
                break;
            case 'pois_all':
                addAllPOIDots(update);
                break;
            case 'position_recaled':
                clearRecalageElements();
                const recaledIcon = L.divIcon({ className: 'recaled-marker', html: '<div style="font-size:28px;">🚩</div>', iconSize: [32, 32], iconAnchor: [16, 32] });
                const recaledMarker = L.marker([update.lat, update.lon], { icon: recaledIcon }).addTo(confirmedPositionLayer).bindPopup(`<b>${update.source || update.name || 'Position recalée'}</b><br><small>${update.lat.toFixed(5)}, ${update.lon.toFixed(5)}</small>`).openPopup();
                markers.push(recaledMarker);
                map.setView([update.lat, update.lon], 16);
                collectedInfo.position_estimee = { lat: update.lat, lon: update.lon };
                collectedInfo.confiance = update.confidence || 0.95;
                break;
            case 'candidate_landmark':
                // Nettoyer les POI précédents au début d'un nouveau lot de candidats
                if (update.index === 1 && poiLayer) poiLayer.clearLayers();
                const candidateIcon = L.divIcon({
                    className: 'candidate-marker',
                    html: `<div style="background:#ff9800;color:white;border-radius:50%;width:28px;height:28px;display:flex;align-items:center;justify-content:center;font-weight:bold;font-size:14px;border:2px solid #e65100;box-shadow:0 2px 6px rgba(0,0,0,0.3);">${update.index}</div>`,
                    iconSize: [28, 28], iconAnchor: [14, 14]
                });
                const candidateMarker = L.marker([update.lat, update.lon], { icon: candidateIcon }).bindPopup(`<b>${update.index}. ${update.name}</b><br><small>${update.lat.toFixed(5)}, ${update.lon.toFixed(5)}</small>`);
                if (poiLayer) poiLayer.addLayer(candidateMarker);
                if (update.fitBounds) map.setView([update.lat, update.lon], 15);
                break;
            case 'candidates_all':
                addAllCandidateDots(update);
                break;
            case 'evidence_pois':
                addEvidenceDots(update);
                break;
            case 'search_area_circle':
                handleSearchAreaCircle(update);
                break;
        }
    }
    updateInfoPanel();
}

function clearMapElements(keepStructure = false) {
    if (keepStructure) {
        console.log("🧹 Nettoyage sélectif (maintien trajet et progression)");
        if (poiLayer) poiLayer.clearLayers();
        if (evidenceLayer) evidenceLayer.clearLayers();
        if (confirmedPositionLayer) confirmedPositionLayer.clearLayers();
        circles.forEach(c => { if (map.hasLayer(c)) map.removeLayer(c); });
        circles = [];
        return;
    }

    console.log("🧹 Nettoyage COMPLET de la carte");
    markers.forEach(marker => { if (map.hasLayer(marker)) map.removeLayer(marker); });
    markers = [];
    circles.forEach(circle => { if (map.hasLayer(circle)) map.removeLayer(circle); });
    circles = [];
    if (progressCircle) { if (map.hasLayer(progressCircle)) map.removeLayer(progressCircle); progressCircle = null; }
    
    if (poiLayer) poiLayer.clearLayers();
    if (evidenceLayer) evidenceLayer.clearLayers();
    if (manualCircleLayer) manualCircleLayer.clearLayers();
    if (manualPoiLayer) manualPoiLayer.clearLayers();
    if (confirmedPositionLayer) confirmedPositionLayer.clearLayers();
    
    if (routeBufferLayer) { if (map.hasLayer(routeBufferLayer)) map.removeLayer(routeBufferLayer); routeBufferLayer = null; }
    if (confidenceCircle) { if (map.hasLayer(confidenceCircle)) map.removeLayer(confidenceCircle); confidenceCircle = null; }
    if (routeControl) { map.removeControl(routeControl); routeControl = null; }
}

function clearRecalageElements() {
    circles.forEach(c => { if (map.hasLayer(c)) map.removeLayer(c); });
    circles = [];
    if (confidenceCircle) { map.removeLayer(confidenceCircle); confidenceCircle = null; }
    markers = markers.filter(marker => {
        const el = marker.getElement ? marker.getElement() : marker._icon;
        if (el && el.classList && (el.classList.contains('poi-marker-numbered'))) {
            marker.remove(); return false;
        }
        return true;
    });
    if (poiLayer) poiLayer.clearLayers();
    if (evidenceLayer) evidenceLayer.clearLayers();
}

function handleSearchAreaCircle(update) {
    const isManual = (update.source === 'Zone manuelle');
    const targetPoiLayer = isManual ? manualPoiLayer : poiLayer;

    if (update.clear !== false && !isManual) {
        if (poiLayer) poiLayer.clearLayers();
        if (evidenceLayer) evidenceLayer.clearLayers();
        circles.forEach(c => { if (map.hasLayer(c)) map.removeLayer(c); });
        circles = [];
        markers = markers.filter(marker => {
            const el = marker.getElement ? marker.getElement() : marker._icon;
            if (el && el.classList && el.classList.contains('poi-marker-numbered')) {
                marker.remove(); return false;
            }
            return true;
        });
    }

    const isInvestigation = update.radius && update.radius <= 500;
    const circleColor = isManual ? '#3b82f6' : (isInvestigation ? '#ff9800' : '#3b82f6');
    
    const searchCircle = L.circle([update.lat, update.lon], { 
        radius: update.radius || 1000, color: circleColor, fillColor: circleColor,
        fillOpacity: isInvestigation ? 0.15 : 0.05, weight: isInvestigation ? 3 : 2,
        dashArray: isInvestigation ? '8, 8' : ''
    });

    if (isManual) {
        manualCircleLayer.clearLayers(); 
        manualCircleLayer.addLayer(searchCircle);
    } else {
        searchCircle.addTo(map);
        circles.push(searchCircle);
    }

    if (!isManual && !isInvestigation) {
        confirmedPositionLayer.clearLayers();
        const starIcon = L.divIcon({ 
            className: 'search-star-marker', 
            html: '<div style="font-size:32px; filter: drop-shadow(0 0 5px rgba(0,0,0,0.5));">⭐</div>', 
            iconSize: [40, 40], 
            iconAnchor: [20, 20] 
        });
        L.marker([update.lat, update.lon], { icon: starIcon })
            .addTo(confirmedPositionLayer)
            .bindPopup(`<b>📍 ${update.source || 'Position confirmée'}</b><br><small>${update.lat.toFixed(5)}, ${update.lon.toFixed(5)}</small>`)
            .openPopup();
    }

    if (update.nearby_pois && targetPoiLayer) {
        if (isManual) targetPoiLayer.clearLayers();
        update.nearby_pois.forEach(poi => {
            const poiCircle = L.circleMarker([poi.lat, poi.lon], { 
                radius: 8, color: '#155724', fillColor: '#28a745', 
                fillOpacity: 0.9, weight: 2 
            }).bindPopup(`<b>🔍 Indice : ${poi.name}</b><br>${poi.type}<br><small>${poi.lat.toFixed(5)}, ${poi.lon.toFixed(5)}</small>`);
            targetPoiLayer.addLayer(poiCircle);
        });
    }

    if (update.fitBounds && update.clear !== false) map.fitBounds(searchCircle.getBounds().pad(0.1));
}

async function showRoute(startPlace, endPlace, routeData = null, routeBuffer = null) {
    try {
        updateMapStatus("Recherche des coordonnées et calcul de l'itinéraire...");
        const startCoords = await geocodePlace(startPlace);
        const endCoords = await geocodePlace(endPlace);
        if (!startCoords || !endCoords) { updateMapStatus("Impossible de localiser l'un des lieux du trajet"); return; }
        
        clearMapElements(false); // Nettoyage COMPLET pour une nouvelle route
        
        if (routeBuffer) {
            routeBufferLayer = L.geoJSON(routeBuffer, {
                style: { color: '#3b82f6', weight: 2, opacity: 0.5, fillColor: '#3b82f6', fillOpacity: 0.18, dashArray: '8, 8' }
            }).addTo(map);
        }
        const startMarker = L.marker([startCoords.lat, startCoords.lon], { icon: L.divIcon({ className: 'route-marker', html: '🟢', iconSize: [25, 25] }) }).bindPopup(`🟢 Départ: ${startPlace}`).addTo(map);
        const endMarker = L.marker([endCoords.lat, endCoords.lon], { icon: L.divIcon({ className: 'route-marker', html: '🔴', iconSize: [25, 25] }) }).bindPopup(`🔴 Arrivée: ${endPlace}`).addTo(map);
        markers.push(startMarker, endMarker);
        
        routeControl = L.Routing.control({
            waypoints: [L.latLng(startCoords.lat, startCoords.lon), L.latLng(endCoords.lat, endCoords.lon)],
            routeWhileDragging: false, addWaypoints: false, createMarker: () => null,
            lineOptions: { styles: [{ color: '#667eea', weight: 6, opacity: 0.8 }] },
            show: true, collapsible: true
        }).addTo(map);
        
        routeControl.on('routesfound', function (e) {
            const summary = e.routes[0].summary;
            updateMapStatus(`Itinéraire calculé: ${(summary.totalDistance / 1000).toFixed(1)}km, ${Math.round(summary.totalTime / 60)}min`);
        });
        const group = new L.featureGroup([startMarker, endMarker]);
        map.fitBounds(group.getBounds().pad(0.1));
    } catch (error) { console.error("Erreur itinéraire:", error); updateMapStatus("Erreur lors du calcul"); }
}

async function geocodePlace(placeName) {
    try {
        const response = await fetch('/api/geocode', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ query: placeName + ", France" }) });
        const data = await response.json();
        return data.success ? { lat: data.lat, lon: data.lon } : null;
    } catch (error) { console.error("Erreur géocodage:", error); return null; }
}

function addEstimatedPosition(lat, lon, confidence, source = "") {
    const marker = L.marker([lat, lon], { icon: L.divIcon({ className: 'estimated-marker', html: '📍', iconSize: [30, 30] }) }).bindPopup(`Position estimée<br>Confiance: ${(confidence * 100).toFixed(0)}%<br>${source}<br><small>${lat.toFixed(5)}, ${lon.toFixed(5)}</small>`).addTo(map);
    markers.push(marker);
    map.setView([lat, lon], 13);
}

function addPositionWithRadius(lat, lon, radius, confidence, source = "") {
    clearRecalageElements();
    let circleColor = (radius <= 250) ? '#28a745' : (radius <= 500) ? '#fd7e14' : '#667eea';
    
    if (progressCircle) map.removeLayer(progressCircle);
    progressCircle = L.circle([lat, lon], { radius: radius, color: circleColor, fillColor: circleColor, fillOpacity: 0.2, weight: 2, dashArray: '5, 5' }).addTo(map);
    
    const marker = L.marker([lat, lon], { icon: L.divIcon({ className: 'estimated-marker', html: '🎯', iconSize: [30, 30] }) }).bindPopup(`Position estimée<br>Zone: ${radius}m<br>${source}<br><small>${lat.toFixed(5)}, ${lon.toFixed(5)}</small>`).addTo(map);
    markers.push(marker);
    
    map.setView([lat, lon], map.getBoundsZoom(progressCircle.getBounds()));
    collectedInfo.position_estimee = { lat, lon };
    collectedInfo.confiance = confidence;
}

function addRoutePosition(lat, lon, confidence, routeName, source = "") {
    const marker = L.marker([lat, lon], { icon: L.divIcon({ className: 'route-position-marker', html: '🛣️', iconSize: [30, 30] }) }).bindPopup(`Position sur ${routeName}<br>Confiance: ${(confidence * 100).toFixed(0)}%<br>${source}<br><small>${lat.toFixed(5)}, ${lon.toFixed(5)}</small>`).addTo(map);
    markers.push(marker);
    map.setView([lat, lon], 13);
}

function addPOIMarkers(data) {
    const pois = data.pois || data;
    const shouldFitBounds = data.fitBounds || false;
    markers = markers.filter(marker => {
        const el = marker.getElement ? marker.getElement() : marker._icon;
        if (el && el.classList && el.classList.contains('poi-marker-numbered')) { marker.remove(); return false; }
        return true;
    });
    if (poiLayer) poiLayer.clearLayers();
    const boundsGroup = L.featureGroup();
    pois.forEach(poi => {
        const idx = poi.index || '';
        const poiIcon = L.divIcon({
            className: 'poi-marker-numbered',
            html: `<div style="background:#28a745;color:white;border-radius:50%;width:28px;height:28px;display:flex;align-items:center;justify-content:center;font-weight:bold;font-size:13px;border:2px solid #155724;box-shadow:0 2px 6px rgba(0,0,0,0.3);">${idx}</div>`,
            iconSize: [28, 28],
            iconAnchor: [14, 14]
        });
        const marker = L.marker([poi.lat, poi.lon], { icon: poiIcon })
            .bindPopup(`<b>${idx ? idx + '. ' : ''}${poi.name}</b><br>${poi.type}<br><small>${poi.lat.toFixed(5)}, ${poi.lon.toFixed(5)}</small>`);
        poiLayer.addLayer(marker);
        markers.push(marker);
        boundsGroup.addLayer(marker);
    });
    if (shouldFitBounds && boundsGroup.getLayers().length > 0) map.fitBounds(boundsGroup.getBounds(), { padding: [50, 50], maxZoom: 14 });
}

function addAllPOIDots(data) {
    const pois = data.pois || data;
    // Nettoyer les marqueurs POI précédents
    if (poiLayer) poiLayer.clearLayers();
    markers = markers.filter(marker => {
        const el = marker.getElement ? marker.getElement() : marker._icon;
        if (el && el.classList && el.classList.contains('poi-marker-numbered')) { marker.remove(); return false; }
        return true;
    });
    
    pois.forEach(poi => {
        const dot = L.circleMarker([poi.lat, poi.lon], {
            radius: 6, color: '#155724', fillColor: '#28a745',
            fillOpacity: 0.85, weight: 1.5
        }).bindPopup(`<b>${poi.name}</b><br>${poi.type}<br><small>${poi.lat.toFixed(5)}, ${poi.lon.toFixed(5)}</small>`);
        poiLayer.addLayer(dot);
    });
    
    console.log(`🗺️ ${pois.length} POI affichés comme points verts`);
}

function addAllCandidateDots(data) {
    const pois = data.pois || [];
    // Nettoyer les marqueurs précédents
    if (poiLayer) poiLayer.clearLayers();
    
    const boundsGroup = L.featureGroup();
    pois.forEach(poi => {
        const dot = L.circleMarker([poi.lat, poi.lon], {
            radius: 7, color: '#e65100', fillColor: '#ff9800',
            fillOpacity: 0.85, weight: 2
        }).bindPopup(`<b>${poi.name}</b><br>${poi.type || 'repère'}<br><small>${poi.lat.toFixed(5)}, ${poi.lon.toFixed(5)}</small>`);
        poiLayer.addLayer(dot);
        boundsGroup.addLayer(dot);
    });
    
    if (data.fitBounds && boundsGroup.getLayers().length > 0) {
        map.fitBounds(boundsGroup.getBounds(), { padding: [50, 50], maxZoom: 15 });
    }
    console.log(`🗺️ ${pois.length} candidats affichés comme points orange`);
}

function addEvidenceDots(data) {
    const pois = data.pois || [];
    const label = data.label || 'indice';
    // Nettoyer les preuves précédentes
    if (evidenceLayer) evidenceLayer.clearLayers();
    
    pois.forEach(poi => {
        const dot = L.circleMarker([poi.lat, poi.lon], {
            radius: 5, color: '#0d6e1e', fillColor: '#2ecc71',
            fillOpacity: 0.9, weight: 1.5
        }).bindPopup(`<b>🔍 ${poi.name}</b><br><i>${poi.type || 'indice'}</i><br><small>Preuve : ${label}</small><br><small>${poi.lat.toFixed(5)}, ${poi.lon.toFixed(5)}</small>`);
        evidenceLayer.addLayer(dot);
    });
    
    console.log(`🔍 ${pois.length} preuves affichées comme points verts (${label})`);
}

function displaySearchResult(lat, lon, label) {
    const marker = L.marker([lat, lon], { icon: L.divIcon({ className: 'search-marker', html: '<div style="font-size:28px;">🚩</div>', iconSize: [32, 32], iconAnchor: [16, 32] }) })
        .addTo(map).bindPopup(`<b>Recherche :</b><br>${label}`).openPopup();
    markers.push(marker);
    map.setView([lat, lon], 15);
}
