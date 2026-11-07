#!/usr/bin/env bash
# Etapa 04: ejecuta Blender en lote para crear el relieve 3D y el GLB.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

uso() {
    cat <<'AYUDA'
Uso: bash scripts/04_blender_relief.sh [opciones]

Ejemplos:
  bash scripts/04_blender_relief.sh
  bash scripts/04_blender_relief.sh --resolucion 512 --exageracion 2.5
  bash scripts/04_blender_relief.sh --sin-render

Las opciones se pasan a scripts/04_blender_relief.py. El comando siempre usa
Blender en modo batch, sin interfaz gráfica ni GPU.
AYUDA
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
    uso
    echo
    if command -v blender >/dev/null 2>&1; then
        blender -b --factory-startup --python-exit-code 1 \
            -P scripts/04_blender_relief.py -- --help
    fi
    exit 0
fi

if ! command -v blender >/dev/null 2>&1; then
    cat >&2 <<'MSG'
ERROR: falta Blender. En Ubuntu 24.04 instálalo con:
         sudo apt-get update
         sudo apt-get install -y --no-install-recommends blender
MSG
    exit 1
fi

for entrada in \
    output/heightmap_bogota_16bit.png \
    output/textura_bogota.png \
    output/mascara_bogota_8bit.png \
    output/relieve_bogota.json; do
    if [ ! -s "$entrada" ]; then
        echo "ERROR: falta la entrada $entrada. Ejecuta primero scripts/02_gdal_process.sh." >&2
        exit 1
    fi
done

VERSION="$(blender --version | head -n1)"
echo "==> $VERSION · modo batch · Cycles CPU"

blender -b --factory-startup --python-exit-code 1 \
    -P scripts/04_blender_relief.py -- "$@"

if [ ! -s output/bogota_relieve.glb ]; then
    echo "ERROR: Blender terminó sin generar output/bogota_relieve.glb." >&2
    exit 1
fi

TAMANO="$(stat -c %s output/bogota_relieve.glb)"
LIMITE=$((25 * 1024 * 1024))
if [ "$TAMANO" -ge "$LIMITE" ]; then
    echo "ERROR: el GLB pesa $TAMANO bytes; debe ser menor de 25 MiB." >&2
    exit 1
fi

echo "==> GLB validado: output/bogota_relieve.glb ($TAMANO bytes)"
