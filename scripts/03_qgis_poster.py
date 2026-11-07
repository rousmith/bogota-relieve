#!/usr/bin/env python3
# =============================================================================
# scripts/03_qgis_poster.py — Etapa 3: póster con PyQGIS (offscreen, sin GUI)
# =============================================================================
#
# Genera un póster cartográfico de Bogotá D.C. a partir de las salidas de la
# etapa 02:
#   output/dem_bogota_9377.tif        (DEM recortado, EPSG:9377)
#   output/hillshade_bogota_9377.tif  (sombreado recortado)
#   output/limite_bogota_9377.gpkg    (límite reproyectado)
#   output/rampa_hipsometrica.txt     (paleta hipsométrica)
#   output/relieve_bogota.json        (metadatos)
#
# El póster incluye: título, subtítulo, mapa con relieve sombreado, leyenda
# hipsométrica, flecha de norte, escala gráfica, fuente de datos y CRS.
# Se exporta a PNG (300 ppp por defecto) y PDF.
#
# Uso (siempre sin GUI):
#   bash scripts/03_qgis_poster.sh
#   bash scripts/03_qgis_poster.sh --formato png --dpi 200
#   bash scripts/03_qgis_poster.sh --salida output/poster_bogota
#
# Dependencias (Ubuntu 24.04 headless):
#   sudo apt-get update
#   sudo apt-get install -y --no-install-recommends qgis python3-qgis fonts-dejavu-core
#   # QGIS 3.34.4 (Universe) + PyQGIS 3.34; no hace falta xvfb.
#
# La variable QT_QPA_PLATFORM=offscreen se fija antes de importar PyQGIS: no se
# abre ninguna ventana ni se necesita servidor X. La aplicación QGIS se crea
# con GUI deshabilitada.
#
# Salidas: output/poster_bogota.png y output/poster_bogota.pdf (configurables).
# =============================================================================

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
from pathlib import Path

# Debe fijarse ANTES de importar qgis/PyQt: plataforma Qt sin pantalla.
os.environ["QT_QPA_PLATFORM"] = "offscreen"

ROOT = Path(__file__).resolve().parents[1]

try:
    from qgis.core import (
        Qgis,
        QgsApplication,
        QgsColorRampShader,
        QgsContrastEnhancement,
        QgsCoordinateReferenceSystem,
        QgsFillSymbol,
        QgsLayoutExporter,
        QgsLayoutItemLabel,
        QgsLayoutItemLegend,
        QgsLayoutItemMap,
        QgsLayoutItemPicture,
        QgsLayoutItemScaleBar,
        QgsLayoutItemShape,
        QgsLayoutMeasurement,
        QgsLayoutPoint,
        QgsLayoutSize,
        QgsPrintLayout,
        QgsProject,
        QgsRasterBandStats,
        QgsRasterLayer,
        QgsRasterShader,
        QgsSingleBandGrayRenderer,
        QgsSingleBandPseudoColorRenderer,
        QgsSingleSymbolRenderer,
        QgsTextFormat,
        QgsVectorLayer,
    )
    from qgis.PyQt.QtCore import Qt
    from qgis.PyQt.QtGui import QColor, QFont, QPainter
except ImportError as exc:  # pragma: no cover - depende del entorno
    if any(a in ("-h", "--help") for a in sys.argv[1:]):
        print(__doc__)
        raise SystemExit(0) from None
    print(
        "ERROR: no se pudo importar PyQGIS (qgis.core).\n"
        f"       Detalle: {exc}\n"
        "       Instala QGIS con:\n"
        "         sudo apt-get update && sudo apt-get install -y "
        "--no-install-recommends qgis python3-qgis fonts-dejavu-core",
        file=sys.stderr,
    )
    raise SystemExit(1) from None

MM = Qgis.LayoutUnit.Millimeters

