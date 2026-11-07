# Scripts del pipeline

Cada etapa es un script CLI reproducible, pensado para Ubuntu **headless**
(runner de GitHub Actions, sin pantalla ni drivers gráficos). Los prefijos
numerados fijan el orden de ejecución.

```
scripts/01_download.sh        entradas en data/ (DEM + límite)
scripts/02_gdal_process.sh    recorte, hillshade, color-relief, heightmap 16 bits
scripts/03_qgis_poster.sh     póster con PyQGIS offscreen (wrapper del .py)
scripts/03_qgis_poster.py     implementación del póster
scripts/04_blender_relief.sh  ejecuta Blender en modo batch
scripts/04_blender_relief.py  malla, render y exportación GLB
```

Todo se escribe en `output/`; `data/` es de solo lectura para estas etapas.

---

## Instalación (Ubuntu 24.04, sin GUI)

```bash
sudo apt-get update
sudo apt-get install -y --no-install-recommends \
  gdal-bin python3 qgis python3-qgis fonts-dejavu-core blender
```

Versiones con las que se validó el diseño: GDAL 3.8.4 (`gdal-bin`) y QGIS 3.34.4
(`qgis` / `python3-qgis`), ambos en el repositorio *universe* de Ubuntu noble.

No hace falta `xvfb`: la etapa 03 fuerza `QT_QPA_PLATFORM=offscreen`, así que
Qt no necesita servidor X ni abre ninguna ventana.

Comprobación rápida del entorno:

```bash
gdalinfo --version
python3 -c 'import qgis.core; print(qgis.core.Qgis.QGIS_VERSION)'
```

---

## Ejecución

```bash
bash scripts/01_download.sh        # descarga entradas en data/
bash scripts/02_gdal_process.sh    # procesa con GDAL y escribe en output/
bash scripts/03_qgis_poster.sh     # póster PNG + PDF con PyQGIS offscreen
bash scripts/04_blender_relief.sh  # relieve, render y GLB con Blender batch
```

Opciones útiles:

```bash
bash scripts/02_gdal_process.sh --max-px 2048   # heightmap más detallado
bash scripts/02_gdal_process.sh --res 20        # rejilla de trabajo de 20 m
bash scripts/02_gdal_process.sh --sin-remoto    # exige teselas locales

bash scripts/03_qgis_poster.sh --formato png --dpi 200
bash scripts/03_qgis_poster.sh --salida output/poster_bogota
bash scripts/03_qgis_poster.sh --help

bash scripts/04_blender_relief.sh --resolucion 384 --exageracion 2
bash scripts/04_blender_relief.sh --sin-render  # más rápido para depurar CI
```

Las dos etapas aceptan `--help` y devuelven códigos de salida explícitos
(`0` éxito, `1` error de datos, `2` argumento inválido).

---

## Etapa 02 — `02_gdal_process.sh`

Entradas de `data/`:

- `data/dem_bogota_*.tif`: teselas Copernicus GLO-30 en EPSG:4326.
- `data/limite_bogota.geojson`: límite administrativo de Bogotá D.C.

Qué hace, en orden:

1. Valida dependencias (GDAL ≥ 3.4), teselas y límite.
2. Reproyecta el límite a **EPSG:9377** y calcula una rejilla canónica de 30 m
   (por defecto) que contiene el límite completo.
3. Comprueba la cobertura real del DEM por celdas Copernicus de 1°×1° usando
   los `cornerCoordinates` de `gdalinfo`. Si falta una tesela y no se pasó
   `--sin-remoto`, la lee del bucket público con `/vsicurl` (no escribe en
   `data/`).
4. Genera todas las capas sobre la **misma rejilla** (`-te`/`-tr`), para que
   DEM, sombreado, textura, heightmap y máscara estén alineados píxel a píxel:

| Salida | Contenido |
| --- | --- |
| `output/dem_bogota_9377.tif` | DEM recortado al polígono, float32, nodata -9999 |
| `output/hillshade_bogota_9377.tif` | sombreado recortado, Int16, nodata -9999 |
| `output/hillshade_bogota.png` | sombreado RGBA, transparente fuera |
| `output/textura_bogota.png` | color-relief hipsométrico RGBA |
| `output/heightmap_bogota_16bit.png` | heightmap **UInt16** para Blender |
| `output/heightmap_bogota_16bit.tif` | mismo heightmap georreferenciado |
| `output/mascara_bogota_8bit.png` | 255 dentro del límite, 0 fuera |
| `output/rampa_hipsometrica.txt` | paleta usada (formato `gdaldem color-relief`) |
| `output/limite_bogota_9377.gpkg` | límite reproyectado a EPSG:9377 |
| `output/relieve_bogota.json` | bbox, rango, fórmula, hashes de las fuentes |

