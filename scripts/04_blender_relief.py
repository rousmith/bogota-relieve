#!/usr/bin/env python3
# =============================================================================
# scripts/04_blender_relief.py — Etapa 4: relieve 3D de Bogotá en Blender
# =============================================================================
#
# Construye un modelo de relieve 3D a partir de las salidas de la etapa 02 y
# produce el visor web de la etapa 05:
#
#   output/heightmap_bogota_16bit.png   heightmap UInt16 (0 = elev_min)
#   output/textura_bogota.png           color-relief hipsométrico RGBA
#   output/mascara_bogota_8bit.png      255 dentro del límite, 0 fuera
#   output/relieve_bogota.json          bbox, rango de elevación y metadatos
#
# Salidas:
#   output/bogota_relieve.glb           modelo para <model-viewer> (< 25 MB)
#   output/bogota_relieve.png           render de presentación (Cycles CPU)
#   output/blender_relieve.json         parámetros, estadísticas y hashes
#
# Cómo funciona:
#   1. Lee el heightmap con un decodificador PNG propio (zlib + filtros PNG),
#      sin depender de bibliotecas externas ni del espacio de color de Blender.
#      Así los valores UInt16 se leen exactos y la fórmula de la etapa 02 se
#      aplica tal cual.
#   2. Construye una malla de cuadriláteros en unidades de km (1 unidad = 1 km):
#      la superficie dentro del polígono (máscara), paredes verticales en el
#      borde y un fondo espejo a la cota de la base: el modelo queda cerrado y
#      con base sólida, sin depender de triángulos de relleno frágiles.
#   3. Aplica la textura hipsométrica con UV normalizadas (norte arriba → se
#      invierte V, tal como advierte la etapa 02) y un material oscuro a las
#      paredes y a la base.
#   4. Exporta el .glb y comprueba su tamaño real. Si supera el límite (25 MB
#      por defecto), reduce la resolución y vuelve a exportar automáticamente.
#   5. Si no se pidió --sin-render, monta cámara ortográfica en tres cuartos,
#      sol principal + relleno, suelo y renderiza con Cycles en CPU (no usa
#      GPU ni OpenGL: funciona en un runner headless sin drivers gráficos).
#
# Uso (siempre en lote, nunca con GUI):
#   bash scripts/04_blender_relief.sh
#   bash scripts/04_blender_relief.sh --resolucion 512 --exageracion 2.5
#   bash scripts/04_blender_relief.sh --sin-render
#   bash scripts/04_blender_relief.sh --help
#
# También se puede invocar Blender directamente:
#   blender -b --factory-startup --python-exit-code 1 \
#       -P scripts/04_blender_relief.py -- --resolucion 384
#
# Dependencias (Ubuntu 24.04 headless):
#   sudo apt-get update
#   sudo apt-get install -y --no-install-recommends blender
#   # Blender 4.0.2+dfsg de universe. No hace falta xvfb ni GPU.
#   # El script usa solo la API estable de Blender 3.6–4.x y el exportador
#   # glTF incluido (io_scene_gltf2).
#
# Códigos de salida: 0 = éxito | 1 = error de datos/procesamiento | 2 = args
# =============================================================================

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import math
import shutil
import struct
import sys
import tempfile
import traceback
import zlib
from array import array
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Límite duro del proyecto: el .glb publicado en GitHub Pages debe pesar < 25 MB.
LIMITE_MB_DEFECTO = 25.0
# Blender 3.6 es la versión mínima probada con las APIs que usa este script.
VERSION_MINIMA = (3, 6, 0)


# ---------------------------------------------------------------------------
# Utilidades de rutas y consola
# ---------------------------------------------------------------------------
def _ruta(valor: str) -> Path:
    """Resuelve una ruta relativa contra la raíz del repositorio."""
    p = Path(valor)
    return p if p.is_absolute() else (ROOT / p)


def _log(mensaje: str = "") -> None:
    """Imprime y fuerza el vaciado: Blender en lote tampoco vacía siempre."""
    print(mensaje, flush=True)


def _sha256(ruta: Path) -> str:
    h = hashlib.sha256()
    with ruta.open("rb") as fh:
        for bloque in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(bloque)
    return h.hexdigest()


def _miles(valor: float) -> str:
    """Formatea con separador de miles al estilo español (p. ej. 12.345)."""
    return f"{int(round(valor)):,}".replace(",", ".")


