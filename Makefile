# Variables
PYTHON = python
PIP = pip
APP = main.py
PID_FILE = .server.pid

.PHONY: help install run stop clean ingest dev

help:
	@echo "Usage:"
	@echo "  make install    Installe l'environnement virtuel et les dépendances"
	@echo "  make run        Lance le Finder Bot en arrière-plan"
	@echo "  make dev        Lance le Finder Bot en mode interactif (reload)"
	@echo "  make stop       Arrête le serveur Finder Bot"
	@echo "  make clean      Supprime les fichiers temporaires et les caches"
	@echo "  make ingest     Lance l'ingestion de la base OSM locale"

install:
	python3 -m venv .venv
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	@echo "✅ Environnement prêt. N'oubliez pas de configurer votre .env"

run:
	@echo "🚀 Démarrage du Finder Bot..."
	nohup $(PYTHON) $(APP) > server.log 2>&1 & echo $$! > $(PID_FILE)
	@echo "📡 Serveur lancé (PID: $$(cat $(PID_FILE))). Logs dans server.log"

dev:
	$(PYTHON) $(APP)

stop:
	@if [ -f $(PID_FILE) ]; then \
		kill $$(cat $(PID_FILE)) && rm $(PID_FILE) && echo "🛑 Serveur arrêté."; \
	else \
		echo "⚠️  Aucun fichier PID trouvé. Tentative de pkill..."; \
		pkill -f $(APP) || echo "❌ Aucun processus trouvé."; \
	fi

ingest:
	$(PYTHON) scripts/ingest_osm.py

clean:
	rm -rf __pycache__
	rm -rf */__pycache__
	rm -rf */*/__pycache__
	rm -rf .pytest_cache
	rm -rf cache/*
	rm -f server.log
	rm -f $(PID_FILE)
	find . -type f -name "*.pyc" -delete
	@echo "🧹 Nettoyage terminé."
