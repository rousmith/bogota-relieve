# 2026-11-06 — Modelo Blender y visor interactivo

- **Fecha:** 2026-11-06 (viernes)
- **Agente:** `blender-agent` (implementación parcial) + agente principal
- **Modelo:** modelo gratuito del proveedor `opencode`

## Prompt

> Implementar la etapa Blender headless: leer el heightmap de 16 bits, textura
> y máscara; construir un relieve con base sólida; renderizar; exportar un GLB
> menor de 25 MB y preparar el visor de GitHub Pages.

## Resultado

- `scripts/04_blender_relief.py`: lector PNG UInt16, malla cerrada recortada por
  máscara, materiales, cámara, luces, render Cycles CPU, exportación y validación
  GLB.
- `scripts/04_blender_relief.sh`: wrapper reproducible con `blender -b`, control
  de entradas y límite final de 25 MiB.
- `web/index.html`: visor responsive basado en `<model-viewer>`, controles de
  rotación/zoom, progreso, error comprensible, créditos y enlace al póster.

## Optimización de costo

La tarea se asignó primero al agente especializado económico. Su cuota gratuita
terminó después de crear el script Python; el agente principal conservó ese
trabajo y completó el wrapper y el visor, evitando repetir la generación.
Blender limita la malla a 384 px inicialmente y reduce su resolución si el GLB
supera 25 MiB, lo que también reduce tiempo de CI y transferencia web.

## Verificación

- Sintaxis Python comprobada fuera de Blender mediante compilación.
- Sintaxis Bash comprobada con `bash -n`.
- La ejecución funcional queda para GitHub Actions porque el equipo Windows no
  tiene Blender instalado.

## Errores y solución

- Los subagentes de Blender y web alcanzaron el límite de uso gratuito. Se
  reutilizó el archivo parcial de Blender y el agente principal terminó los
  componentes pendientes sin cambiar a un modelo de pago.

## Tokens y costo

El proveedor no expuso el total exacto de tokens. Costo monetario registrado:
**0 USD**, usando modelos gratuitos de OpenCode.
