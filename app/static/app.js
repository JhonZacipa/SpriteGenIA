const $ = (id) => document.getElementById(id);

let current = null;      // metadata del sprite en pantalla
let view = "sprite";     // sprite | raw | video (clip Wan original)
let panelPinned = null;  // plegado del panel lateral: null = automático
let revealed = null;     // ¿el historial destapa los ocultos? lo manda el servidor

const ICON = (id, cls = "ic") => `<svg class="${cls}"><use href="#${id}"/></svg>`;

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

/* ---------- Motores de generación ---------- */

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
    opt.textContent = e.installed ? e.label : `${e.label} · (faltan archivos)`;
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
    if (fillEngineSelect($("engine"), images)) applyEngineDefaults();
    if (fillEngineSelect($("videoEngine"), videos, "wan22_14b_pixel")) applyVideoEngine();
  } catch { /* servidor reiniciándose */ }
}

function currentEngine() {
  return ENGINES.find((e) => e.id === $("engine").value);
}

function currentVideoEngine() {
  return ENGINES.find((e) => e.id === $("videoEngine").value);
}

/* El desplegable guarda FRAMES, no segundos: la duración depende del fps del
   motor (16 en el 14B, 24 en el 5B). Se marca la opción más cercana a los 5 s
   con los que se entrenó Wan. */
function applyVideoLengths(fps) {
  const opts = [...$("videoLength").options];
  const optima = opts.reduce((a, b) =>
    Math.abs(a.value / fps - 5) < Math.abs(b.value / fps - 5) ? a : b);
  for (const o of opts) {
    const s = (Number(o.value) / fps).toFixed(1).replace(".", ",");
    o.textContent = `${s} s` + (o === optima ? " · óptimo" : "");
  }
}

/* Los motores de video «libres» no pixelizan: sus controles de ciclo y de
   frames no aplican, y el prompt viaja en crudo. */
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

/* ---------- Generación ---------- */

