/* SpriteGen · mesa de luz
   La máquina escribe su estado en la barra de registro y nunca tapa la mesa:
   se puede seguir recorriendo el archivo mientras un trabajo está en marcha. */

const $ = (id) => document.getElementById(id);

let current = null;      // metadatos de la pieza que está en el vidrio
let view = "sprite";     // sprite | raw | frames | video | 3d | 3dweb
let panelPinned = null;  // plegado de la hoja de exposición: null = automático
let revealed = null;     // ¿el archivo destapa los ocultos? lo manda el servidor
let ITEMS = [];          // último historial recibido, sin filtrar

const ICON = (id, cls = "ic") => `<svg class="${cls}"><use href="#${id}"/></svg>`;
const LS = {
  get: (k, d) => { try { return localStorage.getItem(k) ?? d; } catch { return d; } },
  set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* modo privado */ } },
};

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    // Los errores de validación de FastAPI llegan como lista de objetos
    const msg = Array.isArray(data.detail)
      ? data.detail.map((d) => d.msg || JSON.stringify(d)).join("; ")
      : data.detail;
    throw new Error(msg || `Error ${res.status}`);
  }
  return data;
}

/* ═══ La barra de registro: el trabajo en curso ═══════════════════════════ */

const JOB = {
  t0: 0, tick: null, poll: null, busy: false,
  base: null,      // firma de los fotogramas al arrancar (detecta datos rancios)
  frames: false,   // ya se vio avanzar los fotogramas: son del trabajo actual
  peekSeq: null,   // último preview mostrado (instantánea al arrancar)
  stages: null,    // nodo del grafo → etapa legible (trabajos con etapas largas: 3D)
};

const BUSY_BTNS = ["btnGen", "btnVar", "btnRepeat", "btnAnimate", "btnQueue",
                   "btnVariation", "btnTerrain", "btnTileset", "btnFx",
                   "btnUnshadow", "btnModel3d", "btnBake", "btnWeb", "queueRun"];

function setBusy(on) {
  JOB.busy = on;
  for (const id of BUSY_BTNS) {
    const el = $(id);
    if (el) el.disabled = on;
  }
}

