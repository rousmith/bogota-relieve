# 2026-11-06 — Etapas GIS: GDAL (02) y póster PyQGIS (03)

- **Fecha:** 2026-11-06
- **Agente:** `gis-agent` (subagente)
- **Modelo:** `opencode/deepseek-v4.1-flash-free`

## Prompt

> Implementa solo `scripts/02_gdal_process` y `scripts/03_qgis_poster`: recorte al
> límite de Bogotá, hillshade, color-relief y heightmap de 16 bits en EPSG:9377,
> y póster (leyenda, norte, escala) con PyQGIS **offscreen**. Todo por CLI en
> Ubuntu headless, salidas solo en `output/`, sin pasos manuales.

## Resultado

- `scripts/02_gdal_process.sh`: valida entradas, reproyecta el límite a
  EPSG:9377, calcula una rejilla canónica de 30 m y genera DEM recortado,
  hillshade (Int16 con nodata -9999) + PNG RGBA, textura hipsométrica, heightmap
  UInt16, máscara 8 bits, rampa, GPKG y `relieve_bogota.json`; valida CRS, tipo y
  dimensiones al final.
- `scripts/03_qgis_poster.py` + `scripts/03_qgis_poster.sh`: póster A3 con mapa
  hipsométrico, sombreado multiplicado, leyenda, norte, escala gráfica, fuente y
  CRS; se exporta a PNG y PDF con `QT_QPA_PLATFORM=offscreen`.
- `scripts/README.md`: instalación y comandos exactos de ejecución.
- `output/.gitkeep` para que el directorio sobreviva al clon.

## Decisiones

- La tesela `N04_00_W075_00` **no cubre todo Bogotá** (el bbox llega a lat
  3.728 y lon -73.996). La etapa 02 comprueba la cobertura por celdas Copernicus
  de 1°×1° y completa las que faltan con `/vsicurl` del bucket público; con
  `--sin-remoto` falla y lista los `curl` exactos. Así no se escribe en `data/`.
- Heightmap rectangular (sin agujeros) + máscara aparte, con normalización
  lineal `0 = elev_min`, `65535 = elev_max`, lado mayor 1024 px por defecto.
- En el póster, el sombreado se añade al proyecto con `addMapLayer(hl, False)`
  para que aparezca en el mapa pero no en la leyenda.
- La «N» del norte se dibuja como etiqueta y no dentro del SVG: el soporte de
  texto de QtSvg es limitado.

## Verificación

- `python -m py_compile scripts/03_qgis_poster.py`: OK (Python 3.12).
- `bash -n` y `shellcheck -x` sobre los dos `.sh`: sin avisos.
- Firmas de la API QGIS 3.34 comprobadas contra las cabeceras del repositorio
  (`setUnits`, `setUnitsPerSegment`, `zoomToExtent`, `scale`, `initializeDefaults`,
  `addMapLayer(..., addToLegend)`, `QgsLayoutItemPicture.Zoom`, etc.).
- **No ejecutado** con GDAL/QGIS reales: la máquina local es Windows y no tiene
  ninguno de los dos. Queda pendiente el primer run en el runner Ubuntu.

## Errores y soluciones

- `QgsLayoutItemLegend.setCustomLayerTree` no es público en 3.34: se sustituyó
  por leyenda auto-actualizada sobre el árbol del proyecto.
- `QgsApplication` se inicializaba después de crear las capas: se movió
  `initQgis()` antes de cargar DEM y límite, con `exitQgis()` en `finally`.
- `layout.referenceMap()` no es la API del elemento mapa: `_construir_poster`
  devuelve ahora la escala calculada con `mapa.scale()`.

## Tokens y costo

No se registró el consumo exacto. Costo monetario: 0 USD (modelo gratuito).