# Paleta de respaldo (la misma que genera la etapa 02).
PALETA_RESPALDO = [
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


def _ruta(valor: str) -> Path:
    """Resuelve una ruta relativa contra la raíz del repositorio."""
    p = Path(valor)
    return p if p.is_absolute() else (ROOT / p)


def _miles(valor: float) -> str:
    """Formatea un número con separador de miles al estilo español."""
    return f"{int(round(valor)):,}".replace(",", ".")


def _leer_meta(ruta: Path) -> dict:
    if not ruta.is_file():
        return {}
    try:
        with ruta.open(encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"AVISO: no se pudo leer {ruta}: {exc}", file=sys.stderr)
        return {}


def _leer_rampa(ruta: Path) -> list[tuple[float, tuple[int, int, int]]]:
    """Lee el formato de gdaldem color-relief: 'valor R G B'."""
    items: list[tuple[float, tuple[int, int, int]]] = []
    if not ruta.is_file():
        return items
    try:
        lineas = ruta.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        print(f"AVISO: no se pudo leer {ruta}: {exc}", file=sys.stderr)
        return items
    for linea in lineas:
        texto = linea.strip()
        if not texto or texto.startswith("#"):
            continue
        partes = texto.split()
        if partes[0].lower() == "nv" or len(partes) < 4:
            continue
        try:
            valor = float(partes[0])
            r, g, b = (int(partes[1]), int(partes[2]), int(partes[3]))
        except ValueError:
            continue
        items.append((valor, (r, g, b)))
    items.sort(key=lambda x: x[0])
    return items


def _rampa_por_defecto(mn: float, mx: float) -> list[tuple[float, tuple[int, int, int]]]:
    return [(mn + (mx - mn) * f, rgb) for f, rgb in PALETA_RESPALDO]


def _etiqueta(
    layout: QgsPrintLayout,
    texto: str,
    x: float,
    y: float,
    ancho: float,
    alto: float,
    tam: float,
    color: str = "#1b2a2f",
    negrita: bool = False,
    halign=Qt.AlignLeft,
    valign=Qt.AlignVCenter,
) -> QgsLayoutItemLabel:
    """Crea una etiqueta de maquetación con formato tipográfico explícito."""
    item = QgsLayoutItemLabel(layout)
    item.setText(texto)

    fmt = QgsTextFormat()
    fuente = QFont("DejaVu Sans")
    fuente.setBold(negrita)
    fmt.setFont(fuente)
    fmt.setSize(tam)
    fmt.setColor(QColor(color))
    item.setTextFormat(fmt)

    item.setHAlign(halign)
    item.setVAlign(valign)
    item.setMargin(0)

    layout.addLayoutItem(item)
    item.attemptMove(QgsLayoutPoint(x, y, MM))
    item.attemptResize(QgsLayoutSize(ancho, alto, MM))
    return item


def _colocar(layout, item, x, y, ancho, alto) -> None:
    layout.addLayoutItem(item)
    item.attemptMove(QgsLayoutPoint(x, y, MM))
    item.attemptResize(QgsLayoutSize(ancho, alto, MM))


def _crear_svg_norte(destino: Path) -> Path:
    """Genera una flecha de norte propia (no depende de recursos de QGIS).

    El SVG solo contiene la flecha: la letra «N» se añade como etiqueta de
    maquetación para que la dibuje QGIS con la misma tipografía que el resto
    del póster (el soporte de texto de QtSvg es limitado).
    """
    svg = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="72" height="84" viewBox="0 0 72 84">
  <polygon points="36,4 64,78 36,64 8,78" fill="#1b2a2f"/>
  <polygon points="36,4 36,64 8,78" fill="#7d8b90"/>
</svg>
"""
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(svg, encoding="utf-8")
    return destino


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Genera el póster de relieve de Bogotá con PyQGIS offscreen.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--dem", default="output/dem_bogota_9377.tif")
    parser.add_argument("--hillshade", default="output/hillshade_bogota_9377.tif")
    parser.add_argument("--limite", default="output/limite_bogota_9377.gpkg")
    parser.add_argument("--rampa", default="output/rampa_hipsometrica.txt")
    parser.add_argument("--metadata", default="output/relieve_bogota.json")
    parser.add_argument(
        "--salida",
        default="output/poster_bogota",
        help="Ruta base sin extensión; se añaden .png y/o .pdf",
    )
    parser.add_argument(
        "--formato",
        choices=("png", "pdf", "ambos"),
        default="ambos",
        help="Formato de exportación",
    )
    parser.add_argument("--dpi", type=int, default=300, help="Resolución de exportación")
    parser.add_argument(
        "--titulo",
        default="Relieve de Bogotá D.C.",
        help="Título del póster",
    )
    return parser.parse_args()


def _cargar_capas(args, meta: dict):
    dem_path = _ruta(args.dem)
    gpkg_path = _ruta(args.limite)
    hs_path = _ruta(args.hillshade)

    if not dem_path.is_file():
        raise SystemExit(
            f"ERROR: no existe {dem_path}. Ejecuta primero: bash scripts/02_gdal_process.sh"
        )
    if not gpkg_path.is_file():
        raise SystemExit(
            f"ERROR: no existe {gpkg_path}. Ejecuta primero: bash scripts/02_gdal_process.sh"
        )

    dem = QgsRasterLayer(str(dem_path), "DEM Bogotá", "gdal")
    if not dem.isValid():
        raise SystemExit(f"ERROR: QGIS no pudo cargar el DEM: {dem_path}")

    vl = QgsVectorLayer(str(gpkg_path), "Límite de Bogotá", "ogr")
    if not vl.isValid() or vl.featureCount() < 1:
        raise SystemExit(f"ERROR: QGIS no pudo cargar el límite: {gpkg_path}")

    hl = None
    if hs_path.is_file():
        hl = QgsRasterLayer(str(hs_path), "Sombreado", "gdal")
        if not hl.isValid():
            print(f"AVISO: no se pudo cargar {hs_path}; póster sin sombreado.", file=sys.stderr)
            hl = None
    else:
        print(f"AVISO: no existe {hs_path}; póster sin sombreado.", file=sys.stderr)

    # Rango de elevación: metadatos, rampa o estadísticas del ráster.
    mn = meta.get("dem", {}).get("elev_min_m")
    mx = meta.get("dem", {}).get("elev_max_m")
    items = _leer_rampa(_ruta(args.rampa))
    if items:
        mn = items[0][0]
        mx = items[-1][0]

    if mn is None or mx is None:
        stats = dem.dataProvider().bandStatistics(
            1, QgsRasterBandStats.Min | QgsRasterBandStats.Max
        )
        mn = stats.minimumValue if mn is None else mn
        mx = stats.maximumValue if mx is None else mx

    try:
        mn = float(mn)
        mx = float(mx)
    except (TypeError, ValueError):
        raise SystemExit("ERROR: no se pudo determinar el rango de elevación del DEM.") from None

    if not (mx > mn) or mn < -1000:
        raise SystemExit(
            f"ERROR: rango de elevación sospechoso ({mn}, {mx}); revisa la etapa 02."
        )

    if not items:
        items = _rampa_por_defecto(mn, mx)
        print(f"AVISO: no se encontró la rampa; se usa la paleta interna.", file=sys.stderr)

    # Renderer hipsométrico (pseudocolor con rampa continua).
    shader = QgsColorRampShader()
    shader.setColorRampType(QgsColorRampShader.Interpolated)
    shader.setColorRampItemList(
        [
            QgsColorRampShader.ColorRampItem(
                valor, QColor(r, g, b), _miles(valor)
            )
            for valor, (r, g, b) in items
        ]
    )
    raster_shader = QgsRasterShader()
    raster_shader.setRasterShaderFunction(shader)
    renderer = QgsSingleBandPseudoColorRenderer(dem.dataProvider(), 1, raster_shader)
    renderer.setClassificationMin(mn)
    renderer.setClassificationMax(mx)
    dem.setRenderer(renderer)

    # Sombreado: gris con estiramiento fijo 0–255 y multiplicación suave.
    if hl is not None:
        gr = QgsSingleBandGrayRenderer(hl.dataProvider(), 1)
        ce = QgsContrastEnhancement(hl.dataProvider().dataType(1))
        ce.setContrastEnhancementAlgorithm(QgsContrastEnhancement.StretchToMinimumMaximum)
        ce.setMinimumValue(0)
        ce.setMaximumValue(255)
        gr.setContrastEnhancement(ce)
        hl.setRenderer(gr)
        hl.setOpacity(0.55)
        hl.setBlendMode(QPainter.CompositionMode_Multiply)

    # Límite: solo contorno, sin relleno.
    simbolo = QgsFillSymbol.createSimple(
        {
            "style": "no",
            "outline_color": "#1b2a2f",
            "outline_width": "0.5",
            "outline_style": "solid",
        }
    )
    vl.setRenderer(QgsSingleSymbolRenderer(simbolo))

    return dem, hl, vl, mn, mx


def _construir_poster(
    dem,
    hl,
    vl,
    mn: float,
    mx: float,
    meta: dict,
    args,
):
    project = QgsProject.instance()
    project.setCrs(QgsCoordinateReferenceSystem("EPSG:9377"))
    project.removeAllMapLayers()
    # El DEM y el límite sí entran en la leyenda; el sombreado se añade al
    # proyecto pero no al árbol de capas, para que no aparezca en ella.
    project.addMapLayer(dem)
    project.addMapLayer(vl)
    if hl is not None:
        project.addMapLayer(hl, False)

    layout = QgsPrintLayout(project)
    layout.initializeDefaults()
    layout.setName("poster_bogota")
    pagina = layout.pageCollection().page(0)
    pagina.setPageSize(QgsLayoutSize(297, 420, MM))

    # ------------------------------------------------------------------
    # Mapa
    # ------------------------------------------------------------------
    mapa = QgsLayoutItemMap(layout)
    layout.addLayoutItem(mapa)

    extension = vl.extent()
    extension.grow(max(extension.width(), extension.height()) * 0.012)

    alto = 305.0
    ancho = alto * extension.width() / extension.height()
    if ancho > 175.0:
        ancho = 175.0
        alto = ancho * extension.height() / extension.width()
    x_mapa = (297.0 - ancho) / 2.0
    y_mapa = 49.0

    mapa.attemptMove(QgsLayoutPoint(x_mapa, y_mapa, MM))
    mapa.attemptResize(QgsLayoutSize(ancho, alto, MM))
    mapa.setCrs(QgsCoordinateReferenceSystem("EPSG:9377"))
    capas = [vl, hl, dem] if hl is not None else [vl, dem]
    mapa.setLayers(capas)
    mapa.setBackgroundEnabled(True)
    mapa.setBackgroundColor(QColor("#ffffff"))
    mapa.setFrameEnabled(True)
    mapa.setFrameStrokeColor(QColor("#3b3b3b"))
    mapa.setFrameStrokeWidth(QgsLayoutMeasurement(0.4, MM))
    mapa.zoomToExtent(extension)

    # ------------------------------------------------------------------
    # Título, subtítulo y filete
    # ------------------------------------------------------------------
    _etiqueta(layout, args.titulo, 14, 10.5, 269, 17, 26, negrita=True)
    try:
        resolucion = float(meta.get("resolucion_m", 30) or 30)
    except (TypeError, ValueError):
        resolucion = 30.0
    _etiqueta(
        layout,
        "Modelo digital de superficie · Copernicus GLO-30 · "
        f"{resolucion:.0f} m · Bogotá D.C., Colombia",
        14,
        28.5,
        269,
        9,
        10.5,
        color="#555555",
    )

    filete = QgsLayoutItemShape(layout)
    filete.setShapeType(QgsLayoutItemShape.Rectangle)
    filete.setSymbol(
        QgsFillSymbol.createSimple({"color": "#1b2a2f", "outline_style": "no"})
    )
    _colocar(layout, filete, 14, 44.5, 269, 0.7)

    # ------------------------------------------------------------------
    # Leyenda hipsométrica (panel izquierdo)
    # ------------------------------------------------------------------
    panel_izq_x = 14.0
    panel_izq_w = max(40.0, x_mapa - 8.0 - panel_izq_x)

    leyenda = QgsLayoutItemLegend(layout)
    leyenda.setLinkedMap(mapa)
    # La leyenda sigue el árbol de capas del proyecto (DEM + límite); el
    # sombreado se añadió sin entrada de leyenda, así que no aparece.
    leyenda.setAutoUpdateModel(True)
    leyenda.setTitle("Elevación (m)")
    leyenda.setColumnCount(1)
    leyenda.setSymbolWidth(10)
    leyenda.setBackgroundEnabled(True)
    leyenda.setBackgroundColor(QColor("#ffffff"))
    leyenda.setFrameEnabled(True)
    leyenda.setFrameStrokeColor(QColor("#d5d5d5"))
    _colocar(layout, leyenda, panel_izq_x, 62, panel_izq_w, 165)

    _etiqueta(
        layout,
        "Metros sobre el nivel del mar",
        panel_izq_x,
        229,
        panel_izq_w,
        7,
        7.5,
        color="#666666",
        valign=Qt.AlignTop,
    )
    _etiqueta(
        layout,
        f"Rango de elevación\n{_miles(mn)} – {_miles(mx)} m\n\n"
        "Resolución\n"
        f"{resolucion:.0f} m\n\n"
        "Proyección\nEPSG:9377",
        panel_izq_x,
        240,
        panel_izq_w,
        95,
        8,
        color="#333333",
        valign=Qt.AlignTop,
    )

    # ------------------------------------------------------------------
    # Norte y escala (panel derecho)
    # ------------------------------------------------------------------
    panel_der_x = x_mapa + ancho + 8.0
    panel_der_w = max(40.0, 283.0 - panel_der_x)

    svg_norte = _crear_svg_norte(_ruta(args.salida).parent / "norte.svg")
    norte_x = panel_der_x + (panel_der_w - 18.0) / 2.0
    _etiqueta(
        layout,
        "N",
        panel_der_x,
        54,
        panel_der_w,
        8,
        12,
        negrita=True,
        halign=Qt.AlignHCenter,
        valign=Qt.AlignBottom,
    )
    norte = QgsLayoutItemPicture(layout)
    norte.setPicturePath(str(svg_norte), QgsLayoutItemPicture.FormatSVG)
    norte.setResizeMode(QgsLayoutItemPicture.Zoom)
    _colocar(layout, norte, norte_x, 62, 18, 21)

    _etiqueta(
        layout,
        "Escala gráfica",
        panel_der_x,
        105,
        panel_der_w,
        8,
        8,
        negrita=True,
        halign=Qt.AlignHCenter,
    )

    escala = mapa.scale()
    objetivo_mm = 50.0
    km_segmento = objetivo_mm * escala / 1e6 / 2.0
    opciones = (1, 2, 5, 10, 20, 25, 50, 100)
    segmento = max([o for o in opciones if o <= km_segmento] or [1])

    barra = QgsLayoutItemScaleBar(layout)
    barra.setLinkedMap(mapa)
    barra.setStyle("Single Box")
    barra.setUnits(Qgis.DistanceUnit.Kilometers)
    barra.setUnitsPerSegment(float(segmento))
    barra.setNumberOfSegments(2)
    barra.setNumberOfSegmentsLeft(0)
    barra.setNumberOfSubdivisions(1)
    barra.setHeight(3.2)
    _colocar(layout, barra, panel_der_x, 116, panel_der_w, 16)

    _etiqueta(
        layout,
        f"1:{_miles(escala)}",
        panel_der_x,
        134,
        panel_der_w,
        8,
        8.5,
        halign=Qt.AlignHCenter,
    )
    _etiqueta(
        layout,
        "MAGNA-SIRGAS\nOrigen Nacional",
        panel_der_x,
        156,
        panel_der_w,
        16,
        7.5,
        color="#666666",
        halign=Qt.AlignHCenter,
        valign=Qt.AlignTop,
    )

    # ------------------------------------------------------------------
    # Pie: fuentes, CRS y fecha
    # ------------------------------------------------------------------
    fecha = str(meta.get("generado_utc", ""))[:10]
    if not fecha:
        fecha = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")

    _etiqueta(
        layout,
        "Fuente: Copernicus DEM GLO-30 (© ESA/Airbus) · "
        "Límite: geoBoundaries gbOpen (ODbL 1.0) · "
        f"Generado: {fecha}",
        14,
        388,
        190,
        14,
        7.2,
        color="#555555",
        valign=Qt.AlignTop,
    )
    _etiqueta(
        layout,
        f"MAGNA-SIRGAS / Origen Nacional · EPSG:9377\n"
        f"Escala 1:{_miles(escala)}",
        204,
        388,
        79,
        14,
        7.2,
        color="#555555",
        halign=Qt.AlignRight,
        valign=Qt.AlignTop,
    )

    return layout, escala


def main() -> int:
    args = _parse_args()
    if args.dpi < 72:
        print("ERROR: --dpi debe ser >= 72.", file=sys.stderr)
        return 2

    salida = _ruta(args.salida)
    if salida.suffix.lower() in (".png", ".pdf"):
        salida = salida.with_suffix("")
    salida.parent.mkdir(parents=True, exist_ok=True)

    # Guardia: nunca escribir en data/.
    try:
        salida.parent.resolve().relative_to((ROOT / "data").resolve())
        print("ERROR: la salida no puede estar dentro de data/.", file=sys.stderr)
        return 1
    except ValueError:
        pass

    meta = _leer_meta(_ruta(args.metadata))

    # QgsApplication debe existir antes de instanciar capas (QgsRasterLayer,
    # QgsVectorLayer) y proveedores de datos.
    QgsApplication.setPrefixPath(os.environ.get("QGIS_PREFIX_PATH", "/usr"), True)
    app = QgsApplication([], False)
    app.initQgis()
    try:
        print("==> Cargando capas y preparando el póster")
        dem, hl, vl, mn, mx = _cargar_capas(args, meta)

        print("    Construyendo la maquetación A3 (offscreen, sin GUI)")
        layout, escala = _construir_poster(dem, hl, vl, mn, mx, meta, args)

        exporter = QgsLayoutExporter(layout)
        generados = []

        if args.formato in ("png", "ambos"):
            png = salida.with_suffix(".png")
            ajustes = QgsLayoutExporter.ImageExportSettings()
            ajustes.dpi = float(args.dpi)
            ajustes.cropToContents = False
            print(f"    Exportando PNG ({args.dpi} ppp): {png}")
            resultado = exporter.exportToImage(str(png), ajustes)
            if resultado != QgsLayoutExporter.Success:
                raise RuntimeError(f"exportToImage devolvió el código {resultado}")
            generados.append(png)

        if args.formato in ("pdf", "ambos"):
            pdf = salida.with_suffix(".pdf")
            ajustes_pdf = QgsLayoutExporter.PdfExportSettings()
            ajustes_pdf.dpi = float(args.dpi)
            ajustes_pdf.rasterizeWholeImage = False
            ajustes_pdf.forceVectorOutput = False
            print(f"    Exportando PDF: {pdf}")
            resultado = exporter.exportToPdf(str(pdf), ajustes_pdf)
            if resultado != QgsLayoutExporter.Success:
                raise RuntimeError(f"exportToPdf devolvió el código {resultado}")
            generados.append(pdf)

        print()
        print("================= RESUMEN (etapa 03_qgis_poster) =================")
        print("Plataforma Qt: offscreen (sin ventana ni servidor X)")
        print(f"CRS del mapa: EPSG:9377 · rango {_miles(mn)}–{_miles(mx)} m")
        print(f"Escala aproximada: 1:{_miles(escala)}")
        for ruta in generados:
            if not ruta.is_file() or ruta.stat().st_size == 0:
                raise RuntimeError(f"salida ausente o vacía: {ruta}")
            print(f"  {ruta}  ({ruta.stat().st_size / 1e6:.2f} MB)")
        print("==================================================================")
        print("Siguiente etapa: bash scripts/04_blender_relief.sh")
        return 0
    finally:
        app.exitQgis()


if __name__ == "__main__":
    raise SystemExit(main())
