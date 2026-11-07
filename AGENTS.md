# AGENTS.md

## Proyecto

Mapa de relieve 3D de Bogotá generado por un pipeline 100 % headless y publicado como visor interactivo (model-viewer) en GitHub Pages. Todo lo ejecutan agentes: si un paso exige clics o GUI, no sirve.

## Reglas duras

- Nada manual: cada paso es un script CLI reproducible, versionado en `scripts/`.
- Los scripts deben correr en Ubuntu headless (runner de GitHub Actions), sin pantalla ni drivers gráficos.
- CRS de trabajo: EPSG:9377 (MAGNA-SIRGAS Origen Nacional).
- No inventar comandos ni dependencias: verificar que existan antes de escribir el script o documentarlo (probarlos en local o en un run de CI).
- Si algo falla en CI: `gh run view --log-failed`, corregir, volver a empujar.
- Idioma del proyecto (bitácora, comentarios, docs): español.

## Estado actual

- Pipeline implementado en `scripts/01_download.sh` a `scripts/04_blender_relief.sh`.
- Visor `<model-viewer>` en `web/index.html` y CI/CD en `.github/workflows/deploy.yml`.
- `data/` y `output/` conservan `.gitkeep`; las entradas y salidas generadas están ignoradas por Git.
- La validación funcional completa se ejecuta en Ubuntu 24.04 mediante GitHub Actions.

Instalación exacta en Ubuntu headless:

```bash
sudo apt-get update
sudo apt-get install -y --no-install-recommends \
  gdal-bin python3 qgis python3-qgis fonts-dejavu-core blender
```

Ejecución exacta:

```bash
bash scripts/01_download.sh
bash scripts/02_gdal_process.sh --sin-remoto --max-px 1024
bash scripts/03_qgis_poster.sh
bash scripts/04_blender_relief.sh --resolucion 384 --exageracion 2 --muestras 32
```

## Estructura y orden del pipeline

Los prefijos numerados fijan el orden de ejecución; respetarlos al insertar pasos.

1. `scripts/01_download` — DEM Copernicus GLO-30 desde el bucket público S3 `copernicus-dem-30m` (sin credenciales) + límite administrativo de Bogotá.
   Patrón de key: `Copernicus_DSM_COG_10_N{lat}_00_{E|W}{lon}_00_DEM/Copernicus_DSM_COG_10_N{lat}_00_{E|W}{lon}_00_DEM.tif`. Tile de Bogotá verificado (HTTP 200, ~43 MB, `image/tiff`): `https://copernicus-dem-30m.s3.amazonaws.com/Copernicus_DSM_COG_10_N04_00_W075_00_DEM/Copernicus_DSM_COG_10_N04_00_W075_00_DEM.tif`
2. `scripts/02_gdal_process` — recorte, hillshade, color-relief y heightmap de 16 bits.
3. `scripts/03_qgis_poster` — PyQGIS offscreen: póster con leyenda, norte y escala. Requiere entorno QGIS sin GUI (`QT_QPA_PLATFORM=offscreen`), no la GUI de QGIS.
4. `scripts/04_blender_relief` — Blender con `blender -b -P <script>`: Displace, render y exportación `.glb`.
5. `web/` — visor y despliegue a Pages vía GitHub Actions.

Directorios: `data/` entradas (DEM, límites), `output/` intermedios (heightmap, textura, póster, `.glb`), `web/` visor publicado, `bitacora/` registro de sesiones.

## Límites de tamaño

- Ningún archivo en `data/` puede superar 100 MB (límite por archivo de GitHub).
- El `.glb` final debe pesar menos de 25 MB: si se pasa, reducir resolución del heightmap o simplificar la malla en Blender.

## Bitácora

Una entrada por sesión en `bitacora/` con: fecha, agente, modelo, prompt, resultado, errores y cómo se resolvieron, tokens y costo. Sin entrada, la sesión se considera incompleta.

## Costos de modelos

- `deepseek-chat` por defecto para escribir y ejecutar.
- Modelo de razonamiento solo para el agente `planner`; `.opencode/agents/` está vacía, así que ese agente hay que crearlo.
- Justificar en la bitácora por qué se eligió cada modelo.

## Git

- Rama principal: `main` (se renombró desde `master`). `origin` = https://github.com/rousmith/bogota-relieve.git, aún sin ramas publicadas.
