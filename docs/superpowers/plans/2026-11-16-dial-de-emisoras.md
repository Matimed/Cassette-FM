# El dial de emisoras — plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Logos por emisora (campo `icono`), el volumen que prende en 50 y un dial horizontal estilo GTA 4 en el
applet que se abre con Super+Alt+Espacio.

**Architecture:** La radio expone los logos en `/estado` (`iconos`, rutas absolutas de los que existen); la CLI los
copia a `~/.config/cassette-fm/iconos/`; el applet dibuja el dial con St/Clutter sobre `Main.uiGroup`, toma el
teclado con `Main.pushModal` y habla con la API como hoy. Lo puro del dial va en `logic.js`.

**Tech Stack:** Python 3 (pytest), GJS de Cinnamon 6.4, Node (`node --test`); el recorte de imágenes, una sola vez,
con el Python del sistema (numpy + GdkPixbuf), fuera del repo.

**Spec:** `docs/superpowers/specs/2026-11-16-dial-de-emisoras-design.md`

## Global Constraints

- Español rioplatense; commits en español con `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` y rutas
  explícitas. Tests sin tocar la config real.
- `VOLUMEN_MINIMO = 50`; subir el volumen desde 0 sigue dando lo que suma la tecla.
- Logos del usuario: config (`~/.config/cassette-fm/iconos/`), nunca en el repo. El genérico sí:
  `applet/cassette-fm@cassette-fm/generico.png`.
- Atajo por defecto `<Super><Alt>space`; ◀ ▶ emisora, ▲ ▼ volumen de a 5, Escape o el mismo atajo cierran, cierre
  solo a los 5 s sin tocar nada; actual ≈160 px, las demás ≈96 px; 3 a cada lado con más de 7.
- `applet.js`: nada sincrónico, sin `JSON.parse`; `ReloadXlet` no recarga `logic.js` (reiniciar Cinnamon al probar).

## Review Focus

- Un `icono` que apunta a un archivo que no existe: la radio arranca igual y la emisora usa el genérico (Task 2).
- Abrir el dial con la radio caída: mensaje y cierre solo, sin dejar el teclado tomado (test de estructura, Task 6:
  todo `pushModal` tiene su `popModal` en el cierre, incluido el de error).
- Teclas rápidas: cinco ▶ seguidos mandan a lo sumo dos pedidos (Task 5: `crearCola`).
- Quitar el applet con el dial abierto: se cierra y suelta el teclado y el atajo (Task 6: `on_applet_removed_from_panel`).
- Una imagen elegida en el modal con espacios o acentos en la ruta: llega entera a `--icono` (Task 4, argv sin shell).

---

### Task 1: prender desde 0 sube a 50

**Files:** Modify `src/cassette_fm/radio.py:23`, `tests/test_radio.py` (los dos tests de arriba), README si menciona el 10.

- [ ] **Step 1:** renombrar `test_encender_con_volumen_cero_sube_a_minimo` → `…_sube_a_50`, esperando 50 (y
  `("volumen", 50)`); agregar `test_rotar_con_volumen_cero_sube_a_50` (`Estado(volumen=0)`, `radio.siguiente()` →
  `volumen() == 50`); dejar `test_subir_volumen_enciende_la_estacion_guardada` (10) como está.
- [ ] **Step 2:** `pytest tests/test_radio.py -k volumen -q` → FAIL. **Step 3:** `VOLUMEN_MINIMO = 50`.
- [ ] **Step 4:** PASS + `pytest -q`. **Step 5: commit** `Volumen: prender desde 0 sube a 50`.

### Task 2: campo `icono` y `iconos` en la API

**Files:** `src/cassette_fm/emisoras.py` (`_CAMPOS`, `DefEmisora.icono: Path | None`, `Catalogo.iconos()`),
`src/cassette_fm/radio.py` (`iconos: Callable[[], dict[str, str]] | None = None` en el constructor; `estado()` suma
`"iconos"`), `src/cassette_fm/servicio.py` (pasa `catalogo.iconos`); tests `tests/test_emisoras.py`,
`tests/test_radio.py`.

**Interfaces:**
- Produces: `"icono"` opcional: texto no vacío o `ErrorConfig` (`"<nombre>": "icono" tiene que ser la ruta de una
  imagen`); relativa → contra la carpeta de `estaciones.json`.
- Produces: `Catalogo.iconos() -> dict[str, str]` (nombre → ruta absoluta) solo de los archivos que existen; un
  `_log.warning` por archivo faltante, una vez por ruta.
- Produces: `estado()["iconos"]` (dict; `{}` sin catálogo).

- [ ] **Step 1: tests que fallan**
  - `test_icono_relativo_se_resuelve_contra_la_carpeta` (`"icono": "iconos/p.png"` → `DefEmisora.icono ==
    tmp/iconos/p.png`); `test_icono_que_no_es_texto_es_error` (`3` y `""`).
  - `test_iconos_solo_los_que_existen` (dos emisoras, una con archivo creado, otra con ruta inexistente →
    `{"A": ruta}` y un warning con la ruta en `caplog`).
  - `test_estado_trae_los_iconos` (Radio con `iconos=lambda: {"A": "/x.png"}` → `estado()["iconos"] == {"A": "/x.png"}`).
