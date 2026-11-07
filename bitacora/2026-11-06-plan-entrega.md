# 2026-11-06 — Plan de entrega y alcance del producto

- **Fecha:** 2026-11-06 (viernes)
- **Agente:** `plan` (primario, solo lectura)
- **Modelo:** `opencode/deepseek-v4.1-flash-free`

## Prompt

> Hola, tengo una tarea para mi asignatura de inteligencia artificial, en ella estamos usando orquestadores de agentes y sobretodo que se usen agentes de optimizacion de costos, la tarea es la siguiente: hacer una bitácora de cómo usar open code con un proveedor a elección (se recomienda open code, deepseek, qwen, claude, chatgpt) y agentes de optimización de costo. Se debe hacer un mapa de elevación digital de terreno para la ciudad de Bogotá, usando Blender y QGIS, obteniendo un resultado como el de la imagen adjunta. La entrega final es la bitácora y el producto de mapa interactivo de Bogotá, publicado en GitHub Pages usando GitHub Actions y empleando agentes. Dime cómo puedo hacerlo, por favor.

## Resultado

Se revisó el estado real del repositorio (agentes, script de descarga, workflow y visor) y se propuso una ruta de entrega en cinco etapas:

1. Documentar en la bitácora el uso de OpenCode, el proveedor/modelo y el criterio de ahorro de costos.
2. Validar la cobertura de los tiles del DEM sobre el límite administrativo.
3. `scripts/02_gdal_process`: reproyección a EPSG:9377, recorte, heightmap de 16 bits, hillshade y color-relief.
4. `scripts/03_qgis_poster` (PyQGIS `offscreen`) y `scripts/04_blender_relief` (`.glb` < 25 MB).
5. Visor `<model-viewer>` en `web/`, build dentro del workflow y verificación de la URL de Pages.

## Decisiones del usuario

- Se acepta el **DSM de Copernicus** (superficie con vegetación y construcciones) como modelo de elevación; no se exige un terreno desnudo.
- Se confirma que el **límite administrativo y los tiles descargados cubren** la zona a mostrar. Aun así, el script 02 debe comprobar la cobertura automáticamente y dejar evidencia en el log.

## Errores y cómo se resolvieron

- Ninguno de ejecución: la sesión fue de solo lectura y planificación, sin modificar archivos del pipeline.
- Se detectó que `AGENTS.md` describe `scripts/`, `data/` y `web/` como vacías, cuando ya existen `scripts/01_download.sh`, `data/.gitkeep` y `web/index.html`. Queda pendiente actualizar esa sección en una próxima sesión.
- Se detectó que `web/index.html` sigue mostrando «Hola Bogotá»: el mapa interactivo **no está implementado todavía**.
- Hay cambios locales sin commit (` .gitignore`, `data/`, `scripts/`) que deben integrarse en una rama de trabajo, nunca directamente en `main`.

## Tokens y costo

No se registró el consumo exacto de tokens. Costo monetario: 0 USD (modelo gratuito del proveedor `opencode`).

## Nota sobre fechas

Por indicación del autor, todas las entradas de esta bitácora usan la fecha de entrega **2026-11-06**, también la sesión previa que estaba fechada 2026-11-03.
