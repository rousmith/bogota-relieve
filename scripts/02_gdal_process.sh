#!/usr/bin/env bash
# =============================================================================
# scripts/02_gdal_process.sh — Etapa 2: procesamiento GIS con GDAL
# =============================================================================
#
# Qué hace:
#   1. Valida las entradas de data/ (DEM Copernicus y límite de Bogotá).
#   2. Comprueba que el DEM cubra TODO el límite administrativo. Si faltan
#      teselas de 1°x1° de Copernicus, las lee directamente del bucket público
#      con /vsicurl (no escribe nunca en data/). Se puede desactivar con
#      --sin-remoto.
#   3. Reproyecta el límite a EPSG:9377 y calcula una rejilla canónica de 30 m
#      que contiene el límite completo.
#   4. Genera, con esa misma rejilla (píxeles alineados 1:1):
#        - output/dem_bogota_9377.tif          DEM recortado al polígono
#        - output/hillshade_bogota_9377.tif    sombreado (Int16, nodata -9999)
#        - output/hillshade_bogota.png         sombreado RGBA (transparente fuera)
#        - output/textura_bogota.png           color-relief hipsométrico RGBA
#        - output/heightmap_bogota_16bit.png   heightmap 16 bits para Blender
#        - output/heightmap_bogota_16bit.tif   heightmap georreferenciado
#        - output/mascara_bogota_8bit.png      máscara 255 dentro / 0 fuera
#        - output/rampa_hipsometrica.txt       paleta usada (la reutiliza 03)
#        - output/limite_bogota_9377.gpkg      límite reproyectado
#        - output/relieve_bogota.json          metadatos para las etapas 03/04
#   5. Valida las salidas (CRS, tipo de dato, dimensiones, rango de elevación).
#
# Qué NO hace (a propósito):
#   - No escribe en data/: las entradas son de solo lectura.
#   - No genera el póster ni el .glb: eso es de scripts/03_* y scripts/04_*.
#
# Uso:
#   bash scripts/02_gdal_process.sh
#   bash scripts/02_gdal_process.sh --sin-remoto      # exige teselas locales
#   bash scripts/02_gdal_process.sh --max-px 2048     # más detalle de heightmap
#   bash scripts/02_gdal_process.sh --res 20          # otra resolución (m)
#   bash scripts/02_gdal_process.sh --help
#
# Dependencias (Ubuntu 24.04 headless, sin GUI):
#   sudo apt-get update
#   sudo apt-get install -y --no-install-recommends gdal-bin python3
#   # GDAL 3.8.4 (gdal-bin), Python 3.12. No hace falta QGIS para esta etapa.
#
#   Comandos de GDAL usados: gdalinfo, gdalsrsinfo, gdalbuildvrt, gdalwarp,
#   gdaldem, gdal_translate, gdal_rasterize, gdaltransform, ogr2ogr, ogrinfo.
#   Python 3 solo con la biblioteca estándar (json, hashlib, math, subprocess).
#
# Salidas: solo en output/ (nunca se sobrescribe data/).
#
# Códigos de salida:
#   0 = éxito | 1 = error de datos/procesamiento | 2 = argumento inválido
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Rutas y parámetros
# ---------------------------------------------------------------------------
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

OUT_DIR="${OUT_DIR:-output}"
LIMITE_IN="${LIMITE_IN:-data/limite_bogota.geojson}"
DEM_GLOB="${DEM_GLOB:-data/dem_bogota_*.tif}"

CRS_TRABAJO="EPSG:9377"          # MAGNA-SIRGAS / Origen Nacional (metros)
RES_M="${RES_M:-30}"             # resolución de trabajo en metros
NODATA="${NODATA:--9999}"        # nodata del DEM recortado
HEIGHTMAP_MAX_PX="${HEIGHTMAP_MAX_PX:-1024}"  # lado mayor del heightmap
PERMITIR_REMOTO="${PERMITIR_REMOTO:-1}"       # 1 = completar con /vsicurl
BUCKET_COPERNICUS="https://copernicus-dem-30m.s3.amazonaws.com"

uso() {
    cat <<'AYUDA'
Uso: bash scripts/02_gdal_process.sh [opciones]

Opciones:
  --sin-remoto       No descarga teselas faltantes con /vsicurl; falla si el
                     DEM local no cubre todo el límite.
  --max-px N         Lado mayor del heightmap en píxeles (por defecto 1024).
  --res N            Resolución de trabajo en metros (por defecto 30).
  -h | --help        Muestra esta ayuda.

Procesa el DEM y el límite de data/ y escribe todos los derivados en output/.
CRS de trabajo obligatorio: EPSG:9377 (MAGNA-SIRGAS / Origen Nacional).
AYUDA
}

error() {
    echo "ERROR: $*" >&2
}

# Comprueba que un comando exista antes de usarlo.
requiere() {
    if ! command -v "$1" >/dev/null 2>&1; then
        error "falta el comando '$1'. Instala las dependencias con:"
        echo "       sudo apt-get update && sudo apt-get install -y --no-install-recommends gdal-bin python3" >&2
        exit 1
    fi
}

# Comprueba que un archivo exista y no esté vacío.
exige_archivo() {
    local fichero="$1" pista="$2"
    if [ ! -s "$fichero" ]; then
        error "no existe o está vacío: $fichero"
        if [ -n "$pista" ]; then
            echo "       $pista" >&2
        fi
        exit 1
    fi
}