- [ ] **Step 2:** FAIL. **Step 3:** implementar. **Step 4:** PASS + `pytest -q`.
- [ ] **Step 5: commit** `Emisoras: campo icono y los logos en el estado de la radio`.

### Task 3: `cassette nueva --icono` y `cassette icono`

**Files:** `src/cassette_fm/emisora_nueva.py` (`copiar_icono`), `src/cassette_fm/cli.py`, README; tests
`tests/test_emisora_nueva.py`, `tests/test_cli.py`.

**Interfaces:**
- Produces: `copiar_icono(origen: Path, base: Path) -> str` → ruta relativa a `base` (`"iconos/power.png"`): si
  `origen` ya está dentro de `base/iconos`, no copia; si hay un archivo con el mismo nombre y mismo contenido, lo
  reusa; con distinto contenido, `power-2.png`, `-3`…; extensión no `.png/.jpg/.jpeg/.svg` o archivo que no existe →
  `ErrorConfig`.
- Produces: `cassette nueva … --icono RUTA` (copia y guarda `"icono"`); `cassette icono NOMBRE RUTA` y
  `cassette icono NOMBRE --quitar` (buscar como `borrar`, escribir, rescan; nunca borra archivos de `iconos/`);
  salida `🖼 Power F.M. · iconos/power.png` / `🖼 Power F.M. · sin logo`.

- [ ] **Step 1: tests que fallan** — `copiar_icono`: copia, reusa igual, sufijo si distinto, no copia lo que ya está
  adentro, extensión rara es error. CLI: `nueva --icono` guarda `"icono": "iconos/x.png"` y el archivo existe;
  `icono` pone y `--quitar` saca (archivo sigue); emisora inexistente → 1; radio caída → 0 con aviso.
- [ ] **Step 2:** FAIL. **Step 3:** implementar. **Step 4:** PASS + `pytest -q`.
- [ ] **Step 5: commit** `cassette icono y nueva --icono: logos de las emisoras en la config`.

### Task 4: logo en el modal de emisora nueva

**Files:** `applet/cassette-fm@cassette-fm/logic.js` (`argumentosNueva` suma `--icono=RUTA` si hay;
`argumentosExaminar()`; `rutaElegida(codigo, stdout)`), `applet.js` (fila "Logo": miniatura 48 px, Examinar…,
Quitar; bloqueados en `_ocupado`), tests `applet/tests/logic.test.js`, `tests/test_applet_estructura.py`.

- [ ] **Step 1: tests que fallan** —
  `argumentosNueva("S", link, sel, "/home/x/Mis imágenes/á.png")` → termina en `["--icono=/home/x/Mis imágenes/á.png",
  "--", "S", link]` (opciones antes del `--`); sin icono, igual que hoy.
  `argumentosExaminar()` → `["--file-selection", "--title=Logo de la emisora", "--file-filter=Imágenes | *.png *.jpg *.jpeg *.svg"]`.
  `rutaElegida(0, "/a/b.png\n") === "/a/b.png"`; `rutaElegida(1, "") === null` (cancelado).
  Estructura: `"zenity"` en applet.js y `_ocupado` incluye `this._botonExaminar` y `this._botonQuitarLogo`.
- [ ] **Step 2:** FAIL. **Step 3:** implementar (zenity con `_correr`, límite 600 s). **Step 4:** PASS + `pytest -q`.
- [ ] **Step 5: commit** `Modal de emisora nueva: elegir el logo con Examinar`.

### Task 5: lógica del dial en `logic.js`

**Files:** `logic.js`, `applet/tests/logic.test.js`.

**Interfaces (todas exportadas):**
- `filaDial(estaciones, actual, lado=3) -> [{nombre, desplazamiento}]`: con `n <= 2*lado+1` todas, si no `2*lado+1`;
  circular, `desplazamiento` de `-k` a `+k` con la actual en 0 (con `n` par y todas visibles, sobra una a la derecha).
  Sin actual (apagada sin emisora) → la primera en 0.
- `teclaDial(nombreTecla) -> "anterior"|"siguiente"|"subir"|"bajar"|"cerrar"|null` (`Left`, `Right`, `Up`, `Down`,
  `Escape`).
- `crearCola(enviar) -> {pedir(destino), listo()}`: `pedir` manda en el acto si no hay nada en curso; si hay, guarda
  solo el último destino; `listo()` (al volver la respuesta) manda el guardado si hay.
- `barraVolumen(v) -> string` de 10 celdas (`▮`×round(v/10) + `▱`) + `" " + v`; `v === 0` → `"Apagada"`.
- `iconoDe(nombre, iconos, generico) -> string`.