async function generate(seedMode) {
  const subject = $("subject").value.trim();
  if (!subject) { alert("Escribe primero la descripción del sprite."); return; }

  if (seedMode === "repeat" && !current) {
    alert("No hay ningún sprite en pantalla del cual repetir la semilla.");
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

  const engineOn = ($("engineDot").classList.contains("on"));
  $("overlayMsg").textContent = engineOn
    ? "Generando… (~1 minuto)"
    : "Encendiendo el motor de IA y generando… (2-3 minutos la primera vez)";
  $("overlay").classList.remove("hidden");
  try {
    const meta = await api("/api/generate", { method: "POST", body: JSON.stringify(body) });
    setCurrent(meta);
    await loadHistory();
    refreshStatus();
  } catch (e) {
    alert(e.message);
  } finally {
    $("overlay").classList.add("hidden");
  }
}

function setCurrent(meta) {
  current = meta;
  view = "sprite";
  panelPinned = null;
  $("viewerEmpty").classList.add("hidden");
  $("bigImg").classList.remove("hidden");
  $("viewerBar").classList.remove("hidden");
  $("sidePanel").classList.remove("hidden");
  render();
}

function clearViewer() {
  current = null;
  $("bigImg").classList.add("hidden");
  $("viewerBar").classList.add("hidden");
  $("sidePanel").classList.add("hidden");
  $("viewerEmpty").classList.remove("hidden");
}

function engineLabel(id) {
  const e = ENGINES.find((x) => x.id === id);
  // nombre completo del motor sin la coletilla descriptiva ("FLUX.2 Klein 4B")
  return e ? e.label.split("·")[0].trim() : id;
}

function panelCollapsed() {
  if (panelPinned !== null) return panelPinned;
  // en el sprite sheet (formato apaisado) el ancho manda: plegado automático
  return !!current && (current.kind || "sprite") === "animation" && view === "raw";
}

function renderPanel() {
  const m = current;
  const chips = [
    `<span class="chip chip-click" id="chipSeed" title="Clic: copia la semilla y la deja en el formulario">semilla <b>${m.seed}</b> ${ICON("i-copy", "ic ic-xs")}</span>`,
  ];
  if (m.native) chips.push(`<span class="chip"><b>${m.native}</b> px</span>`);
  if (m.colors) chips.push(`<span class="chip"><b>${m.colors}</b> colores</span>`);
  if (m.kind === "animation" && m.frames) chips.push(`<span class="chip"><b>${m.frames}</b> frames</span>`);
  if (m.kind === "terrain" && m.variants) chips.push(`<span class="chip"><b>${m.variants}</b> variantes</span>`);
  if (m.used_palette) chips.push(`<span class="chip">paleta global</span>`);
  if (m.engine) chips.push(`<span class="chip">${engineLabel(m.engine)}</span>`);
  $("metaChips").innerHTML = chips.join("");
  $("chipSeed").onclick = async () => {
    try { await navigator.clipboard.writeText(String(m.seed)); } catch { /* http sin permiso */ }
    $("seed").value = m.seed;
  };
  $("promptBox").textContent = m.subject || "";
}

async function deleteItem(m) {
  const what = m.kind === "animation"
    ? `la animación «${m.subject}» (GIF, sprite sheet y sus ${m.frames} frames)`
    : `el sprite «${m.subject}»`;
  if (!confirm(`¿Eliminar ${what}?\n\nSe borrarán definitivamente sus archivos del disco.`)) return;
  try {
    await api(`/api/history/${encodeURIComponent(m.id)}`, { method: "DELETE" });
    if (current && current.id === m.id) clearViewer();
    await loadHistory();
  } catch (e) {
    alert(e.message);
  }
}

const TAB_LABELS = {
  sprite: ["Sprite", "Original IA"],
  animation: ["GIF", "Sprite sheet"],
  terrain: ["Variantes", "Textura IA"],
  tileset: ["Mapa de prueba", "Tileset"],
};

function render() {
  if (!current) return;
  const kind = current.kind || "sprite";
  const labels = TAB_LABELS[kind] || TAB_LABELS.sprite;
  const src = view === "video" ? current.video_url
    : view === "raw" ? current.raw_url : current.sprite_url;
  $("bigImg").src = src + "?t=" + Date.now();
  // En el video libre el GIF principal es el clip del modelo, no un preview
  $("tabSprite").textContent = current.raw_video ? "Video" : labels[0];
  $("tabRaw").textContent = labels[1];
  $("tabVideo").classList.toggle("hidden", !current.video_url);
  $("tabSprite").classList.toggle("active", view === "sprite");
  $("tabRaw").classList.toggle("active", view === "raw");
  $("tabVideo").classList.toggle("active", view === "video");
  const collapsed = panelCollapsed();
  $("sidePanel").classList.toggle("collapsed", collapsed);
  $("btnPanelIcon").setAttribute("href", collapsed ? "#i-expand" : "#i-collapse");
  $("btnMakePalette").style.display =
    (kind === "sprite" || kind === "terrain") ? "" : "none";
  $("btnUnshadow").style.display = kind === "sprite" ? "" : "none";
  $("btnFav").innerHTML = `${ICON(current.favorite ? "i-star-f" : "i-star")} Favorito`;
  $("btnFav").classList.toggle("faved", !!current.favorite);
  $("btnHide").innerHTML = current.hidden
    ? `${ICON("i-eye")} Volver a mostrar`
    : `${ICON("i-eye-off")} Ocultar`;
  $("btnHide").classList.toggle("hidden-on", !!current.hidden);
  updateAnimButton();
  renderPanel();
  document.querySelectorAll(".thumb").forEach((t) =>
    t.classList.toggle("active", t.dataset.id === current.id));
}

/* ---------- Terreno y tilesets ---------- */

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
  if (!subject) { alert("Describe la textura del terreno (ej: dense green grass)."); return; }
  $("overlayMsg").textContent = "Generando terreno… (~1 minuto, más si el motor estaba apagado)";
  $("overlay").classList.remove("hidden");
  try {
    const meta = await api("/api/terrain", { method: "POST", body: JSON.stringify({ subject }) });
    setCurrent(meta);
    await loadHistory();
    refreshStatus();
  } catch (e) { alert(e.message); }
  finally { $("overlay").classList.add("hidden"); }
}

async function runTileset() {
  const a = $("terrA").value, b = $("terrB").value;
  if (!a || !b) { alert("Genera al menos dos terrenos primero."); return; }
  if (a === b) { alert("Elige dos terrenos distintos."); return; }
  $("overlayMsg").textContent = "Creando transiciones y tileset…";
  $("overlay").classList.remove("hidden");
  try {
    const meta = await api("/api/tileset", { method: "POST", body: JSON.stringify({ terrain_a: a, terrain_b: b }) });
    setCurrent(meta);
    await loadHistory();
  } catch (e) { alert(e.message); }
  finally { $("overlay").classList.add("hidden"); }
}

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

/* Un clip de video libre en el visor se puede CONTINUAR: el nuevo tramo
   arranca de su último frame y el resultado es la unión de los dos. */
function chainableClip() {
  return current && current.kind === "animation" && current.raw_video ? current : null;
}

/* El botón del panel de animación pasa a «Continuar clip» cuando el visor
   tiene un clip encadenable y el método es video. */