function reloj(ms) {
  const s = Math.floor(ms / 1000);
  const m = Math.floor(s / 60);
  return `${String(m).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

function jobStart(texto, raíz) {
  JOB.t0 = Date.now();
  JOB.base = null;   // instantánea del progreso: el del servidor puede venir rancio
  JOB.frames = false;
  JOB.peekSeq = null;
  JOB.stages = null;
  jobPeekHide();
  $("jobBox").dataset.state = "run";
  $("jobText").textContent = texto;
  if (raíz) $("jobText").dataset.stem = raíz;
  else delete $("jobText").dataset.stem;
  $("jobFill").style.transform = "scaleX(0)";
  $("btnJobClear").classList.add("hidden");
  setBusy(true);
  clearInterval(JOB.tick);
  JOB.tick = setInterval(() => {
    $("jobClock").textContent = reloj(Date.now() - JOB.t0);
  }, 1000);
  $("jobClock").textContent = "00:00";
  document.title = "⏳ SpriteGen · generando";
  clearInterval(JOB.poll);
  JOB.poll = setInterval(jobPollProgress, 1200);
}

/* /api/live junta dos fuentes: los fotogramas completados (contador del
   servidor, solo animación por esqueleto) y el paso de muestreo + preview
   que ComfyUI empuja por su WebSocket. El contador de fotogramas puede
   venir rancio del trabajo anterior, así que se ignora hasta verlo cambiar;
   el paso lleva bandera `active` y no necesita esa guarda. */
async function jobPollProgress() {
  let s;
  try { s = await api("/api/live"); } catch { return; }

  jobPeekShow(s);
  const paso = s.active && s.step_total ? { v: s.step, m: s.step_total } : null;

  const f = s.frames || {};
  let frames = null;
  if (f.total) {
    const firma = `${f.current}/${f.total}`;
    if (JOB.base === null) JOB.base = firma;
    else if (JOB.frames || firma !== JOB.base) { JOB.frames = true; frames = f; }
  }

  const pasoFrac = paso ? paso.v / paso.m : 0;
  let frac = null;
  if (frames) frac = Math.min((frames.current + pasoFrac) / frames.total, 1);
  else if (paso) frac = pasoFrac;
  // Los nodos que no muestrean (remallado, horneado 3D) no dan pasos: entonces
  // solo cambia el rótulo de la etapa y el raíl se queda donde estaba
  const etapa = s.active && JOB.stages ? JOB.stages[s.node] : null;
  if (frac === null && !etapa) return;
  if (frac !== null) $("jobFill").style.transform = `scaleX(${frac})`;

  const t = $("jobText");
  if (!t.dataset.stem) return;
  const partes = [t.dataset.stem];
  if (etapa) partes.push(etapa);
  if (frames) partes.push(`fotograma ${Math.min(frames.current + 1, frames.total)} de ${frames.total}`);
  if (paso) partes.push(`paso ${paso.v} de ${paso.m}`);
  t.textContent = partes.join(" · ");
}

/* Miniatura del preview que ComfyUI emite mientras desruida: la primera
   lectura solo toma la firma (lo que hubiera es del trabajo anterior). */
function jobPeekShow(s) {
  if (JOB.peekSeq === null) { JOB.peekSeq = s.preview_seq; return; }
  if (!s.preview_seq || s.preview_seq === JOB.peekSeq) return;
  JOB.peekSeq = s.preview_seq;
  const url = `/api/live/preview.jpg?s=${s.preview_seq}`;
  $("jobPeek").src = url;
  $("jobPeekBig").src = url;
  $("jobPeekWrap").classList.remove("hidden");
}

function jobPeekHide() {
  $("jobPeekWrap").classList.add("hidden");
  $("jobPeek").removeAttribute("src");
  $("jobPeekBig").removeAttribute("src");
}

function jobSetText(texto, stem) {
  $("jobText").textContent = texto;
  if (stem) $("jobText").dataset.stem = stem;
  else delete $("jobText").dataset.stem;
}

function jobEnd(ok, texto) {
  clearInterval(JOB.tick); JOB.tick = null;
  clearInterval(JOB.poll); JOB.poll = null;
  jobPeekHide();
  setBusy(false);
  delete $("jobText").dataset.stem;
  const transcurrido = reloj(Date.now() - JOB.t0);
  $("jobBox").dataset.state = ok ? "done" : "fail";
  $("jobText").textContent = texto;
  $("jobClock").textContent = transcurrido;
  $("jobFill").style.transform = "scaleX(1)";
  $("btnJobClear").classList.remove("hidden");
  document.title = ok ? "✓ SpriteGen · listo" : "SpriteGen · sin terminar";
  if (ok) avisar(texto, transcurrido);
}

/* Confirmación instantánea, sin GPU y sin cronómetro (guardar el estilo) */
function jobNote(texto) {
  clearInterval(JOB.tick); JOB.tick = null;
  clearInterval(JOB.poll); JOB.poll = null;
  jobPeekHide();
  $("jobBox").dataset.state = "done";
  $("jobText").textContent = texto;
  $("jobClock").textContent = "";
  $("jobFill").style.transform = "scaleX(1)";
  $("btnJobClear").classList.remove("hidden");
}

function jobClear() {
  jobPeekHide();
  $("jobBox").dataset.state = "idle";
  $("jobText").textContent = "En reposo";
  $("jobClock").textContent = "";
  $("jobFill").style.transform = "scaleX(0)";
  $("btnJobClear").classList.add("hidden");
  document.title = "SpriteGen · Generador de Sprites";
}

/* Aviso al terminar: el usuario se va a hacer otra cosa durante la espera */
function avisar(texto, transcurrido) {
  if (LS.get("spritegen.notify") !== "1") return;
  if (!("Notification" in window) || Notification.permission !== "granted") return;
  if (!document.hidden) return;
  try {
    new Notification("SpriteGen · trabajo terminado", {
      body: `${texto} — ${transcurrido}`,
      tag: "spritegen-job",
    });
  } catch { /* el navegador puede negarlo */ }
}

async function toggleNotify() {
  const on = LS.get("spritegen.notify") === "1";
  if (on) { LS.set("spritegen.notify", "0"); paintNotify(); return; }
  if (!("Notification" in window)) {
    alert("Este navegador no admite notificaciones de escritorio.");
    return;
  }
  let permiso = Notification.permission;
  if (permiso === "default") {
    try { permiso = await Notification.requestPermission(); } catch { permiso = "denied"; }
  }
  if (permiso !== "granted") {
    alert("El navegador tiene bloqueadas las notificaciones para esta página.\n"
      + "Actívalas en el candado de la barra de direcciones y vuelve a intentarlo.");
    return;
  }
  LS.set("spritegen.notify", "1");
  paintNotify();
}

function paintNotify() {
  const on = LS.get("spritegen.notify") === "1";
  $("btnNotify").classList.toggle("on", on);
  $("btnNotify").innerHTML = `${ICON("i-bell", "ic ic-xs")} ${on ? "Avisando" : "Avisar"}`;
}

/* ═══ Ayuda: cada control lleva su explicación, accesible con el teclado ═══ */

function wireHelp() {
  for (const lbl of document.querySelectorAll("[data-help]")) {
    if (lbl.dataset.helpWired) continue;
    lbl.dataset.helpWired = "1";
    const texto = lbl.dataset.help;
    lbl.title = texto;
    const b = document.createElement("button");
    b.type = "button";
    b.className = "help";
    b.textContent = "?";
    b.setAttribute("aria-expanded", "false");
    b.setAttribute("aria-label", "Qué es esto");
    b.title = texto;
    const nota = document.createElement("p");
    nota.className = "help-note hidden";
    nota.textContent = texto;
    b.onclick = (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      const abierto = nota.classList.toggle("hidden");
      b.setAttribute("aria-expanded", String(!abierto));
    };
    if (lbl.classList.contains("chk")) {
      // El «?» va FUERA de la casilla: dentro, pulsarlo la marcaría
      const linea = document.createElement("div");
      linea.className = "chk-line";
      lbl.parentElement.insertBefore(linea, lbl);
      linea.append(lbl, b);
      linea.after(nota);
    } else {
      lbl.appendChild(b);
      (lbl.closest(".fld") || lbl.parentElement).appendChild(nota);
    }
  }
}

/* ═══ Las hojas ═══════════════════════════════════════════════════════════ */

/* La tira de hojas ocasionales vive anclada al pie de la columna. Pulsar una
   pestaña la despliega; pulsar la que ya está activa la vuelve a plegar, para
   devolverle la altura a las dos hojas diarias. */
function openSheet(nombre, plegar = false) {
  const rare = $("rare");
  if (plegar && rare.classList.contains("open")
      && document.querySelector(".stab.active")?.dataset.sheet === nombre) {
    rare.classList.remove("open");
    LS.set("spritegen.rare", "closed");
    return;
  }
  for (const t of document.querySelectorAll(".stab")) {
    t.classList.toggle("active", t.dataset.sheet === nombre);
  }
  for (const s of document.querySelectorAll(".sheet")) {
    s.classList.toggle("hidden", s.dataset.sheet !== nombre);
  }
  rare.classList.add("open");
  LS.set("spritegen.sheet", nombre);
  LS.set("spritegen.rare", "open");
}

/* ═══ Motores de generación ═══════════════════════════════════════════════ */

let ENGINES = [];

/* Rellena un <select> de motores. Devuelve true si hubo que repoblarlo, para
   no pisar la elección del usuario en cada refresco de estado. */
function fillEngineSelect(sel, list, preferred) {
  const signature = list.map((e) => `${e.id}:${e.installed}`).join("|");
  if (sel.dataset.sig === signature) return false;
  const selected = sel.value;
  sel.innerHTML = "";
  for (const e of list) {
    const opt = document.createElement("option");
    opt.value = e.id;
    opt.textContent = e.installed ? e.label : `${e.label} · faltan archivos`;
    opt.disabled = !e.installed;
    sel.appendChild(opt);
  }
  const target = list.find((e) => e.id === selected && e.installed)
    || list.find((e) => e.id === preferred && e.installed)
    || list.find((e) => e.default && e.installed)
    || list.find((e) => e.installed);
  if (target) sel.value = target.id;
  sel.dataset.sig = signature;
  return true;
}

async function loadEngines() {
  try {
    const engines = await api("/api/engines");
    ENGINES = engines;
    const images = engines.filter((e) => e.kind === "image");
    const videos = engines.filter((e) => e.kind === "video");
    const modelos = engines.filter((e) => e.kind === "model3d");
    if (fillEngineSelect($("engine"), images)) applyEngineDefaults();
    if (fillEngineSelect($("videoEngine"), videos, "wan22_14b_pixel")) applyVideoEngine();
    if (fillEngineSelect($("m3dEngine"), modelos, "trellis2")) applyModel3dEngine();
  } catch { /* servidor reiniciándose */ }
}

/* Las calidades (caras y textura) las declara cada motor 3D en motores.json */
function applyModel3dEngine() {
  const e = ENGINES.find((x) => x.id === $("m3dEngine").value);
  if (!e) return;
  $("m3dEngineDesc").textContent = e.description || "";
  const sel = $("m3dQuality");
  const elegida = sel.value || e.params.quality;
  sel.innerHTML = "";
  for (const [id, q] of Object.entries(e.params.qualities || {})) {
    const opt = document.createElement("option");
    opt.value = id;
    opt.textContent = q.label || id;
    sel.appendChild(opt);
  }
  if ([...sel.options].some((o) => o.value === elegida)) sel.value = elegida;
}

function currentEngine() {
  return ENGINES.find((e) => e.id === $("engine").value);
}

function currentVideoEngine() {
  return ENGINES.find((e) => e.id === $("videoEngine").value);
}

/* El desplegable guarda FOTOGRAMAS, no segundos: la duración depende del fps
   del motor (16 en el 14B, 24 en el 5B). Se marca la opción más cercana a los
   5 s con los que se entrenó Wan. */
function applyVideoLengths(fps) {
  const opts = [...$("videoLength").options];
  const optima = opts.reduce((a, b) =>
    Math.abs(a.value / fps - 5) < Math.abs(b.value / fps - 5) ? a : b);
  for (const o of opts) {
    const s = (Number(o.value) / fps).toFixed(1).replace(".", ",");
    o.textContent = `${s} s` + (o === optima ? " · óptimo" : "");
  }
}

/* Los motores de vídeo «libres» no pixelizan: sus controles de ciclo y de
   fotogramas no aplican, y el prompt viaja en crudo. */
function applyVideoEngine() {
  const e = currentVideoEngine();
  if (!e) return;
  $("videoEngineDesc").textContent = e.description || "";
  applyVideoLengths(Number(e.params.fps) || 16);
  const free = !!e.params.raw_output;
  $("videoPixelRow").classList.toggle("hidden", free);
  $("videoMotion").placeholder = free
    ? "the character slowly turns their head and smiles, wind in the hair"
    : "walk cycle / idle breathing / attack slash";
}

function applyEngineDefaults() {
  const e = currentEngine();
  if (!e) return;
  $("engineDesc").textContent = e.description || "";
  if (e.params.steps) $("steps").value = e.params.steps;
  if (e.params.cfg !== undefined) $("cfg").value = e.params.cfg;
}

function engineLabel(id) {
  const e = ENGINES.find((x) => x.id === id);
  // nombre completo del motor sin la coletilla descriptiva ("FLUX.2 Klein 4B")
  return e ? e.label.split("·")[0].trim() : id;
}

/* ═══ Generación ══════════════════════════════════════════════════════════ */

async function generate(seedMode) {
  const subject = $("subject").value.trim();
  if (!subject) { alert("Escribe primero la descripción del sprite."); return; }

  if (seedMode === "repeat" && !current) {
    alert("No hay ninguna pieza en el vidrio de la cual repetir la semilla.");
    return;
  }
  let seed = null;
  if (seedMode === "repeat" && current) seed = current.seed;
  else if (seedMode === "form" && $("seed").value !== "") seed = Number($("seed").value);
  // seedMode === "new" → semilla aleatoria (null)

  const body = {
    subject,
    engine: $("engine").value || null,
    seed,
    native: Number($("native").value),
    scale: Number($("scale").value),
    colors: Number($("colors").value),
    // vacío = usar el default del motor (Number("") sería 0 y el servidor lo rechaza)
    steps: $("steps").value === "" ? null : Number($("steps").value),
    cfg: $("cfg").value === "" ? null : Number($("cfg").value),
    use_palette: $("usePalette").checked,
    raw_prompt: $("rawPrompt").checked,
  };

  const encendido = $("engineDot").classList.contains("on");
  jobStart(encendido ? "Generando sprite" : "Encendiendo el motor y generando el sprite",
           "Generando sprite");
  try {
    const meta = await api("/api/generate", { method: "POST", body: JSON.stringify(body) });
    setCurrent(meta);
    await loadHistory();
    refreshStatus();
    jobEnd(true, `Sprite listo · ${meta.native} px`);
  } catch (e) {
    jobEnd(false, "El sprite no salió");
    alert(e.message);
  }
}

function setCurrent(meta) {
  current = meta;
  // Un modelo 3D se abre en su visor; lo demás, en la imagen principal
  view = meta.kind === "model3d" ? "3d" : "sprite";
  frameIdx = 0;
  panelPinned = null;
  $("viewerEmpty").classList.add("hidden");
  $("bigImg").classList.remove("hidden");
  $("viewerBar").classList.remove("hidden");
  $("sidePanel").classList.remove("hidden");
  render();
}

function clearViewer() {
  current = null;
  hide3d();
  updateSheet3d();
  $("bigImg").classList.add("hidden");
  $("frameSlice").classList.add("hidden");
  $("stage").classList.remove("onionskin");
  $("viewerBar").classList.add("hidden");
  $("sidePanel").classList.add("hidden");
  $("viewerEmpty").classList.remove("hidden");
}

/* ═══ El vidrio: escala entera, luz y hoja de fotogramas ══════════════════ */

let zoom = LS.get("spritegen.zoom", "fit");   // "fit" | "1" | "2" | "4" | "6"
let frameIdx = 0;
const SHEETS = new Map();   // id → {w, h, frames} medido del sprite sheet

function setZoom(k) {
  zoom = k;
  LS.set("spritegen.zoom", k);
  paintRuler();
  applyZoom();
}

function paintRuler() {
  for (const b of document.querySelectorAll("#scaleRuler .rule-btn")) {
    b.classList.toggle("active", b.dataset.k === zoom);
  }
}

/* El sprite solo se agranda en múltiplos ENTEROS de su rejilla nativa: es la
   única forma de juzgar el píxel real sin que el navegador lo interpole. */
function applyZoom() {
  const img = $("bigImg");
  const nativo = Number(current?.native) || 0;
  if (view === "3d" || view === "3dweb") return;   // el visor 3D encuadra solo
  if (view === "frames") { paintFrames(); return; }
  if (zoom === "fit" || !nativo) {
    img.classList.remove("zoomed");
    img.style.width = "";
    return;
  }
  img.classList.add("zoomed");
  img.style.width = `${nativo * Number(zoom)}px`;
}

function toggleLight() {
  const g = $("glassBox");
  g.dataset.lit = g.dataset.lit === "off" ? "on" : "off";
  LS.set("spritegen.lit", g.dataset.lit);
  // El botón queda marcado cuando el vidrio está APAGADO, que es el estado
  // no predeterminado. Antes se marcaba al revés que en el arranque.
  $("btnLight").classList.toggle("on", g.dataset.lit === "off");
}

/* ¿Se puede desplegar como hoja de fotogramas? El sprite sheet es una tira
   horizontal, así que se recorta con background-position sin pedir nada más
   al servidor. Los clips largos de vídeo quedan fuera: su tira es enorme. */
function framesAvailable() {
  return !!current
    && current.kind === "animation"
    && current.frames >= 2
    && current.frames <= 48
    && !!current.raw_url;
}

function measureSheet() {
  if (!current || SHEETS.has(current.id)) return Promise.resolve(SHEETS.get(current.id));
  const id = current.id, n = current.frames;
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => {
      const d = { w: img.naturalWidth / n, h: img.naturalHeight, url: img.src };
      SHEETS.set(id, d);
      resolve(d);
    };
    img.onerror = () => resolve(null);
    img.src = current.raw_url;
  });
}

async function paintFrames() {
  const d = await measureSheet();
  if (!d || !current) return;
  const n = current.frames;
  const caja = $("stage").getBoundingClientRect();
  const nativo = Number(current.native) || d.w;
  let z = zoom === "fit"
    ? Math.min((caja.width - 56) / d.w, (caja.height - 56) / d.h, 1)
    : (nativo * Number(zoom)) / d.w;
  if (!(z > 0)) z = 1;
  const fw = Math.round(d.w * z), fh = Math.round(d.h * z);

  // El corte va en PORCENTAJE: con el fondo a n veces el ancho de la caja, la
  // fórmula del navegador cae exactamente en el fotograma i. Con píxeles
  // redondeados el error se acumula y asoma el fotograma vecino.
  const pon = (el, i) => {
    el.style.width = `${fw}px`;
    el.style.height = `${fh}px`;
    el.style.backgroundImage = `url("${d.url}")`;
    el.style.backgroundSize = `${n * 100}% 100%`;
    el.style.backgroundPosition = n > 1 ? `${(i / (n - 1)) * 100}% 0` : "0 0";
  };
  const i = ((frameIdx % n) + n) % n;
  pon($("frameSlice"), i);
  pon($("onion1"), (i - 1 + n) % n);
  pon($("onion2"), (i - 2 + n) % n);
  paintXsFrames();
}

function paintXsFrames() {
  const caja = $("xsFrames");
  const cuerpo = document.querySelector(".panel-body");
  if (view !== "frames" || !current) {
    caja.classList.add("hidden");
    cuerpo.classList.remove("with-frames");
    return;
  }
  caja.classList.remove("hidden");
  cuerpo.classList.add("with-frames");
  const n = current.frames;
  const i = ((frameIdx % n) + n) % n;
  if (caja.dataset.id !== current.id) {
    caja.dataset.id = current.id;
    const fps = current.fps || 12;
    // Un horneado 3D no es un ciclo en el tiempo: cada fotograma es un ángulo
    const giro = !!current.baked_from;
    caja.innerHTML = giro
      ? `<p class="plabel">Direcciones <span class="hint">${n} · vuelta completa</span></p>`
        + `<div class="xs-frames-list"></div>`
      : `<p class="plabel">Fotogramas <span class="hint">${n} · ${fps} fps</span></p>`
        + `<div class="xs-frames-list"></div>`;
    const lista = caja.querySelector(".xs-frames-list");
    for (let k = 0; k < n; k++) {
      const b = document.createElement("button");
      b.className = "xs-frame";
      b.dataset.i = k;
      const marca = giro
        ? `${Math.round((k * 360) / n)}°`
        : `${(k / fps).toFixed(2).replace(".", ",")} s`;
      b.innerHTML = `<span class="n">${String(k + 1).padStart(2, "0")}</span>`
        + `<span class="bar"></span>`
        + `<span>${marca}</span>`;
      b.onclick = () => { frameIdx = k; paintFrames(); };
      lista.appendChild(b);
    }
  }
  for (const b of caja.querySelectorAll(".xs-frame")) {
    const act = Number(b.dataset.i) === i;
    b.classList.toggle("active", act);
    if (act) b.scrollIntoView({ block: "nearest" });
  }
}

/* ═══ Pintado de la pieza en el vidrio ════════════════════════════════════ */

const TAB_LABELS = {
  sprite: ["Sprite", "Original IA"],
  animation: ["GIF", "Sprite sheet"],
  terrain: ["Variantes", "Textura IA"],
  tileset: ["Mapa de prueba", "Tileset"],
  model3d: ["Miniatura", "Original IA"],
};

/* ═══ El visor 3D (módulo aparte, se carga la primera vez que hace falta) ═══ */

let VISOR = null;
const fmtMiles = (n) => Number(n || 0).toLocaleString("es-ES");

function visor3d() {
  // La ?v= va aquí y no en index.html: es este import el que pide el módulo
  if (!VISOR) VISOR = import("./visor3d.js?v=20261016f");
  return VISOR;
}

/* La versión web que enseña la pestaña «3D web»: la elegida en la hoja si
   existe, si no la que haya */
function webVersion(m = current) {
  const web = m?.web || {};
  return web[$("webPreset").value] || Object.values(web)[0] || null;
}

async function show3d() {
  const msg = $("viewer3dMsg");
  const pieza = current;
  const url = view === "3dweb" ? webVersion(pieza)?.url : pieza.model_url;
  try {
    const v = await visor3d();
    if (current !== pieza || !(view === "3d" || view === "3dweb") || !url) return;
    await v.mostrar($("viewer3d"), url);
    // La orientación es del modelo (va en su ficha); la luz, del horneado
    v.orientar(pieza.yaw || 0);
    v.luz($("bakeLight").value);
    msg.classList.add("hidden");
    paintCamRuler(v);
    updateBakeEstimate();
  } catch (e) {
    msg.textContent = `No se pudo mostrar el modelo 3D: ${e.message || e}`;
    msg.classList.remove("hidden");
  }
}

function hide3d() {
  $("viewer3d").classList.add("hidden");
  if (VISOR) VISOR.then((v) => v.ocultar()).catch(() => {});
}

/* La hoja 3D cambia según lo que haya en el vidrio: un sprite se convierte
   en modelo; un modelo se hornea a sprites */
function updateSheet3d() {
  const es3d = current?.kind === "model3d";
  $("m3dConvert").classList.toggle("hidden", es3d);
  $("m3dBake").classList.toggle("hidden", !es3d);
  if (es3d) $("bakeYaw").textContent = `${current.yaw || 0}°`;
  $("bakeTilesRow").classList.toggle("hidden", $("bakeScale").value !== "tiles");
}

/* Los ajustes del horneado tal como los pide visor3d.planHorneado y
   hornearPieza: la escala y el envío viven allí, compartidos con la página de
   horneado de la CLI (hornear.html), para que las dos vías den lo mismo */
function bakeSettings() {
  return {
    vista: $("bakeView").value,
    direcciones: Number($("bakeDirs").value),
    modo: $("bakeScale").value,
    tiles: Number($("bakeTiles").value),
    tilePx: Number($("bakeTilePx").value),
    rejilla: Number($("native").value),
    luz: $("bakeLight").value,
    colores: Number($("colors").value),
    escala: Number($("scale").value),
    paleta: $("usePalette").checked,
  };
}

async function updateBakeEstimate() {
  const nota = $("bakeEstimate");
  if (current?.kind !== "model3d" || !VISOR) { nota.textContent = ""; return; }
  const v = await VISOR;
  const direcciones = Number($("bakeDirs").value);
  const e = v.planHorneado(bakeSettings());
  if (!e) { nota.textContent = ""; return; }
  const tam = `${e.w} × ${e.h} px`;
  nota.textContent = direcciones === 1
    ? `El sprite saldrá de unos ${tam} de rejilla.`
    : `Cada dirección saldrá de unos ${tam} de rejilla; la hoja, de ${e.w * direcciones} × ${e.h} px.`;
  nota.classList.toggle("warn", Math.max(e.w, e.h) > 512);
}

async function rotateModel(delta) {
  if (current?.kind !== "model3d") return;
  const pieza = current;
  const yaw = ((((pieza.yaw || 0) + delta) % 360) + 360) % 360;
  const v = await visor3d();
  v.orientar(yaw);
  pieza.yaw = yaw;
  $("bakeYaw").textContent = `${yaw}°`;
  updateBakeEstimate();
  try {
    const meta = await api("/api/model3d/orient", {
      method: "POST", body: JSON.stringify({ id: pieza.id, yaw }),
    });
    const i = ITEMS.findIndex((m) => m.id === meta.id);
    if (i >= 0) ITEMS[i] = meta;
    if (current?.id === meta.id) current.yaw = meta.yaw;
  } catch (e) { alert(e.message); }
}

const VISTA_NOMBRE = {
  iso: "Isométrica 2:1", iso_real: "Isométrica real", tres_cuartos: "Cenital 3/4",
  cenital: "Cenital 60°", frente: "Lateral",
};
const LUZ_NOMBRE = { dia: "Día", atardecer: "Atardecer", noche: "Noche" };

async function runBake() {
  if (current?.kind !== "model3d") {
    alert("Selecciona primero en el vidrio el modelo 3D que quieres hornear.");
    return;
  }
  const pieza = current;
  // Se hornea lo que se ve: el vidrio pasa al visor 3D si no estaba en él
  if (view !== "3d") { view = "3d"; render(); }
  const v = await visor3d();
  await v.mostrar($("viewer3d"), pieza.model_url);
  const ajustes = bakeSettings();
  const direcciones = ajustes.direcciones;
  const rótulo = direcciones === 1 ? "Horneando el sprite" : `Horneando ${direcciones} direcciones`;
  jobStart(rótulo, rótulo);
  try {
    const meta = await v.hornearPieza(pieza, ajustes,
                                      (fase) => jobSetText(`${rótulo} · ${fase}`));
    setCurrent(meta);
    await loadHistory();
    jobEnd(true, direcciones === 1
      ? `Sprite horneado · ${meta.native} px`
      : `Hoja horneada · ${meta.frames} direcciones`);
  } catch (err) {
    jobEnd(false, "El horneado no salió");
    alert(err.message);
  }
}

/* Versión web del GLB (gltf-transform en el servidor: un par de segundos).
   Al terminar, el vidrio la enseña tal como la cargará Three.js. */
async function runWeb() {
  if (current?.kind !== "model3d") return;
  const pieza = current;
  const preset = $("webPreset").value;
  jobStart("Creando la versión web del modelo");
  try {
    const meta = await api("/api/model3d/web", {
      method: "POST", body: JSON.stringify({ id: pieza.id, preset }),
    });
    const i = ITEMS.findIndex((m) => m.id === meta.id);
    if (i >= 0) ITEMS[i] = meta;
    if (current?.id === meta.id) {
      current = meta;
      view = "3dweb";
      render();
    }
    const v = meta.web[preset];
    jobEnd(true, `Versión web lista · ${String(v.mb).replace(".", ",")} MB `
      + `(el original pesa ${String(meta.glb_mb).replace(".", ",")} MB)`);
  } catch (e) {
    jobEnd(false, "La versión web no salió");
    alert(e.message);
  }
}

function paintCamRuler(v, girando = null) {
  for (const b of document.querySelectorAll("#camRuler .rule-btn")) {
    if (b.dataset.cam === "girar") {
      if (girando !== null) b.classList.toggle("active", girando);
    } else {
      b.classList.toggle("active", b.dataset.cam === v.vistaActual());
    }
  }
}

function panelCollapsed() {
  if (panelPinned !== null) return panelPinned;
  // en el sprite sheet (formato apaisado) el ancho manda: plegado automático
  return !!current && (current.kind || "sprite") === "animation" && view === "raw";
}

function specLine(m) {
  const trozos = [];
  if (m.engine) trozos.push(engineLabel(m.engine));
  if (m.kind === "model3d") {
    // En la pestaña «3D web» la línea describe la versión web, no el maestro
    const w = view === "3dweb" && m === current ? webVersion(m) : null;
    const d = w ? { faces: w.faces, texture: w.texture, mb: w.mb } : { faces: m.faces, texture: m.texture, mb: m.glb_mb };
    if (w) trozos.push("versión web");
    trozos.push(`<b>${fmtMiles(d.faces)}</b> caras`);
    if (d.texture) trozos.push(`textura <b>${d.texture}</b>`);
    if (d.mb) trozos.push(`${String(d.mb).replace(".", ",")} MB`);
    trozos.push(`seed <b>${m.seed}</b>`);
    return trozos.join('<span class="sep">·</span>');
  }
  if (m.native) trozos.push(`<b>${m.native}</b> px`);
  if (m.colors) trozos.push(`<b>${m.colors}</b> col`);
  if (m.kind === "animation" && m.frames) trozos.push(`<b>${m.frames}</b> fotogramas`);
  if (m.kind === "terrain" && m.variants) trozos.push(`<b>${m.variants}</b> variantes`);
  trozos.push(`seed <b>${m.seed}</b>`);
  if (m.steps) trozos.push(`${m.steps} pasos`);
  if (m.cfg) trozos.push(`cfg ${String(m.cfg).replace(".", ",")}`);
  if (m.used_palette) trozos.push("paleta global");
  return trozos.join('<span class="sep">·</span>');
}

function render() {
  if (!current) return;
  const kind = current.kind || "sprite";
  const labels = TAB_LABELS[kind] || TAB_LABELS.sprite;

  const hayHoja = framesAvailable();
  $("tabFrames").classList.toggle("hidden", !hayHoja);
  if (view === "frames" && !hayHoja) view = "sprite";
  const es3d = kind === "model3d" && !!current.model_url;
  const web = es3d ? webVersion() : null;
  $("tab3d").classList.toggle("hidden", !es3d);
  $("tab3dWeb").classList.toggle("hidden", !web);
  if (view === "3d" && !es3d) view = "sprite";
  if (view === "3dweb" && !web) view = es3d ? "3d" : "sprite";

  const enHoja = view === "frames";
  const en3d = view === "3d" || view === "3dweb";
  $("frameSlice").classList.toggle("hidden", !enHoja);
  $("stage").classList.toggle("onionskin", enHoja);
  $("bigImg").classList.toggle("hidden", enHoja || en3d);
  $("viewer3d").classList.toggle("hidden", !en3d);
  $("scaleRuler").classList.toggle("hidden", en3d);
  $("camRuler").classList.toggle("hidden", !en3d);
  if (en3d) show3d(); else hide3d();
  if (!enHoja && !en3d) {
    const src = view === "video" ? current.video_url
      : view === "raw" ? current.raw_url : current.sprite_url;
    $("bigImg").src = src + "?t=" + (current.ts || 0);
  }

  // En el vídeo libre el GIF principal es el clip del modelo, no una vista previa
  $("tabSprite").textContent = current.raw_video ? "Vídeo" : labels[0];
  $("tabRaw").textContent = labels[1];
  $("tabVideo").classList.toggle("hidden", !current.video_url);
  $("tabSprite").classList.toggle("active", view === "sprite");
  $("tabRaw").classList.toggle("active", view === "raw");
  $("tabFrames").classList.toggle("active", enHoja);
  $("tabVideo").classList.toggle("active", view === "video");
  $("tab3d").classList.toggle("active", view === "3d");
  $("tab3dWeb").classList.toggle("active", view === "3dweb");
  updateSheet3d();
  $("btnGlb").classList.toggle("hidden", !es3d);
  if (es3d) {
    $("btnGlb").href = current.model_url;
    $("btnGlb").download = current.model;
  }
  // Un enlace de descarga por versión web ya creada
  const enlaces = $("glbWebLinks");
  enlaces.innerHTML = "";
  for (const [preset, v] of Object.entries(es3d ? current.web || {} : {})) {
    const a = document.createElement("a");
    a.className = "btn-side";
    a.href = v.url;
    a.download = v.file;
    a.title = `Versión ${preset} para Three.js: ${fmtMiles(v.faces)} caras, texturas WebP de ${v.texture} px`;
    a.innerHTML = `${ICON("i-download")} GLB ${preset} · ${String(v.mb).replace(".", ",")} MB`;
    enlaces.appendChild(a);
  }

  $("specLine").innerHTML = specLine(current);
  applyZoom();
  paintXsFrames();

  const collapsed = panelCollapsed();
  $("sidePanel").classList.toggle("collapsed", collapsed);
  $("btnPanelIcon").setAttribute("href", collapsed ? "#i-expand" : "#i-collapse");
  $("btnMakePalette").classList.toggle("hidden", !(kind === "sprite" || kind === "terrain"));
  $("btnUnshadow").classList.toggle("hidden", kind !== "sprite");
  $("btnFav").innerHTML = `${ICON(current.favorite ? "i-star-f" : "i-star")} Favorito`;
  $("btnFav").classList.toggle("faved", !!current.favorite);
  $("btnHide").innerHTML = current.hidden
    ? `${ICON("i-eye")} Volver a mostrar`
    : `${ICON("i-eye-off")} Ocultar del archivo`;
  $("btnHide").classList.toggle("hidden-on", !!current.hidden);
  updateAnimButton();
  renderPanel();
  document.querySelectorAll(".leaf").forEach((t) =>
    t.classList.toggle("active", t.dataset.id === current.id));
}

/* La hoja de exposición: una fila reglada por dato, con cifras tabulares */
function renderPanel() {
  const m = current;
  const filas = [];
  const fila = (k, v, cls = "", attrs = "") => filas.push(
    `<dl class="xs-row${cls}"${attrs}><dt>${k}</dt><dd>${v}</dd></dl>`);

  fila("Semilla", `${m.seed} ${ICON("i-copy", "ic ic-xs")}`,
       " clickable", ' id="chipSeed" role="button" tabindex="0"');
  if (m.engine) fila("Motor", engineLabel(m.engine));
  if (m.kind === "model3d") {
    fila("Caras", fmtMiles(m.faces));
    if (m.texture) fila("Textura", `${m.texture} px`);
    if (m.glb_mb) fila("GLB", `${String(m.glb_mb).replace(".", ",")} MB`);
    if (m.quality) fila("Calidad", m.quality);
    if (m.seconds) fila("Tiempo", `${Math.floor(m.seconds / 60)} min ${m.seconds % 60} s`);
    for (const [preset, v] of Object.entries(m.web || {})) {
      fila(`GLB ${preset}`, `${String(v.mb).replace(".", ",")} MB · ${Math.round(v.faces / 1000)}k caras`);
    }
  }
  if (m.baked_from) {
    fila("Vista", VISTA_NOMBRE[m.view] || m.view);
    if (m.directions > 1) fila("Direcciones", m.directions);
    if (m.light) fila("Luz", LUZ_NOMBRE[m.light] || m.light);
    if (m.tiles) fila("Tiles", `${String(m.tiles).replace(".", ",")} de ${m.tile_px} px`);
    if (m.yaw) fila("Orientación", `${m.yaw}°`);
  }
  if (m.native) fila("Rejilla", `${m.native} px`);
  if (m.colors) fila("Colores", m.colors);
  if (m.scale) fila("Escala", `×${m.scale}`);
  if (m.steps) fila("Pasos", m.steps);
  if (m.cfg) fila("CFG", String(m.cfg).replace(".", ","));
  if (m.kind === "animation" && m.frames) fila("Fotogramas", m.frames);
  if (m.fps) fila("fps", m.fps);
  if (m.segments?.length) fila("Tramos", m.segments.length);
  if (m.variants) fila("Variantes", m.variants);
  if (m.used_palette) fila("Paleta", "global");
  if (m.method) fila("Pixelizado", m.method);
  $("metaChips").innerHTML = filas.join("");

  const semilla = $("chipSeed");
  if (semilla) {
    semilla.title = "Copia la semilla y la deja escrita en el registro";
    const copiar = async () => {
      try { await navigator.clipboard.writeText(String(m.seed)); } catch { /* sin permiso */ }
      $("seed").value = m.seed;
    };
    semilla.onclick = copiar;
    semilla.onkeydown = (ev) => {
      if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); copiar(); }
    };
  }
  $("promptBox").textContent = m.subject || "";
}

async function deleteItem(m) {
  const qué = m.kind === "animation"
    ? `la animación «${m.subject}» (GIF, sprite sheet y sus ${m.frames} fotogramas)`
    : m.kind === "model3d"
      ? `el modelo 3D «${m.subject}» (GLB, miniatura y su copia de la imagen original)`
      : `«${m.subject}»`;
  if (!confirm(`¿Eliminar ${qué}?\n\nSe borrarán definitivamente sus archivos del disco.`)) return;
  try {
    await api(`/api/history/${encodeURIComponent(m.id)}`, { method: "DELETE" });
    if (current && current.id === m.id) clearViewer();
    await loadHistory();
  } catch (e) {
    alert(e.message);
  }
}

/* ═══ Terreno y tilesets ══════════════════════════════════════════════════ */

function syncTerrains(terrains) {
  for (const id of ["terrA", "terrB"]) {
    const sel = $(id);
    const have = [...sel.options].map((o) => o.value).join("|");
    const want = terrains.map((t) => t.id).join("|");
    if (have === want) continue;
    const selected = sel.value;
    sel.innerHTML = "";
    for (const t of terrains) {
      const opt = document.createElement("option");
      opt.value = t.id;
      opt.textContent = `${t.id} (${t.variants} var.)`;
      sel.appendChild(opt);
    }
    if (terrains.some((t) => t.id === selected)) sel.value = selected;
  }
}

async function runTerrain() {
  const subject = $("terrainSubject").value.trim();
  if (!subject) { alert("Describe la textura del terreno (por ejemplo: dense green grass)."); return; }
  jobStart("Generando terreno", "Generando terreno");
  try {
    const meta = await api("/api/terrain", { method: "POST", body: JSON.stringify({ subject }) });
    setCurrent(meta);
    await loadHistory();
    refreshStatus();
    jobEnd(true, `Terreno listo · ${meta.variants || 4} variantes`);
  } catch (e) { jobEnd(false, "El terreno no salió"); alert(e.message); }
}

async function runTileset() {
  const a = $("terrA").value, b = $("terrB").value;
  if (!a || !b) { alert("Genera al menos dos terrenos primero."); return; }
  if (a === b) { alert("Elige dos terrenos distintos."); return; }
  jobStart("Componiendo transiciones y tileset");
  try {
    const meta = await api("/api/tileset", { method: "POST", body: JSON.stringify({ terrain_a: a, terrain_b: b }) });
    setCurrent(meta);
    await loadHistory();
    jobEnd(true, "Tileset listo · 16 transiciones");
  } catch (e) { jobEnd(false, "El tileset no salió"); alert(e.message); }
}

/* ═══ Animación ═══════════════════════════════════════════════════════════ */

function toggleAnimUI() {
  const video = $("animMethod").value === "video";
  $("animKindRow").classList.toggle("hidden", video);
  $("posePreviewBox").classList.toggle("hidden", video);
  $("animBaseRow").classList.toggle("hidden", video);
  $("animDenoiseRow").classList.toggle("hidden", video);
  $("videoUI").classList.toggle("hidden", !video);
  $("animNoteSkeleton").classList.toggle("hidden", video);
  $("animNoteVideo").classList.toggle("hidden", !video);
  updateAnimButton();
}

/* Un clip de vídeo libre en el vidrio se puede CONTINUAR: el nuevo tramo
   arranca de su último fotograma y el resultado es la unión de los dos. */
function chainableClip() {
  return current && current.kind === "animation" && current.raw_video ? current : null;
}

/* El botón pasa a «Continuar clip» cuando el vidrio tiene un clip encadenable
   y el método elegido es vídeo. */
function updateAnimButton() {
  const cadena = $("animMethod").value === "video" ? chainableClip() : null;
  $("btnAnimate").innerHTML =
    ICON("i-video") + (cadena ? " Continuar el clip" : " Generar animación");
  // La cola solo tiene sentido en el método de vídeo
  $("btnQueue").classList.toggle("hidden", $("animMethod").value !== "video");
  $("chainNote").classList.toggle("hidden", !cadena);
  if (cadena) {
    const n = cadena.segments?.length || 1;
    const seg = (cadena.frames / (cadena.fps || 16)).toFixed(1).replace(".", ",");
    $("chainNote").textContent =
      `Continuará el clip del vidrio (${n} tramo${n > 1 ? "s" : ""}, ${seg} s) desde su `
      + "último fotograma, a su misma resolución. Se creará una entrada nueva en el "
      + "archivo; el clip actual no se toca.";
  }
  if (JOB.busy) setBusy(true);
}

async function animateVideo() {
  const cadena = chainableClip();
  if (!cadena && (!current || (current.kind || "sprite") !== "sprite")) {
    alert("El método de vídeo parte del sprite del vidrio: genera o selecciona uno primero.");
    return;
  }
  const motion = $("videoMotion").value.trim();
  if (!motion) { alert("Describe el movimiento (por ejemplo: walk cycle)."); return; }
  let engine = currentVideoEngine();
  if (cadena && !engine?.params.raw_output) {
    // Encadenar exige un motor libre: los que pixelizan no producen fotogramas
    // continuables. Se conmuta solo en vez de fallar.
    const libre = ENGINES.find((e) => e.kind === "video" && e.params.raw_output && e.installed);
    if (!libre) { alert("Para continuar un clip necesitas un motor de vídeo libre instalado."); return; }
    $("videoEngine").value = libre.id;
    applyVideoEngine();
    engine = libre;
  }
  const body = {
    base_id: current.id,
    motion,
    engine_id: $("videoEngine").value || null,
    cycle_seconds: Number($("videoCycle").value),
    length: Number($("videoLength").value),
    seed: $("seed").value !== "" ? Number($("seed").value) : null,
    frames: Number($("videoFrames").value),
    native: Number($("animNative").value),
    scale: Number($("scale").value),
    colors: Number($("colors").value),
    use_palette: $("usePalette").checked,
  };
  const tramo = cadena ? (cadena.segments?.length || 1) + 1 : 0;
  const rótulo = cadena
    ? `Generando el tramo ${tramo} y uniéndolo al clip`
    : `Generando vídeo con ${engine ? engineLabel(engine.id) : "Wan 2.2"}`;
  jobStart(rótulo, rótulo);
  try {
    const meta = await api("/api/animate_video", { method: "POST", body: JSON.stringify(body) });
    setCurrent(meta);
    await loadHistory();
    refreshStatus();
    jobEnd(true, `Clip listo · ${meta.frames} fotogramas`);
  } catch (e) {
    jobEnd(false, "El clip no salió");
    alert(e.message);
  }
}

async function animate() {
  if ($("animMethod").value === "video") return animateVideo();

  const subject = $("subject").value.trim();
  if (!subject) { alert("Escribe primero la descripción del personaje en la hoja Generar."); return; }
  const useBase = $("animUseBase").checked;
  if (useBase && (!current || current.kind === "animation")) {
    alert("Para partir de un sprite, genera o selecciona antes un sprite normal en el vidrio.");
    return;
  }
  const body = {
    subject,
    anim: $("animKind").value,
    seed: useBase ? current.seed : ($("seed").value !== "" ? Number($("seed").value) : null),
    base_id: useBase ? current.id : null,
    denoise: Number($("animDenoise").value),
    native: Number($("animNative").value),
    scale: Number($("scale").value),
    colors: Number($("colors").value),
    use_palette: $("usePalette").checked,
  };
  jobStart("Generando animación por esqueleto", "Animación por esqueleto");
  try {
    const meta = await api("/api/animate", { method: "POST", body: JSON.stringify(body) });
    setCurrent(meta);
    await loadHistory();
    refreshStatus();
    jobEnd(true, `Animación lista · ${meta.frames} fotogramas`);
  } catch (e) {
    jobEnd(false, "La animación no salió");
    alert(e.message);
  }
}

async function runVariation() {
  if (!current || (current.kind || "sprite") !== "sprite") {
    alert("Selecciona primero un sprite en el vidrio.");
    return;
  }
  const instruction = $("varInstruction").value.trim();
  if (!instruction) { alert("Escribe la instrucción de la variación."); return; }
  jobStart("Generando variación con Klein", "Variación Klein");
  try {
    const meta = await api("/api/variation", {
      method: "POST",
      body: JSON.stringify({
        base_id: current.id,
        instruction,
        raw_prompt: $("rawPrompt").checked,
      }),
    });
    setCurrent(meta);
    await loadHistory();
    refreshStatus();
    jobEnd(true, "Variación lista");
  } catch (e) {
    jobEnd(false, "La variación no salió");
    alert(e.message);
  }
}

/* ═══ Modelo 3D ═══════════════════════════════════════════════════════════ */

/* Etapas del grafo 3D (claves de engines.build_model3d_graph). La mitad del
   tiempo se va en nodos que no muestrean, y sin esto la barra solo diría
   «generando» durante minutos. */
const ETAPAS_3D = {
  mask: "separando el fondo", cond: "leyendo la imagen",
  k_ss: "estructura", dec_ss: "estructura",
  k_sh: "forma", up: "forma en detalle", k_up: "forma en detalle", dec_sh: "malla",
  k_tex: "textura", dec_tex: "textura",
  remesh: "remallando", decimate: "reduciendo caras", unwrap: "desplegando las UV",
  bake: "horneando el color", normal: "horneando el relieve", ao: "horneando la oclusión",
  apply: "montando el material", save: "guardando el GLB", render: "miniatura",
};

async function runModel3d() {
  if (!current || (current.kind || "sprite") !== "sprite") {
    alert("Selecciona primero en el vidrio el sprite que quieres convertir en 3D.");
    return;
  }
  const engine = $("m3dEngine").value || null;
  const body = {
    base_id: current.id,
    engine_id: engine,
    quality: $("m3dQuality").value || null,
    seed: $("seed").value !== "" ? Number($("seed").value) : null,
  };
  const rótulo = `Modelo 3D con ${engine ? engineLabel(engine) : "TRELLIS.2"}`;
  const encendido = $("engineDot").classList.contains("on");
  jobStart(encendido ? rótulo : `Encendiendo el motor · ${rótulo}`, rótulo);
  JOB.stages = ETAPAS_3D;
  try {
    const meta = await api("/api/model3d", { method: "POST", body: JSON.stringify(body) });
    setCurrent(meta);
    await loadHistory();
    refreshStatus();
    jobEnd(true, `Modelo 3D listo · ${fmtMiles(meta.faces)} caras`);
  } catch (e) {
    jobEnd(false, "El modelo 3D no salió");
    alert(e.message);
  }
}

/* ═══ Cola de clips encadenados ═══════════════════════════════════════════ */

let queueTimer = null;

function queueRows() {
  return [...document.querySelectorAll("#queueList textarea")];
}

function queueAddRow(valor = "") {
  const n = queueRows().length + 1;
  const row = document.createElement("div");
  row.className = "queue-row";
  row.innerHTML = `<span class="num">${n}</span>`;
  const ta = document.createElement("textarea");
  ta.rows = 2;
  ta.placeholder = n === 1
    ? "qué ocurre en el primer clip…"
    : "y después, en este clip…";
  ta.value = valor;
  ta.oninput = queueRefreshSummary;
  const quitar = document.createElement("button");
  quitar.className = "btn-icon";
  quitar.title = "Quitar este clip";
  quitar.innerHTML = ICON("i-x");
  quitar.onclick = () => { row.remove(); queueRenumber(); };
  row.append(ta, quitar);
  $("queueList").appendChild(row);
  queueRefreshSummary();
  ta.focus();
}

function queueRenumber() {
  document.querySelectorAll("#queueList .queue-row").forEach((r, i) => {
    r.querySelector(".num").textContent = i + 1;
  });
  queueRefreshSummary();
}

function queueRefreshSummary() {
  const n = queueRows().filter((t) => t.value.trim()).length;
  const e = ENGINES.find((x) => x.id === $("queueEngine").value);
  const fps = Number(e?.params.fps) || 16;
  const frames = Number($("queueLength").value) || 81;
  const seg = (frames / fps) * n;
  // 6:51 medidos para 81 fotogramas a 768x768; se escala por fotogramas
  const min = Math.round((n * 411 * (frames / 81)) / 60);
  $("queueSummary").textContent = n
    ? `${n} clip${n > 1 ? "s" : ""} · ${seg.toFixed(1).replace(".", ",")} s de vídeo final · unos ${min} min de GPU`
    : "Añade al menos un prompt.";
}

function openQueue() {
  const base = current;
  if (!base) { alert("Selecciona antes una imagen o un clip en el vidrio."); return; }
  const esClip = !!(base.kind === "animation" && base.raw_video);
  $("queueBase").textContent = esClip
    ? `Continuará el clip del vidrio (${base.frames} fotogramas) y encadenará los nuevos a partir de él.`
    : "Arrancará de la imagen del vidrio y encadenará los clips uno tras otro.";
  // El selector de motor y el de duración replican los de la hoja de animación
  fillEngineSelect($("queueEngine"), ENGINES.filter((e) => e.kind === "video"),
                   esClip ? "wan22_14b_free" : $("videoEngine").value);
  $("queueLength").innerHTML = $("videoLength").innerHTML;
  $("queueLength").value = $("videoLength").value;
  if (!queueRows().length) queueAddRow();
  queueRefreshSummary();
  $("queueModal").classList.remove("hidden");
  wireHelp();
}

function closeQueue() { $("queueModal").classList.add("hidden"); }

async function runQueue() {
  const prompts = queueRows().map((t) => t.value.trim()).filter(Boolean);
  if (!prompts.length) { alert("Escribe al menos un prompt."); return; }
  try {
    await api("/api/animate_video_batch", {
      method: "POST",
      body: JSON.stringify({
        base_id: current.id,
        prompts,
        engine_id: $("queueEngine").value || null,
        length: Number($("queueLength").value),
        cycle_seconds: 0,
        seed: $("seed").value !== "" ? Number($("seed").value) : null,
      }),
    });
    closeQueue();
    pollQueue();
  } catch (e) { alert(e.message); }
}

/* Sondea el estado de la cola y refresca el archivo conforme salen clips */
async function pollQueue() {
  clearInterval(queueTimer);
  let vistos = 0;
  let arrancada = false;
  const tick = async () => {
    let s;
    try { s = await api("/api/batch"); } catch { return; }
    if (s.running) {
      if (!arrancada) { arrancada = true; jobStart("Cola de clips"); }
      $("btnQueueStop").classList.remove("hidden");
      jobSetText(`Cola · clip ${s.current} de ${s.total} · «${(s.prompt || "").slice(0, 48)}»`,
                 `Cola · clip ${s.current} de ${s.total}`);
      if (s.done.length > vistos) { vistos = s.done.length; loadHistory(); }
      return;
    }
    clearInterval(queueTimer);
    queueTimer = null;
    $("btnQueueStop").classList.add("hidden");
    if (arrancada) jobEnd(!s.error, s.error ? "La cola se detuvo" : `Cola terminada · ${vistos} clips`);
    await loadHistory();
    refreshStatus();
    if (s.error) alert(`La cola se detuvo: ${s.error}`);
    else if (s.last_id) {
      try {
        const m = await api("/api/history").then((h) => h.find((x) => x.id === s.last_id));
        if (m) setCurrent(m);  // puede faltar si el clip nació oculto
      } catch { /* el archivo ya está refrescado */ }
    }
  };
  await tick();
  if (!queueTimer) queueTimer = setInterval(tick, 4000);
}

/* ═══ El archivo ══════════════════════════════════════════════════════════ */

let binFilter = "all";
let binQuery = "";

const sinTildes = (s) => (s || "").toLowerCase()
  .normalize("NFD").replace(/[\u0300-\u036f]/g, "");

function binMatches(m) {
  if (binFilter === "fav" && !m.favorite) return false;
  if (binFilter === "terrain" && !["terrain", "tileset"].includes(m.kind)) return false;
  if (["sprite", "animation", "model3d"].includes(binFilter) && m.kind !== binFilter) return false;
  if (!binQuery) return true;
  return sinTildes(m.subject).includes(binQuery)
    || String(m.seed).includes(binQuery)
    || sinTildes(engineLabel(m.engine)).includes(binQuery);
}

const KIND_NAME = {
  sprite: "sprite", animation: "animación", terrain: "terreno", tileset: "tileset",
  model3d: "modelo 3D",
};

/* Cómo se hizo la pieza. El motor exacto solo consta si su meta lo guardó
   (los sprites desde hace tiempo; las animaciones, solo las nuevas), así que
   cuando falta se dice el MÉTODO, que sí es cierto por construcción: el ciclo
   de poses y el terreno pasan siempre por SDXL, los clips por Wan 2.2, y los
   efectos son matemática pura sin GPU. Nunca se inventa un modelo. */
function comoSeHizo(m) {
  if (m.engine) return engineLabel(m.engine);
  if (m.baked_from) return "horneado 3D";
  if (m.kind === "animation") {
    const a = String(m.anim || "");
    if (m.raw_video || /^(video|libre)_/.test(a)) return "Wan 2.2";
    if (/^(sway|flame|wave|smoke)$/.test(a)) return "efecto sin GPU";
    return "SDXL + ControlNet";
  }
  if (m.kind === "terrain" || m.kind === "tileset") return "SDXL";
  return null;
}

/* El rótulo no repite lo que ya dice la marca de lápiz (el tipo de pieza):
   lleva la medida y con qué se generó. La semilla vive en la hoja de
   exposición, donde además se copia con un clic. */
function leafMeta(m) {
  const t = [];
  if (m.kind === "animation" && m.baked_from) t.push(`${m.frames} dir`);
  else if (m.kind === "animation") t.push(`${m.frames} fot`);
  else if (m.kind === "model3d") t.push(`${Math.round((m.faces || 0) / 1000)}k caras`);
  else if (m.native) t.push(`${m.native} px`);
  // Si no consta, se dice que no consta: meter la semilla en el hueco del
  // motor rompería el significado de la columna
  t.push(comoSeHizo(m) || "motor sin registrar");
  return t.join(" · ");
}

function paintBin() {
  const box = $("history");
  const vistos = ITEMS.filter(binMatches);
  box.innerHTML = "";
  $("binCount").textContent = vistos.length === ITEMS.length
    ? `· ${ITEMS.length}`
    : `· ${vistos.length} de ${ITEMS.length}`;

  if (!vistos.length) {
    const p = document.createElement("p");
    p.className = "bin-empty";
    p.textContent = ITEMS.length
      ? "Ninguna pieza del archivo coincide con este filtro."
      : "El archivo está vacío: lo que generes irá apareciendo aquí.";
    box.appendChild(p);
    return;
  }

  for (const m of vistos) {
    if (!m.sprite_url) continue;
    const hoja = document.createElement("div");
    // Los ocultos solo llegan aquí con el interruptor activo: se distinguen
    hoja.className = m.hidden ? "leaf is-hidden" : "leaf";
    hoja.dataset.id = m.id;
    hoja.dataset.kind = m.kind || "sprite";
    hoja.tabIndex = 0;
    hoja.setAttribute("role", "button");
    hoja.title = `${m.subject}\n${KIND_NAME[m.kind] || "sprite"} · semilla ${m.seed}${m.engine ? " · " + engineLabel(m.engine) : ""}`;

    const th = document.createElement("div");
    th.className = "leaf-thumb";
    const img = document.createElement("img");
    img.loading = "lazy";
    img.alt = "";
    img.src = m.sprite_url;
    th.appendChild(img);

    const txt = document.createElement("div");
    txt.className = "leaf-txt";
    const nombre = document.createElement("p");
    nombre.className = "leaf-name";
    nombre.textContent = m.subject || "(sin descripción)";
    if (m.favorite) {
      nombre.insertAdjacentHTML("afterbegin", ICON("i-star-f", "ic ic-xs leaf-fav") + " ");
    }
    const meta = document.createElement("p");
    meta.className = "leaf-meta";
    meta.innerHTML = `<i class="pencil pencil-${m.kind || "sprite"}"></i>`;
    const rotulo = document.createElement("span");
    rotulo.textContent = leafMeta(m);
    meta.appendChild(rotulo);
    txt.append(nombre, meta);

    const tools = document.createElement("div");
    tools.className = "leaf-tools";
    const ojo = document.createElement("button");
    ojo.className = "leaf-tool";
    ojo.innerHTML = ICON(m.hidden ? "i-eye-off" : "i-eye", "ic ic-xs");
    ojo.title = m.hidden ? "Volver a mostrar" : "Ocultar del archivo y del Explorador";
    ojo.onclick = (ev) => { ev.stopPropagation(); toggleHide(m); };
    const borrar = document.createElement("button");
    borrar.className = "leaf-tool strike";
    borrar.innerHTML = ICON("i-del", "ic ic-xs");
    borrar.title = "Eliminar (borra los archivos del disco)";
    borrar.onclick = (ev) => { ev.stopPropagation(); deleteItem(m); };
    tools.append(ojo, borrar);

    const abrir = () => { $("subject").value = m.subject; setCurrent(m); };
    hoja.onclick = abrir;
    hoja.onkeydown = (ev) => {
      if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); abrir(); }
    };

    hoja.append(th, txt, tools);
    box.appendChild(hoja);
  }
  if (current) {
    document.querySelectorAll(".leaf").forEach((t) =>
      t.classList.toggle("active", t.dataset.id === current.id));
  }
}

async function loadHistory() {
  ITEMS = await api("/api/history");
  const favs = ITEMS.filter((m) => m.favorite).length;
  // El bloque de título imprime un dato REAL, no un número de producción inventado
  $("prodLine").textContent = `${ITEMS.length} hoja${ITEMS.length === 1 ? "" : "s"}`;
  $("favCount").innerHTML = favs ? `${ICON("i-star-f", "ic ic-xs")} ${favs}` : "";
  paintBin();
  // Lo que ya no está en la lista (recién ocultado o borrado) sale del vidrio
  if (current && !ITEMS.some((m) => m.id === current.id)) clearViewer();
  if (current) render();
}

async function toggleHide(m) {
  try {
    const meta = await api("/api/hide", {
      method: "POST",
      body: JSON.stringify({ id: m.id }),
    });
    if (current && current.id === meta.id) current = meta;
    await loadHistory();
    await refreshStatus();  // repinta el contador del interruptor
  } catch (e) {
    alert(e.message);
  }
}

async function toggleReveal() {
  try {
    await api("/api/reveal", {
      method: "POST",
      body: JSON.stringify({ on: !revealed }),
    });
    revealed = !revealed;
    await loadHistory();
    await refreshStatus();
  } catch (e) {
    alert(e.message);
  }
}

/* ═══ Efectos ambientales ═════════════════════════════════════════════════ */

function fxValue() {
  // El valor respeta el rango del efecto activo (el servidor lo valida igual)
  const el = $("fxParam");
  const v = Number(el.value) || Number(el.min);
  return Math.min(Number(el.max), Math.max(Number(el.min), v));
}

async function runEffect() {
  const type = $("fxType").value;
  const body = { type };
  if (type === "sway") {
    if (!current || current.kind === "animation") {
      alert("Selecciona antes un sprite (un árbol, un arbusto…) en el vidrio.");
      return;
    }
    body.base_id = current.id;
    body.amplitude = fxValue();
  } else if (type === "wave") {
    if (current && current.kind !== "animation") body.base_id = current.id;
    body.amplitude = fxValue();
    body.color = $("fxColor").value.trim();
  } else {
    body.size = fxValue();
    body.flame_kind = $("fxFlameKind").value;
  }
  jobStart("Generando efecto");
  try {
    const meta = await api("/api/effect", { method: "POST", body: JSON.stringify(body) });
    setCurrent(meta);
    await loadHistory();
    jobEnd(true, `Efecto listo · ${meta.frames} fotogramas`);
  } catch (e) {
    jobEnd(false, "El efecto no salió");
    alert(e.message);
  }
}

/* ═══ Estilo global ═══════════════════════════════════════════════════════ */

async function loadConfig() {
  const cfg = await api("/api/config");
  $("tpl").value = cfg.prompt_template;
  $("neg").value = cfg.negative_prompt;
  $("loraStrength").value = cfg.lora_strength;
  $("bgThreshold").value = cfg.bg_removal_threshold;
  $("removeShadow").checked = cfg.remove_shadow !== false;
  // los pasos y el CFG del registro los gobierna el motor, no el estilo
}

async function saveStyle() {
  try {
    // No se envían steps/cfg: esos pertenecen al motor seleccionado, y el
    // estilo global alimenta los flujos SDXL fijos (esqueleto, terreno)
    await api("/api/config", {
      method: "POST",
      body: JSON.stringify({
        prompt_template: $("tpl").value,
        negative_prompt: $("neg").value,
        lora_strength: Number($("loraStrength").value),
        bg_removal_threshold: Number($("bgThreshold").value),
        remove_shadow: $("removeShadow").checked,
      }),
    });
    jobNote("Estilo global guardado · se aplica a todo lo nuevo");
  } catch (e) { alert(e.message); }
}

/* ═══ Paleta global ═══════════════════════════════════════════════════════ */

function paintPalette(colors) {
  const box = $("paletteSwatches");
  box.innerHTML = "";
  for (const c of colors) {
    const s = document.createElement("span");
    s.style.background = c;
    s.title = c;
    box.appendChild(s);
  }
  $("usePalette").disabled = colors.length === 0;
}

async function makePalette() {
  if (!current?.sprite) return;
  if (!confirm("¿Fijar los colores de esta pieza como paleta global de todas tus generaciones?")) return;
  try {
    const { colors } = await api("/api/palette", {
      method: "POST",
      body: JSON.stringify({ sprite: current.sprite }),
    });
    paintPalette(colors);
    $("usePalette").checked = true;
    alert(`Paleta global creada con ${colors.length} colores.`);
  } catch (e) { alert(e.message); }
}

/* ═══ Estado de la máquina ════════════════════════════════════════════════ */

async function refreshStatus() {
  try {
    const s = await api("/api/status");
    $("engineDot").className = "dot " + (s.engine_on ? "on" : "off");
    $("engineText").textContent = "Motor IA: " + (s.engine_on ? "encendido" : "apagado");
    $("btnEngineOff").disabled = !s.engine_on;
    paintPalette(s.palette);
    if (s.anims) syncAnims(s.anims);
    if (s.terrains) syncTerrains(s.terrains);
    paintReveal(s);
  } catch { /* servidor reiniciándose */ }
}

function paintReveal(s) {
  const btn = $("btnReveal");
  // Sin nada oculto el interruptor sobra; se mantiene visible si está activo
  btn.classList.toggle("hidden", !s.hidden_count && !s.reveal_hidden);
  btn.innerHTML = `${ICON(s.reveal_hidden ? "i-eye" : "i-eye-off", "ic ic-xs")} `
    + `${s.reveal_hidden ? "Ocultos a la vista" : "Ver ocultos"} (${s.hidden_count})`;
  btn.classList.toggle("on", !!s.reveal_hidden);
  btn.title = s.reveal_hidden
    ? "Vuelve a tapar los elementos ocultos del archivo"
    : "Muestra en el archivo los elementos marcados con el ojo. Solo afecta a esta"
      + " aplicación: sus archivos siguen ocultos en el Explorador.";
  // Si lo cambiaron por fuera (otra pestaña), el archivo se pone al día
  if (revealed !== null && revealed !== s.reveal_hidden) loadHistory();
  revealed = s.reveal_hidden;
}

function syncAnims(anims) {
  const sel = $("animKind");
  const have = [...sel.options].map((o) => o.value).join("|");
  const want = anims.map((a) => a.id).join("|");
  if (have === want) return;
  const selected = sel.value;
  sel.innerHTML = "";
  for (const a of anims) {
    const opt = document.createElement("option");
    opt.value = a.id;
    opt.textContent = a.label;
    opt.dataset.files = JSON.stringify(a.files || []);
    sel.appendChild(opt);
  }
  if (anims.some((a) => a.id === selected)) sel.value = selected;
  updatePosePreview();
}

function updatePosePreview() {
  const opt = $("animKind").selectedOptions[0];
  if (!opt) return;
  const id = encodeURIComponent(opt.value);
  $("poseGif").src = `/api/anims/${id}/preview.gif?v=${Date.now()}`;
  const box = $("poseFrames");
  box.innerHTML = "";
  for (const name of JSON.parse(opt.dataset.files || "[]")) {
    const img = document.createElement("img");
    img.src = `/poses/${id}/${encodeURIComponent(name)}`;
    img.title = name;
    img.alt = name;
    box.appendChild(img);
  }
}

async function engineOff() {
  try {
    await api("/api/engine/stop", { method: "POST" });
  } catch (e) {
    alert(e.message);
  }
  refreshStatus();
}

/* ═══ Eventos ═════════════════════════════════════════════════════════════ */

for (const t of document.querySelectorAll(".stab")) {
  t.onclick = () => openSheet(t.dataset.sheet, true);
}

$("btnGen").onclick = () => generate("form");
$("btnVar").onclick = () => generate("new");
$("btnRepeat").onclick = () => generate("repeat");
$("btnAnimate").onclick = animate;
$("animKind").onchange = updatePosePreview;
$("btnFx").onclick = runEffect;
$("btnTerrain").onclick = runTerrain;
$("btnTileset").onclick = runTileset;
$("btnVariation").onclick = runVariation;
$("animMethod").onchange = toggleAnimUI;
$("engine").onchange = applyEngineDefaults;
$("videoEngine").onchange = applyVideoEngine;
$("btnQueue").onclick = openQueue;
$("queueAdd").onclick = () => queueAddRow();
$("queueClose").onclick = closeQueue;
$("queueCancelBtn").onclick = closeQueue;
$("queueRun").onclick = runQueue;
$("queueLength").onchange = queueRefreshSummary;
$("queueEngine").onchange = queueRefreshSummary;
$("queueModal").onclick = (ev) => { if (ev.target === $("queueModal")) closeQueue(); };
$("btnQueueStop").onclick = async () => {
  if (!confirm("¿Detener la cola cuando acabe el clip actual?")) return;
  try { await api("/api/batch/cancel", { method: "POST" }); } catch (e) { alert(e.message); }
};
$("btnJobClear").onclick = jobClear;
$("btnNotify").onclick = toggleNotify;

$("fxType").onchange = () => {
  const t = $("fxType").value;
  const fx = $("fxParam");
  // Rangos del servidor: amplitud (mecer/tela) 1–24 px · tamaño (fuego/humo) 24–160 px
  if (t === "sway" || t === "wave") { fx.min = 1; fx.max = 24; }
  else { fx.min = 24; fx.max = 160; }
  fx.value = t === "sway" ? 4 : t === "wave" ? 6 : t === "smoke" ? 96 : 64;
};
$("btnDice").onclick = () => { $("seed").value = ""; };

$("tabSprite").onclick = () => { view = "sprite"; render(); };
$("tabRaw").onclick = () => { view = "raw"; render(); };
$("tabFrames").onclick = () => { if (framesAvailable()) { view = "frames"; render(); } };
$("tabVideo").onclick = () => { if (current?.video_url) { view = "video"; render(); } };
$("tab3d").onclick = () => { if (current?.model_url) { view = "3d"; render(); } };
$("tab3dWeb").onclick = () => { if (webVersion()) { view = "3dweb"; render(); } };
$("btnWeb").onclick = runWeb;
$("webPreset").onchange = () => { if (view === "3dweb") render(); };
$("btnLight").onclick = toggleLight;
for (const b of document.querySelectorAll("#scaleRuler .rule-btn")) {
  b.onclick = () => setZoom(b.dataset.k);
}
for (const b of document.querySelectorAll("#camRuler .rule-btn")) {
  b.onclick = async () => {
    const v = await visor3d();
    paintCamRuler(v, v.vista(b.dataset.cam));
    // Las vistas de la regleta existen también en el horneado: quedan elegidas
    if ([...$("bakeView").options].some((o) => o.value === b.dataset.cam)) {
      $("bakeView").value = b.dataset.cam;
      updateBakeEstimate();
    }
  };
}
$("btnModel3d").onclick = runModel3d;
$("m3dEngine").onchange = applyModel3dEngine;
$("btnBake").onclick = runBake;
$("bakeRotL").onclick = () => rotateModel(-90);
$("bakeRotR").onclick = () => rotateModel(90);
$("bakeView").onchange = async () => {
  // Lo que se elige para hornear se ve en el vidrio en el acto
  if (current?.kind === "model3d" && VISOR) {
    const v = await VISOR;
    v.vista($("bakeView").value);
    paintCamRuler(v);
  }
  updateBakeEstimate();
};
$("bakeLight").onchange = async () => {
  if (VISOR) (await VISOR).luz($("bakeLight").value);
};
$("bakeScale").onchange = () => { updateSheet3d(); updateBakeEstimate(); };
for (const id of ["bakeDirs", "bakeTiles", "bakeTilePx", "native"]) {
  $(id).addEventListener("input", updateBakeEstimate);
}

$("btnSaveStyle").onclick = saveStyle;
$("btnMakePalette").onclick = makePalette;
$("btnDelete").onclick = () => { if (current) deleteItem(current); };
$("btnUnshadow").onclick = async () => {
  if (!current || (current.kind || "sprite") !== "sprite") return;
  jobStart("Quitando la sombra (sobre una copia)");
  try {
    const meta = await api("/api/unshadow", { method: "POST", body: JSON.stringify({ id: current.id }) });
    setCurrent(meta);
    await loadHistory();
    jobEnd(true, "Copia sin sombra lista");
  } catch (e) {
    jobEnd(false, "No se pudo quitar la sombra");
    alert(e.message);
  }
};
$("btnFav").onclick = async () => {
  if (!current) return;
  try {
    const meta = await api("/api/favorite", {
      method: "POST",
      body: JSON.stringify({ id: current.id }),
    });
    current = meta;   // conserva la pestaña activa del vidrio
    render();
    await loadHistory();
  } catch (e) { alert(e.message); }
};
$("btnHide").onclick = () => { if (current) toggleHide(current); };
$("btnReveal").onclick = toggleReveal;
$("btnPanel").onclick = () => { panelPinned = !panelCollapsed(); render(); };
$("btnEngineOff").onclick = engineOff;
$("btnBin").onclick = () => {
  const plegado = $("bin").classList.toggle("folded");
  LS.set("spritegen.bin", plegado ? "folded" : "open");
};

for (const p of document.querySelectorAll("#binFilters .pill[data-kind]")) {
  p.onclick = () => {
    binFilter = p.dataset.kind;
    for (const q of document.querySelectorAll("#binFilters .pill")) {
      q.classList.toggle("active", q === p);
    }
    paintBin();
  };
}
$("binSearch").oninput = () => { binQuery = sinTildes($("binSearch").value.trim()); paintBin(); };

/* ═══ Importar imágenes propias al archivo ════════════════════════════════ */

/* Van al servidor como data URL dentro del JSON (el venv no trae multipart).
   Un archivo ilegible no tumba a los demás: el servidor los separa. */
const leerDataURL = (f) => new Promise((ok, ko) => {
  const r = new FileReader();
  r.onload = () => ok(r.result);
  r.onerror = () => ko(r.error || new Error(`No se pudo leer «${f.name}»`));
  r.readAsDataURL(f);
});

const IMPORT_MAX = 25 * 1024 * 1024;

$("btnImport").onclick = () => $("importFile").click();
$("importFile").onchange = async () => {
  const files = [...$("importFile").files];
  $("importFile").value = "";   // permite volver a elegir el mismo archivo
  if (!files.length) return;
  const grandes = files.filter((f) => f.size > IMPORT_MAX).map((f) => f.name);
  if (grandes.length) {
    alert(`Demasiado grandes (máximo 25 MB por imagen):\n${grandes.join("\n")}`);
    return;
  }
  const btn = $("btnImport");
  btn.disabled = true;
  try {
    const payload = [];
    for (const f of files) payload.push({ name: f.name, data: await leerDataURL(f) });
    const r = await api("/api/import", { method: "POST", body: JSON.stringify({ files: payload }) });
    if (r.items.length) setCurrent(r.items[r.items.length - 1]);
    await loadHistory();
    const n = r.items.length;
    // Sin cronómetro ni GPU: una nota, pero nunca pisando un trabajo en curso
    if (!JOB.busy) {
      jobNote(n ? `${n} imagen${n === 1 ? "" : "es"} importada${n === 1 ? "" : "s"} al archivo`
                : "No se importó ninguna imagen");
    }
    if (r.errors.length) alert(r.errors.join("\n"));
  } catch (e) {
    alert(e.message);
  } finally {
    btn.disabled = false;
  }
};

$("subject").addEventListener("input", () =>
  LS.set("spritegen.subject", $("subject").value));

// Recorrer la hoja de fotogramas con el teclado, como en una mesa de luz
document.addEventListener("keydown", (ev) => {
  if (view !== "frames" || !current) return;
  const escribiendo = /^(INPUT|TEXTAREA|SELECT)$/.test(ev.target.tagName);
  if (escribiendo) return;
  if (ev.key === "ArrowRight" || ev.key === "ArrowLeft") {
    ev.preventDefault();
    frameIdx += ev.key === "ArrowRight" ? 1 : -1;
    paintFrames();
  }
});

// Al volver a la ventana, el título deja de llamar la atención; la marca de la
// barra de registro se queda hasta que se pulsa «Visto».
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && $("jobBox").dataset.state === "done") {
    document.title = "SpriteGen · Generador de Sprites";
  }
});

let reflow;
window.addEventListener("resize", () => {
  clearTimeout(reflow);
  reflow = setTimeout(() => { if (view === "frames") paintFrames(); }, 140);
});

/* ═══ Arranque ════════════════════════════════════════════════════════════ */

wireHelp();
// El estado plegado se lee ANTES: openSheet lo reescribe al montar la pestaña
const raraAbierta = LS.get("spritegen.rare", "closed") === "open";
const guardada = LS.get("spritegen.sheet", "klein");
openSheet(document.querySelector(`.stab[data-sheet="${guardada}"]`) ? guardada : "klein");
// Arranca plegada salvo que se dejara abierta: las hojas diarias mandan
if (!raraAbierta) {
  $("rare").classList.remove("open");
  LS.set("spritegen.rare", "closed");
}
paintRuler();
paintNotify();
$("glassBox").dataset.lit = LS.get("spritegen.lit", "on");
$("btnLight").classList.toggle("on", $("glassBox").dataset.lit === "off");
if (LS.get("spritegen.bin", "open") === "folded") $("bin").classList.add("folded");
$("subject").value = LS.get("spritegen.subject", "");

loadConfig();
loadEngines();
loadHistory();
refreshStatus();
toggleAnimUI();
// Si el servidor tenía una cola en marcha (por ejemplo, cerraste el navegador),
// se retoma sola en cuanto vuelves a abrir la mesa
pollQueue();
setInterval(() => { refreshStatus(); loadEngines(); }, 15000);
