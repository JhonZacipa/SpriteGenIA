/* SpriteGen · visor 3D del vidrio
   Módulo ES que app.js carga solo al abrir una pieza 3D: así la mesa no paga
   el arranque de Three.js (r186, copiado en vendor/three/ para que funcione
   sin internet) hasta que hace falta.

   El lienzo es transparente: detrás se sigue viendo el vidrio, con su
   cuadrícula y su interruptor de luz. Cámara ORTOGRÁFICA, como la de un
   sprite prerenderizado; la luz principal viaja pegada a la cámara, así que
   al orbitar el modelo siempre se ve iluminado desde arriba a la izquierda,
   y el giro automático rota el MODELO (como en un horneado de direcciones),
   no la cámara.

   El mismo módulo HORNEA los sprites (`hornear`): renderiza cada dirección
   con los mismos materiales, luz y vista que se ven en el vidrio, así que lo
   que se encuadra es exactamente lo que sale. */

import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
// Las versiones web (gltf-transform) comprimen la geometría con meshopt
import { MeshoptDecoder } from "three/addons/libs/meshopt_decoder.module.js";

/* Elevación y acimut en grados. `diagonal`: la cámara mira en diagonal a la
   rejilla, así que un tile se ve como un rombo (la escala por tiles cuenta
   su ancho, que es la diagonal del cuadrado). 30° es la isometría 2:1 del
   pixel art (sen 30° = 1/2); 35,26° la isometría verdadera. */
const VISTAS = {
  iso: { elev: 30, azim: 45, diagonal: true },
  iso_real: { elev: 35.264, azim: 45, diagonal: true },
  tres_cuartos: { elev: 45, azim: 0, diagonal: false },
  cenital: { elev: 60, azim: 0, diagonal: false },
  frente: { elev: 0, azim: 0, diagonal: false },
};

/* La luz principal va en coordenadas de la CÁMARA (x a la derecha, y arriba,
   z hacia el espectador): arriba a la izquierda, como en un sprite. El
   entorno de estudio rellena las sombras. */
const LUCES = {
  dia: { color: 0xffffff, intensidad: 1.7, pos: [-2, 3, 2], entorno: 0.9 },
  atardecer: { color: 0xffa062, intensidad: 2.3, pos: [-3, 1, 1.5], entorno: 0.45 },
  noche: { color: 0x9db4ff, intensidad: 0.9, pos: [-1, 3, 1.5], entorno: 0.22 },
};

const st = {
  host: null, renderer: null, scene: null, camera: null, controls: null, luzObj: null,
  model: null, url: null, cargando: null, radius: 0.9, verts: null, vista: "iso", luz: "dia",
  yaw: 0, giro: 0, girando: false, activo: false, turno: 0,
};

const rad = THREE.MathUtils.degToRad;

function entornoPara(renderer) {
  // Entorno neutro de estudio: los materiales PBR de TRELLIS (metal/rugosidad)
  // salen negros si no tienen nada que reflejar
  const pmrem = new THREE.PMREMGenerator(renderer);
  const tex = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
  pmrem.dispose();
  return tex;
}

function aplicarLuz(luz, scene, nombre) {
  const p = LUCES[nombre] || LUCES.dia;
  luz.color.setHex(p.color);
  luz.intensity = p.intensidad;
  luz.position.set(...p.pos);
  scene.environmentIntensity = p.entorno;
}

function iniciar(host) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setClearColor(0x000000, 0);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.NeutralToneMapping;

  const scene = new THREE.Scene();
  scene.environment = entornoPara(renderer);
  const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.01, 100);
  const luzObj = new THREE.DirectionalLight(0xffffff, 1.7);
  camera.add(luzObj);
  scene.add(camera);
  aplicarLuz(luzObj, scene, st.luz);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.12;
  controls.minZoom = 0.25;
  controls.maxZoom = 12;

  Object.assign(st, { host, renderer, scene, camera, controls, luzObj });
  host.appendChild(renderer.domElement);
  new ResizeObserver(ajustar).observe(host);
  ajustar();
}

/* El encuadre sale del radio real del modelo, nunca de la caja de cada vista:
   así el objeto mide lo mismo desde cualquier ángulo. */
function ajustar() {
  const { host, renderer, camera } = st;
  const w = Math.max(1, host.clientWidth), h = Math.max(1, host.clientHeight);
  renderer.setSize(w, h);
  const medio = st.radius * 1.05;
  const aspecto = w / h;
  camera.left = -medio * Math.max(aspecto, 1);
  camera.right = medio * Math.max(aspecto, 1);
  camera.top = medio / Math.min(aspecto, 1);
  camera.bottom = -medio / Math.min(aspecto, 1);
  camera.updateProjectionMatrix();
}

