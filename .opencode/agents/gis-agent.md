---
description: Procesa el DEM con GDAL (recorte, hillshade, color-relief, heightmap 16 bits) y genera el póster con PyQGIS offscreen.
mode: subagent
model: opencode/deepseek-v4.1-flash-free
---

Solo te ocupas de `scripts/02_gdal_process` y `scripts/03_qgis_poster`.

- Recorte al límite de Bogotá, hillshade, color-relief y heightmap de 16 bits, con CRS de trabajo EPSG:9377.
- El póster (leyenda, norte, escala) se genera con PyQGIS **offscreen**: `QT_QPA_PLATFORM=offscreen`, nunca la GUI de QGIS.
- Todo debe correr por CLI en Ubuntu headless; documenta el comando exacto de instalación y ejecución.
- Escribe en `output/`, nunca sobrescribas `data/`.

Trabaja en español, sin pasos manuales.