# URL pública de una tesela Copernicus GLO-30 a partir de su nombre.
url_tesela() {
    local nombre="$1"
    echo "${BUCKET_COPERNICUS}/${nombre}/${nombre}.tif"
}

# Nombre local sugerido (coherente con scripts/01_download.sh): n03_w075.
nombre_local_tesela() {
    local nombre="$1" ns ew
    ns="$(echo "$nombre" | sed -E 's/.*_([NS][0-9]{2})_00_[EW][0-9]{3}_00_DEM/\1/')"
    ew="$(echo "$nombre" | sed -E 's/.*_[NS][0-9]{2}_00_([EW][0-9]{3})_00_DEM/\1/')"
    echo "data/dem_bogota_${ns,,}_${ew,,}.tif"
}

# ---------------------------------------------------------------------------
# Argumentos
# ---------------------------------------------------------------------------
while [ $# -gt 0 ]; do
    case "$1" in
        --sin-remoto)
            PERMITIR_REMOTO=0
            shift
            ;;
        --max-px)
            if [ $# -lt 2 ]; then
                error "--max-px necesita un valor."
                exit 2
            fi
            HEIGHTMAP_MAX_PX="$2"
            shift 2
            ;;
        --res)
            if [ $# -lt 2 ]; then
                error "--res necesita un valor."
                exit 2
            fi
            RES_M="$2"
            shift 2
            ;;
        -h | --help)
            uso
            exit 0
            ;;
        *)
            error "argumento no reconocido: $1"
            uso >&2
            exit 2
            ;;
    esac
done

# Validaciones sencillas de los parámetros numéricos.
if ! [[ "$RES_M" =~ ^[0-9]+([.][0-9]+)?$ ]] || [ "$(awk -v r="$RES_M" 'BEGIN{print (r>0)}')" != "1" ]; then
    error "--res debe ser un número positivo (recibido: $RES_M)."
    exit 2
fi
if ! [[ "$HEIGHTMAP_MAX_PX" =~ ^[0-9]+$ ]] || [ "$HEIGHTMAP_MAX_PX" -lt 64 ]; then
    error "--max-px debe ser un entero >= 64 (recibido: $HEIGHTMAP_MAX_PX)."
    exit 2
fi

# Guardia: las salidas van a output/, nunca a data/.
OUT_ABS="$(realpath -m "$OUT_DIR")"
DATA_ABS="$(realpath -m "$ROOT_DIR/data")"
case "$OUT_ABS" in
    "$DATA_ABS" | "$DATA_ABS"/*)
        error "OUT_DIR no puede estar dentro de data/ (recibido: $OUT_DIR)."
        exit 1
        ;;
esac

# ---------------------------------------------------------------------------
# Comprobaciones previas
# ---------------------------------------------------------------------------
echo "==> [1/8] Comprobando dependencias y entradas"

for cmd in gdalinfo gdalsrsinfo gdalbuildvrt gdalwarp gdaldem \
    gdal_translate gdal_rasterize gdaltransform ogr2ogr ogrinfo python3 \
    sort realpath; do
    requiere "$cmd"
done

GDAL_VERSION="$(gdalinfo --version | sed -E 's/^GDAL ([0-9.]+).*/\1/')"
if [ "$(printf '%s\n' "3.4.0" "$GDAL_VERSION" | sort -V | head -n1)" != "3.4.0" ]; then
    error "se requiere GDAL >= 3.4 (detectado: $GDAL_VERSION)."
    exit 1
fi

exige_archivo "$LIMITE_IN" "Ejecuta primero: bash scripts/01_download.sh"

DEM_FILES=()
while IFS= read -r fichero; do
    [ -n "$fichero" ] && DEM_FILES+=("$fichero")
done < <(compgen -G "$DEM_GLOB" | sort || true)

if [ "${#DEM_FILES[@]}" -eq 0 ]; then
    error "no se encontró ningún DEM con el patrón: $DEM_GLOB"
    echo "       Ejecuta primero: bash scripts/01_download.sh" >&2
    exit 1
fi

# Cada tesela debe ser un TIFF válido en EPSG:4326 (formato de Copernicus).
for dem in "${DEM_FILES[@]}"; do
    if ! gdalinfo -json "$dem" >/dev/null 2>&1; then
        error "GDAL no puede abrir el DEM: $dem"
        exit 1
    fi
    # gdalsrsinfo suele anteponer una línea vacía; tomamos la primera línea
    # que contenga realmente un identificador EPSG.
    srs_dem="$(gdalsrsinfo -o epsg "$dem" 2>/dev/null | tr -d '\r' | grep -m1 '^EPSG:' || true)"
    if [ "$srs_dem" != "EPSG:4326" ]; then
        error "el DEM $dem debe estar en EPSG:4326 (detectado: ${srs_dem:-desconocido})."
        echo "       Esta etapa espera las teselas COG de Copernicus GLO-30." >&2
        exit 1
    fi
done

if ! ogrinfo -al -so "$LIMITE_IN" >/dev/null 2>&1; then
    error "GDAL/OGR no puede leer el límite: $LIMITE_IN"
    exit 1
fi
FEATURES="$(ogrinfo -al -so "$LIMITE_IN" | sed -n 's/^Feature Count: *//p' | head -n1 || true)"
if [ -z "$FEATURES" ] || [ "$FEATURES" -lt 1 ]; then
    error "el límite $LIMITE_IN no contiene features."
    exit 1
