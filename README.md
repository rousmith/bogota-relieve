# Bogotá en relieve

Mapa de elevación 3D interactivo de Bogotá construido de forma reproducible
con agentes de OpenCode, Copernicus GLO-30, GDAL, QGIS, Blender, GitHub Actions
y GitHub Pages.

## Productos

- Modelo interactivo GLB para rotar y ampliar en el navegador.
- Póster cartográfico A3 con escala, norte, leyenda y fuentes.
- [Bitácora de agentes, modelos, costos y errores](bitacora/README.md).

Sitio publicado: <https://rousmith.github.io/bogota-relieve/>

## Pipeline headless

```bash
bash scripts/01_download.sh
bash scripts/02_gdal_process.sh --sin-remoto --max-px 1024
bash scripts/03_qgis_poster.sh
bash scripts/04_blender_relief.sh --resolucion 384 --exageracion 2 --muestras 32
```

Las instrucciones y dependencias completas están en
[`scripts/README.md`](scripts/README.md). No se requiere abrir las interfaces
gráficas de QGIS o Blender: GitHub Actions ejecuta todo en Ubuntu headless.

## Datos y referencia espacial

- Elevación: Copernicus DEM GLO-30 (DSM de 30 m).
- Límite: geoBoundaries gbOpen, Bogotá D.C. (`CO-DC`).
- CRS de trabajo: MAGNA-SIRGAS / Origen Nacional (`EPSG:9377`).

Los archivos grandes de `data/` y `output/` no se guardan en Git; los scripts
los descargan o regeneran y el workflow conserva los productos como artefactos.