function bucle() {
  if (!st.activo) return;
  requestAnimationFrame(bucle);
  if (st.girando) st.giro += 0.008;
  if (st.model) st.model.rotation.y = rad(st.yaw) + st.giro;
  st.controls.update();
  st.renderer.render(st.scene, st.camera);
}

function liberar(obj) {
  obj.traverse((o) => {
    if (!o.isMesh) return;
    o.geometry?.dispose();
    for (const m of [].concat(o.material || [])) {
      for (const v of Object.values(m)) if (v?.isTexture) v.dispose();
      m.dispose();
    }
  });
}

async function cargar(url) {
  const turno = ++st.turno;
  st.url = url;
  let gltf;
  try {
    gltf = await new GLTFLoader().setMeshoptDecoder(MeshoptDecoder).loadAsync(url);
  } catch (e) {
    if (turno === st.turno) st.url = null;   // que el siguiente intento lo recargue
    throw e;
  }
  if (turno !== st.turno) { liberar(gltf.scene); return; }   // llegó otro modelo antes
  if (st.model) { st.scene.remove(st.model); liberar(st.model); }
  const modelo = gltf.scene;
  modelo.updateMatrixWorld(true);
  const centro = new THREE.Box3().setFromObject(modelo).getCenter(new THREE.Vector3());
  // Vértices centrados (en el marco del pivote): de ellos salen el radio real
  // —el vértice más alejado, no la esfera de la caja, que sobra mucho—, la
  // huella en planta y la proyección exacta de cada dirección del horneado
  let total = 0;
  modelo.traverse((o) => { if (o.isMesh) total += o.geometry.attributes.position.count; });
  const paso = Math.max(1, Math.ceil(total / 400000));   // basta una muestra densa
  const verts = new Float32Array(Math.ceil(total / paso) * 3 + 3);
  let n = 0, r2 = 0;
  const p = new THREE.Vector3();
  modelo.traverse((o) => {
    if (!o.isMesh) return;
    const pos = o.geometry.attributes.position;
    for (let i = 0; i < pos.count; i += paso) {
      p.fromBufferAttribute(pos, i).applyMatrix4(o.matrixWorld).sub(centro);
      verts[n++] = p.x; verts[n++] = p.y; verts[n++] = p.z;
      r2 = Math.max(r2, p.lengthSq());
    }
  });
  modelo.position.sub(centro);
  // Pivote en el centro: el giro y la orientación rotan el objeto sobre sí mismo
  const pivote = new THREE.Group();
  pivote.add(modelo);
  st.scene.add(pivote);
  st.model = pivote;
  st.verts = verts.subarray(0, n);
  st.radius = Math.sqrt(r2) || 0.9;
  ajustar();
  vista(st.vista);
}

/* Base de la cámara de una vista: derecha, arriba y posición del ojo, con la
   misma convención que Camera.lookAt para que la proyección cuadre al píxel */
function baseDe(nombre) {
  const v = VISTAS[nombre] || VISTAS.iso;
  const e = rad(v.elev), a = rad(v.azim);
  const ojo = new THREE.Vector3(Math.cos(e) * Math.sin(a), Math.sin(e), Math.cos(e) * Math.cos(a))
    .multiplyScalar(10);
  const cam = new THREE.OrthographicCamera();
  cam.position.copy(ojo);
  cam.lookAt(0, 0, 0);
  cam.updateMatrixWorld(true);
  const der = new THREE.Vector3(), arr = new THREE.Vector3(), z = new THREE.Vector3();
  cam.matrixWorld.extractBasis(der, arr, z);
  return { ojo, der, arr };
}

/* Caja en pantalla (unidades de mundo) que contiene el modelo en TODAS las
   direcciones: con un solo encuadre para todas, el origen del modelo cae en
   el mismo píxel de cada sprite y el objeto no cambia de tamaño al girar. */
function proyectar(nombre, direcciones, yaw) {
  const { der, arr } = baseDe(nombre);
  const caja = { xmin: Infinity, xmax: -Infinity, ymin: Infinity, ymax: -Infinity };
  const vs = st.verts;
  for (let d = 0; d < direcciones; d++) {
    const t = rad(yaw + (d * 360) / direcciones);
    const c = Math.cos(t), s = Math.sin(t);
    // Rotación sobre Y igual que Object3D.rotation.y
    const rx = [c * der.x - s * der.z, der.y, s * der.x + c * der.z];
    const ux = [c * arr.x - s * arr.z, arr.y, s * arr.x + c * arr.z];
    for (let i = 0; i < vs.length; i += 3) {
      const x = vs[i] * rx[0] + vs[i + 1] * rx[1] + vs[i + 2] * rx[2];
      const y = vs[i] * ux[0] + vs[i + 1] * ux[1] + vs[i + 2] * ux[2];
      if (x < caja.xmin) caja.xmin = x;
      if (x > caja.xmax) caja.xmax = x;
      if (y < caja.ymin) caja.ymin = y;
      if (y > caja.ymax) caja.ymax = y;
    }
  }
  return caja;
}