5. Valida CRS de salida, tipo del heightmap (`UInt16`), dimensiones y rango de
   elevación.

### Heightmap: cómo leerlo en Blender

Normalización lineal sobre el rectángulo completo del límite:

```
elev (m) = elev_min + (pixel / 65535) * (elev_max - elev_min)
```

`0` = `elev_min`, `65535` = `elev_max`. La fila 0 es el **norte**; al mapear la
textura en Blender hay que invertir el eje V (o usar `flip` en la imagen) para
que el relieve no salga espejado. El heightmap es rectangular (sin agujeros);
usa `mascara_bogota_8bit.png` para recortar la malla al polígono.

---

## Etapa 03 — `03_qgis_poster.sh` / `03_qgis_poster.py`

Genera un póster A3 (297×420 mm) con:

- mapa hipsométrico + sombreado multiplicado,
- leyenda de elevación restringida a DEM y límite,
- flecha de norte (SVG generado por el script, sin depender de recursos QGIS),
- escala gráfica y escala numérica,
- fuente de datos, CRS y fecha.

Salidas por defecto: `output/poster_bogota.png` (300 ppp) y
`output/poster_bogota.pdf`, más `output/norte.svg`.

El wrapper fija y verifica el entorno headless antes de ejecutar el `.py`:

```bash
export QT_QPA_PLATFORM=offscreen
export QGIS_PREFIX_PATH=/usr
unset DISPLAY WAYLAND_DISPLAY
```

Si PyQGIS no está instalado, el wrapper termina con el comando exacto de
instalación; no hay que tocar la GUI de QGIS en ningún momento.

---

## Etapa 04 — `04_blender_relief.sh` / `04_blender_relief.py`

Blender se ejecuta con `-b --factory-startup`: no abre ventanas ni usa GPU.
Lee el heightmap UInt16, la textura, la máscara y los metadatos de la etapa 02.
Construye una malla cerrada con base sólida, exageración vertical configurable
y textura hipsométrica. Produce:

- `output/bogota_relieve.glb`: modelo glTF binario para `<model-viewer>`;
- `output/bogota_relieve.png`: render de presentación con Cycles en CPU;
- `output/blender_relieve.json`: parámetros, hashes y tamaño del modelo.

El script comprueba la cabecera glTF 2.0 y exige que el GLB pese menos de
25 MiB. Si se excede, reduce automáticamente la resolución de la malla y vuelve
a exportar. La resolución inicial de 384 px evita cargas excesivas en móviles.

---

## Verificación manual (útil en CI)

```bash
gdalinfo output/dem_bogota_9377.tif | head -n 20
gdalinfo output/heightmap_bogota_16bit.png   # debe decir Type=UInt16
du -h output/*
python3 -c "import json;d=json.load(open('output/relieve_bogota.json'));print(d['bbox_9377'],d['dem']['elev_min_m'],d['dem']['elev_max_m'])"
```

---

## Problemas frecuentes

- **`import qgis.core` falla**: falta `python3-qgis` (el paquete `qgis` solo no
  instala los bindings de Python).
- **Qt intenta abrir una ventana / error de `xcb`**: no se usó el wrapper; hay
  que lanzar `bash scripts/03_qgis_poster.sh`, que exporta
  `QT_QPA_PLATFORM=offscreen`.
- **Faltan teselas del DEM**: la etapa 02 las completa con `/vsicurl` si hay
  red. Con `--sin-remoto` falla y lista los `curl` exactos para dejarlas en
  `data/`. La tesela `N04_00_W075_00` **no cubre todo Bogotá**: hacen falta
  también `N03_00_W075_00`, `N04_00_W074_00` y `N03_00_W074_00`.
- **Texto borroso o con cuadros en el PDF/PNG**: instala `fonts-dejavu-core`;
  el póster usa «DejaVu Sans».