function updateAnimButton() {
  const cadena = $("animMethod").value === "video" ? chainableClip() : null;
  $("btnAnimate").innerHTML =
    ICON("i-video") + (cadena ? " Continuar clip" : " Generar animación");
  // La cola solo tiene sentido en el método de video
  $("btnQueue").classList.toggle("hidden", $("animMethod").value !== "video");
  $("chainNote").classList.toggle("hidden", !cadena);
  if (cadena) {
    const n = cadena.segments?.length || 1;
    const seg = (cadena.frames / (cadena.fps || 16)).toFixed(1).replace(".", ",");
    $("chainNote").textContent =
      `Continuará el clip del visor (${n} tramo${n > 1 ? "s" : ""}, ${seg} s) desde su `
      + "último frame, a su misma resolución. Se creará una entrada nueva en el "
      + "historial; el clip actual no se toca.";
  }
}

async function animateVideo() {
  const cadena = chainableClip();
  if (!cadena && (!current || (current.kind || "sprite") !== "sprite")) {
    alert("El método de video parte del sprite del visor: genera o selecciona uno primero.");
    return;
  }
  const motion = $("videoMotion").value.trim();
  if (!motion) { alert("Describe el movimiento (ej. walk cycle)."); return; }
  let engine = currentVideoEngine();
  if (cadena && !engine?.params.raw_output) {
    // Encadenar exige un motor libre: los que pixelizan no producen frames
    // continuables. Se conmuta solo en vez de fallar.
    const libre = ENGINES.find((e) => e.kind === "video" && e.params.raw_output && e.installed);
    if (!libre) { alert("Para continuar un clip necesitas un motor de video libre instalado."); return; }
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
  $("overlayMsg").textContent = cadena
    ? `Generando el tramo ${tramo} y uniéndolo al clip… (varios minutos en la GPU)`
    : `Generando video con ${engine ? engine.label : "Wan 2.2"}… (varios minutos en la GPU)`;
  $("overlay").classList.remove("hidden");
  try {
    const meta = await api("/api/animate_video", { method: "POST", body: JSON.stringify(body) });
    setCurrent(meta);
    await loadHistory();
    refreshStatus();
  } catch (e) {
    alert(e.message);
  } finally {
    $("overlay").classList.add("hidden");
  }
}

/* ---------- Cola de clips encadenados ---------- */

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
    ? "qué ocurre en el primer clip..."
    : "y después, en este clip...";
  ta.value = valor;
  ta.oninput = queueRefreshSummary;
  const quitar = document.createElement("button");
  quitar.className = "btn-icon";
  quitar.title = "Quitar este clip";
  quitar.textContent = "✕";
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
  // 6:51 medidos para 81 frames a 768x768; se escala por frames como estimación
  const min = Math.round((n * 411 * (frames / 81)) / 60);
  $("queueSummary").textContent = n
    ? `${n} clip${n > 1 ? "s" : ""} · ${seg.toFixed(1)} s de video final · ~${min} min de GPU`
    : "Añade al menos un prompt.";
}

function openQueue() {
  const base = current;
  if (!base) { alert("Selecciona antes una imagen o un clip en el visor."); return; }
  const esClip = !!(base.kind === "animation" && base.raw_video);
  $("queueBase").textContent = esClip
    ? `Continuará el clip del visor (${base.frames} frames) y encadenará los nuevos a partir de él.`
    : `Arrancará de la imagen del visor y encadenará los clips uno tras otro.`;
  // El selector de motor y el de duración replican los del panel de animación
  fillEngineSelect($("queueEngine"), ENGINES.filter((e) => e.kind === "video"),
                   esClip ? "wan22_14b_free" : $("videoEngine").value);
  $("queueLength").innerHTML = $("videoLength").innerHTML;
  $("queueLength").value = $("videoLength").value;
  if (!queueRows().length) queueAddRow();
  queueRefreshSummary();
  $("queueModal").classList.remove("hidden");
}

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
    $("queueModal").classList.add("hidden");
    pollQueue();
  } catch (e) { alert(e.message); }
}

