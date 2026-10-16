---
version: 1
slug: "app-static-index-html"
primary_target: "app/static/index.html"
related_targets: ["app/static/style.css","app/static/app.js"]
---

Ámbito: la interfaz completa de SpriteGen (`app/static/index.html`, `style.css`, `app.js`), una sola
pantalla local en `127.0.0.1:8787`. Modo de visitante: **Operate**.

Audiencia: el autor, en sesiones de horas, con Godot en el otro monitor; y quien clone el repo y deba
entenderla sin README. Tarea: describir, generar, juzgar el píxel, animar, y saber siempre qué hace la
máquina. Restricciones: sin red (nada de CDN), viewport real ~1920×890, español en la UI, prompts en
inglés, ninguna función puede perderse.

Dolores declarados por el usuario, en orden: (1) todo apretado en la barra lateral, acordeones de peso
idéntico; (2) el sprite no se ve bien: sin zoom, sin escalas, sin comparar; (3) no se sabe qué está
pasando: overlay que bloquea la app con un spinner durante esperas de hasta 30 minutos. Pidió además
progreso real con tiempo, seguir navegando mientras genera, y aviso al terminar.

Compromisos: el marco rúnico de `esquina.png` se conserva; los cinco parámetros numéricos se ven todos
a la vez.

Momento memorable: el vidrio con papel cebolla — al recorrer una animación con el teclado, los
fotogramas vecinos asoman en fantasma bajo el actual, como acetatos sobre la mesa.

Decisiones abiertas: ninguna bloqueante.

## Direction contract

THESIS: Mesa de luz de animación, no panel de IA: solo el sprite está iluminado. Refuta el acordeón de
peso único y el overlay que tapa la aplicación.

OWN-WORLD: Tablero #141310 y un único campo luminoso #f4f1e6. Barra de clavijas de la que cuelgan las
hojas; perforaciones, filetes de 1 px, cifras tabulares. Lápices de color como dato, no adorno; el rojo
de nota de cámara reservado por ley a la acción que gasta GPU. Sin cristal, desenfoque ni gradientes.

STORY: Comprende que es un taller de fotogramas, confía porque la máquina imprime su estado, y juzga el
píxel real sin salir de la mesa.

FIRST VIEWPORT: Barra de registro arriba con motor y contador de trabajo. Izquierda, hojas ordenadas por
frecuencia: Generar y Animar abiertas con sus cinco números; Klein, Terreno y Efectos como pestañas
rotuladas. Centro, el vidrio: sprite sobre damero, marco rúnico como perforaciones de registro, regleta
de escalas ×1 ×2 ×4 ×6, papel cebolla en animaciones. Derecha, hoja de exposición reglada: una fila por
dato o por fotograma. Abajo, la caja de hojas con canto rotulado.

FORM: Mesa de luz y hoja de exposición de animación tradicional; candidato 1 de mi lista ordenada,
elegido por el usuario sobre el asignado; seed 0fea1beb.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