fi
GEOM_TYPE="$(ogrinfo -al -so "$LIMITE_IN" | sed -n 's/^Geometry: *//p' | head -n1 || true)"
case "$GEOM_TYPE" in
    *Polygon* | *polygon*) ;;
    *)
        error "se esperaba una geometría de polígono en $LIMITE_IN (detectado: ${GEOM_TYPE:-desconocido})."
        exit 1
        ;;
esac

mkdir -p "$OUT_DIR"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

echo "    GDAL $GDAL_VERSION · ${#DEM_FILES[@]} tesela(s) local(es) · CRS $CRS_TRABAJO"

# ---------------------------------------------------------------------------
# 2) Límite reproyectado y rejilla canónica
# ---------------------------------------------------------------------------
echo "==> [2/8] Reproyectando el límite a $CRS_TRABAJO"

GPKG_LIMITE="$OUT_DIR/limite_bogota_9377.gpkg"
ogr2ogr -f GPKG -t_srs "$CRS_TRABAJO" -nln limite -overwrite "$GPKG_LIMITE" "$LIMITE_IN"

EXTENT_LINE="$(ogrinfo -al -so "$GPKG_LIMITE" | grep -m1 'Extent:' || true)"
if [[ "$EXTENT_LINE" =~ Extent:\ \(([-0-9.eE+]+),\ ([-0-9.eE+]+)\)\ -\ \(([-0-9.eE+]+),\ ([-0-9.eE+]+)\) ]]; then
    XV_MIN="${BASH_REMATCH[1]}"
    YV_MIN="${BASH_REMATCH[2]}"
    XV_MAX="${BASH_REMATCH[3]}"
    YV_MAX="${BASH_REMATCH[4]}"
else
    error "no se pudo leer el extent del límite reproyectado."
    echo "       Línea de ogrinfo: ${EXTENT_LINE:-<vacía>}" >&2
    exit 1
fi

# Rejilla canónica: se ajusta hacia fuera a múltiplos de la resolución.
read -r X_MIN Y_MIN X_MAX Y_MAX < <(python3 - "$XV_MIN" "$YV_MIN" "$XV_MAX" "$YV_MAX" "$RES_M" <<'PY'
import math
import sys

xmin, ymin, xmax, ymax = map(float, sys.argv[1:5])
res = float(sys.argv[5])
print(
    f"{math.floor(xmin / res) * res:.6f}",
    f"{math.floor(ymin / res) * res:.6f}",
    f"{math.ceil(xmax / res) * res:.6f}",
    f"{math.ceil(ymax / res) * res:.6f}",
)
PY
)

if ! python3 - "$X_MIN" "$Y_MIN" "$X_MAX" "$Y_MAX" <<'PY'
import sys
xmin, ymin, xmax, ymax = map(float, sys.argv[1:5])
sys.exit(0 if xmax > xmin and ymax > ymin else 1)
PY
then
    error "la rejilla canónica es degenerada: $X_MIN $Y_MIN $X_MAX $Y_MAX"
    exit 1
fi

ANCHO_PX=""
ALTO_PX=""
read -r ANCHO_PX ALTO_PX < <(python3 - "$X_MIN" "$Y_MIN" "$X_MAX" "$Y_MAX" "$RES_M" <<'PY'
import sys

xmin, ymin, xmax, ymax = map(float, sys.argv[1:5])
res = float(sys.argv[5])
print(round((xmax - xmin) / res), round((ymax - ymin) / res))
PY
)

echo "    Extensión (EPSG:9377): $X_MIN $Y_MIN $X_MAX $Y_MAX"
echo "    Rejilla: ${ANCHO_PX} x ${ALTO_PX} px a ${RES_M} m"

# BBox en WGS84 del rectángulo proyectado (25 muestras para cubrir la curvatura).
PUNTOS_9377="$TMP_DIR/puntos_9377.txt"
PUNTOS_4326="$TMP_DIR/puntos_4326.txt"
python3 - "$X_MIN" "$Y_MIN" "$X_MAX" "$Y_MAX" >"$PUNTOS_9377" <<'PY'
import sys

xmin, ymin, xmax, ymax = map(float, sys.argv[1:5])
n = 5
for i in range(n):
    for j in range(n):
        x = xmin + (xmax - xmin) * i / (n - 1)
        y = ymin + (ymax - ymin) * j / (n - 1)
        print(f"{x:.6f} {y:.6f}")
PY
gdaltransform -s_srs "$CRS_TRABAJO" -t_srs EPSG:4326 <"$PUNTOS_9377" >"$PUNTOS_4326"

read -r LON_MIN LAT_MIN LON_MAX LAT_MAX < <(python3 - "$PUNTOS_4326" <<'PY'
import sys

xs, ys = [], []
with open(sys.argv[1], encoding="utf-8") as fh:
    for linea in fh:
        partes = linea.split()
        if len(partes) >= 2:
            try:
                xs.append(float(partes[0]))
                ys.append(float(partes[1]))
            except ValueError:
                pass
if not xs or not ys:
    raise SystemExit("sin coordenadas transformadas")
print(f"{min(xs):.8f} {min(ys):.8f} {max(xs):.8f} {max(ys):.8f}")
PY
)
if [ -z "${LON_MIN:-}" ] || [ -z "${LAT_MIN:-}" ]; then
    error "no se pudo calcular el bbox WGS84 de la rejilla."
    exit 1
