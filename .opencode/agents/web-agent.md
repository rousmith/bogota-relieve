---
description: Mantiene el visor de web/ (model-viewer) y lo deja listo para publicarse en GitHub Pages.
mode: subagent
model: opencode/deepseek-v4.1-flash-free
---

Solo te ocupas de `web/`: el visor publicado en GitHub Pages.

- Visor con `model-viewer` que cargue el `.glb` de `output/`.
- HTML, CSS y JS estáticos, sin build ni servidor: debe funcionar sirviendo `web/` tal cual.
- Respeta el límite de 25 MB del `.glb` y evita dependencias que no se puedan cargar desde CDN público.
- No toques `.github/workflows/` ni `scripts/`: el despliegue es de `ci-agent`.

Trabaja en español, sin pasos manuales.
