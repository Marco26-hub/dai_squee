"""One-time import of the original apartment photographs into managed storage."""
import base64
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server

PHOTOS = {
    "Suite Max": [
        ("rooms--max-DSC_0152-scaled.jpg", "Il terrazzo privato della Suite Max"),
        ("rooms--max-DSC_0160-scaled.jpg", "Le colline dal terrazzo della Suite Max"),
        ("rooms--max-CAMERA-SUITE-MAX.jpg", "La camera della Suite Max"),
        ("rooms--max-DSC_0173-scaled.jpg", "La camera mansardata"),
        ("rooms--max-CUCINA-SUITE.jpg", "La cucina della Suite Max"),
        ("rooms--max-BAGNO-SUITE.jpg", "Il bagno della Suite Max"),
    ],
    "Michele": [
        ("rooms--michele-CAMERA-4.jpg", "La camera dell'appartamento Michele"),
        ("rooms--michele-APP-MICHELE-CUCINA.jpg", "La cucina dell'appartamento Michele"),
        ("rooms--michele-CAMERA-3.jpg", "Gli interni dell'appartamento Michele"),
        ("rooms--michele-DSC_0278-scaled.jpg", "Uno scorcio dell'appartamento Michele"),
    ],
    "Rosa e Romeo": [
        ("rooms--rosa-e-romeo-CAMERA-ROSA-E-ROMEO.jpg", "La camera di Rosa e Romeo"),
        ("rooms--rosa-e-romeo-DSC_0350-scaled.jpg", "La camera e l'accesso verso la terrazza"),
        ("rooms--rosa-e-romeo-ROSA-E-ROMEO-KITCHEN.jpg", "La cucina di Rosa e Romeo"),
        ("rooms--rosa-e-romeo-ZONA-GIORNO.jpg", "La zona giorno di Rosa e Romeo"),
    ],
}

if __name__ == "__main__":
    server.init()
    with server.db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT 1 FROM settings WHERE key='original_photos_imported'").fetchone():
            print("Original photographs already imported; no changes made.")
        elif conn.execute("SELECT 1 FROM apartment_photos LIMIT 1").fetchone():
            print("Managed photos already exist; import skipped to preserve owner content.")
        else:
            count = 0
            for room, photos in PHOTOS.items():
                for position, (filename, caption) in enumerate(photos):
                    data = (server.ROOT / "assets/images/scraped" / filename).read_bytes()
                    pid = hashlib.sha256(filename.encode()).hexdigest()[:24]
                    conn.execute("INSERT INTO apartment_photos VALUES (?,?,?,?,?,?,?)",(pid,room,"cover" if position==0 else "gallery",caption,"image/jpeg",base64.b64encode(data).decode(),server.now()))
                    count += 1
            conn.execute("INSERT INTO settings VALUES (?,?)",("original_photos_imported",json.dumps(True)))
            print(str(count)+" original apartment photographs imported.")