def _ruta_documentada(ruta: Path) -> str:
    """Ruta relativa a la raíz si es posible (para los metadatos)."""
    try:
        return str(ruta.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(ruta).replace("\\", "/")


# ---------------------------------------------------------------------------
# Lector PNG (solo escala de grises, 8 o 16 bits, sin entrelazar)
# ---------------------------------------------------------------------------
def _dimensiones_png(ruta: Path) -> tuple[int, int, int, int]:
    """Devuelve (ancho, alto, bits, color_type) leyendo solo el IHDR."""
    datos = ruta.read_bytes()
    if datos[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{ruta} no es un PNG válido")
    if len(datos) < 33 or datos[12:16] != b"IHDR":
        raise ValueError(f"{ruta} no tiene un IHDR al inicio")
    ancho, alto, bits, color = struct.unpack(">IIBB", datos[16:26])
    return ancho, alto, bits, color


def leer_png_gris(ruta: Path) -> tuple[int, int, int, array]:
    """Decodifica un PNG en escala de grises.

    Devuelve (ancho, alto, valor_maximo, pixeles). ``pixeles`` es un
    array('H') para 16 bits o array('B') para 8 bits, en orden de filas
    (fila 0 = norte, tal como lo escribe la etapa 02).

    Se implementa aquí en vez de usar ``bpy.data.images`` porque Blender
    convierte las imágenes sRGB a espacio lineal al leer ``image.pixels``: eso
    alteraría la escala de elevación. Un PNG UInt16 leído a mano es exacto.
    """
    datos = ruta.read_bytes()
    if datos[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{ruta} no es un PNG válido")

    pos = 8
    ancho = alto = None
    bits = color = None
    compresion = filtro = interlace = None
    idat = bytearray()

    while pos + 8 <= len(datos):
        (largo,) = struct.unpack(">I", datos[pos:pos + 4])
        tipo = datos[pos + 4:pos + 8]
        cuerpo = datos[pos + 8:pos + 8 + largo]
        if len(cuerpo) != largo:
            raise ValueError(f"PNG truncado en el chunk {tipo!r} de {ruta}")
        pos += 12 + largo  # largo + tipo + datos + CRC
        if tipo == b"IHDR":
            ancho, alto, bits, color, compresion, filtro, interlace = struct.unpack(
                ">IIBBBBB", cuerpo
            )
        elif tipo == b"IDAT":
            idat.extend(cuerpo)
        elif tipo == b"IEND":
            break

    if ancho is None or alto is None:
        raise ValueError(f"PNG sin cabecera IHDR: {ruta}")
    if interlace != 0:
        raise ValueError(f"PNG entrelazado no soportado: {ruta}")
    if compresion != 0 or filtro != 0:
        raise ValueError(f"PNG con compresión/filtro no estándar: {ruta}")
    if color != 0:
        raise ValueError(
            f"{ruta} debe ser PNG en escala de grises (color type 0); "
            f"se encontró color type {color}"
        )
    if bits not in (8, 16):
        raise ValueError(f"{ruta} debe ser de 8 o 16 bits; se encontró {bits}")

    bytes_px = bits // 8
    stride = ancho * bytes_px

    try:
        crudo = zlib.decompress(bytes(idat))
    except zlib.error as exc:  # pragma: no cover - depende del archivo
        raise ValueError(f"no se pudo descomprimir el IDAT de {ruta}: {exc}") from exc

    if len(crudo) != (stride + 1) * alto:
        raise ValueError(
            f"tamaño de datos inesperado en {ruta}: "
            f"{len(crudo)} bytes, se esperaban {(stride + 1) * alto}"
        )

    salida = bytearray(stride * alto)
    previa = bytearray(stride)
    off = 0

    for fila in range(alto):
        tipo_filtro = crudo[off]
        off += 1
        linea = bytearray(crudo[off:off + stride])
        off += stride

        if tipo_filtro == 0:  # None
            pass
        elif tipo_filtro == 1:  # Sub
            for i in range(bytes_px, stride):
                linea[i] = (linea[i] + linea[i - bytes_px]) & 0xFF
        elif tipo_filtro == 2:  # Up
            for i in range(stride):
                linea[i] = (linea[i] + previa[i]) & 0xFF
        elif tipo_filtro == 3:  # Average
            for i in range(stride):
                izq = linea[i - bytes_px] if i >= bytes_px else 0
                linea[i] = (linea[i] + ((izq + previa[i]) >> 1)) & 0xFF
        elif tipo_filtro == 4:  # Paeth
            for i in range(stride):
                a = linea[i - bytes_px] if i >= bytes_px else 0
                b = previa[i]
                c = previa[i - bytes_px] if i >= bytes_px else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                linea[i] = (linea[i] + pr) & 0xFF
        else:
            raise ValueError(f"filtro PNG {tipo_filtro} desconocido en {ruta}")

        salida[fila * stride:(fila + 1) * stride] = linea
        previa = linea

    if bits == 16:
        pixeles = array("H")
        pixeles.frombytes(salida)
        # PNG guarda los 16 bits en big-endian; array usa el orden nativo.
        if sys.byteorder == "little":
            pixeles.byteswap()
        valor_max = 65535
    else:
        pixeles = array("B")
        pixeles.frombytes(salida)
        valor_max = 255

    return ancho, alto, valor_max, pixeles


def _bilineal(
    pixeles: array, ancho: int, alto: int, x: float, y: float, valor_max: int
) -> float:
    """Muestrea un píxel con interpolación bilineal y normaliza a 0..1."""
    x = min(max(x, 0.0), ancho - 1.0)
    y = min(max(y, 0.0), alto - 1.0)
    x0 = int(math.floor(x))
    y0 = int(math.floor(y))
    x1 = min(x0 + 1, ancho - 1)
    y1 = min(y0 + 1, alto - 1)
    fx = x - x0
    fy = y - y0

    p00 = pixeles[y0 * ancho + x0]
    p10 = pixeles[y0 * ancho + x1]
    p01 = pixeles[y1 * ancho + x0]
    p11 = pixeles[y1 * ancho + x1]

    valor = (
        p00 * (1.0 - fx) * (1.0 - fy)
        + p10 * fx * (1.0 - fy)
        + p01 * (1.0 - fx) * fy
        + p11 * fx * fy
    )
    return valor / valor_max


def _mascara_dentro(
    pixeles: array, ancho: int, alto: int, x: float, y: float, umbral: int = 127
) -> bool:
    """Muestreo por vecino más cercano de la máscara (255 dentro)."""
    xi = int(round(min(max(x, 0.0), ancho - 1.0)))
    yi = int(round(min(max(y, 0.0), alto - 1.0)))
    return pixeles[yi * ancho + xi] > umbral


# ---------------------------------------------------------------------------
# Argumentos (se parsean antes de importar bpy para permitir --help sin Blender)
# ---------------------------------------------------------------------------
def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="04_blender_relief.py",
        description=(
            "Etapa 04: construye el relieve 3D de Bogotá en Blender (batch), "
            "exporta output/bogota_relieve.glb (<25 MB) y un render PNG."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Ejemplos:\n"
            "  bash scripts/04_blender_relief.sh\n"
            "  bash scripts/04_blender_relief.sh --resolucion 512 --exageracion 2.5\n"
            "  bash scripts/04_blender_relief.sh --sin-render\n"
            "\n"
            "El .glb se valida tras exportar: si supera --limite-mb se reduce la\n"
            "resolución de la malla y se reintenta automáticamente.\n"
        ),
    )
    parser.add_argument(
        "--heightmap",
        default="output/heightmap_bogota_16bit.png",
        help="heightmap UInt16 de la etapa 02 (por defecto: %(default)s)",
    )
    parser.add_argument(
        "--textura",
        default="output/textura_bogota.png",
        help="textura hipsométrica de la etapa 02 (por defecto: %(default)s)",
    )
    parser.add_argument(
        "--mascara",
        default="output/mascara_bogota_8bit.png",
        help="máscara 8 bits de la etapa 02 (por defecto: %(default)s)",
    )
    parser.add_argument(
        "--metadatos",
        default="output/relieve_bogota.json",
        help="metadatos de la etapa 02 (por defecto: %(default)s)",
    )
    parser.add_argument(
        "--salida-glb",
        default="output/bogota_relieve.glb",
        help="ruta del .glb (por defecto: %(default)s)",
    )
    parser.add_argument(
        "--salida-render",
        default="output/bogota_relieve.png",
        help="ruta del render PNG (por defecto: %(default)s)",
    )
    parser.add_argument(
        "--resolucion",
        type=int,
        default=384,
        help=(
            "lado mayor de la malla en píxeles (64–2048; por defecto: %(default)s). "
            "Más resolución = más detalle y más peso."
        ),
    )
    parser.add_argument(
        "--exageracion",
        type=float,
        default=2.0,
        help="exageración vertical respecto a la escala horizontal (por defecto: %(default)s)",
    )
    parser.add_argument(
        "--profundidad",
        type=float,
        default=0.35,
        help=(
            "grosor de la base como fracción del rango vertical "
            "(por defecto: %(default)s)"
        ),
    )
    parser.add_argument(
        "--textura-max",
        type=int,
        default=2048,
        help="lado mayor de la textura incrustada en el .glb (por defecto: %(default)s)",
    )
    parser.add_argument(
        "--limite-mb",
        type=float,
        default=LIMITE_MB_DEFECTO,
        help="tamaño máximo del .glb en MB (por defecto: %(default)s)",
    )
    parser.add_argument(
        "--muestras",
        type=int,
        default=48,
        help="muestras de Cycles para el render (por defecto: %(default)s)",
    )
    parser.add_argument(
        "--ancho",
        type=int,
        default=1600,
        help="ancho del render en píxeles (por defecto: %(default)s)",
    )
    parser.add_argument(
        "--alto",
        type=int,
        default=1200,
        help="alto del render en píxeles (por defecto: %(default)s)",
    )
    parser.add_argument(
        "--sin-mascara",
        action="store_true",
        help="ignora la máscara y genera el relieve rectangular completo",
    )
    parser.add_argument(
        "--sin-render",
        action="store_true",
        help="exporta solo el .glb (más rápido en CI)",
    )
    return parser


def _validar_args(args: argparse.Namespace) -> None:
    """Comprueba rangos antes de arrancar Blender."""
    errores = []
    if not 64 <= args.resolucion <= 2048:
        errores.append("--resolucion debe estar entre 64 y 2048")
    if args.exageracion <= 0:
        errores.append("--exageracion debe ser > 0")
    if not 0.05 <= args.profundidad <= 2.0:
        errores.append("--profundidad debe estar entre 0.05 y 2.0")
    if args.textura_max < 256:
        errores.append("--textura-max debe ser >= 256")
    if args.limite_mb <= 0:
        errores.append("--limite-mb debe ser > 0")
    if args.muestras < 1:
        errores.append("--muestras debe ser >= 1")
    if args.ancho < 64 or args.alto < 64:
        errores.append("--ancho y --alto deben ser >= 64")
    if errores:
        _log("ERROR: argumentos inválidos:")
        for error in errores:
            _log(f"  - {error}")
        raise SystemExit(2)


# ---------------------------------------------------------------------------
# Preparación de la textura (opcionalmente reducida para el .glb)
# ---------------------------------------------------------------------------
def _preparar_textura(ruta: Path, max_px: int, tmp_dir: Path):
    """Carga la textura y, si excede ``max_px``, la reescala a un PNG temporal.

    Se guarda a disco y se recarga para que el exportador glTF lea exactamente
    el mismo archivo que ve el render (evita depender de si usa el búfer en
    memoria o el archivo original).
    """
    import bpy  # import local: el script debe poder compilarse fuera de Blender

    ancho, alto, _bits, _color = _dimensiones_png(ruta)
    imagen = bpy.data.images.load(str(ruta), check_existing=False)
    imagen.colorspace_settings.name = "sRGB"

    if max(ancho, alto) <= max_px:
        return imagen, (ancho, alto), False

    factor = max_px / float(max(ancho, alto))
    nuevo_ancho = max(1, int(round(ancho * factor)))
    nuevo_alto = max(1, int(round(alto * factor)))
    _log(
        f"    Textura {ancho}x{alto} px → se reduce a "
        f"{nuevo_ancho}x{nuevo_alto} px para el .glb"
    )

    try:
        imagen.scale(nuevo_ancho, nuevo_alto)
        destino = tmp_dir / "textura_escalada.png"
        imagen.filepath_raw = str(destino)
        imagen.file_format = "PNG"
        imagen.save()
    except Exception as exc:  # pragma: no cover - depende de Blender
        _log(
            f"    AVISO: no se pudo reescalar la textura ({exc}); "
            "se usa la original."
        )
        return imagen, (ancho, alto), False

    bpy.data.images.remove(imagen)
    imagen = bpy.data.images.load(str(destino), check_existing=False)
    imagen.colorspace_settings.name = "sRGB"
    imagen.pack()
    return imagen, (nuevo_ancho, nuevo_alto), True


# ---------------------------------------------------------------------------
# Materiales
# ---------------------------------------------------------------------------
def _material_textura(imagen):
    """Material del relieve: textura hipsométrica + rugosidad alta."""
    import bpy

    mat = bpy.data.materials.new("TexturaHipsometrica")
    mat.use_nodes = True
    nodos = mat.node_tree.nodes
    enlaces = mat.node_tree.links
    nodos.clear()

    salida = nodos.new("ShaderNodeOutputMaterial")
    salida.location = (320, 0)
    bsdf = nodos.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (0, 0)
    textura = nodos.new("ShaderNodeTexImage")
    textura.location = (-420, 0)
    textura.image = imagen
    textura.interpolation = "Smart"

    enlaces.new(textura.outputs["Color"], bsdf.inputs["Base Color"])
    enlaces.new(bsdf.outputs["BSDF"], salida.inputs["Surface"])
    bsdf.inputs["Roughness"].default_value = 0.85
    # El nombre del entrada especular cambió en Blender 4.x; se admite ambos.
    for nombre, valor in (("Specular IOR Level", 0.25), ("Specular", 0.25)):
        if nombre in bsdf.inputs:
            bsdf.inputs[nombre].default_value = valor
            break
    return mat


def _material_base():
    """Material oscuro para paredes y fondo: da sensación de bloque sólido."""
    import bpy

    mat = bpy.data.materials.new("BaseRelieve")
    mat.use_nodes = True
    nodos = mat.node_tree.nodes
    enlaces = mat.node_tree.links
    nodos.clear()

    salida = nodos.new("ShaderNodeOutputMaterial")
    bsdf = nodos.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Base Color"].default_value = (0.155, 0.135, 0.115, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.95
    enlaces.new(bsdf.outputs["BSDF"], salida.inputs["Surface"])
    return mat


# ---------------------------------------------------------------------------
# Construcción de la malla
# ---------------------------------------------------------------------------
def _crear_malla(
    heightmap: array,
    hm_ancho: int,
    hm_alto: int,
    hm_max: int,
    mascara: tuple[array, int, int] | None,
    resolucion: int,
    ancho_km: float,
    alto_km: float,
    escala_z_km: float,
    profundidad_km: float,
    mat_textura,
    mat_base,
):
    """Crea el objeto de relieve y devuelve (objeto, estadísticas).

    Sistema de coordenadas: X = este, Y = norte, Z = altura (1 unidad = 1 km).
    La malla es cerrada: superficie superior, paredes laterales y fondo espejo.
    """
    import bpy

    # Rejilla de la malla conservando la proporción del heightmap.
    factor = resolucion / float(max(hm_ancho, hm_alto))
    gw = max(2, int(round(hm_ancho * factor)))
    gh = max(2, int(round(hm_alto * factor)))

    celdas_w = gw - 1
    celdas_h = gh - 1

    # --- Alturas y UV de cada vértice de la rejilla -------------------------
    verts: list[tuple[float, float, float]] = []
    uvs: list[tuple[float, float]] = []
    tope_idx = [0] * (gw * gh)
    z_max = 0.0

    for j in range(gh):
        sy = j * (hm_alto - 1) / float(gh - 1)
        y = (0.5 - j / float(gh - 1)) * alto_km
        v = 1.0 - j / float(gh - 1)  # norte arriba → V invertida (etapa 02)
        for i in range(gw):
            sx = i * (hm_ancho - 1) / float(gw - 1)
            x = (i / float(gw - 1) - 0.5) * ancho_km
            u = i / float(gw - 1)

            altura_normalizada = _bilineal(heightmap, hm_ancho, hm_alto, sx, sy, hm_max)
            z = altura_normalizada * escala_z_km
            z_max = max(z_max, z)

            tope_idx[j * gw + i] = len(verts)
            verts.append((x, y, z))
            uvs.append((u, v))

    z_base = -abs(profundidad_km)

    # --- Celdas dentro del polígono -----------------------------------------
    dentro = bytearray(celdas_w * celdas_h)
    total_dentro = 0

    if mascara is not None:
        m_pixeles, m_ancho, m_alto = mascara
        for cj in range(celdas_h):
            my = (cj + 0.5) * (m_alto - 1) / float(celdas_h)
            fila = cj * celdas_w
            for ci in range(celdas_w):
                mx = (ci + 0.5) * (m_ancho - 1) / float(celdas_w)
                if _mascara_dentro(m_pixeles, m_ancho, m_alto, mx, my):
                    dentro[fila + ci] = 1
                    total_dentro += 1
        if total_dentro == 0:
            raise ValueError(
                "la máscara no contiene ninguna celda dentro del límite; "
                "revisa output/mascara_bogota_8bit.png o usa --sin-mascara"
            )
    else:
        dentro[:] = b"\x01" * len(dentro)
        total_dentro = celdas_w * celdas_h

    # --- Caras: superficie, fondo y paredes ---------------------------------
    caras: list[tuple[int, ...]] = []
    uv_caras = array("f")

    def agregar_cara(indices: tuple[int, ...]) -> None:
        caras.append(indices)
        for indice in indices:
            uv_caras.extend(uvs[indice])

    for cj in range(celdas_h):
        fila = cj * celdas_w
        for ci in range(celdas_w):
            if not dentro[fila + ci]:
                continue
            a = tope_idx[cj * gw + ci]
            b = a + 1
            c = a + gw + 1
            d = a + gw
            # Superficie: orden (a, b, c, d) → normal +Z.
            agregar_cara((a, b, c, d))

    num_tope = len(caras)

    # Fondo espejo: mismos cuadriláteros a la cota de la base, con winding
    # invertido (normal -Z). Los vértices se crean solo donde hacen falta.
    fondo_idx = [-1] * (gw * gh)

    def indice_fondo(indice_superior: int) -> int:
        if fondo_idx[indice_superior] < 0:
            x, y, _z = verts[indice_superior]
            fondo_idx[indice_superior] = len(verts)
            verts.append((x, y, z_base))
            uvs.append(uvs[indice_superior])
        return fondo_idx[indice_superior]

    for cj in range(celdas_h):
        fila = cj * celdas_w
        for ci in range(celdas_w):
            if not dentro[fila + ci]:
                continue
            a = tope_idx[cj * gw + ci]
            b = a + 1
            c = a + gw + 1
            d = a + gw
            agregar_cara(
                (
                    indice_fondo(a),
                    indice_fondo(d),
                    indice_fondo(c),
                    indice_fondo(b),
                )
            )

    # Paredes en los bordes de la máscara (y en el borde de la rejilla, si la
    # máscara llega hasta él): cierran el volumen y dan el efecto de base.
    for cj in range(celdas_h):
        fila = cj * celdas_w
        for ci in range(celdas_w):
            if not dentro[fila + ci]:
                continue
            a = tope_idx[cj * gw + ci]
            b = a + 1
            c = a + gw + 1
            d = a + gw

            # Norte (j-1): normal +Y.
            if cj == 0 or not dentro[(cj - 1) * celdas_w + ci]:
                agregar_cara((a, b, indice_fondo(b), indice_fondo(a)))
            # Sur (j+1): normal -Y.
            if cj == celdas_h - 1 or not dentro[(cj + 1) * celdas_w + ci]:
                agregar_cara((c, d, indice_fondo(d), indice_fondo(c)))
            # Oeste (i-1): normal -X.
            if ci == 0 or not dentro[fila + ci - 1]:
                agregar_cara((d, a, indice_fondo(a), indice_fondo(d)))
            # Este (i+1): normal +X.
            if ci == celdas_w - 1 or not dentro[fila + ci + 1]:
                agregar_cara((b, c, indice_fondo(c), indice_fondo(b)))

    # --- Malla y objeto ------------------------------------------------------
    malla = bpy.data.meshes.new("RelieveBogota")
    malla.from_pydata(verts, [], caras)
    malla.update()

    total_caras = len(caras)
    malla.polygons.foreach_set(
        "use_smooth", [True] * num_tope + [False] * (total_caras - num_tope)
    )
    malla.polygons.foreach_set(
        "material_index", [0] * num_tope + [1] * (total_caras - num_tope)
    )

    capa_uv = malla.uv_layers.new(name="UVMap")
    capa_uv.data.foreach_set("uv", uv_caras)

    malla.materials.append(mat_textura)
    malla.materials.append(mat_base)
    malla.update()

    objeto = bpy.data.objects.new("RelieveBogota", malla)
    bpy.context.scene.collection.objects.link(objeto)

    return objeto, {
        "vertices": len(verts),
        "caras": total_caras,
        "caras_superficie": num_tope,
        "triangulos": total_caras * 2,  # todas las caras son cuadriláteros
        "rejilla_px": [gw, gh],
        "celdas_dentro": total_dentro,
        "celdas_totales": celdas_w * celdas_h,
        "z_max_km": z_max,
        "z_base_km": z_base,
        "ancho_km": ancho_km,
        "alto_km": alto_km,
    }


# ---------------------------------------------------------------------------
# Exportación y validación del .glb
# ---------------------------------------------------------------------------
def _exportar_glb(objeto, destino: Path) -> None:
    import bpy

    destino.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.object.select_all(action="DESELECT")
    objeto.select_set(True)
    bpy.context.view_layer.objects.active = objeto

    bpy.ops.export_scene.gltf(
        filepath=str(destino),
        export_format="GLB",
        use_selection=True,
        export_apply=False,
        export_yup=True,
        export_texcoords=True,
        export_normals=True,
        export_image_format="AUTO",
        export_materials="EXPORT",
    )


def _validar_glb(destino: Path) -> int:
    """Comprueba la cabecera GLB y devuelve su tamaño en bytes."""
    with destino.open("rb") as fh:
        cabecera = fh.read(12)
    if len(cabecera) != 12:
        raise ValueError(f"{destino} está truncado")
    magia, version, largo = struct.unpack("<4sII", cabecera)
    if magia != b"glTF":
        raise ValueError(f"{destino} no es un GLB (magic={magia!r})")
    if version != 2:
        raise ValueError(f"{destino} usa glTF versión {version}; se esperaba 2")
    tamano = destino.stat().st_size
    if largo != tamano:
        raise ValueError(
            f"{destino} declara {_miles(largo)} bytes pero pesa {_miles(tamano)}"
        )
    return tamano


def _eliminar_objeto(objeto) -> None:
    import bpy

    malla = objeto.data
    bpy.data.objects.remove(objeto, do_unlink=True)
    if malla.users == 0:
        bpy.data.meshes.remove(malla)


# ---------------------------------------------------------------------------
# Escena, cámara, luz y render
# ---------------------------------------------------------------------------
def _configurar_render(ancho: int, alto: int, muestras: int) -> None:
    import bpy

    escena = bpy.context.scene
    try:
        escena.render.engine = "CYCLES"
    except TypeError as exc:  # pragma: no cover - según la compilación de Blender
        raise RuntimeError(
            "Cycles no está disponible en este Blender; el render headless "
            "necesita Cycles en CPU (no se usa EEVEE/OpenGL)."
        ) from exc
    # CPU siempre: el runner de CI no tiene GPU ni contexto OpenGL.
    escena.cycles.device = "CPU"
    escena.cycles.samples = muestras
    escena.cycles.use_adaptive_sampling = True
    if hasattr(escena.cycles, "use_denoising"):
        escena.cycles.use_denoising = False  # evita depender de OIDN
    escena.render.resolution_x = ancho
    escena.render.resolution_y = alto
    escena.render.resolution_percentage = 100
    escena.render.image_settings.file_format = "PNG"
    escena.render.image_settings.color_mode = "RGB"
    escena.render.film_transparent = False

    # Vista estándar: la textura hipsométrica se ve como en el póster.
    try:
        escena.view_settings.view_transform = "Standard"
    except TypeError:  # pragma: no cover - versiones antiguas
        pass

    mundo = bpy.data.worlds.new("MundoRelieve")
    mundo.use_nodes = True
    escena.world = mundo
    fondo = mundo.node_tree.nodes.get("Background")
    if fondo is not None:
        fondo.inputs["Color"].default_value = (0.86, 0.90, 0.95, 1.0)
        fondo.inputs["Strength"].default_value = 0.75


def _crear_sol(nombre: str, direccion, energia: float, angulo: float):
    """Sol orientado según la dirección de viaje de la luz."""
    import bpy
    from mathutils import Vector

    datos = bpy.data.lights.new(nombre, type="SUN")
    datos.energy = energia
    datos.angle = angulo
    objeto = bpy.data.objects.new(nombre, datos)
    bpy.context.scene.collection.objects.link(objeto)
    vector = Vector(direccion).normalized()
    objeto.rotation_euler = vector.to_track_quat("-Z", "Y").to_euler()
    return objeto


def _crear_suelo(tamano: float, z: float, mat_suelo):
    """Plano grande bajo el modelo: recibe sombra y sirve de fondo."""
    import bpy

    lado = tamano / 2.0
    verts = [(-lado, -lado, z), (lado, -lado, z), (lado, lado, z), (-lado, lado, z)]
    malla = bpy.data.meshes.new("Suelo")
    malla.from_pydata(verts, [], [(0, 1, 2, 3)])
    malla.update()
    malla.materials.append(mat_suelo)
    objeto = bpy.data.objects.new("Suelo", malla)
    bpy.context.scene.collection.objects.link(objeto)
    return objeto


def _material_suelo():
    import bpy

    mat = bpy.data.materials.new("SueloEstudio")
    mat.use_nodes = True
    nodos = mat.node_tree.nodes
    enlaces = mat.node_tree.links
    nodos.clear()
    salida = nodos.new("ShaderNodeOutputMaterial")
    bsdf = nodos.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Base Color"].default_value = (0.80, 0.82, 0.85, 1.0)
    bsdf.inputs["Roughness"].default_value = 1.0
    enlaces.new(bsdf.outputs["BSDF"], salida.inputs["Surface"])
    return mat


def _crear_camara(ancho_km: float, alto_km: float, z_max: float, z_base: float,
                  ancho_render: int, alto_render: int):
    """Cámara ortográfica en tres cuartos, encuadrando la caja del modelo."""
    import bpy
    from mathutils import Vector

    centro = Vector((0.0, 0.0, (z_max + z_base) / 2.0))
    direccion = Vector((0.42, -1.0, 0.72)).normalized()  # desde el sur-sureste
    distancia = max(ancho_km, alto_km, z_max - z_base) * 4.0

    cam_datos = bpy.data.cameras.new("CamaraRelieve")
    cam_datos.type = "ORTHO"
    camara = bpy.data.objects.new("CamaraRelieve", cam_datos)
    bpy.context.scene.collection.objects.link(camara)
    camara.location = centro + direccion * distancia
    camara.rotation_euler = (centro - camara.location).to_track_quat("-Z", "Y").to_euler()
    # La escena se mide en km y el suelo es enorme: sin estos límites, Blender
    # recortaría el modelo con el clip_end por defecto (100).
    cam_datos.clip_start = max(0.01, distancia / 10000.0)
    cam_datos.clip_end = max(1000.0, distancia * 12.0)

    # Encuadre exacto: proyecta las 8 esquinas de la caja sobre el plano imagen.
    derecha = Vector((0.0, 0.0, 1.0)).cross(direccion)
    if derecha.length < 1e-6:
        derecha = Vector((1.0, 0.0, 0.0))
    derecha.normalize()
    arriba = direccion.cross(derecha).normalized()

    xs: list[float] = []
    ys: list[float] = []
    for x in (-ancho_km / 2.0, ancho_km / 2.0):
        for y in (-alto_km / 2.0, alto_km / 2.0):
            for z in (z_base, z_max):
                esquina = Vector((x, y, z))
                xs.append(esquina.dot(derecha))
                ys.append(esquina.dot(arriba))

    margen = 1.09
    ancho_proyectado = (max(xs) - min(xs)) * margen
    alto_proyectado = (max(ys) - min(ys)) * margen
    # ortho_scale controla la dimensión mayor del sensor; se convierte el alto
    # requerido a esa misma escala según la relación de aspecto del render.
    relacion = ancho_render / float(alto_render)
    cam_datos.ortho_scale = max(ancho_proyectado, alto_proyectado * relacion)

    return camara


def _renderizar(destino: Path, ancho: int, alto: int, muestras: int,
                ancho_km: float, alto_km: float, z_max: float, z_base: float) -> None:
    import bpy

    escena = bpy.context.scene
    _configurar_render(ancho, alto, muestras)

    # Luz principal desde el noroeste (convención cartográfica) + relleno suave.
    _crear_sol("SolPrincipal", (0.60, -0.60, -0.85), 3.2, math.radians(2.5))
    _crear_sol("SolRelleno", (-0.55, 0.35, -0.55), 0.9, math.radians(12.0))

    tamano = max(ancho_km, alto_km) * 10.0
    _crear_suelo(tamano, z_base - 0.002 * max(ancho_km, alto_km), _material_suelo())
    escena.camera = _crear_camara(
        ancho_km, alto_km, z_max, z_base, ancho, alto
    )

    destino.parent.mkdir(parents=True, exist_ok=True)
    escena.render.filepath = str(destino)
    bpy.ops.render.render(write_still=True)


# ---------------------------------------------------------------------------
# Lectura de metadatos de la etapa 02
# ---------------------------------------------------------------------------
def _leer_metadatos(ruta: Path) -> dict:
    with ruta.open(encoding="utf-8") as fh:
        datos = json.load(fh)
    bbox = datos.get("bbox_9377") or {}
    dem = datos.get("dem") or {}
    faltan = [
        clave
        for clave, valor in (
            ("bbox_9377.xmin", bbox.get("xmin")),
            ("bbox_9377.ymin", bbox.get("ymin")),
            ("bbox_9377.xmax", bbox.get("xmax")),
            ("bbox_9377.ymax", bbox.get("ymax")),
            ("dem.elev_min_m", dem.get("elev_min_m")),
            ("dem.elev_max_m", dem.get("elev_max_m")),
        )
        if valor is None
    ]
    if faltan:
        raise ValueError(
            f"{ruta} no tiene los campos esperados: {', '.join(faltan)}"
        )
    return datos


# ---------------------------------------------------------------------------
# Programa principal
# ---------------------------------------------------------------------------
def principal(argv: list[str]) -> int:
    args = construir_parser().parse_args(argv)
    _validar_args(args)

    # Rutas resueltas y comprobación de que no se escribe en data/.
    heightmap_ruta = _ruta(args.heightmap)
    textura_ruta = _ruta(args.textura)
    mascara_ruta = _ruta(args.mascara)
    metadatos_ruta = _ruta(args.metadatos)
    glb_ruta = _ruta(args.salida_glb)
    render_ruta = _ruta(args.salida_render)

    data_dir = (ROOT / "data").resolve()
    for salida in (glb_ruta, render_ruta):
        resuelta = salida.resolve()
        if resuelta == data_dir or data_dir in resuelta.parents:
            _log(f"ERROR: la salida {salida} no puede estar dentro de data/.")
            return 1

    try:
        import bpy  # noqa: F401  (import de prueba)
    except ImportError:
        _log(
            "ERROR: este script debe ejecutarse dentro de Blender, no con python3.\n"
            "       Usa:  bash scripts/04_blender_relief.sh\n"
            "       o:    blender -b --factory-startup --python-exit-code 1 \\\n"
            "                 -P scripts/04_blender_relief.py -- [opciones]"
        )
        return 1

    _log("==> [1/7] Comprobando versión de Blender y entradas")
    version = tuple(bpy.app.version[:3])
    if version < VERSION_MINIMA:
        _log(
            f"ERROR: se requiere Blender >= {'.'.join(map(str, VERSION_MINIMA))} "
            f"(detectado {bpy.app.version_string})."
        )
        return 1
    _log(f"    Blender {bpy.app.version_string} · render CYCLES en CPU")

    obligatorios = [
        (heightmap_ruta, "heightmap"),
        (textura_ruta, "textura"),
        (metadatos_ruta, "metadatos"),
    ]
    if not args.sin_mascara:
        obligatorios.append((mascara_ruta, "máscara"))
    for ruta, nombre in obligatorios:
        if not ruta.is_file() or ruta.stat().st_size == 0:
            _log(
                f"ERROR: falta la {nombre} de la etapa 02: {ruta}\n"
                "       Ejecuta primero: bash scripts/02_gdal_process.sh"
            )
            return 1

    _log("==> [2/7] Leyendo heightmap, máscara y metadatos")
    hm_ancho, hm_alto, hm_max, hm_pixeles = leer_png_gris(heightmap_ruta)
    if hm_max != 65535:
        _log(
            f"ERROR: {heightmap_ruta} no es un PNG de 16 bits "
            f"(valor máximo detectado: {hm_max})."
        )
        return 1
    _log(f"    Heightmap: {hm_ancho}x{hm_alto} px · UInt16")

    mascara = None
    if args.sin_mascara:
        _log("    Máscara: desactivada (--sin-mascara); relieve rectangular")
    else:
        m_ancho, m_alto, m_max, m_pixeles = leer_png_gris(mascara_ruta)
        if (m_ancho, m_alto) != (hm_ancho, hm_alto):
            _log(
                f"ERROR: la máscara mide {m_ancho}x{m_alto} px y el heightmap "
                f"{hm_ancho}x{hm_alto} px; deben estar alineados 1:1."
            )
            return 1
        mascara = (m_pixeles, m_ancho, m_alto)
        _log(f"    Máscara: {m_ancho}x{m_alto} px · {m_max} niveles")

    metadatos = _leer_metadatos(metadatos_ruta)
    bbox = metadatos["bbox_9377"]
    elev_min = float(metadatos["dem"]["elev_min_m"])
    elev_max = float(metadatos["dem"]["elev_max_m"])
    ancho_km = (float(bbox["xmax"]) - float(bbox["xmin"])) / 1000.0
    alto_km = (float(bbox["ymax"]) - float(bbox["ymin"])) / 1000.0
    rango_m = elev_max - elev_min
    if rango_m <= 0 or ancho_km <= 0 or alto_km <= 0:
        _log("ERROR: los metadatos de la etapa 02 tienen un rango o bbox inválidos.")
        return 1

    hm_meta = metadatos.get("heightmap") or {}
    if hm_meta.get("ancho_px") and hm_meta.get("alto_px"):
        if (int(hm_meta["ancho_px"]), int(hm_meta["alto_px"])) != (hm_ancho, hm_alto):
            _log(
                f"    AVISO: el JSON de la etapa 02 declara un heightmap de "
                f"{hm_meta['ancho_px']}x{hm_meta['alto_px']} px, pero el PNG mide "
                f"{hm_ancho}x{hm_alto} px; se usan las dimensiones del PNG."
            )

    escala_z_km = rango_m * args.exageracion / 1000.0
    profundidad_km = args.profundidad * escala_z_km
    _log(
        f"    Extensión: {ancho_km:.2f} x {alto_km:.2f} km · "
        f"elevación {_miles(elev_min)}–{_miles(elev_max)} m"
    )
    _log(
        f"    Escala vertical: x{args.exageracion:g} → "
        f"{escala_z_km * 1000.0:.0f} m de relieve · base {profundidad_km * 1000.0:.0f} m"
    )

    _log("==> [3/7] Limpiando la escena y preparando materiales")
    # --factory-startup trae la escena por defecto (cubo, cámara, luz): fuera.
    for objeto in list(bpy.data.objects):
        bpy.data.objects.remove(objeto, do_unlink=True)

    tmp_dir = Path(tempfile.mkdtemp(prefix="blender_relieve_"))
    imagen, tamanio_textura, textura_escalada = _preparar_textura(
        textura_ruta, args.textura_max, tmp_dir
    )
    mat_textura = _material_textura(imagen)
    mat_base = _material_base()
    _log(f"    Textura en el .glb: {tamanio_textura[0]}x{tamanio_textura[1]} px")

    limite_bytes = int(args.limite_mb * 1024 * 1024)
    resolucion = args.resolucion
    stats = None
    objeto = None
    tamano_glb = 0
    intentos = 0

    try:
        _log("==> [4/7] Construyendo la malla y exportando el .glb")
        while True:
            intentos += 1
            objeto, stats = _crear_malla(
                heightmap=hm_pixeles,
                hm_ancho=hm_ancho,
                hm_alto=hm_alto,
                hm_max=hm_max,
                mascara=mascara,
                resolucion=resolucion,
                ancho_km=ancho_km,
                alto_km=alto_km,
                escala_z_km=escala_z_km,
                profundidad_km=profundidad_km,
                mat_textura=mat_textura,
                mat_base=mat_base,
            )
            _log(
                f"    Intento {intentos}: rejilla {stats['rejilla_px'][0]}x"
                f"{stats['rejilla_px'][1]} px · {_miles(stats['vertices'])} vértices · "
                f"{_miles(stats['triangulos'])} triángulos"
            )

            _exportar_glb(objeto, glb_ruta)
            tamano_glb = _validar_glb(glb_ruta)
            _log(f"    GLB: {tamano_glb / (1024 * 1024):.2f} MB")

            if tamano_glb < limite_bytes:
                break
            if resolucion <= 96:
                _log(
                    f"ERROR: el .glb sigue pesando {tamano_glb / (1024 * 1024):.2f} MB "
                    f"con la malla mínima (96 px), por encima de {args.limite_mb:g} MB.\n"
                    "       Reduce la textura con --textura-max o regenera la etapa 02 "
                    "con --max-px más bajo."
                )
                glb_ruta.unlink(missing_ok=True)
                return 1

            _log(
                f"    AVISO: supera {args.limite_mb:g} MB; se reduce la resolución "
                f"y se reintenta."
            )
            _eliminar_objeto(objeto)
            objeto = None
            resolucion = max(96, int(resolucion * 0.8))

        if args.sin_render:
            _log("==> [5/7] Render omitido (--sin-render)")
            info_render = None
        else:
            _log("==> [5/7] Renderizando con Cycles (CPU)")
            _renderizar(
                render_ruta,
                args.ancho,
                args.alto,
                args.muestras,
                ancho_km,
                alto_km,
                stats["z_max_km"],
                stats["z_base_km"],
            )
            if not render_ruta.is_file() or render_ruta.stat().st_size == 0:
                _log(f"ERROR: el render no se generó: {render_ruta}")
                return 1
            _log(
                f"    Render: {render_ruta.name} · {args.ancho}x{args.alto} px · "
                f"{args.muestras} muestras"
            )
            info_render = {
                "archivo": _ruta_documentada(render_ruta),
                "ancho_px": args.ancho,
                "alto_px": args.alto,
                "muestras": args.muestras,
                "bytes": render_ruta.stat().st_size,
                "sha256": _sha256(render_ruta),
            }

        _log("==> [6/7] Escribiendo metadatos de la etapa 04")
        salida_json = ROOT / "output" / "blender_relieve.json"
        datos = {
            "proyecto": "bogota-relieve",
            "etapa": "04_blender_relief",
            "generado_utc": _dt.datetime.now(_dt.timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "blender": {
                "version": bpy.app.version_string,
                "motor": "CYCLES",
                "dispositivo": "CPU",
            },
            "entradas": {
                "heightmap": _ruta_documentada(heightmap_ruta),
                "textura": _ruta_documentada(textura_ruta),
                "mascara": (
                    _ruta_documentada(mascara_ruta) if mascara is not None else None
                ),
                "metadatos": _ruta_documentada(metadatos_ruta),
                "elev_min_m": elev_min,
                "elev_max_m": elev_max,
                "bbox_9377_km": {
                    "ancho": round(ancho_km, 4),
                    "alto": round(alto_km, 4),
                },
            },
            "parametros": {
                "resolucion_lado_mayor_px": resolucion,
                "resolucion_solicitada_px": args.resolucion,
                "exageracion_vertical": args.exageracion,
                "profundidad_base_fraccion": args.profundidad,
                "textura_max_px": args.textura_max,
                "textura_usada_px": list(tamanio_textura),
                "textura_reescalada": textura_escalada,
                "limite_mb": args.limite_mb,
                "intentos_exportacion": intentos,
                "mascara_aplicada": mascara is not None,
            },
            "malla": stats,
            "unidades": "1 unidad Blender = 1 km (Z = altura exagerada)",
            "salidas": {
                "glb": {
                    "archivo": _ruta_documentada(glb_ruta),
                    "bytes": tamano_glb,
                    "sha256": _sha256(glb_ruta),
                },
                "render": info_render,
            },
            "validacion": {
                "limite_bytes": limite_bytes,
                "cumple_limite": tamano_glb < limite_bytes,
                "glb_cabecera": "glTF 2.0",
            },
        }
        salida_json.parent.mkdir(parents=True, exist_ok=True)
        with salida_json.open("w", encoding="utf-8") as fh:
            json.dump(datos, fh, indent=2, ensure_ascii=False)
            fh.write("\n")

        _log("==> [7/7] Listo")
        _log()
        _log("================= RESUMEN (etapa 04_blender_relief) =================")
        _log(f"Rejilla: {stats['rejilla_px'][0]} x {stats['rejilla_px'][1]} px")
        _log(
            f"Malla: {_miles(stats['vertices'])} vértices · "
            f"{_miles(stats['triangulos'])} triángulos"
        )
        _log(f"GLB: {glb_ruta} · {tamano_glb / (1024 * 1024):.2f} MB")
        if info_render:
            _log(f"Render: {render_ruta}")
        _log(f"Metadatos: {salida_json}")
        _log("Siguiente etapa: visor en web/ (model-viewer) y GitHub Pages.")
        _log("==================================================================")
        return 0

    except Exception:
        _log("ERROR no controlado durante la etapa 04:")
        _log(traceback.format_exc())
        return 1
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _argv_tras_blender() -> list[str]:
    """Argumentos propios: los que van después del separador '--'."""
    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1:]
    return []


if __name__ == "__main__":
    raise SystemExit(principal(_argv_tras_blender()))
