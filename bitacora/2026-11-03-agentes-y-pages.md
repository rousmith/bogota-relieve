# 2026-11-03 — Agentes del pipeline y primer despliegue a Pages

- **Fecha:** 2026-11-03
- **Agente:** build (primario) + subagentes del proyecto
- **Modelo:** `opencode/deepseek-v4.1-flash-free` (variante `#high` solo en `planner`)

## Prompt

> Lee AGENTS.md. Primero averigua los identificadores exactos de modelo disponibles con `opencode models` (o `opencode models deepseek`) y dime cuál estás usando tú ahora. Luego crea en `.opencode/agents/` siete agentes en markdown con frontmatter (description, mode, model): `planner` (primary, modelo de razonamiento, con write/edit/bash en false) y `data-agent`, `gis-agent`, `blender-agent`, `web-agent`, `ci-agent`, `docs-agent` (subagent, modelo barato). Cada uno con un prompt corto que lo limite a su etapa y exija scripts headless para Ubuntu; `docs-agent` debe escribir una entrada en `bitacora/` por sesión. Después crea `.github/workflows/deploy.yml` mínimo que publique `web/index.html` ("Hola Bogotá") en GitHub Pages, haz commit y push, activa Pages con `gh api -X POST repos/rousmith/bogota-relieve/pages -f build_type=workflow`, verifica con `gh run list` que el workflow pasó y di qué modelos puso en cada agente.

## Catálogo de modelos disponible

`opencode models` no está en el `PATH` de esta máquina (solo existe la app de escritorio, `C:\Users\pauh2\AppData\Local\Programs\@opencodedesktop\OpenCode.exe`). Se consultó el catálogo con la herramienta de modelos de OpenCode, que lee el mismo registro. Proveedor único: `opencode`, 9 modelos, todos gratuitos (input/output a 0 USD/M tokens):

| ID | Variantes |
| --- | --- |
| `opencode/crouton-alpha-free` | minimal, low, medium, high, xhigh, max |
| `opencode/pulse-alpha-free` | low, high, max |
| `opencode/flint-40b-free` | low, medium, high, xhigh, max |
| `opencode/nemotron-3.5-super-vl-free` | none, minimal, low, medium, high, xhigh |
| `opencode/beam-free` | low, medium, high, xhigh, max |
| `opencode/mimo-v2.6-flash-free` | — |
| `opencode/deepseek-v4.1-flash-free` | low, high, max |
| `opencode/glm-5.3-flash-free` | low, high, max |
| `opencode/big-pickle` | — |

No hay `deepseek-chat` ni ningún modelo etiquetado explícitamente como "razonamiento": el catálogo solo trae modelos generalistas gratuitos con variantes de esfuerzo.

## Resultado

- `.opencode/agents/` con 7 agentes en formato V2 (`description`, `mode`, `model`, `permissions`): `planner` (primary) y 6 subagentes.
- `web/index.html` con la portada mínima "Hola Bogotá".
- `.github/workflows/deploy.yml`: `configure-pages@v6`, `upload-pages-artifact@v5` (publica `web/`) y `deploy-pages@v5`.
- Sitio de Pages activado con `build_type=workflow`.

## Verificación

- Flujo: rama `feat/agentes-pipeline` → PR #1 → merge a `main` (fast-forward). No hubo push directo a `main`.
- Pages activado antes del merge: `gh api -X POST repos/rousmith/bogota-relieve/pages -f build_type=workflow` → `build_type: workflow`, `html_url: https://rousmith.github.io/bogota-relieve/`.
- Run `41769291175` (`deploy`, `main`, evento `push`): **success** en 22 s. Los cuatro pasos (`configure-pages@v6`, `upload-pages-artifact@v5`, `deploy-pages@v5`) terminaron en verde.
- `https://rousmith.github.io/bogota-relieve/` responde HTTP 200 y contiene `<h1>Hola Bogotá</h1>`.

## Decisiones de modelo

- **Subagentes:** `opencode/deepseek-v4.1-flash-free` sin variante. Es el modelo que ejecuta esta sesión, el más barato del catálogo (coste 0) y el que pide `AGENTS.md` para escribir y ejecutar.
- **`planner`:** mismo modelo con variante `#high`, porque no hay un modelo de razonamiento dedicado y `#high` sube el esfuerzo de razonamiento sin cambiar de modelo. Si aparece uno específico de razonamiento en el catálogo, basta con editar el `model` de ese archivo.
- `AGENTS.md` menciona `deepseek-chat` como modelo por defecto, pero ese ID no existe en este catálogo: se usa su equivalente disponible, `opencode/deepseek-v4.1-flash-free`.

## Errores y soluciones

- `opencode` y `gh` no estaban en el `PATH` de PowerShell. `gh` se encontró en `C:\Program Files\GitHub CLI\gh.exe` y se usó con la ruta completa; `opencode` CLI no está instalado (solo la app de escritorio).
- El frontmatter V2 no acepta `tools: {write: false, ...}` (formato V1, obsoleto): el equivalente es `permissions` con `action: edit` y `action: shell` en `effect: deny`.

## Tokens y costo

No se registró el consumo exacto de tokens. Costo monetario: 0 USD (modelos gratuitos del proveedor `opencode`).