- [ ] **Step 1: tests que fallan** (ejemplos):
  `filaDial(["A","B","C"], "B")` → `[{A,-1},{B,0},{C,1}]`; con 8 nombres y la actual `"A"` → 7 elementos, de `F`(-3)…
  `A`(0)…`D`(+3); `crearCola`: `pedir(1)`, `pedir(2)`, `pedir(3)` → `enviados == [1]`; `listo()` → `[1, 3]`;
  `listo()` → sin cambios. `barraVolumen(60) === "▮▮▮▮▮▮▱▱▱▱ 60"`, `barraVolumen(0) === "Apagada"`.
  `iconoDe("Sing", {"Power F.M.": "/p.png"}, "/g.png") === "/g.png"`.
- [ ] **Step 2:** FAIL. **Step 3:** implementar. **Step 4:** PASS. **Step 5: commit** `applet: lógica del dial`.

### Task 6: el dial en el applet

**Files:** `applet.js` (clase `Dial`, por composición), `settings-schema.json` (`"atajo_dial"`, `type: "keybinding"`,
`default: "<Super><Alt>space"`), `tests/test_applet_estructura.py`.

- [ ] **Step 1: tests de estructura que fallan** — el schema tiene `atajo_dial` con ese default y el applet lo enlaza
  (el test de ajustes existente ya exige que coincidan); `Main.keybindingManager.addHotKey` y `removeHotKey` (este en
  `on_applet_removed_from_panel`, que también cierra el dial); `pushModal` y `popModal` aparecen la misma cantidad de
  veces y el cierre del dial llama a `popModal`; usa `teclaDial`, `filaDial`, `crearCola`, `barraVolumen`, `iconoDe`.
- [ ] **Step 2:** FAIL. **Step 3: implementar**
  - Abrir: `GET /estado`; si no responde, tira con "cassette-fm no responde" que se cierra sola a los 2 s; si está
    apagada, `POST /encender`. Mostrar sobre `Main.uiGroup`, centrada en el monitor principal, a un tercio de alto.
  - Logos: `St.Icon` con `Gio.FileIcon` de `iconoDe(...)` (genérico: `AppletDir`/`generico.png` vía
    `metadata.path`), tamaños 160/96, opacidad 255/150, animación `ease` ~150 ms al moverse; nombre, `pista` y
    `barraVolumen` debajo.
  - Teclas: `teclaDial`; además, la combinación de `atajo_dial` cierra. ◀ ▶ mueven la actual localmente y
    `crearCola` manda `/sintonizar`; ▲ ▼ calculan el volumen nuevo localmente y lo mandan por otra cola
    (`/volumen {"valor": n}`). Con la radio apagada, ◀ ▶ sintonizan (prende en 50).
  - Mouse: clic en logo → `/sintonizar`; clic fuera → cerrar; rueda → anterior/siguiente.
  - Cierre: Escape, atajo, clic afuera o 5 s sin tocar; fundido y `popModal`; siempre se puede cerrar aunque falle un
    pedido.
- [ ] **Step 4:** PASS + `pytest -q`. **Step 5: commit** `applet: el dial de emisoras (Super+Alt+Espacio)`.

### Task 7: los logos de verdad (fuera del repo, salvo el genérico)

- [ ] **Step 1:** script en el scratchpad (Python del sistema: numpy + GdkPixbuf) que, de
  `…/images/1.jpg`, separa los seis logos: máscara de "fondo" por distancia de color al gris del fondo, relleno desde
  los bordes de cada recorte (así lo oscuro de adentro del logo no se vuelve transparente), borde suavizado de 1–2 px,
  recorte al contenido y lienzo cuadrado de 512 px. Lo mismo para el genérico de `…/images/2.jpg`.
- [ ] **Step 2:** mirar cada resultado sobre un fondo de color fuerte (capturas leídas) y ajustar el umbral hasta que
  no queden halos ni partes comidas (la cinta del cassette, las llamas, el rayo, los autos).
- [ ] **Step 3:** guardar los seis en `~/.config/cassette-fm/iconos/` (`happy-eighties.png`, `mas-gasolina.png`,
  `pop-hits.png`, `power.png`, `whisper.png`, `xcelerate.png`), asignarlos con `cassette icono`, y el genérico en
  `applet/cassette-fm@cassette-fm/generico.png` (commit `applet: logo genérico de las emisoras`).
- [ ] **Step 4:** mostrarle al usuario una lámina con los siete recortes.

### Task 8: prueba real y contexto

- [ ] **Step 1:** reiniciar el servicio y Cinnamon; abrir el dial por Eval (y por el atajo, con `xdotool` si está);
  capturas: emisora actual agrandada con su logo, Sing con el genérico, barra de volumen; ▶ por Eval → cambia la
  emisora; Escape → cierra y `Main.modalCount == 0`.
- [ ] **Step 2:** README (sección del applet: el dial y su atajo; los logos) y `docs/project-context.md`; marcar
  CASSETTE-FM-inkb y la épica según corresponda; commit `Contexto: el dial de emisoras`.
