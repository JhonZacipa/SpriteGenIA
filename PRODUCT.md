# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Existente, sin build: HTML/CSS/JS vanilla en `app/static/` servido como estáticos por FastAPI
(`app/server.py`, uvicorn en `127.0.0.1:8787`). Sin framework, sin bundler, sin CDN: el proyecto se
declara «100 % local» y la interfaz debe seguir funcionando sin conexión a internet, así que
cualquier fuente, icono o librería tiene que quedar incrustada o servida desde el propio repo. El
uvicorn corre sin `--reload`: los cambios de HTML/CSS/JS se ven con F5, los de Python exigen
reiniciar.

## Users

- **Primario — el autor**, desarrollador en solitario, en sesiones largas de producción: abre la
  herramienta durante horas para sacar tandas de assets. Es experto en su propio pipeline y conoce
  cada parámetro; lo que necesita es velocidad, contexto simultáneo y saber qué está pasando.
- **Secundario — quien clona el repo**: el proyecto es público. La interfaz debe explicarse sola sin
  obligar a leer el README. Hoy esto se sostiene con `title` en casi todos los controles.

No hay usuarios remotos, ni cuentas, ni multiusuario: la app escucha solo en `127.0.0.1`.

## Product Purpose

Producir sprites pixel art listos para usar en un motor de videojuegos: PNG con fondo transparente,
animaciones (GIF/WebP + sprite sheet), efectos ambientales y tilesets de terreno con transiciones.
Todo se genera en la GPU del propio usuario con modelos locales, sin servicios de pago ni
suscripciones. Éxito = el usuario sale de una sesión con assets que puede importar directamente en
su motor, coherentes entre sí en estilo y paleta.

## Positioning

No es un frontend de un servicio de imágenes ni un wrapper de ComfyUI. Es un **pipeline completo de
asset**: la generación IA es solo el primer paso, y detrás vienen cuatro etapas propias que ningún
generador genérico hace — eliminación de fondo plano con guarda de croma, tres detectores de sombra,
pixelizado a rejilla nativa con cuantización median-cut refinada por k-means, y paleta global
compartida entre todos los sprites. Los motores son intercambiables por registro (`config/motores.json`),
así que el modelo de moda de mañana entra sin tocar código de la interfaz.

## Operating Context

- **Escena real**: monitor 1080p con el navegador maximizado. El alto útil NO es 1080 — el cromo del
  navegador se lo come, el viewport real ronda los **880–900 px**. El alto es el recurso escaso y
  el diseño no puede asumir 1080 limpios.
- **Tiempos**: una generación va de ~45 s (SDXL) a **31 min** (un clip de vídeo largo). Hay trabajos
  encadenados (cola de clips) que duran una hora. El usuario no se queda mirando: hace otra cosa y
  vuelve. Se puede cerrar el navegador sin abortar el trabajo, porque corre en el servidor.
- **Proceso aparte**: ComfyUI es un segundo proceso que se enciende solo al generar y retiene ~9 GB
  de RAM; el usuario lo apaga a mano al terminar. Su estado (encendido/apagado) es información
  operativa de primera línea, no un detalle.
- **Volumen actual**: `output/` ya tiene 280 PNG y 272 ficheros de metadatos. El historial no es una
  lista corta: es un archivo que crece cada día y hoy no se puede filtrar ni buscar.
- **Trabajo en paralelo**: la ventana convive con el motor de juego y un editor; a veces se usa
  maximizada, a veces reducida a un lado.

## Capabilities and Constraints

**Lo que hace la interfaz hoy** (todo debe sobrevivir al rediseño):

- Generar sprite: motor + prompt + semilla + rejilla nativa + colores + escala + pasos + CFG, con
  «Variación» (semilla nueva) y «Misma semilla».
- Animar por **esqueleto** (ControlNet OpenPose, 12 ciclos + ciclos propios, con previsualización del
  GIF de poses y sus frames) o por **vídeo** (Wan 2.2: modelo, movimiento, duración del clip, frames
  a extraer, cíclico vs completo), más la **cola de clips encadenados** (N prompts que se generan
  solos y continúan uno del otro).
- **Variación de personaje** con FLUX.2 Klein: editar el sprite del visor conservando su identidad.
- **Terreno y tilesets**: generar 4 variantes seamless de 64 px, y combinar dos terrenos en un
  tileset de 16 transiciones Wang + mapa de prueba.
