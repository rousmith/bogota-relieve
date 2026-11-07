# Bitácora del proyecto Bogotá en relieve

Registro de la construcción del mapa interactivo con OpenCode, agentes
especializados, QGIS, GDAL, Blender, GitHub Actions y GitHub Pages.

## Entradas

| Fecha | Sesión | Resultado principal |
| --- | --- | --- |
| 06/11/2026 | [Agentes y Pages](2026-11-06-agentes-y-pages.md) | Orquestación, modelos gratuitos y primer despliegue |
| 06/11/2026 | [Plan de entrega](2026-11-06-plan-entrega.md) | Alcance, etapas y criterios de aceptación |
| 06/11/2026 | [GIS y póster](2026-11-06-gis-gdal-poster.md) | GDAL EPSG:9377 y PyQGIS offscreen |
| 06/11/2026 | [Blender y visor](2026-11-06-blender-y-visor.md) | Malla, GLB y página interactiva |
| 06/11/2026 | [Pipeline y Actions](2026-11-06-pipeline-y-actions.md) | Automatización completa y verificaciones |

## Estrategia de optimización de costos

- Modelos gratuitos para implementación, ejecución y documentación.
- Variante de mayor razonamiento solo para el agente planificador.
- Un agente por especialidad para reducir contexto innecesario.
- Tareas independientes en paralelo; etapas dependientes en orden.
- Validaciones tempranas para evitar repetir ejecuciones costosas de QGIS y
  Blender.

Cuando OpenCode no expone el número exacto de tokens, la entrada lo indica de
forma explícita en vez de inventar una cifra. El costo monetario registrado en
estas sesiones es 0 USD.
