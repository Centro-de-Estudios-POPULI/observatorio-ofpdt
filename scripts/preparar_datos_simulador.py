"""
Consolida los 4 indicadores para el simulador de coparticipación:
1. Población (Censo INE 2024)
2. Extensión territorial (km², calculada desde GeoJSON OEP 2025)
3. NBI - Necesidades Básicas Insatisfechas (Censo 2024)
4. Fragilidad fiscal (% ingresos por transferencias, SIGEP 2024)

Salida: data/entidades_simulador.json
"""

import json
import csv
import os
import math
from pathlib import Path
from shapely.geometry import shape
from pyproj import Transformer

BASE = Path(r"C:\Users\HP\OneDrive\Desktop\Proyectos")
OPF = BASE / "Observatorio de Presupuesto Fiscal Departamental"
CENSO = BASE / "Retrato_Censal_2024" / "Censo2024_Tabulados"
OUT = Path(r"C:\Users\HP\OneDrive\Desktop\Proyectos\observatorio-ofpdt\data")
OUT.mkdir(parents=True, exist_ok=True)

# ── 1. Load GeoJSON and calculate areas ──
print("Loading GeoJSON (339 features)...")
with open(OPF / "_recursos_gis" / "Bolivia_Mapa_Municipal_OEP" / "bolivia_municipios_oep2025.geojson", encoding="utf-8") as f:
    geo = json.load(f)

# Map cod_ine -> sigep for features missing sigep
INE_TO_SIGEP = {
    "011002": "3101",   # Huacaya (GAIOC)
    "020807": "1280",   # Taraco
    "040104": "1401",   # Paria → check
    "040801": "3402",   # Salinas de Garci Mendoza (GAIOC)
    "040903": "3401",   # Chipaya (GAIOC)
    "070702": "3701",   # Charagua Iyambae (GAIOC)
    "070705": "1716",   # Gutiérrez
}

# UTM zone transformer (Bolivia spans UTM 19S-21S, use 20S as central)
transformer = Transformer.from_crs("EPSG:4326", "EPSG:32720", always_xy=True)

areas = {}
geo_features = {}
for feat in geo["features"]:
    props = feat["properties"]
    sigep = props.get("sigep") or INE_TO_SIGEP.get(props.get("cod_ine", ""))
    if not sigep:
        print(f"  SKIP: {props.get('municipio')} - no sigep/ine match")
        continue

    geom = shape(feat["geometry"])
    # Reproject to UTM 20S for area calculation
    if geom.geom_type == "Polygon":
        coords = [list(transformer.transform(x, y)) for x, y in geom.exterior.coords]
        from shapely.geometry import Polygon
        projected = Polygon(coords)
    elif geom.geom_type == "MultiPolygon":
        from shapely.geometry import MultiPolygon, Polygon as Poly
        polys = []
        for poly in geom.geoms:
            coords = [list(transformer.transform(x, y)) for x, y in poly.exterior.coords]
            polys.append(Poly(coords))
        projected = MultiPolygon(polys)
    else:
        print(f"  SKIP: {props.get('municipio')} - unexpected geometry type {geom.geom_type}")
        continue

    area_km2 = projected.area / 1e6
    areas[sigep] = round(area_km2, 2)
    geo_features[sigep] = {
        "municipio": props.get("municipio", ""),
        "dpto": props.get("dpto", ""),
    }

print(f"  Areas calculated: {len(areas)} features")
print(f"  Total area: {sum(areas.values()):,.0f} km2 (Bolivia ~ 1,098,581 km2)")

# ── 2. Load population + NBI from censo ──
print("Loading censo 2024 + NBI...")
with open(CENSO / "censo_municipios_con_nbi.json", encoding="utf-8") as f:
    censo = json.load(f)
print(f"  Censo entries: {len(censo)}")

# ── 3. Load catálogo for metadata ──
print("Loading catálogo municipios...")
with open(OPF / "municipios" / "_datos" / "catalogo_municipios.json", encoding="utf-8") as f:
    catalogo = json.load(f)
print(f"  Catálogo entries: {len(catalogo)}")

# ── 4. Calculate fiscal fragility ──
print("Calculating fiscal fragility (343 entities)...")
csv_dir = OPF / "municipios" / "_datos" / "csv"

