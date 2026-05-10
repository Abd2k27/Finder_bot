import os
import sqlite3
import osmium
import sys
import glob

# --- CONFIGURATION ---
# Recherche automatique du premier fichier .osm.pbf dans le dossier data/
def get_osm_file():
    osm_files = glob.glob("data/*.osm.pbf")
    if not osm_files:
        return "data/france-latest.osm.pbf" # Valeur par défaut si rien n'est trouvé
    return osm_files[0]

OSM_FILE = get_osm_file()
DB_FILE = "data/pois_local.db"

# Cas particuliers à prendre même sans nom (souvent identifiés par 'ref')
STRUCTURAL_TAGS = {
    'highway': ['motorway_junction', 'milestone', 'toll_gantry'],
    'railway': ['level_crossing', 'station', 'stop'],
    'man_made': ['water_tower', 'lighthouse', 'tower', 'windmill', 'antenna']
}

class POIHandler(osmium.SimpleHandler):
    def __init__(self, db_conn):
        super(POIHandler, self).__init__()
        self.db = db_conn
        self.cursor = self.db.cursor()
        self.count = 0
        self._setup_db()

    def _setup_db(self):
        """Crée la table SQLite avec indexation optimisée"""
        self.cursor.execute("DROP TABLE IF EXISTS pois")
        self.cursor.execute("""
            CREATE TABLE pois (
                id INTEGER PRIMARY KEY,
                name TEXT,
                type TEXT,
                category TEXT,
                lat REAL,
                lon REAL,
                tags TEXT
            )
        """)
        self.cursor.execute("CREATE INDEX idx_coords ON pois (lat, lon)")
        self.cursor.execute("CREATE INDEX idx_name ON pois (name)")
        self.db.commit()

    def _process_object(self, obj, lat, lon):
        """Logique commune pour Nodes et Ways"""
        if not obj.tags:
            return

        name = obj.tags.get('name', obj.tags.get('ref'))
        poi_type = None
        poi_cat = None

        # STRATÉGIE 1: Si l'objet a un NOM, on le prend d'office (très inclusif)
        if name:
            # On cherche la catégorie principale pour le type
            for key in ['amenity', 'shop', 'tourism', 'historic', 'leisure', 'man_made', 'railway', 'natural', 'waterway', 'highway', 'office', 'military', 'craft']:
                if key in obj.tags:
                    poi_type = obj.tags[key]
                    poi_cat = key
                    break
            
            # Si on a un nom mais pas de catégorie connue, on le prend quand même comme 'other'
            if not poi_type:
                poi_type = 'landmark'
                poi_cat = 'other'
        
        # STRATÉGIE 2: Objets structurels (même sans nom)
        else:
            for key, values in STRUCTURAL_TAGS.items():
                if key in obj.tags and obj.tags[key] in values:
                    poi_type = obj.tags[key]
                    poi_cat = key
                    name = f"{poi_type} {obj.tags.get('ref', '')}".strip().title()
                    break

        if poi_type:
            # Nettoyage
            name = name.strip()
            tags_json = str({t.k: t.v for t in obj.tags})
            
            try:
                self.cursor.execute(
                    "INSERT INTO pois (name, type, category, lat, lon, tags) VALUES (?, ?, ?, ?, ?, ?)",
                    (name, poi_type, poi_cat, lat, lon, tags_json)
                )
                self.count += 1
                if self.count % 10000 == 0:
                    print(f"📦 Extraits : {self.count} POI...", end='\r')
                    self.db.commit()
            except Exception as e:
                pass

    def node(self, n):
        """Traitement des points"""
        self._process_object(n, n.location.lat, n.location.lon)

    def way(self, w):
        """Traitement des surfaces/lignes (commerces en bâtiments, etc.)"""
        if not w.tags:
            return
        
        # On calcule le centre approximatif de la surface
        try:
            # On prend le centre de la bounding box des points du Way
            lats = [p.lat for p in w.nodes if p.location.valid()]
            lons = [p.lon for p in w.nodes if p.location.valid()]
            if lats and lons:
                center_lat = sum(lats) / len(lats)
                center_lon = sum(lons) / len(lons)
                self._process_object(w, center_lat, center_lon)
        except:
            pass

def run_ingestion():
    if not os.path.exists(OSM_FILE):
        print(f"❌ Erreur : Fichier {OSM_FILE} introuvable.")
        return

    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)

    print(f"🚀 Démarrage de l'ingestion FULL POI (Nodes + Ways) de {OSM_FILE}...")
    db = sqlite3.connect(DB_FILE)
    
    # ACTIVER LE MODE WAL (Permet de lire la base pendant que le script écrit dedans)
    db.execute("PRAGMA journal_mode=WAL")
    
    handler = POIHandler(db)
    
    try:
        # 'locations=True' est CRITIQUE pour avoir les coordonnées dans les Ways
        handler.apply_file(OSM_FILE, locations=True)
        db.commit()
        print(f"\n✅ Ingestion terminée : {handler.count} POI extraits dans {DB_FILE}")
    except Exception as e:
        print(f"\n❌ Erreur pendant l'ingestion : {e}")
    finally:
        db.close()

if __name__ == "__main__":
    run_ingestion()
