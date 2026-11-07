#!/usr/bin/env bash
# =============================================================================
# scripts/01_download.sh — Etapa 1 del pipeline: descarga de entradas crudas
# =============================================================================
#
# Qué hace:
#   1. Descarga las cuatro teselas Copernicus GLO-30 que cubren el límite de
#      Bogotá desde el bucket público S3 (sin credenciales).
#   2. Descarga los límites administrativos ADM1 de Colombia (geoBoundaries
#      gbOpen, licencia ODbL 1.0, URL pinneada a un commit) y extrae el único
#      feature de Bogotá D.C. (shapeISO == "CO-DC") a data/limite_bogota.geojson.
#   3. Valida el DEM (tamaño exacto + cabecera TIFF) y deja un resumen con
#      rutas, tamaños, sha256 y bbox del límite.
#
# Qué NO hace (a propósito):
#   - No recorta, no reproyecta, no genera salidas. Eso es de scripts/02_*.
#   - No usa GDAL ni Python de terceros: solo bash, curl y python3 (stdlib).
#
# Idempotente: las teselas completas no se vuelven a descargar; el límite se
# regenera siempre (es barato, ~9 MB de descarga).
#
# Uso:
#   bash scripts/01_download.sh            # normal (reanuda/omite si ya existe)
#   bash scripts/01_download.sh --force    # fuerza re-descarga del DEM
#   bash scripts/01_download.sh --help     # ayuda
#
# Dependencias (todas preinstaladas en ubuntu-latest, headless):
#   - bash, curl, python3 (solo json y sys), coreutils (mkdir, stat, head, od,
#     du, sha256sum, mktemp, rm)
#   - Red hacia copernicus-dem-30m.s3.amazonaws.com y github.com
#
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Variables de configuración
# ---------------------------------------------------------------------------
# El límite cruza los meridianos 75°O/74°O y el paralelo 4°N; requiere cuatro
# celdas de 1°x1°. Tamaños verificados por HTTP HEAD.
DEM_NOMBRES=(
    "Copernicus_DSM_COG_10_N04_00_W075_00_DEM"
    "Copernicus_DSM_COG_10_N03_00_W075_00_DEM"
    "Copernicus_DSM_COG_10_N04_00_W074_00_DEM"
    "Copernicus_DSM_COG_10_N03_00_W074_00_DEM"
)
DEM_TAMANOS=(42787983 43112475 43029370 43813417)
DEM_PATHS=(
    "data/dem_bogota_n04_w075.tif"
    "data/dem_bogota_n03_w075.tif"
    "data/dem_bogota_n04_w074.tif"
    "data/dem_bogota_n03_w074.tif"
)
BUCKET_DEM="https://copernicus-dem-30m.s3.amazonaws.com"

# geoBoundaries gbOpen COL ADM1, pinneado al commit 9469f09 (33 departamentos).
# Verificado: HTTP 200, 8.898.990 bytes, FeatureCollection con 1 feature CO-DC.
ADM1_URL="https://github.com/wmgeolab/geoBoundaries/raw/9469f09/releaseData/gbOpen/COL/ADM1/geoBoundaries-COL-ADM1.geojson"
ADM1_ISO="CO-DC"
LIMIT_PATH="data/limite_bogota.geojson"

# Límite duro del proyecto: ningún archivo en data/ puede pasar de 100 MB
# (es el límite por archivo de GitHub). El DEM son ~43 MB, así que sobra margen.
MAX_BYTES=$((100 * 1024 * 1024))

# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
# Trabajamos siempre desde la raíz del repo, para que las rutas relativas
# (data/...) no dependan del directorio desde el que se invoque el script.
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

uso() {
    cat <<'AYUDA'
Uso: bash scripts/01_download.sh [--force]

  --force   Vuelve a descargar el DEM aunque ya exista con el tamaño correcto.
  --help    Muestra esta ayuda.

Descarga cuatro teselas Copernicus GLO-30 y el límite administrativo de Bogotá
D.C. en data/. No recorta ni reproyecta.
AYUDA
}

error() {
    echo "ERROR: $*" >&2
}

# Comprueba que un comando exista antes de usarlo.
requiere() {
    if ! command -v "$1" >/dev/null 2>&1; then
        error "falta el comando '$1'. Instálalo antes de continuar."
        exit 1
    fi
}

