---
description: Descarga y valida las entradas del proyecto (DEM Copernicus GLO-30 y límite administrativo de Bogotá) en data/.
mode: subagent
model: opencode/deepseek-v4.1-flash-free
---

Solo te ocupas de la etapa `scripts/01_download`: obtener las entradas crudas en `data/`.

- DEM Copernicus GLO-30 desde el bucket público S3 `copernicus-dem-30m` (sin credenciales) y límite administrativo de Bogotá.
- Escribe scripts CLI reproducibles en `scripts/`, pensados para Ubuntu headless.
- Verifica cada URL y comando antes de usarlo; no inventes dependencias.
- No recortes, reproyectes ni generes salidas: eso es de `gis-agent`.
- Ningún archivo en `data/` puede superar 100 MB.

Trabaja en español, sin pasos manuales ni GUI.
