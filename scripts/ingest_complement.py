"""
Script d'ingestion COMPLÉMENTAIRE — Ajoute les catégories manquantes.

Lit le même fichier .osm.pbf mais extrait UNIQUEMENT les catégories
non couvertes par ingest_osm.py (landuse, power, barrier, aeroway, place).
Les données sont AJOUTÉES à la base existante (pas de DROP TABLE).

Usage:
    python scripts/ingest_complement.py
"""

import os
import sqlite3
import osmium
import glob

# --- CONFIGURATION ---
def get_osm_file():
    osm_files = glob.glob("data/*.osm.pbf")
    if not osm_files:
        return "data/france-latest.osm.pbf"
    return osm_files[0]

OSM_FILE = get_osm_file()
DB_FILE = "data/pois_local.db"

# Catégories DÉJÀ importées par ingest_osm.py (on les IGNORE)
ALREADY_IMPORTED = {
    'amenity', 'shop', 'tourism', 'historic', 'leisure',
    'man_made', 'railway', 'natural', 'waterway', 'highway',
    'office', 'military', 'craft'
}

# NOUVELLES catégories à importer
NEW_CATEGORIES = {
    'landuse': None,     # Toutes les valeurs (farmland, meadow, vineyard, forest, etc.)
    'power': ['tower', 'pole', 'substation', 'plant', 'generator', 'line'],
    'barrier': ['toll_booth', 'gate', 'lift_gate', 'border_control'],
    'aeroway': ['aerodrome', 'helipad', 'terminal'],
    'place': ['hamlet', 'village', 'locality', 'isolated_dwelling', 'neighbourhood'],
}

# Landuse intéressants (on filtre les moins utiles)
LANDUSE_USEFUL = {
    'farmland', 'meadow', 'vineyard', 'orchard', 'forest',
    'industrial', 'commercial', 'retail', 'quarry', 'cemetery',
    'military', 'reservoir', 'landfill', 'allotments',
    'recreation_ground', 'farmyard'
}


class ComplementHandler(osmium.SimpleHandler):
    def __init__(self, db_conn):
        super(ComplementHandler, self).__init__()
        self.db = db_conn
        self.cursor = self.db.cursor()
        self.count = 0

    def _process_object(self, obj, lat, lon):
        """Extrait les POI des nouvelles catégories uniquement."""
        if not obj.tags:
            return

        name = obj.tags.get('name', obj.tags.get('ref'))
        poi_type = None
        poi_cat = None

        # Vérifier les NOUVELLES catégories
        for key, allowed_values in NEW_CATEGORIES.items():
            if key in obj.tags:
                value = obj.tags[key]
                
                # Filtre landuse: garder seulement les utiles
                if key == 'landuse' and value not in LANDUSE_USEFUL:
                    continue
                
                # Filtre par valeurs autorisées (si spécifiées)
                if allowed_values and value not in allowed_values:
                    continue
                
                poi_type = value
                poi_cat = key
                
                # Générer un nom si absent
                if not name:
                    if key == 'landuse':
                        # Les landuse sans nom sont trop génériques → skip
                        continue
                    elif key == 'power':
                        name = f"Pylône {obj.tags.get('ref', '')}".strip()
                        if name == 'Pylône':
                            name = f"Pylône électrique"
                    elif key == 'barrier':
                        name = f"Péage {obj.tags.get('ref', '')}".strip()
                    elif key == 'aeroway':
                        name = value.replace('_', ' ').title()
                    elif key == 'place':
                        continue  # Places sans nom = inutile
                
                break

        # Ignorer si c'est une catégorie déjà importée
        for key in ALREADY_IMPORTED:
            if key in obj.tags and poi_cat != key:
                # L'objet a aussi un tag de catégorie déjà importée → probablement déjà en base
                if not poi_cat:
                    return

        if poi_type and name:
            tags_json = str({t.k: t.v for t in obj.tags})
            try:
                self.cursor.execute(
                    "INSERT INTO pois (name, type, category, lat, lon, tags) VALUES (?, ?, ?, ?, ?, ?)",
                    (name.strip(), poi_type, poi_cat, lat, lon, tags_json)
                )
                self.count += 1
                if self.count % 5000 == 0:
                    print(f"📦 Ajoutés : {self.count} POI complémentaires...", end='\r')
                    self.db.commit()
            except Exception:
                pass

    def node(self, n):
        self._process_object(n, n.location.lat, n.location.lon)

    def way(self, w):
        if not w.tags:
            return
        try:
            lats = [p.lat for p in w.nodes if p.location.valid()]
            lons = [p.lon for p in w.nodes if p.location.valid()]
            if lats and lons:
                center_lat = sum(lats) / len(lats)
                center_lon = sum(lons) / len(lons)
                self._process_object(w, center_lat, center_lon)
        except:
            pass


def run_complement():
    if not os.path.exists(OSM_FILE):
        print(f"❌ Fichier {OSM_FILE} introuvable.")
        return

    if not os.path.exists(DB_FILE):
        print(f"❌ Base {DB_FILE} introuvable. Lancez d'abord ingest_osm.py")
        return

    # Compter les POI existants
    db = sqlite3.connect(DB_FILE)
    db.execute("PRAGMA journal_mode=WAL")
    cursor = db.cursor()
    cursor.execute("SELECT COUNT(*) FROM pois")
    existing_count = cursor.fetchone()[0]
    print(f"📊 Base existante : {existing_count:,} POI")
    print(f"🚀 Ingestion complémentaire depuis {OSM_FILE}...")
    print(f"📋 Nouvelles catégories : {', '.join(NEW_CATEGORIES.keys())}")

    handler = ComplementHandler(db)

    try:
        handler.apply_file(OSM_FILE, locations=True)
        db.commit()

        # Recompter
        cursor.execute("SELECT COUNT(*) FROM pois")
        new_total = cursor.fetchone()[0]
        added = new_total - existing_count

        print(f"\n✅ Ingestion complémentaire terminée !")
        print(f"   + {added:,} nouveaux POI ajoutés")
        print(f"   = {new_total:,} POI au total")

        # Stats des nouvelles catégories
        print(f"\n📊 Détail des ajouts :")
        for cat in NEW_CATEGORIES:
            cursor.execute("SELECT COUNT(*) FROM pois WHERE category = ?", (cat,))
            cnt = cursor.fetchone()[0]
            if cnt > 0:
                print(f"   {cat:15s} : {cnt:>8,}")

    except Exception as e:
        print(f"\n❌ Erreur : {e}")
    finally:
        db.close()


if __name__ == "__main__":
    run_complement()