# Valida el DEM: tamaño exacto y cabecera TIFF.
# Cabeceras válidas: "II*\0" (little endian) o "MM\0*" (big endian),
# o sea, en hexadecimal: 49492a00 o 4d4d002a.
valida_dem() {
    local fichero="$1" esperado="$2" tamano magia

    if [ ! -f "$fichero" ]; then
        error "no existe el DEM en $fichero"
        return 1
    fi

    tamano="$(stat -c %s "$fichero" 2>/dev/null || echo -1)"
    if [ "$tamano" -ne "$esperado" ]; then
        error "tamaño incorrecto en $fichero: $tamano bytes (esperados $esperado)."
        return 1
    fi

    magia="$(head -c 4 "$fichero" | od -An -tx1 | tr -d ' \n')"
    case "$magia" in
        49492a00 | 4d4d002a)
            return 0
            ;;
        *)
            error "cabecera TIFF inválida en $fichero (bytes: $magia; esperados 49492a00 o 4d4d002a)."
            return 1
            ;;
    esac
}

# Falla si un archivo supera el límite de 100 MB.
comprueba_limite() {
    local fichero="$1" tamano
    tamano="$(stat -c %s "$fichero")"
    if [ "$tamano" -gt "$MAX_BYTES" ]; then
        error "$fichero pesa $tamano bytes y supera el límite de 100 MB por archivo."
        return 1
    fi
}

# ---------------------------------------------------------------------------
# Argumentos
# ---------------------------------------------------------------------------
FORCE=0
for arg in "$@"; do
    case "$arg" in
        --force) FORCE=1 ;;
        -h | --help)
            uso
            exit 0
            ;;
        *)
            error "argumento no reconocido: $arg"
            uso >&2
            exit 2
            ;;
    esac
done

# ---------------------------------------------------------------------------
# Comprobaciones previas
# ---------------------------------------------------------------------------
requiere curl
requiere python3
requiere sha256sum
requiere stat
requiere od

mkdir -p data

# Temporales en un directorio propio: se borra siempre al salir (éxito o error).
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
ADM1_TMP="$TMP_DIR/col_adm1.geojson"
BBOX_TMP="$TMP_DIR/bbox.txt"

# ---------------------------------------------------------------------------
# 1) DEM Copernicus GLO-30
# ---------------------------------------------------------------------------
echo "==> [1/2] DEM Copernicus GLO-30 (4 teselas)"

for i in "${!DEM_NOMBRES[@]}"; do
    nombre="${DEM_NOMBRES[$i]}"
    esperado="${DEM_TAMANOS[$i]}"
    destino="${DEM_PATHS[$i]}"
    url="${BUCKET_DEM}/${nombre}/${nombre}.tif"

    if [ "$FORCE" -eq 0 ] && [ -f "$destino" ] \
        && [ "$(stat -c %s "$destino" 2>/dev/null || echo -1)" -eq "$esperado" ]; then
        echo "    Ya existe $destino; se omite."
    else
        tam_local="$(stat -c %s "$destino" 2>/dev/null || echo 0)"
        if [ -f "$destino" ] && { [ "$FORCE" -eq 1 ] || [ "$tam_local" -gt "$esperado" ]; }; then
            rm -f "$destino"
        fi
        echo "    Descargando $destino"
        curl --fail --location --retry 3 --continue-at - \
            --silent --show-error --output "$destino" "$url"
    fi

    if ! valida_dem "$destino" "$esperado"; then
        error "la tesela no es válida; se elimina $destino."
        rm -f "$destino"
        exit 1
    fi
    comprueba_limite "$destino"
    echo "    OK: $destino ($esperado bytes, TIFF válido)."
done

# ---------------------------------------------------------------------------
# 2) Límite administrativo de Bogotá D.C.
# ---------------------------------------------------------------------------
echo "==> [2/2] Límite administrativo de Bogotá D.C. (geoBoundaries ADM1)"

echo "    Descargando ADM1 de Colombia (33 departamentos, ~9 MB)..."
curl --fail --location --retry 3 \
    --silent --show-error \
    --output "$ADM1_TMP" \
    "$ADM1_URL"

echo "    Filtrando el feature shapeISO == \"$ADM1_ISO\"..."
# El heredoc va entre comillas ('PY') para que bash no expanda nada del código.
# Argumentos: <entrada> <salida> <archivo temporal para el bbox> <shapeISO>.
python3 - "$ADM1_TMP" "$LIMIT_PATH" "$BBOX_TMP" "$ADM1_ISO" <<'PY'
import json
import sys

if len(sys.argv) != 5:
    sys.exit("Uso: python3 - <adm1.geojson> <salida.geojson> <bbox.txt> <shapeISO>")

origen, destino, bbox_salida, shape_iso = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]

# utf-8-sig tolera un BOM si el servidor lo añadiera (GitHub raw no lo hace).
try:
    with open(origen, encoding="utf-8-sig") as fh:
        datos = json.load(fh)
except json.JSONDecodeError as exc:
    sys.exit(f"ERROR: {origen} no es JSON válido: {exc}")
except OSError as exc:
    sys.exit(f"ERROR: no se pudo leer {origen}: {exc}")

