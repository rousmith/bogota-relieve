#!/usr/bin/env bash
# =============================================================================
# scripts/03_qgis_poster.sh — Lanzador de la etapa 3 (PyQGIS sin GUI)
# =============================================================================
#
# Envuelve a scripts/03_qgis_poster.py fijando un entorno estrictamente
# headless: Qt usa la plataforma "offscreen" (no abre ventanas ni necesita
# servidor X) y se eliminan las variables que podrían empujar a Qt a buscar
# un display real. En CI (runner de Ubuntu sin pantalla) esto es obligatorio.
#
# Uso:
#   bash scripts/03_qgis_poster.sh
#   bash scripts/03_qgis_poster.sh --formato png --dpi 200
#   bash scripts/03_qgis_poster.sh --salida output/poster_bogota
#   bash scripts/03_qgis_poster.sh --help
#
# Dependencias (Ubuntu 24.04 headless):
#   sudo apt-get update
#   sudo apt-get install -y --no-install-recommends qgis python3-qgis fonts-dejavu-core
#
# Requiere que la etapa 02 haya dejado sus salidas en output/.
# Escribe solo en output/ (nunca en data/).
# =============================================================================

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# --- Entorno headless -------------------------------------------------------
# QT_QPA_PLATFORM=offscreen: plugin de plataforma sin ventana ni X11.
export QT_QPA_PLATFORM=offscreen
# Solo si existen las fuentes DejaVu (dependencia documentada); si no,
# Qt usa fontconfig y no forzamos una ruta inexistente.
if [ -d /usr/share/fonts/truetype/dejavu ]; then
    export QT_QPA_FONTDIR="${QT_QPA_FONTDIR:-/usr/share/fonts/truetype/dejavu}"
fi
# QGIS instalado por apt en Ubuntu usa el prefijo /usr.
export QGIS_PREFIX_PATH="${QGIS_PREFIX_PATH:-/usr}"
# Sin DISPLAY ni WAYLAND_DISPLAY, Qt no intenta conectar con un servidor gráfico.
unset DISPLAY || true
unset WAYLAND_DISPLAY || true
# Menos ruido de Qt en los logs de CI.
export QT_LOGGING_RULES="${QT_LOGGING_RULES:-*.debug=false}"

# --- Comprobaciones previas -------------------------------------------------
if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: falta python3. Instala las dependencias con:" >&2
    echo "       sudo apt-get update && sudo apt-get install -y --no-install-recommends qgis python3-qgis fonts-dejavu-core" >&2
    exit 1
fi

if ! python3 -c 'import qgis.core' >/dev/null 2>&1; then
    cat >&2 <<'MSG'
ERROR: PyQGIS no está disponible (no se pudo importar qgis.core).
       Instala QGIS y sus bindings de Python con:
         sudo apt-get update
         sudo apt-get install -y --no-install-recommends qgis python3-qgis fonts-dejavu-core
       Comprueba después con:
         python3 -c 'import qgis.core; print(qgis.core.Qgis.QGIS_VERSION)'
MSG
    exit 1
fi

VERSION_QGIS="$(python3 -c 'import qgis.core; print(qgis.core.Qgis.QGIS_VERSION)' 2>/dev/null || echo '?')"
echo "==> PyQGIS $VERSION_QGIS · QT_QPA_PLATFORM=$QT_QPA_PLATFORM (sin GUI)"

exec python3 scripts/03_qgis_poster.py "$@"