fragilidad = {}
for csv_file in sorted(csv_dir.glob("entidad_*_ingreso.csv")):
    sigep = csv_file.stem.split("_")[1]
    try:
        with open(csv_file, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        # Use most recent year available (prefer 2024, fallback 2023)
        for year in ["2024", "2023", "2022"]:
            year_rows = [r for r in rows if r["gestion"] == year]
            if year_rows:
                total = sum(float(r["percibido"] or 0) for r in year_rows)
                transf = sum(float(r["percibido"] or 0) for r in year_rows
                             if "TRANSFERENCIA" in (r.get("rubro_desc_tipo") or "").upper())
                if total > 0:
                    fragilidad[sigep] = {
                        "pct_transferencias": round(transf / total * 100, 1),
                        "ingreso_total": round(total),
                        "transferencias": round(transf),
                        "gestion": int(year),
                    }
                break
    except Exception as e:
        print(f"  Error {sigep}: {e}")

print(f"  Fiscal fragility calculated: {len(fragilidad)} entities")

# ── 5. Consolidate ──
print("Consolidating...")
entidades = []
missing_censo = []
missing_area = []
missing_fiscal = []

all_sigeps = set(catalogo.keys()) | set(areas.keys())
for sigep in sorted(all_sigeps, key=lambda x: int(x)):
    cat = catalogo.get(sigep, {})
    geo_f = geo_features.get(sigep, {})
    cen = censo.get(sigep, {})
    fis = fragilidad.get(sigep, {})

    nombre = cat.get("municipio") or geo_f.get("municipio") or cen.get("nombre", "")
    dpto = cat.get("dpto") or geo_f.get("dpto") or cen.get("dpto", "")

    # Determine type
    nombre_largo = cat.get("nombre", "")
    if "Indígena" in nombre_largo or "Originario" in nombre_largo:
        tipo = "GAIOC"
    else:
        tipo = "Municipio"

    pob = cen.get("pob_total")
    area = areas.get(sigep)
    nbi = cen.get("pct_nbi_pobre")
    frag = fis.get("pct_transferencias")

    if pob is None:
        missing_censo.append(sigep)
    if area is None:
        missing_area.append(sigep)
    if frag is None:
        missing_fiscal.append(sigep)

    entry = {
        "sigep": sigep,
        "nombre": nombre,
        "dpto": dpto.upper() if dpto else "",
        "tipo": tipo,
        "poblacion": pob,
        "area_km2": area,
        "nbi_pobre": nbi,
        "fragilidad_fiscal": frag,
    }

    # Extra NBI components for tooltip
    if cen:
        entry["nbi_moderada"] = cen.get("pct_nbi_moderada")
        entry["nbi_indigente"] = cen.get("pct_nbi_indigente")
        entry["nbi_marginal"] = cen.get("pct_nbi_marginal")

    if fis:
        entry["gestion_fiscal"] = fis.get("gestion")

    entidades.append(entry)

# Department mapping
DPTOS = {
    "CHUQUISACA": "11", "LA PAZ": "12", "COCHABAMBA": "13",
    "ORURO": "14", "POTOSI": "15", "TARIJA": "16",
    "SANTA CRUZ": "17", "BENI": "18", "PANDO": "19"
}
for e in entidades:
    e["cod_dep"] = DPTOS.get(e["dpto"], "")

# Stats
valid = [e for e in entidades if all(e.get(k) is not None for k in ["poblacion", "area_km2", "nbi_pobre", "fragilidad_fiscal"])]
print(f"\n  Total entities: {len(entidades)}")
print(f"  Complete (4 indicators): {len(valid)}")
print(f"  Missing censo: {len(missing_censo)} → {missing_censo[:10]}")
print(f"  Missing area: {len(missing_area)} → {missing_area[:10]}")
print(f"  Missing fiscal: {len(missing_fiscal)} → {missing_fiscal[:10]}")

# Summary by department
print("\n  By department:")
from collections import Counter
dpto_counts = Counter(e["dpto"] for e in entidades)
for d, c in sorted(dpto_counts.items()):
    pob = sum(e["poblacion"] or 0 for e in entidades if e["dpto"] == d)
    print(f"    {d}: {c} entities, pop {pob:,}")

# ── 6. Save ──
output = {
    "meta": {
        "fuentes": {
            "poblacion": "Censo INE 2024",
            "area": "GeoJSON OEP 2025 (reproyectado a UTM 20S)",
            "nbi": "Censo INE 2024 - NBI método directo",
            "fragilidad": "SIGEP - percibido más reciente disponible",
        },
        "total_entidades": len(entidades),
        "completas": len(valid),
        "generado": "2026-05-28",
    },
    "entidades": entidades,
}

with open(OUT / "entidades_simulador.json", "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print(f"\nSaved to {OUT / 'entidades_simulador.json'}")
print(f"  File size: {os.path.getsize(OUT / 'entidades_simulador.json') / 1024:.1f} KB")
