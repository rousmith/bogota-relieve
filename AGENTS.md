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

- El pipeline **no está implementado**. `scripts/`, `data/`, `output/`, `web/` y `.opencode/agents/` están vacías; solo existen este archivo y un `bitacora/README.md` vacío. La estructura de abajo es el objetivo, no código existente.
- No hay manifiesto de dependencias ni CI todavía: al agregar el primero, documentar aquí el comando exacto de instalación y ejecución.
- Git no versiona directorios vacíos: si `data/` u `output/` deben sobrevivir a un clon, agregar un placeholder (y decidir si van en `.gitignore`).

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
