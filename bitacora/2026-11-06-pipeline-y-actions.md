# 2026-11-06 — Pipeline completo y GitHub Actions

- **Fecha:** 2026-11-06 (viernes)
- **Agente:** agente principal, con apoyo de `gis-agent` y `blender-agent`
- **Modelo:** modelos gratuitos del proveedor `opencode`

## Prompt

> Ya empecemos a trabajar en el proyecto porque no tengo mucho tiempo.

## Resultado

Se creó la rama `feat/pipeline-relieve` para no trabajar directamente sobre
`main` y se integró el pipeline reproducible:

1. Descarga de cuatro teselas Copernicus GLO-30 y límite administrativo.
2. Reproyección, recorte y derivados GDAL en EPSG:9377.
3. Póster A3 mediante PyQGIS con `QT_QPA_PLATFORM=offscreen`.
4. Malla, render y GLB mediante Blender en modo batch.
5. Visor estático `<model-viewer>` y workflow de construcción/publicación.

El workflow `.github/workflows/deploy.yml` instala las dependencias en Ubuntu
24.04, ejecuta todas las etapas, guarda los productos como artefacto y publica
`web/` en GitHub Pages cuando el cambio llega a `main`.

## Optimización de costo

- Se asignó GIS y Blender a agentes especializados con modelos gratuitos.
- Se ejecutaron GIS, Blender y web en paralelo cuando no modificaban los mismos
  archivos.
- Se reutilizó la implementación parcial producida antes de agotarse la cuota
  del agente Blender; no se repitió el trabajo con un modelo de pago.
- La malla empieza en 384 px y se reduce automáticamente si supera 25 MiB.

## Verificación local

- `bash -n scripts/*.sh`: correcto.
- `git diff --check`: sin errores de espacios (solo avisos de finales de línea
  propios de Windows).
- DEM N04/W075 descargado: 42.787.983 bytes y cabecera TIFF válida.
- Las otras tres URLs respondieron HTTP 200 y declararon tamaños menores de
  44 MB cada una.

## Errores y cómo se resolvieron

- El equipo Windows no tiene GDAL, QGIS, Blender, Python, Docker ni WSL. La
  validación funcional se trasladó a GitHub Actions, que instala un entorno
  Ubuntu headless reproducible.
- La primera prueba local de `01_download.sh` descargó correctamente el DEM,
  pero no pudo filtrar el límite por falta de Python. El runner incluye
  `python3`; además, la URL y el filtro quedan comprobados en CI.
- Se comprobó que una tesela no cubre Bogotá completa. La etapa 01 se amplió a
  cuatro teselas y la etapa 02 vuelve a verificar la cobertura antes de operar.
- El primer run de Actions (`42385957464`) falló al validar el CRS porque
  `gdalsrsinfo -o epsg` imprime una línea vacía antes de `EPSG:4326`. Se cambió
  `head -n1` por una búsqueda explícita de la primera línea `EPSG:`.

## Tokens y costo

El proveedor no expuso el total exacto de tokens. Costo monetario registrado:
**0 USD** usando modelos gratuitos de OpenCode.
