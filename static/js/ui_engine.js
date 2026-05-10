/**
 * UI ENGINE - Gestion de l'interface, des formulaires et de l'autocomplétion
 */

function updateMapStatus(status) {
    const statusElement = document.getElementById("map-status");
    if (statusElement) {
        statusElement.textContent = status;
    }
}

async function updateInfoPanel() {
    const updateElement = (id, value) => {
        const element = document.getElementById(id);
        if (element) {
            element.textContent = value;
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
    
    await syncFormFromState();
}

async function syncFormFromState() {
    try {
        const response = await fetch('/api/state');
        const state = await response.json();
        
        if (state.start) document.getElementById('form-start').value = state.start;
        if (state.end) document.getElementById('form-end').value = state.end;
        if (state.transport) document.getElementById('form-transport').value = state.transport;
        if (state.duration) document.getElementById('form-duration').value = state.duration;
        
    } catch (error) {
        console.error("Erreur synchro formulaire:", error);
    }
}

async function applyForm() {
    const applyBtn = document.getElementById("apply-form-btn");
    const originalBtnText = applyBtn.innerHTML;
    
    const formData = {
        start: document.getElementById('form-start').value || null,
        end: document.getElementById('form-end').value || null,
        transport: document.getElementById('form-transport').value || null,
        duration: parseInt(document.getElementById('form-duration').value) || null,
        step: step
    };

    applyBtn.disabled = true;
    applyBtn.innerHTML = '<span class="spinner"></span>';

    try {
        const response = await fetch("/api/update_context", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(formData)
        });

        const data = await response.json();
        addMessage(data.message);
        step = data.step;

        if (data.map_updates && Array.isArray(data.map_updates)) {
            await handleMapUpdates(data.map_updates);
        }

    } catch (error) {
        console.error("Erreur applyForm:", error);
    } finally {
        applyBtn.disabled = false;
        applyBtn.innerHTML = originalBtnText;
    }
}

// --- GESTION CERCLE MANUEL ---
function toggleManualCircle() {
    const btn = document.getElementById('btn-toggle-circle');
    
    // Basculer l'affichage des layers manuels
    const layers = [userDrawnCircle, manualCircleLayer, manualPoiLayer];
    let isCurrentlyVisible = false;
    
    // On vérifie si au moins un élément est visible
    if (userDrawnCircle && map.hasLayer(userDrawnCircle)) isCurrentlyVisible = true;
    if (manualCircleLayer && map.hasLayer(manualCircleLayer)) isCurrentlyVisible = true;
    if (manualPoiLayer && map.hasLayer(manualPoiLayer)) isCurrentlyVisible = true;

    if (isCurrentlyVisible) {
        if (userDrawnCircle) map.removeLayer(userDrawnCircle);
        if (manualCircleLayer) map.removeLayer(manualCircleLayer);
        if (manualPoiLayer) map.removeLayer(manualPoiLayer);
        btn.innerHTML = "Afficher";
    } else {
        if (userDrawnCircle) userDrawnCircle.addTo(map);
        if (manualCircleLayer) manualCircleLayer.addTo(map);
        if (manualPoiLayer) manualPoiLayer.addTo(map);
        btn.innerHTML = "Masquer";
    }
}

async function deleteManualCircle() {
    // 1. Supprimer le cercle rouge (manuel)
    if (userDrawnCircle) {
        if (map.hasLayer(userDrawnCircle)) map.removeLayer(userDrawnCircle);
        userDrawnCircle = null;
    }
    
    // 2. Nettoyer UNIQUEMENT les calques manuels
    if (manualCircleLayer) manualCircleLayer.clearLayers();
    if (manualPoiLayer) manualPoiLayer.clearLayers();
    
    collectedInfo.manual_zone = null;
    document.getElementById('manual-circle-controls').style.display = 'none';
    
    // 3. Notifier le bot
    try {
        await fetch("/api/update_context", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                type: 'manual_zone_delete',
                step: step
            })
        });
        updateMapStatus("Éléments manuels supprimés");
    } catch (e) {}
}

async function searchAddress() {
    const searchInput = document.getElementById("address-search");
    const query = searchInput.value.trim();

    if (!query) return;

    hideAutocomplete();
    updateMapStatus(`Recherche de : ${query}...`);

    try {
        const response = await fetch('/api/geocode', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query: query })
        });
        const data = await response.json();

        if (data.success) {
            displaySearchResult(data.lat, data.lon, query);
        } else {
            updateMapStatus(`Non trouvé : ${query}`);
        }
    } catch (error) {
        console.error("Erreur recherche adresse:", error);
    }
}

// AUTOCOMPLÉTION
let autocompleteTimeout = null;

function handleAutocomplete() {
    const input = document.getElementById("address-search");
    const query = input.value.trim();

    clearTimeout(autocompleteTimeout);

    if (query.length < 3) {
        hideAutocomplete();
        return;
    }

    autocompleteTimeout = setTimeout(async () => {
        try {
            const response = await fetch(`/api/autocomplete?query=${encodeURIComponent(query)}`);
            const data = await response.json();

            if (data && data.length > 0) {
                showAutocomplete(data);
            } else {
                hideAutocomplete();
            }
        } catch (error) {
            console.error("Erreur autocomplete:", error);
        }
    }, 400);
}

function showAutocomplete(results) {
    const container = document.getElementById("autocomplete-results");
    container.innerHTML = "";
    container.style.display = "block";

    results.forEach(item => {
        const div = document.createElement("div");
        div.className = "autocomplete-item";
        div.innerHTML = `📍 ${item.display_name}`;
        div.onclick = () => {
            document.getElementById("address-search").value = item.display_name;
            displaySearchResult(item.lat, item.lon, item.display_name);
            hideAutocomplete();
        };
        container.appendChild(div);
    });
}

function hideAutocomplete() {
    const container = document.getElementById("autocomplete-results");
    if (container) {
        container.style.display = "none";
    }
}