/* Muestra el modelo de `url` en `host`. Lanza si el GLB no se puede leer. */
export async function mostrar(host, url) {
  if (!st.renderer) iniciar(host);
  else if (st.host !== host) { host.appendChild(st.renderer.domElement); st.host = host; }
  if (!st.activo) { st.activo = true; bucle(); }
  // Siempre se espera a la carga EN CURSO: si dos llamadas piden el mismo
  // modelo, la segunda no debe volver antes de que esté listo (el horneado
  // pintaría el modelo anterior)
  if (url !== st.url) st.cargando = cargar(url);
  await st.cargando;
}

/* Para el bucle de pintado mientras el vidrio enseña otra cosa */
export function ocultar() {
  st.activo = false;
}

/* Coloca la cámara en una vista fija; con "girar", alterna el giro del modelo.
   Devuelve si el modelo está girando. */
export function vista(nombre) {
  if (nombre === "girar") {
    st.girando = !st.girando;
    return st.girando;
  }
  st.vista = nombre in VISTAS ? nombre : "iso";
  st.giro = 0;
  if (!st.camera) return st.girando;   // aún sin iniciar: se aplica al cargar
  st.camera.position.copy(baseDe(st.vista).ojo);
  st.camera.zoom = 1;
  st.camera.updateProjectionMatrix();
  st.controls.target.set(0, 0, 0);
  st.controls.update();
  return st.girando;
}

export function vistaActual() {
  return st.vista;
}

export function esDiagonal(nombre) {
  return !!(VISTAS[nombre] || VISTAS.iso).diagonal;
}

/* Orientación del modelo en pasos de 90°: TRELLIS no garantiza qué cara
   queda de frente, así que el usuario la elige y el horneado la respeta */
export function orientar(grados) {
  st.yaw = ((Math.round(grados / 90) * 90) % 360 + 360) % 360;
  st.giro = 0;
  return st.yaw;
}

export function luz(nombre) {
  st.luz = nombre in LUCES ? nombre : "dia";
  if (st.luzObj) aplicarLuz(st.luzObj, st.scene, st.luz);
}

/* Lado mayor de la planta del modelo (unidades de mundo). No cambia al
   girarlo 90°: el ancho y el fondo solo se intercambian. */
export function huella() {
  if (!st.verts) return null;
  const vs = st.verts;
  let x0 = Infinity, x1 = -Infinity, z0 = Infinity, z1 = -Infinity;
  for (let i = 0; i < vs.length; i += 3) {
    if (vs[i] < x0) x0 = vs[i];
    if (vs[i] > x1) x1 = vs[i];
    if (vs[i + 2] < z0) z0 = vs[i + 2];
    if (vs[i + 2] > z1) z1 = vs[i + 2];
  }
  return Math.max(x1 - x0, z1 - z0);
}

/* Tamaño en píxeles nativos de cada sprite para `ppu` (píxeles por unidad) */
export function estimar({ vista: nombre, direcciones, ppu }) {
  if (!st.verts) return null;
  const c = proyectar(nombre, direcciones, st.yaw);
  return { w: Math.ceil((c.xmax - c.xmin) * ppu) + 2, h: Math.ceil((c.ymax - c.ymin) * ppu) + 2 };
}

/* Escala y tamaño de un horneado. Por tiles: la planta del objeto ocupa
   `tiles` tiles de `tilePx` píxeles; en las vistas diagonales un tile es un
   rombo cuyo ancho es la diagonal del cuadrado (de ahí el √2). Por rejilla: el
   lado mayor mide `rejilla`, incluido el píxel de aire de cada lado.
   Devuelve { ppu, w, h, ss } o null si aún no hay modelo. La GUI y la página
   de horneado de la CLI usan esta MISMA función. */
export function planHorneado({ vista: nombre, direcciones, modo = "tiles", tiles = 2,
                               tilePx = 64, rejilla = 192 }) {
  if (!st.verts) return null;
  let ppu;
  if (modo === "rejilla") {
    const e = estimar({ vista: nombre, direcciones, ppu: 100 });
    ppu = (100 * (rejilla - 2)) / Math.max(e.w - 2, e.h - 2);
  } else {
    const porTile = huella() / Math.max(0.5, Number(tiles) || 1);
    ppu = Math.max(8, Number(tilePx) || 64) / (porTile * (esDiagonal(nombre) ? Math.SQRT2 : 1));
  }
  const { w, h } = estimar({ vista: nombre, direcciones, ppu });
  // Supermuestreo: 4× la rejilla, o lo que quepa en 4096 px
  const ss = Math.max(1, Math.min(4, Math.floor(4096 / Math.max(w, h))));
  return { ppu, w, h, ss };
}