fi

# ---------------------------------------------------------------------------
# 3) Cobertura del DEM: teselas de 1°x1° necesarias
# ---------------------------------------------------------------------------
echo "==> [3/8] Validando cobertura del DEM sobre el límite"

# La comprobación se hace en WGS84 sobre las teselas, que son de 1°x1°.
# Se exige que TODAS las celdas que toca el bbox estén presentes: así el
# heightmap rectangular (que usa todo el bbox) tampoco tiene huecos.
python3 - "$LON_MIN" "$LAT_MIN" "$LON_MAX" "$LAT_MAX" "${DEM_FILES[@]}" >"$TMP_DIR/teselas.txt" <<'PY'
import json
import math
import subprocess
import sys

lon_min, lat_min, lon_max, lat_max = map(float, sys.argv[1:5])
rutas = sys.argv[5:]

# Extents reales de las teselas locales (no se fía del nombre del archivo).
# Algunas compilaciones de GDAL 3 respetan el orden de ejes oficial de
# EPSG:4326 (latitud, longitud) al serializar cornerCoordinates, mientras otras
# entregan el orden GIS tradicional (longitud, latitud). Guardamos ambos
# candidatos y la comparación con el bbox escogerá el que corresponda.
extents = []
for ruta in rutas:
    salida = subprocess.run(
        ["gdalinfo", "-json", ruta],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    datos = json.loads(salida)
    cc = datos.get("cornerCoordinates") or {}
    ul = cc.get("upperLeft") or [None, None]
    lr = cc.get("lowerRight") or [None, None]
    if ul[0] is None or lr[0] is None:
        raise SystemExit(f"sin cornerCoordinates en {ruta}")
    normal = (
        min(ul[0], lr[0]),
        min(ul[1], lr[1]),
        max(ul[0], lr[0]),
        max(ul[1], lr[1]),
    )
    extents.append(normal)
    extents.append((normal[1], normal[0], normal[3], normal[2]))

TOL = 1e-8


def nombre_tesela(lat, lon):
    ns = f"N{lat:02d}" if lat >= 0 else f"S{abs(lat):02d}"
    ew = f"E{lon:03d}" if lon >= 0 else f"W{abs(lon):03d}"
    return f"Copernicus_DSM_COG_10_{ns}_00_{ew}_00_DEM"


# Celdas [lat, lat+1) x [lon, lon+1) que intersectan el bbox.
lat0 = math.floor(lat_min + TOL)
lat1 = math.ceil(lat_max - TOL) - 1
lon0 = math.floor(lon_min + TOL)
lon1 = math.ceil(lon_max - TOL) - 1

for lat in range(lat0, lat1 + 1):
    for lon in range(lon0, lon1 + 1):
        celda = (lon, lat, lon + 1, lat + 1)
        cubierta = any(
            e[0] <= celda[0] + TOL
            and e[1] <= celda[1] + TOL
            and e[2] >= celda[2] - TOL
            and e[3] >= celda[3] - TOL
            for e in extents
        )
        print(("R" if cubierta else "M"), nombre_tesela(lat, lon))
PY

FUENTES=("${DEM_FILES[@]}")
REMOTAS=()
FALTANTES=()

while read -r estado tesela; do
    [ -z "$estado" ] && continue
    if [ "$estado" = "R" ]; then
        echo "    OK   $tesela"
        continue
    fi
    if [ "$PERMITIR_REMOTO" -eq 1 ]; then
        url="$(url_tesela "$tesela")"
        echo "    FALTA $tesela → se lee de $url"
        FUENTES+=("/vsicurl/${url}")
        REMOTAS+=("$tesela")
    else
        echo "    FALTA $tesela"
        FALTANTES+=("$tesela")
    fi
done <"$TMP_DIR/teselas.txt"

if [ "${#FALTANTES[@]}" -gt 0 ]; then
    error "el DEM local no cubre todo el límite y --sin-remoto está activo."
    echo "       Descarga las teselas que faltan en data/ (etapa 01) con:" >&2
    for tesela in "${FALTANTES[@]}"; do
        echo "         curl -L --fail -o $(nombre_local_tesela "$tesela") \"$(url_tesela "$tesela")\"" >&2
    done
    echo "       O vuelve a ejecutar sin --sin-remoto para leerlas con /vsicurl." >&2
    exit 1
fi

if [ "${#REMOTAS[@]}" -gt 0 ]; then
    echo "    AVISO: se completan ${#REMOTAS[@]} tesela(s) con /vsicurl (no se escribe en data/)."
    echo "           Para dejarlas en local, descárgalas en data/ con:"
    for tesela in "${REMOTAS[@]}"; do
        echo "             curl -L --fail -o $(nombre_local_tesela "$tesela") \"$(url_tesela "$tesela")\""
    done
fi

# VRT con todas las fuentes (locales y, si hace falta, remotas).
gdalbuildvrt -q -overwrite "$TMP_DIR/dem.vrt" "${FUENTES[@]}"

# Evidencia: el extent del VRT debe contener el bbox WGS84 del límite.
python3 - "$TMP_DIR/dem.vrt" "$LON_MIN" "$LAT_MIN" "$LON_MAX" "$LAT_MAX" <<'PY'
import json
import subprocess
import sys

vrt, lon_min, lat_min, lon_max, lat_max = sys.argv[1], *map(float, sys.argv[2:6])
datos = json.loads(
    subprocess.run(["gdalinfo", "-json", vrt], capture_output=True, text=True, check=True).stdout
)
cc = datos["cornerCoordinates"]
ul = cc["upperLeft"]
lr = cc["lowerRight"]
normal = (min(ul[0], lr[0]), min(ul[1], lr[1]), max(ul[0], lr[0]), max(ul[1], lr[1]))
candidatos = [normal, (normal[1], normal[0], normal[3], normal[2])]
tol = 1e-8
elegido = next(
    (
        e for e in candidatos
        if e[0] <= lon_min + tol and e[1] <= lat_min + tol
        and e[2] >= lon_max - tol and e[3] >= lat_max - tol
    ),
    None,
)
if elegido is None:
    raise SystemExit(
        "el VRT no cubre el bbox del límite: "
        f"VRT={normal} "
        f"límite=({lon_min:.6f},{lat_min:.6f},{lon_max:.6f},{lat_max:.6f})"
    )
vxmin, vymin, vxmax, vymax = elegido
print(f"    Cobertura verificada: VRT {vxmin:.6f} {vymin:.6f} {vxmax:.6f} {vymax:.6f}")
PY

# ---------------------------------------------------------------------------
# 4) DEM reproyectado: recortado y rectangular (misma rejilla)
# ---------------------------------------------------------------------------
echo "==> [4/8] Reproyectando y recortando el DEM a $CRS_TRABAJO"

DEM_RECORTADO="$OUT_DIR/dem_bogota_9377.tif"
DEM_BBOX="$TMP_DIR/dem_bbox_9377.tif"

# Recortado al polígono (nodata fuera). -cutline sin -crop_to_cutline para
# conservar exactamente la rejilla canónica definida con -te/-tr.
gdalwarp -overwrite -q \
    -t_srs "$CRS_TRABAJO" \
    -te "$X_MIN" "$Y_MIN" "$X_MAX" "$Y_MAX" -tr "$RES_M" "$RES_M" \
    -r bilinear -multi -wo NUM_THREADS=ALL_CPUS \
    -cutline "$GPKG_LIMITE" -cl limite \
    -dstnodata "$NODATA" \
    -of GTiff -co TILED=YES -co COMPRESS=DEFLATE -co PREDICTOR=3 \
    -co BIGTIFF=IF_SAFER -co NUM_THREADS=ALL_CPUS \
    "$TMP_DIR/dem.vrt" "$DEM_RECORTADO"

# Rectangular (sin recorte): base del heightmap y del sombreado, para que
# Blender tenga un grid completo sin agujeros.
gdalwarp -overwrite -q \
    -t_srs "$CRS_TRABAJO" \
    -te "$X_MIN" "$Y_MIN" "$X_MAX" "$Y_MAX" -tr "$RES_M" "$RES_M" \
    -r bilinear -multi -wo NUM_THREADS=ALL_CPUS \
    -dstnodata "$NODATA" \
    -of GTiff -co TILED=YES -co COMPRESS=DEFLATE -co PREDICTOR=3 \
    -co BIGTIFF=IF_SAFER -co NUM_THREADS=ALL_CPUS \
    "$TMP_DIR/dem.vrt" "$DEM_BBOX"

# Limpiamos el nodata del rectangular (la cobertura ya está garantizada).
DEM_BBOX_SIN_NODATA="$TMP_DIR/dem_bbox_sin_nodata.tif"
gdal_translate -q -a_nodata none -of GTiff \
    -co TILED=YES -co COMPRESS=DEFLATE -co PREDICTOR=3 \
    "$DEM_BBOX" "$DEM_BBOX_SIN_NODATA"

# Dimensiones reales de la rejilla (pueden diferir en 1 px del cálculo teórico).
read -r ANCHO_PX ALTO_PX < <(gdalinfo -json "$DEM_RECORTADO" | python3 -c '
import json
import sys
j = json.load(sys.stdin)
print(j["size"][0], j["size"][1])
')

# ---------------------------------------------------------------------------
# 5) Estadísticas y paleta hipsométrica
# ---------------------------------------------------------------------------
echo "==> [5/8] Calculando rango de elevación y paleta"

MINMAX="$(gdalinfo -mm "$DEM_BBOX" | sed -n 's/.*Computed Min\/Max=\([^,]*\), *\([^ ]*\).*/\1 \2/p' | head -n1 || true)"
if [ -z "$MINMAX" ]; then
    error "no se pudo calcular el rango de elevación del DEM."
    exit 1
fi
read -r ELEV_MIN ELEV_MAX <<<"$MINMAX"

if ! python3 - "$ELEV_MIN" "$ELEV_MAX" <<'PY'
import math
import sys

mn, mx = map(float, sys.argv[1:3])
if not (math.isfinite(mn) and math.isfinite(mx)) or mx <= mn:
    raise SystemExit(1)
# Bogotá está por encima de 2.000 m; un mínimo <= 0 delata huecos/nodata.
if mn <= 0:
    raise SystemExit(2)
PY
then
    error "rango de elevación inválido (min=$ELEV_MIN, max=$ELEV_MAX)."
    echo "       Suele indicar huecos en el DEM o un nodata no declarado." >&2
    exit 1
fi

echo "    Elevación: ${ELEV_MIN} m a ${ELEV_MAX} m"

RAMPA="$OUT_DIR/rampa_hipsometrica.txt"
python3 - "$ELEV_MIN" "$ELEV_MAX" "$RAMPA" <<'PY'
import sys

mn, mx = float(sys.argv[1]), float(sys.argv[2])
destino = sys.argv[3]

# Paleta hipsométrica: verde (bajo) → ocre/marrón → blanco (alto).
paradas = [
    (0.00, (46, 125, 50)),
    (0.12, (102, 187, 106)),
    (0.28, (174, 213, 129)),
    (0.42, (230, 214, 110)),
    (0.55, (214, 166, 90)),
    (0.68, (166, 120, 84)),
    (0.80, (138, 101, 88)),
    (0.92, (191, 163, 143)),
    (1.00, (250, 250, 250)),
]

with open(destino, "w", encoding="utf-8") as fh:
    fh.write("# Rampa hipsométrica para gdaldem color-relief\n")
    fh.write("# valor R G B  (interpolación lineal; 'nv' = sin datos)\n")
    for fraccion, (r, g, b) in paradas:
        valor = mn + (mx - mn) * fraccion
        fh.write(f"{valor:.2f} {r} {g} {b}\n")
    fh.write("nv 0 0 0 0\n")
PY

# Máscara Booleana del polígono en la rejilla canónica (255 dentro, 0 fuera).
MASCARA="$TMP_DIR/mascara_9377.tif"
gdal_rasterize -q -l limite -burn 255 -init 0 \
    -te "$X_MIN" "$Y_MIN" "$X_MAX" "$Y_MAX" -tr "$RES_M" "$RES_M" \
    -ot Byte -of GTiff -co COMPRESS=DEFLATE \
    "$GPKG_LIMITE" "$MASCARA"

# ---------------------------------------------------------------------------
# 6) Sombreado y color-relief
# ---------------------------------------------------------------------------
echo "==> [6/8] Generando hillshade y color-relief"

# Sombreado sobre el DEM rectangular (sin nodata): no hay agujeros.
HILLSHADE_BBOX="$TMP_DIR/hillshade_bbox.tif"
gdaldem hillshade -q -compute_edges -alg Horn -az 315 -alt 45 -z 1 \
    -of GTiff -co TILED=YES -co COMPRESS=DEFLATE -co PREDICTOR=2 \
    "$DEM_BBOX_SIN_NODATA" "$HILLSHADE_BBOX"

# Versión recortada para el póster: Int16 + nodata -9999 (0 y 255 siguen
# siendo valores válidos de sombra/luz, así que no usamos 0 como nodata).
HILLSHADE_TIF="$OUT_DIR/hillshade_bogota_9377.tif"
gdalwarp -overwrite -q \
    -te "$X_MIN" "$Y_MIN" "$X_MAX" "$Y_MAX" -tr "$RES_M" "$RES_M" \
    -r near -cutline "$GPKG_LIMITE" -cl limite \
    -ot Int16 -dstnodata "$NODATA" \
    -of GTiff -co TILED=YES -co COMPRESS=DEFLATE -co PREDICTOR=2 \
    "$HILLSHADE_BBOX" "$HILLSHADE_TIF"

# PNG RGBA del sombreado (transparente fuera del límite).
gdalwarp -overwrite -q \
    -te "$X_MIN" "$Y_MIN" "$X_MAX" "$Y_MAX" -tr "$RES_M" "$RES_M" \
    -r near -cutline "$GPKG_LIMITE" -cl limite -dstalpha \
    -of GTiff "$HILLSHADE_BBOX" "$TMP_DIR/hillshade_rgba.tif"
gdal_translate -q -of PNG "$TMP_DIR/hillshade_rgba.tif" "$OUT_DIR/hillshade_bogota.png"

# Color-relief hipsométrico con alfa (nodata fuera del polígono).
COLOR_TIF="$TMP_DIR/color_relief.tif"
gdaldem color-relief -q -alpha \
    -of GTiff -co TILED=YES -co COMPRESS=DEFLATE -co PREDICTOR=2 \
    "$DEM_RECORTADO" "$RAMPA" "$COLOR_TIF"
gdal_translate -q -of PNG "$COLOR_TIF" "$OUT_DIR/textura_bogota.png"

# ---------------------------------------------------------------------------
# 7) Heightmap 16 bits y máscara para Blender
# ---------------------------------------------------------------------------
echo "==> [7/8] Generando heightmap de 16 bits y máscara"

read -r HM_W HM_H HM_RESX HM_RESY < <(python3 - "$X_MIN" "$Y_MIN" "$X_MAX" "$Y_MAX" "$HEIGHTMAP_MAX_PX" <<'PY'
import sys

xmin, ymin, xmax, ymax = map(float, sys.argv[1:5])
maxpx = int(sys.argv[5])
ancho_m = xmax - xmin
alto_m = ymax - ymin
if ancho_m >= alto_m:
    w = maxpx
    h = max(1, round(maxpx * alto_m / ancho_m))
else:
    h = maxpx
    w = max(1, round(maxpx * ancho_m / alto_m))
print(w, h, f"{ancho_m / w:.10f}", f"{alto_m / h:.10f}")
PY
)

# Remuestreo a la rejilla del heightmap conservando el extent exacto.
gdalwarp -overwrite -q \
    -te "$X_MIN" "$Y_MIN" "$X_MAX" "$Y_MAX" -tr "$HM_RESX" "$HM_RESY" \
    -r average -dstnodata "$NODATA" \
    -of GTiff -co TILED=YES -co COMPRESS=DEFLATE -co PREDICTOR=3 \
    "$DEM_BBOX_SIN_NODATA" "$TMP_DIR/heightmap_f32.tif"

# Dimensiones reales del heightmap.
read -r HM_W HM_H < <(gdalinfo -json "$TMP_DIR/heightmap_f32.tif" | python3 -c '
import json
import sys
j = json.load(sys.stdin)
print(j["size"][0], j["size"][1])
')

HM_TIF="$OUT_DIR/heightmap_bogota_16bit.tif"
HM_PNG="$OUT_DIR/heightmap_bogota_16bit.png"

# Normalización lineal: 0 = ELEV_MIN, 65535 = ELEV_MAX.
gdal_translate -q -ot UInt16 \
    -scale "$ELEV_MIN" "$ELEV_MAX" 0 65535 -a_nodata none \
    -of GTiff -co TILED=YES -co COMPRESS=DEFLATE -co PREDICTOR=2 \
    "$TMP_DIR/heightmap_f32.tif" "$HM_TIF"
gdal_translate -q -ot UInt16 \
    -scale "$ELEV_MIN" "$ELEV_MAX" 0 65535 \
    -of PNG "$TMP_DIR/heightmap_f32.tif" "$HM_PNG"

# Máscara alineada 1:1 con el heightmap (para recortar la malla en Blender).
gdalwarp -overwrite -q \
    -te "$X_MIN" "$Y_MIN" "$X_MAX" "$Y_MAX" -tr "$HM_RESX" "$HM_RESY" \
    -r near -of GTiff -co COMPRESS=DEFLATE \
    "$MASCARA" "$TMP_DIR/mascara_hm.tif"
gdal_translate -q -of PNG "$TMP_DIR/mascara_hm.tif" "$OUT_DIR/mascara_bogota_8bit.png"

# ---------------------------------------------------------------------------
# 8) Metadatos y validaciones finales
# ---------------------------------------------------------------------------
echo "==> [8/8] Escribiendo metadatos y validando salidas"

export RELIEVE_CRS="$CRS_TRABAJO"
export RELIEVE_RES="$RES_M"
export RELIEVE_NODATA="$NODATA"
export RELIEVE_XMIN="$X_MIN" RELIEVE_YMIN="$Y_MIN" RELIEVE_XMAX="$X_MAX" RELIEVE_YMAX="$Y_MAX"
export RELIEVE_LONMIN="$LON_MIN" RELIEVE_LATMIN="$LAT_MIN" RELIEVE_LONMAX="$LON_MAX" RELIEVE_LATMAX="$LAT_MAX"
export RELIEVE_ELEV_MIN="$ELEV_MIN" RELIEVE_ELEV_MAX="$ELEV_MAX"
export RELIEVE_HM_W="$HM_W" RELIEVE_HM_H="$HM_H" RELIEVE_HM_MAXPX="$HEIGHTMAP_MAX_PX"
export RELIEVE_ANCHO_PX="$ANCHO_PX" RELIEVE_ALTO_PX="$ALTO_PX"
export RELIEVE_GDAL="$GDAL_VERSION"
RELIEVE_DEM_FILES="$(printf '%s\n' "${DEM_FILES[@]}")"
export RELIEVE_DEM_FILES
RELIEVE_REMOTAS="$(printf '%s\n' "${REMOTAS[@]}")"
export RELIEVE_REMOTAS

python3 - "$OUT_DIR" <<'PY'
import datetime
import hashlib
import json
import os
import sys

salida = sys.argv[1]
env = os.environ

rutas_locales = [p for p in env.get("RELIEVE_DEM_FILES", "").splitlines() if p]
remotas = [p for p in env.get("RELIEVE_REMOTAS", "").splitlines() if p]


def sha256(ruta):
    h = hashlib.sha256()
    with open(ruta, "rb") as fh:
        for bloque in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(bloque)
    return h.hexdigest()


fuentes = []
for ruta in rutas_locales:
    fuentes.append(
        {
            "archivo": ruta,
            "bytes": os.path.getsize(ruta),
            "sha256": sha256(ruta),
        }
    )
for nombre in remotas:
    fuentes.append(
        {
            "tesela": nombre,
            "url": f"https://copernicus-dem-30m.s3.amazonaws.com/{nombre}/{nombre}.tif",
            "modo": "vsicurl",
        }
    )

datos = {
    "proyecto": "bogota-relieve",
    "etapa": "02_gdal_process",
    "generado_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "crs": env["RELIEVE_CRS"],
    "crs_nombre": "MAGNA-SIRGAS / Origen Nacional",
    "resolucion_m": float(env["RELIEVE_RES"]),
    "bbox_9377": {
        "xmin": float(env["RELIEVE_XMIN"]),
        "ymin": float(env["RELIEVE_YMIN"]),
        "xmax": float(env["RELIEVE_XMAX"]),
        "ymax": float(env["RELIEVE_YMAX"]),
    },
    "bbox_wgs84": {
        "lon_min": float(env["RELIEVE_LONMIN"]),
        "lat_min": float(env["RELIEVE_LATMIN"]),
        "lon_max": float(env["RELIEVE_LONMAX"]),
        "lat_max": float(env["RELIEVE_LATMAX"]),
    },
    "dem": {
        "archivo": "output/dem_bogota_9377.tif",
        "ancho_px": int(env["RELIEVE_ANCHO_PX"]),
        "alto_px": int(env["RELIEVE_ALTO_PX"]),
        "elev_min_m": float(env["RELIEVE_ELEV_MIN"]),
        "elev_max_m": float(env["RELIEVE_ELEV_MAX"]),
        "nodata": float(env["RELIEVE_NODATA"]),
        "recortado_al_limite": True,
    },
    "heightmap": {
        "archivo": "output/heightmap_bogota_16bit.png",
        "geotiff": "output/heightmap_bogota_16bit.tif",
        "ancho_px": int(env["RELIEVE_HM_W"]),
        "alto_px": int(env["RELIEVE_HM_H"]),
        "lado_mayor_px": int(env["RELIEVE_HM_MAXPX"]),
        "tipo": "uint16",
        "elev_min_m": float(env["RELIEVE_ELEV_MIN"]),
        "elev_max_m": float(env["RELIEVE_ELEV_MAX"]),
        "formula_elevacion": "elev = elev_min + (pixel / 65535) * (elev_max - elev_min)",
        "orientacion_filas": "norte arriba (fila 0 = norte)",
        "nota_blender": "La imagen tiene el norte arriba; al mapearla en Blender invierte el eje V (o usa la textura con flip) para que coincida con el plano.",
    },
    "textura": {
        "archivo": "output/textura_bogota.png",
        "tipo": "png RGBA color-relief",
        "rampa": "output/rampa_hipsometrica.txt",
    },
    "mascara": {
        "archivo": "output/mascara_bogota_8bit.png",
        "ancho_px": int(env["RELIEVE_HM_W"]),
        "alto_px": int(env["RELIEVE_HM_H"]),
        "valores": "255 dentro del límite, 0 fuera",
    },
    "fuentes": fuentes,
    "herramientas": {"gdal": env.get("RELIEVE_GDAL", "")},
}

ruta_json = os.path.join(salida, "relieve_bogota.json")
with open(ruta_json, "w", encoding="utf-8") as fh:
    json.dump(datos, fh, indent=2, ensure_ascii=False)
    fh.write("\n")
PY

# Validaciones finales.
SALIDAS=(
    "$DEM_RECORTADO"
    "$HILLSHADE_TIF"
    "$OUT_DIR/hillshade_bogota.png"
    "$OUT_DIR/textura_bogota.png"
    "$HM_TIF"
    "$HM_PNG"
    "$OUT_DIR/mascara_bogota_8bit.png"
    "$GPKG_LIMITE"
    "$OUT_DIR/relieve_bogota.json"
)
for fichero in "${SALIDAS[@]}"; do
    if [ ! -s "$fichero" ]; then
        error "salida ausente o vacía: $fichero"
        exit 1
    fi
done

SRS_SALIDA="$(gdalsrsinfo -o epsg "$DEM_RECORTADO" 2>/dev/null | tr -d '\r' | head -n1 || true)"
if [ "$SRS_SALIDA" != "EPSG:9377" ]; then
    error "el DEM recortado no quedó en EPSG:9377 (detectado: ${SRS_SALIDA:-desconocido})."
    exit 1
fi

TIPO_HM="$(gdalinfo -json "$HM_PNG" | python3 -c 'import json,sys; print(json.load(sys.stdin)["bands"][0]["type"])')"
if [ "$TIPO_HM" != "UInt16" ]; then
    error "el heightmap PNG no es de 16 bits (tipo detectado: $TIPO_HM)."
    exit 1
fi

DIM_HM="$(gdalinfo -json "$HM_PNG" | python3 -c 'import json,sys; j=json.load(sys.stdin); print(j["size"][0], j["size"][1])')"
if [ "$DIM_HM" != "$HM_W $HM_H" ]; then
    error "el heightmap mide $DIM_HM px y se esperaba $HM_W x $HM_H."
    exit 1
fi

# ---------------------------------------------------------------------------
# Resumen
# ---------------------------------------------------------------------------
echo
echo "================= RESUMEN (etapa 02_gdal_process) ================="
echo "CRS: $CRS_TRABAJO (MAGNA-SIRGAS / Origen Nacional)"
echo "Rejilla: ${ANCHO_PX} x ${ALTO_PX} px · ${RES_M} m/px"
echo "Elevación: ${ELEV_MIN} m a ${ELEV_MAX} m"
echo "Heightmap: ${HM_W} x ${HM_H} px · UInt16 · 0 = ${ELEV_MIN} m · 65535 = ${ELEV_MAX} m"
echo
echo "Salidas en $OUT_DIR/:"
printf '  %s\n' \
    "dem_bogota_9377.tif" \
    "hillshade_bogota_9377.tif" \
    "hillshade_bogota.png" \
    "textura_bogota.png" \
    "heightmap_bogota_16bit.tif" \
    "heightmap_bogota_16bit.png" \
    "mascara_bogota_8bit.png" \
    "rampa_hipsometrica.txt" \
    "limite_bogota_9377.gpkg" \
    "relieve_bogota.json"
echo
du -h "${SALIDAS[@]}" "$RAMPA"
echo
echo "Validación rápida:"
echo "  gdalinfo -stats $DEM_RECORTADO"
echo "  gdalinfo $HM_PNG"
echo "Siguiente etapa: bash scripts/03_qgis_poster.sh"
echo "=================================================================="