- **Efectos ambientales sin GPU**: mecer, fuego, bandera/tela, humo. Instantáneos.
- **Estilo global**: plantilla de prompt con `{subject}`, negative prompt, fuerza del LoRA, umbral de
  fondo, quitar sombra automática.
- **Visor** con pestañas Sprite / Original IA / Vídeo Wan y panel de detalles (chips de metadatos,
  prompt, favorito ⭐, usar como paleta global, quitar sombra, ocultar 👁, eliminar).
- **Historial** con miniaturas, marcado de favoritos y ocultos, e interruptor global «ver ocultos».
- Apagar el motor IA para liberar RAM/VRAM.

**Restricciones duras**:

- Sin red: nada de fuentes, iconos o librerías desde CDN.
- El backend es el que manda: los parámetros por defecto (pasos, CFG) los dicta el motor
  seleccionado vía `/api/engines`, y `config/estilo.json` nunca debe recibirlos.
- Todos los controles llevan hoy un `title` explicativo largo. Ese conocimiento es parte del
  producto: si desaparece, el usuario secundario se queda sin manual.
- La app es de un solo usuario y de una sola generación a la vez (hay un lock global en el servidor).

**Terminología fijada** (la usa el usuario y el resto de la documentación): motor, rejilla nativa,
semilla, pasos, CFG, sprite sheet, tileset, transiciones Wang, seamless, paleta global, LoRA,
raw / «Original IA».

## Brand Commitments

- Nombre: **SpriteGen** en la interfaz (el repo es SpriteGenIA).
- Idioma: **la interfaz siempre en español**; los prompts de generación siempre en inglés, y la UI
  lo señala con la pista «(en inglés)».
- **La interfaz nunca menciona** el videojuego concreto del autor, Steam, ni su hardware. El producto
  se presenta como un generador de sprites pixel art útil para cualquiera. Godot y Tiled sí se citan,
  pero solo como destino de exportación del tileset, que es una función real.
- Las licencias de los modelos se declaran en términos generales («no usable en proyectos
  comerciales»), nunca personalizadas.
- Iconos TDesign (MIT) ya incrustados como símbolos SVG en el HTML.
- **El marco rúnico del visor se queda.** Las esquinas ornamentales de `app/static/esquina.png` son un
  sprite hecho con la propia herramienta y dan carácter al visor: el rediseño las conserva (puede
  reencuadrarlas o reubicarlas, no eliminarlas).
- **Los parámetros numéricos se ven todos a la vez.** Rejilla, colores, escala, pasos y CFG no se
  esconden detrás de un desplegable «avanzado»: el usuario quiere los números delante mientras genera.

## Evidence on Hand

- `output/` — 280 PNG y 272 metadatos JSON de generaciones reales: sprites de casas medievales,
  caballeros, torres, castillos isométricos, terrenos y animaciones. Material real para poblar
  cualquier maqueta; no hace falta inventar contenido de relleno.
- `docs/portada.png` — collage de sprites reales del proyecto.
- `docs/arquitectura.png` / `.svg` / `.md` — diagrama de arquitectura.
- `app/static/esquina.png` — sprite de esquina ornamental usado hoy en el visor.
- No existen testimonios, métricas de uso, casos de estudio ni benchmarks: no deben inventarse.

## Product Principles

1. **El asset manda.** El sprite generado es el protagonista de la pantalla; la interfaz es el taller
   que lo rodea, no el espectáculo.
2. **Nunca dejar al usuario a ciegas.** Las esperas duran de segundos a media hora: el estado del
   trabajo, del motor y de la cola tiene que ser legible siempre, sin bloquear el resto de la app.
3. **Densidad con jerarquía, no compresión.** Es una herramienta experta con muchos parámetros; el
   objetivo no es esconderlos, es ordenarlos para que el camino frecuente sea inmediato y el raro
   siga a un clic.
4. **El historial es un archivo, no una tira.** Crece indefinidamente y es la memoria del proyecto:
   debe poder recorrerse, filtrarse y compararse.
5. **Autoexplicativa sin manual.** Cada parámetro carga su propia explicación, porque el segundo
   usuario llega sin contexto.

## Accessibility & Inclusion

No hay un estándar exigido por el usuario. Requisitos derivados del uso real: contraste suficiente
para sesiones largas de horas en pantalla oscura, objetivos de clic cómodos para acciones
destructivas (eliminar borra archivos del disco), y foco de teclado visible — hoy los `title` nativos
son el único canal de ayuda y no son accesibles por teclado.
