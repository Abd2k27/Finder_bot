/**
 * CHAT ENGINE - Gestion de la conversation et des interactions avec le bot
 */

function addMessage(content, isUser = false) {
    const chatBox = document.getElementById("chat-box");
    if (!chatBox) return;

    const messageDiv = document.createElement("div");
    messageDiv.className = isUser ? "message user-message" : "message bot-message";
    
    // Formater le contenu :
    // 1. Échapper le HTML pour la sécurité
    let formattedContent = content
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
    
    // 2. Gérer le gras (**texte**)
    formattedContent = formattedContent.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");
    
    const sender = isUser ? 'Vous' : 'Finder Bot';
    messageDiv.innerHTML = `<strong>${sender}:</strong> ${formattedContent}`;
    
    chatBox.appendChild(messageDiv);
    chatBox.scrollTop = chatBox.scrollHeight;
}

async function sendMessage() {
    const input = document.getElementById("user-input");
    const sendBtn = document.getElementById("send-btn");
    const message = input.value.trim();

    if (!message) return;

    addMessage(message, true);
    input.value = "";

    // LOADING STATE
    input.disabled = true;
    if (sendBtn) {
        sendBtn.disabled = true;
        sendBtn.dataset.originalHtml = sendBtn.innerHTML;
        sendBtn.innerHTML = '<span class="spinner"></span>';
    }

    try {
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

        addMessage(data.message);
        step = data.step;

        if (data.map_updates && Array.isArray(data.map_updates)) {
            await handleMapUpdates(data.map_updates);
        }

    } catch (error) {
        console.error("Erreur fetch /chat:", error);
    } finally {
        input.disabled = false;
        if (sendBtn) {
            sendBtn.disabled = false;
            sendBtn.innerHTML = sendBtn.dataset.originalHtml || '✈️';
        }
        input.focus();
    }
}

async function resetChat() {
    try {
        const response = await fetch("/reset", { method: "POST" });
        const data = await response.json();

        document.getElementById("chat-box").innerHTML =
            `<div class="message bot-message"><strong>Finder Bot:</strong> ${data.message}</div>`;

        clearMapElements();
        map.setView([46.603354, 1.888334], 6);

        collectedInfo = {
            trajet: { start: null, end: null },
            transport: null,
            position_estimee: null,
            confiance: 0,
            route_data: null
        };

        // Vider le formulaire
        document.getElementById('form-start').value = "";
        document.getElementById('form-end').value = "";
        document.getElementById('form-transport').value = "";
        document.getElementById('form-duration').value = "";

        updateInfoPanel();
        updateMapStatus("Carte réinitialisée - En attente d'informations");
        step = 0;

    } catch (error) {
        console.error("Erreur lors du reset:", error);
        addMessage("Erreur lors de la réinitialisation", false);
    }
}

async function downloadReport() {
    try {
        addMessage("📋 Génération du rapport en cours...", false);
        window.open('/api/report', '_blank');
    } catch (error) {
        console.error("Erreur rapport:", error);
        addMessage("❌ Erreur lors de la génération du rapport.", false);
    }
}