if datos.get("type") != "FeatureCollection":
    sys.exit(f"ERROR: se esperaba una FeatureCollection en {origen} y llegó {datos.get('type')!r}.")

features = datos.get("features") or []

# Bogotá D.C. es el único feature con shapeISO "CO-DC".
coincidencias = [
    f for f in features
    if isinstance(f, dict) and (f.get("properties") or {}).get("shapeISO") == shape_iso
]

if len(coincidencias) != 1:
    iso = sorted({
        (f.get("properties") or {}).get("shapeISO") or "?"
        for f in features if isinstance(f, dict)
    })
    sys.exit(
        f"ERROR: se esperaba exactamente 1 feature con shapeISO={shape_iso!r} en {origen} "
        f"y se encontraron {len(coincidencias)}. "
        f"shapeISO presentes: {', '.join(iso)}"
    )

feature = coincidencias[0]
geometria = feature.get("geometry")
if not geometria or not geometria.get("coordinates"):
    sys.exit(f"ERROR: el feature {shape_iso} no tiene geometría con coordenadas.")

# bbox: recorremos las coordenadas sin importar si es Polygon o MultiPolygon.
xs, ys = [], []


def recorrer(nodo):
    if isinstance(nodo, (list, tuple)):
        if nodo and all(isinstance(v, (int, float)) for v in nodo):
            xs.append(nodo[0])
            ys.append(nodo[1])
        else:
            for hijo in nodo:
                recorrer(hijo)


recorrer(geometria["coordinates"])

if not xs or not ys:
    sys.exit(f"ERROR: no se pudieron extraer coordenadas del feature {shape_iso}.")

# Escribimos una FeatureCollection con ese único feature (compacta: sin
# indentar el archivo queda en ~110 KB en vez de varios MB).
with open(destino, "w", encoding="utf-8") as fh:
    json.dump(
        {"type": "FeatureCollection", "features": [feature]},
        fh,
        ensure_ascii=False,
        separators=(",", ":"),
    )

# bbox en formato "oeste sur este norte" (WGS84, grados decimales).
with open(bbox_salida, "w", encoding="utf-8") as fh:
    fh.write(f"{min(xs):.6f} {min(ys):.6f} {max(xs):.6f} {max(ys):.6f}\n")

nombre = (feature.get("properties") or {}).get("shapeName")
print(f"    OK: feature {nombre!r} (shapeISO={shape_iso}) escrito en {destino}")
PY

if [ ! -s "$LIMIT_PATH" ]; then
    error "el filtro no generó $LIMIT_PATH (archivo vacío o inexistente)."
    exit 1
fi
comprueba_limite "$LIMIT_PATH"

BBOX="$(cat "$BBOX_TMP")"

# ---------------------------------------------------------------------------
# Resumen
# ---------------------------------------------------------------------------
echo
echo "================= RESUMEN (etapa 01_download) ================="
echo "Archivos generados:"
printf '  %s\n' "${DEM_PATHS[@]}" "$LIMIT_PATH"
echo
echo "Tamaños en disco:"
du -h "${DEM_PATHS[@]}" "$LIMIT_PATH"
echo
echo "SHA-256:"
sha256sum "${DEM_PATHS[@]}" "$LIMIT_PATH"
echo
echo "bbox del límite (WGS84, oeste sur este norte): $BBOX"
echo "=============================================================="
echo "Listo. El recorte, la reproyección y los derivados son de la etapa 02."

# =============================================================================
# Cómo se ejecuta y qué necesita (resumen rápido)
# =============================================================================
#
# Ejecución (siempre desde la raíz del repo, en Ubuntu headless):
#   bash scripts/01_download.sh            # normal: reanuda u omite si ya existe
#   bash scripts/01_download.sh --force    # fuerza la re-descarga del DEM
#   bash scripts/01_download.sh --help     # ayuda
#
# Salidas (todas en data/):
#   data/dem_bogota_n{03,04}_w{074,075}.tif   cuatro teselas GLO-30
#   data/limite_bogota.geojson     FeatureCollection con 1 feature (CO-DC)
#
# Dependencias:
#   - bash (set -euo pipefail), curl, python3 (solo json y sys)
#   - coreutils: mkdir, mktemp, stat, head, od, tr, du, sha256sum, cat, rm
#   Todas vienen preinstaladas en ubuntu-latest. No hace falta GDAL, ni
#   credenciales de AWS: el bucket copernicus-dem-30m es público.
#
# Códigos de salida:
#   0 = éxito | 1 = error de descarga/validación | 2 = argumento inválido
#
# Reejecutar el script es seguro: si el DEM ya está completo no se descarga
# otra vez, y el límite se regenera siempre desde el geojson original.
# =============================================================================