/* Sondea el estado de la cola y refresca el historial conforme salen clips */
async function pollQueue() {
  clearInterval(queueTimer);
  let vistos = 0;
  const tick = async () => {
    let s;
    try { s = await api("/api/batch"); } catch { return; }
    if (s.running) {
      $("overlayMsg").textContent =
        `Cola: clip ${s.current} de ${s.total} — «${(s.prompt || "").slice(0, 60)}»`;
      $("overlay").classList.remove("hidden");
      $("btnQueueStop").classList.remove("hidden");
      if (s.done.length > vistos) { vistos = s.done.length; loadHistory(); }
      return;
    }
    clearInterval(queueTimer);
    queueTimer = null;
    $("overlay").classList.add("hidden");
    $("btnQueueStop").classList.add("hidden");
    await loadHistory();
    refreshStatus();
    if (s.error) alert(`La cola se detuvo: ${s.error}`);
    else if (s.last_id) {
      try {
        const m = await api(`/api/history`).then((h) => h.find((x) => x.id === s.last_id));
        if (m) setCurrent(m);  // puede faltar si el clip nació oculto
      } catch { /* el historial ya está refrescado */ }
    }
  };
  await tick();
  if (!queueTimer) queueTimer = setInterval(tick, 4000);
}

async function runVariation() {
  if (!current || (current.kind || "sprite") !== "sprite") {
    alert("Selecciona primero un sprite en el visor.");
    return;
  }
  const instruction = $("varInstruction").value.trim();
  if (!instruction) { alert("Escribe la instrucción de la variación."); return; }
  $("overlayMsg").textContent = "Generando variación con Klein…";
  $("overlay").classList.remove("hidden");
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
  } catch (e) {
    alert(e.message);
  } finally {
    $("overlay").classList.add("hidden");
  }
}

async function animate() {
  if ($("animMethod").value === "video") {
    return animateVideo();
  }
  const subject = $("subject").value.trim();
  if (!subject) { alert("Escribe primero la descripción del personaje."); return; }
  const useBase = $("animUseBase").checked;
  if (useBase && (!current || current.kind === "animation")) {
    alert("Para partir de un sprite, genera o selecciona antes un sprite normal en el visor.");
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
  $("overlayMsg").textContent = "Preparando animación…";
  $("overlay").classList.remove("hidden");
  const poll = setInterval(async () => {
    try {
      const s = await api("/api/status");
      if (s.progress?.total) {
        const done = Math.min(s.progress.current + 1, s.progress.total);
        $("overlayMsg").textContent = `Generando frame ${done} de ${s.progress.total}… (~1 min por frame)`;
      }
    } catch { /* transitorio */ }
  }, 3000);
  try {
    const meta = await api("/api/animate", { method: "POST", body: JSON.stringify(body) });
    setCurrent(meta);
    await loadHistory();
    refreshStatus();
  } catch (e) {
    alert(e.message);
  } finally {
    clearInterval(poll);
    $("overlay").classList.add("hidden");
  }
}

/* ---------- Historial ---------- */

async function loadHistory() {
  const items = await api("/api/history");
  const favs = items.filter((m) => m.favorite).length;
  $("favCount").innerHTML = favs ? `· ${ICON("i-star-f", "ic ic-xs ic-gold")} ${favs}` : "";
  const box = $("history");
  box.innerHTML = "";
  for (const m of items) {
    if (!m.sprite_url) continue;
    const div = document.createElement("div");
    // Los ocultos solo llegan aquí con el interruptor activo: se atenúan para
    // no confundirlos con los normales
    div.className = m.hidden ? "thumb thumb-hidden" : "thumb";
    div.dataset.id = m.id;
    div.title = `${m.subject}\nsemilla ${m.seed}`;
    const img = document.createElement("img");
    img.loading = "lazy";
    img.src = m.sprite_url;
    div.appendChild(img);
    if (m.favorite) {
      const star = document.createElement("span");
      star.className = "thumb-fav";
      star.innerHTML = ICON("i-star-f", "ic ic-xs ic-gold");
      div.appendChild(star);
    }
    div.onclick = () => { $("subject").value = m.subject; setCurrent(m); };
    const del = document.createElement("button");
    del.className = "thumb-del";
    del.textContent = "×";
    del.title = "Eliminar (borra los archivos del disco)";
    del.onclick = (ev) => { ev.stopPropagation(); deleteItem(m); };
    div.appendChild(del);
    const eye = document.createElement("button");
    eye.className = "thumb-hide";
    eye.innerHTML = ICON(m.hidden ? "i-eye-off" : "i-eye", "ic ic-xs");
    eye.title = m.hidden
      ? "Volver a mostrar"
      : "Ocultar (desaparece del historial y del Explorador)";
    eye.onclick = (ev) => { ev.stopPropagation(); toggleHide(m); };
    div.appendChild(eye);
    box.appendChild(div);
  }
  // Lo que ya no está en la lista (recién ocultado o borrado) sale del visor:
  // «que no se visualice de ninguna manera» incluye la imagen grande
  if (current && !items.some((m) => m.id === current.id)) clearViewer();
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

/* ---------- Efectos ambientales ---------- */

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
      alert("Selecciona antes un sprite (árbol, arbusto...) en el visor.");
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
  $("overlayMsg").textContent = "Generando efecto…";
  $("overlay").classList.remove("hidden");
  try {
    const meta = await api("/api/effect", { method: "POST", body: JSON.stringify(body) });
    setCurrent(meta);
    await loadHistory();
  } catch (e) {
    alert(e.message);
  } finally {
    $("overlay").classList.add("hidden");
  }
}

/* ---------- Estilo global ---------- */

async function loadConfig() {
  const cfg = await api("/api/config");
  $("tpl").value = cfg.prompt_template;
  $("neg").value = cfg.negative_prompt;
  $("loraStrength").value = cfg.lora_strength;
  $("bgThreshold").value = cfg.bg_removal_threshold;
  $("removeShadow").checked = cfg.remove_shadow !== false;
  // steps/cfg del formulario los gobierna el motor seleccionado, no el estilo
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
    alert("Estilo global guardado. Se aplicará a todos los sprites nuevos.");
  } catch (e) { alert(e.message); }
}

