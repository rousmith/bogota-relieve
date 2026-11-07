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

## Verificación en GitHub Actions

El run [`42387313602`](https://github.com/rousmith/bogota-relieve/actions/runs/42387313602)
terminó correctamente en **2 min 22 s** con Ubuntu 24.04:

- GDAL 3.8.4: cuatro teselas, recorte y derivados en EPSG:9377.
- QGIS 3.34.4-Prizren en modo `offscreen`: póster PNG de 2,36 MB y PDF de
  0,65 MB.
- Blender 4.0.2 en modo batch/Cycles CPU: render 1600×1200 y GLB glTF 2.0 de
  **2.151.256 bytes (2,05 MB)**, muy por debajo del límite de 25 MiB.
- Malla: 77.494 vértices, 65.752 triángulos y textura 848×2048.
- Los productos se guardaron como artefacto `productos-bogota` y el contenido
  completo de `web/` se empaquetó correctamente para GitHub Pages.

Se descargaron y revisaron visualmente el render 3D y el póster: ambos muestran
el límite completo de Bogotá, relieve texturizado, norte, escala y leyenda.
Después del éxito se actualizaron `actions/checkout` y `actions/upload-artifact`
a sus versiones mayores actuales con runtime Node.js 24 para retirar el aviso
de obsolescencia observado en el run.

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
- El segundo run (`42386283050`) encontró las cuatro teselas, pero interpretó
  los ejes de `cornerCoordinates` como latitud/longitud y declaró cobertura
  ausente. La validación ahora admite tanto el orden oficial de EPSG:4326 como
  el orden GIS tradicional longitud/latitud.
- El tercer run (`42386589207`) mostró que los extents se expresan por centros
  de píxel y quedan unos metros dentro del grado nominal. Se añadió una
  tolerancia de 0,001° (menor que una tesela y mayor que medio píxel GLO-30).
- El cuarto run (`42387022283`) completó las ocho fases GDAL; la última
  validación de CRS conservaba el antiguo `head -n1`. Se aplicó allí la misma
  búsqueda explícita de `EPSG:` usada al validar las entradas.

## Tokens y costo

El proveedor no expuso el total exacto de tokens. Costo monetario registrado:
**0 USD** usando modelos gratuitos de OpenCode.
