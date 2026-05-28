"""
Simplifica el GeoJSON de municipios para uso en el browser con Shapely.
Target: < 3 MB
"""

import json
import os
from pathlib import Path
from shapely.geometry import shape, mapping

BASE = Path(r"C:\Users\HP\OneDrive\Desktop\Proyectos")
OPF = BASE / "Observatorio de Presupuesto Fiscal Departamental"
OUT = Path(r"C:\Users\HP\OneDrive\Desktop\Proyectos\observatorio-ofpdt\data")

INE_TO_SIGEP = {
    "011002": "3101", "020807": "1280", "040104": "1401",
    "040801": "3402", "040903": "3401", "070702": "3701", "070705": "1716",
}

TOLERANCE = 0.003  # ~330m at Bolivia's latitude

print("Loading GeoJSON...")
with open(OPF / "_recursos_gis" / "Bolivia_Mapa_Municipal_OEP" / "bolivia_municipios_oep2025.geojson", encoding="utf-8") as f:
    geo = json.load(f)

def round_coords(coords, decimals=4):
    if isinstance(coords[0], (int, float)):
        return [round(coords[0], decimals), round(coords[1], decimals)]
    return [round_coords(c, decimals) for c in coords]

features_out = []
for feat in geo["features"]:
    props = feat["properties"]
    sigep = props.get("sigep") or INE_TO_SIGEP.get(props.get("cod_ine", ""))
    if not sigep:
        continue

    geom = shape(feat["geometry"])
    simplified = geom.simplify(TOLERANCE, preserve_topology=True)

    if simplified.is_empty:
        continue

    mapped = mapping(simplified)
    mapped["coordinates"] = round_coords(mapped["coordinates"])

    features_out.append({
        "type": "Feature",
        "properties": {"s": sigep, "n": props.get("municipio", ""), "d": props.get("dpto", "")},
        "geometry": mapped,
    })

output = {"type": "FeatureCollection", "features": features_out}

out_path = OUT / "municipios_sim.geojson"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, separators=(",", ":"))

size_mb = os.path.getsize(out_path) / 1024 / 1024
print(f"Features: {len(features_out)}")
print(f"Size: {size_mb:.2f} MB")