/* El horneado completo de una pieza `model3d` ya cargada en el visor: aplica
   su orientación y la luz, pinta las direcciones y las manda al servidor para
   pixelizarlas. Devuelve la ficha creada. `ajustes` = { vista, direcciones,
   modo, tiles, tilePx, rejilla, luz, colores, escala, paleta }. */
export async function hornearPieza(pieza, ajustes, alAvanzar = () => {}) {
  if (st.url !== pieza.model_url || !st.verts) {
    throw new Error("El modelo no está cargado en el visor");
  }
  orientar(pieza.yaw || 0);
  luz(ajustes.luz);
  const plan = planHorneado(ajustes);
  if (Math.max(plan.w, plan.h) > 1024) {
    throw new Error(`Cada sprite saldría de ${plan.w} × ${plan.h} px: reduce los tiles `
      + "o la rejilla (máximo 1024)");
  }
  const { frames } = await hornear({
    vista: ajustes.vista, direcciones: ajustes.direcciones, ppu: plan.ppu, ss: plan.ss,
  });
  alAvanzar("pixelizando");
  const porTiles = (ajustes.modo || "tiles") === "tiles";
  const res = await fetch("/api/model3d/sprites", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      model_id: pieza.id, frames, ss: plan.ss, ppu: plan.ppu,
      colors: ajustes.colores, scale: ajustes.escala, use_palette: !!ajustes.paleta,
      view: ajustes.vista, yaw: st.yaw, light: st.luz,
      scale_mode: porTiles ? "tiles" : "rejilla",
      tiles: porTiles ? Number(ajustes.tiles) : null,
      tile_px: porTiles ? Number(ajustes.tilePx) : null,
    }),
  });
  const datos = await res.json().catch(() => ({}));
  if (!res.ok) {
    const d = datos.detail;
    throw new Error(Array.isArray(d) ? d.map((x) => x.msg || JSON.stringify(x)).join("; ")
      : d || `Error ${res.status}`);
  }
  return datos;
}

/* Renderiza las direcciones del horneado y devuelve sus PNG (data URL), todos
   del mismo tamaño y con el mismo encuadre. `ss` es el supermuestreo: se
   pinta a ss× la rejilla y el servidor lo reduce al pixelizar. */
export async function hornear({ vista: nombre, direcciones, ppu, ss = 4 }) {
  if (!st.model) throw new Error("No hay ningún modelo cargado en el visor");
  const caja = proyectar(nombre, direcciones, st.yaw);
  // Lienzo en múltiplos enteros de ss, con un píxel nativo de aire por lado
  const w = Math.ceil((caja.xmax - caja.xmin) * ppu + 2) * ss;
  const h = Math.ceil((caja.ymax - caja.ymin) * ppu + 2) * ss;
  const max = 4096;
  if (w > max || h > max) {
    throw new Error(`El sprite saldría de ${Math.round(w / ss)}×${Math.round(h / ss)} px: `
      + "reduce los tiles o la rejilla");
  }

  // Renderizador propio, con su entorno y su luz: las texturas de entorno
  // pertenecen al contexto WebGL que las creó y no se pueden compartir
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
  try {
    renderer.setPixelRatio(1);
    renderer.setSize(w, h, false);
    renderer.setClearColor(0x000000, 0);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.NeutralToneMapping;
    const scene = new THREE.Scene();
    scene.environment = entornoPara(renderer);
    const { ojo } = baseDe(nombre);
    const cx = (caja.xmin + caja.xmax) / 2, cy = (caja.ymin + caja.ymax) / 2;
    const mw = (w / ss) / ppu / 2, mh = (h / ss) / ppu / 2;   // medio encuadre con el aire
    const cam = new THREE.OrthographicCamera(cx - mw, cx + mw, cy + mh, cy - mh, 0.01, 100);
    cam.position.copy(ojo);
    cam.lookAt(0, 0, 0);
    const luzObj = new THREE.DirectionalLight();
    cam.add(luzObj);
    scene.add(cam);
    aplicarLuz(luzObj, scene, st.luz);
    // Clon superficial: comparte geometría y materiales con el del visor
    const modelo = st.model.clone();
    scene.add(modelo);

    const frames = [];
    for (let d = 0; d < direcciones; d++) {
      modelo.rotation.y = rad(st.yaw + (d * 360) / direcciones);
      renderer.render(scene, cam);
      frames.push(renderer.domElement.toDataURL("image/png"));
      await new Promise((r) => setTimeout(r, 0));   // no congela la página
    }
    scene.environment.dispose();
    return { frames, w, h };
  } finally {
    renderer.dispose();
    renderer.forceContextLoss();
  }
}