/* ---------- Paleta global ---------- */

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
  if (!confirm("¿Fijar los colores de este sprite como paleta global de todas tus generaciones?")) return;
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

/* ---------- Estado del motor ---------- */

async function refreshStatus() {
  try {
    const s = await api("/api/status");
    $("engineDot").className = "dot " + (s.engine_on ? "on" : "off");
    $("engineText").textContent = "Motor IA: " + (s.engine_on ? "encendido" : "apagado");
    $("btnEngineOff").style.visibility = s.engine_on ? "visible" : "hidden";
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
  btn.innerHTML = `${ICON(s.reveal_hidden ? "i-eye" : "i-eye-off", "ic ic-xs")} ` +
    `${s.reveal_hidden ? "Ocultos a la vista" : "Ver ocultos"} (${s.hidden_count})`;
  btn.classList.toggle("on", !!s.reveal_hidden);
  // Si lo cambiaron por fuera (otra pestaña), el historial se pone al día
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

/* ---------- Eventos ---------- */

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
$("queueClose").onclick = () => $("queueModal").classList.add("hidden");
$("queueCancelBtn").onclick = () => $("queueModal").classList.add("hidden");
$("queueRun").onclick = runQueue;
$("queueLength").onchange = queueRefreshSummary;
$("queueEngine").onchange = queueRefreshSummary;
$("btnQueueStop").onclick = async () => {
  if (!confirm("¿Detener la cola cuando acabe el clip actual?")) return;
  try { await api("/api/batch/cancel", { method: "POST" }); } catch (e) { alert(e.message); }
};
// Si el servidor tenía una cola en marcha (p. ej. cerraste el navegador), se retoma
pollQueue();
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
$("tabVideo").onclick = () => { if (current?.video_url) { view = "video"; render(); } };
$("btnSaveStyle").onclick = saveStyle;
$("btnMakePalette").onclick = makePalette;
$("btnDelete").onclick = () => { if (current) deleteItem(current); };
$("btnUnshadow").onclick = async () => {
  if (!current || (current.kind || "sprite") !== "sprite") return;
  $("overlayMsg").textContent = "Quitando la sombra (se crea una copia, el original no se toca)…";
  $("overlay").classList.remove("hidden");
  try {
    const meta = await api("/api/unshadow", { method: "POST", body: JSON.stringify({ id: current.id }) });
    setCurrent(meta);
    await loadHistory();
  } catch (e) {
    alert(e.message);
  } finally {
    $("overlay").classList.add("hidden");
  }
};
$("btnFav").onclick = async () => {
  if (!current) return;
  try {
    const meta = await api("/api/favorite", {
      method: "POST",
      body: JSON.stringify({ id: current.id }),
    });
    current = meta;   // conserva la pestaña activa del visor (no se resetea)
    render();
    await loadHistory();
  } catch (e) { alert(e.message); }
};
$("btnHide").onclick = () => { if (current) toggleHide(current); };
$("btnReveal").onclick = toggleReveal;
$("btnPanel").onclick = () => { panelPinned = !panelCollapsed(); render(); };
$("btnEngineOff").onclick = engineOff;
$("subject").addEventListener("input", () =>
  localStorage.setItem("spritegen.subject", $("subject").value));

/* ---------- Init ---------- */

$("subject").value = localStorage.getItem("spritegen.subject") || "";
loadConfig();
loadEngines();
loadHistory();
refreshStatus();
setInterval(() => { refreshStatus(); loadEngines(); }, 15000);
