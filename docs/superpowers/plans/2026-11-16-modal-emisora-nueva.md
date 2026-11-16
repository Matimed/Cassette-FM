# Crear una emisora desde el applet — plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Entrada "Nueva emisora…" en el menú del applet que abre un modal (nombre, playlist, idioma, voz en un
desplegable) y crea la emisora corriendo `cassette nueva`.

**Architecture:** La CLI suma `cassette voces [--json]` (los alias útiles, con idioma y emisoras que los usan). El
applet corre `cassette voces --json` al abrir el modal y `cassette nueva …` al crear, con `Gio.Subprocess` asíncrono.
Toda decisión pura (filtrar voces por idioma, qué idioma fija una voz, argumentos, mensajes) va en `logic.js`,
probada con Node; `applet.js` solo arma widgets y lanza procesos.

**Tech Stack:** Python 3 (argparse, pytest), GJS de Cinnamon 6.4 (`ModalDialog`, St, Gio), Node (`node --test`).

**Spec:** `docs/superpowers/specs/2026-11-16-modal-emisora-nueva-design.md`

## Global Constraints

- Idioma de trabajo y de los textos: español rioplatense. Commits en español, en imperativo llano, con
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; commitear solo archivos propios con rutas explícitas
  (`git commit -- <archivos>`): hay otro agente trabajando en paralelo.
- Los tests nunca tocan la config real (XDG en `tmp_path`, como `_nueva` en `tests/test_cli.py`).
- `applet.js` no contiene `JSON.parse`, `HTTP/1.0` ni `Content-Length` (test existente): el JSON de `cassette voces`
  se parsea en `logic.js`.
- Idiomas del modal: `""` (Cualquiera), `"es"`, `"en"`; una voz `en-gb` cuenta como inglés.
- Desplegable propio dentro del diálogo (el `PopupComboBoxMenuItem` de Cinnamon no funciona en un `ModalDialog`).
- Mientras crea: Crear dice "Creando…"; Crear y Cancelar con `reactive = false` (eso también desactiva sus teclas:
  `dialog.js` solo dispara la acción de una tecla si el botón es reactivo). Vencimiento: 60 s, mata el proceso.

## Review Focus

- Nombres con espacios, comillas o acentos y links con `?si=`: van como elementos de argv, nunca por un shell
  (test en Tarea 2: `argumentosNueva` con `"Sing «2»"`).
- `estaciones.json` inexistente: `cassette voces` igual lista los alias, sin emisoras (test en Tarea 1).
- El panel nunca se congela: nada sincrónico (`spawn_command_line_sync`, `communicate_utf8(` sin `_async`,
  `wait(`) en `applet.js` (test de estructura en Tarea 3).
- Salida de `cassette nueva` con error y stderr vacío, o con varias líneas y salto final: el modal muestra algo
  legible (test en Tarea 2: `mensajeDeError`).
- `cassette voces --json` con basura o una versión vieja de `cassette` sin ese comando: el modal lo dice en vez de
  quedar sin voces en silencio (test en Tarea 2: `parsearVoces` devuelve `null`).

---

### Task 1: `cassette voces [--json]`

**Files:**
- Modify: `src/cassette_fm/emisora_nueva.py` (función nueva al final de la sección de voces)
- Modify: `src/cassette_fm/cli.py` (parser y despacho en `main` junto a `nueva`: usa `rutas.emisoras`, no la radio)
- Modify: `README.md` (una línea junto a `cassette nueva`)
- Test: `tests/test_emisora_nueva.py`, `tests/test_cli.py`

**Interfaces:**
- Produces: `emisora_nueva.voces_disponibles(alias: Mapping[str, str], emisoras: list[dict]) -> list[dict]`, cada
  elemento `{"alias": str, "voz": str, "idioma": str, "emisoras": list[str]}`, en el orden de `alias`, solo los que
  `idioma_de_voz` reconoce; `emisoras` = nombres (sin espacios alrededor) de las emisoras con `dj.voz == alias`.
- Produces: `cassette voces --json` imprime ese JSON (`ensure_ascii=False`) en una línea y sale con 0.

- [ ] **Paso 1: tests que fallan**

```python
# tests/test_emisora_nueva.py
def test_voces_disponibles_con_idioma_y_emisoras_que_las_usan():
    emisoras = [{"nombre": " Sing ", "dj": {"voz": "dora"}}, {"nombre": "Otra", "dj": {"voz": "dora"}},
                {"nombre": "Sin DJ"}]
    assert voces_disponibles(ALIAS, emisoras) == [
        {"alias": "puck", "voz": "am_puck", "idioma": "en", "emisoras": []},
        {"alias": "sarah", "voz": "af_sarah", "idioma": "en", "emisoras": []},
        {"alias": "dora", "voz": "ef_dora", "idioma": "es", "emisoras": ["Sing", "Otra"]},
        {"alias": "daniela", "voz": "piper:es_AR-daniela-high", "idioma": "es", "emisoras": []},
        {"alias": "alex_santa", "voz": "em_alex+em_santa", "idioma": "es", "emisoras": []},
        {"alias": "emma", "voz": "bf_emma", "idioma": "en-gb", "emisoras": []}]     # siwis (francés) no sirve
```

```python
# tests/test_cli.py (usa el helper _nueva: emisora Happy Eighties con voz puck; alias puck y sarah)
def test_voces_json_para_el_applet(tmp_path, monkeypatch, capsys, servidor_http):
    import json as _json
    _nueva(monkeypatch, tmp_path, servidor_http)
    assert main(["voces", "--json"]) == 0
    assert _json.loads(capsys.readouterr().out) == [
        {"alias": "puck", "voz": "am_puck", "idioma": "en", "emisoras": ["Happy Eighties"]},
        {"alias": "sarah", "voz": "af_sarah", "idioma": "en", "emisoras": []}]


def test_voces_sin_estaciones_json_lista_igual(tmp_path, monkeypatch, capsys, servidor_http):
    r, _ = _nueva(monkeypatch, tmp_path, servidor_http)
    r.emisoras.unlink()
    assert main(["voces"]) == 0
    salida = capsys.readouterr().out
    assert "puck" in salida and "am_puck" in salida and "sarah" in salida


def test_voces_sin_alias_dice_donde_se_definen(tmp_path, monkeypatch, capsys, servidor_http):
    _nueva(monkeypatch, tmp_path, servidor_http)
    (tmp_path / "xdg" / "cassette-dj" / "config.toml").write_text("")
    assert main(["voces"]) == 0
    assert "[voces]" in capsys.readouterr().out
```

- [ ] **Paso 2:** `pytest tests/test_emisora_nueva.py tests/test_cli.py -k voces -q` → FAIL (`voces_disponibles` no
  existe; `invalid choice: 'voces'`).

- [ ] **Paso 3: implementar**
  - `voces_disponibles` en `emisora_nueva.py`.
  - En la CLI: `sub.add_parser("voces", help="las voces con alias que puede usar una emisora nueva")` con
    `--json` (`action="store_true"`). Despacho en `main` junto a `nueva`: `return _voces(args, rutas)`.
  - `_voces`: `estaciones.json` inexistente → sin emisoras; roto → mensaje de `leer_crudo` por stderr y 1. Alias con
    `cargar_config_dj(rutas_dj().config).voces` si el archivo existe (como `_nueva`).
  - Sin `--json`: una línea por voz, `f"{alias:<12} {voz:<28} {idioma:<6} {', '.join(emisoras)}"`; sin alias útiles,
    `no hay voces con alias: se definen en [voces] del config de cassette-dj (cassette-dj voces las lista)`.
  - README: `cassette voces` lista los alias que puede usar una emisora (con `--json`, para el applet).

- [ ] **Paso 4:** mismo comando → PASS; después `pytest -q` entero → todo verde.

- [ ] **Paso 5: commit** `cassette voces: los alias que puede usar una emisora nueva, con su idioma`
  (`git commit -- src/cassette_fm/emisora_nueva.py src/cassette_fm/cli.py README.md tests/test_emisora_nueva.py tests/test_cli.py`).

### Task 2: lógica del modal en `logic.js`

**Files:**
- Modify: `applet/cassette-fm@cassette-fm/logic.js` (funciones nuevas, sumadas a `module.exports`)
- Test: `applet/tests/logic.test.js`

**Interfaces:**
- Consumes: el JSON de `cassette voces --json` (Tarea 1).
- Produces (todas exportadas):
  - `parsearVoces(texto) -> Array<{alias, voz, idioma, emisoras}> | null` — `null` si no es JSON, no es lista o algún
    elemento no tiene `alias`/`idioma` string y `emisoras` lista.
  - `idiomaBase(idioma) -> "es" | "en" | ""` — `"en-gb"` → `"en"`; desconocido → `""`.
  - `vocesDelIdioma(voces, idioma) -> Array` — `idioma === ""` → todas; si no, las de `idiomaBase(v.idioma) === idioma`.
  - `etiquetaDeVoz(voz) -> string` — `"dora"` o `"dora · Sing, Otra"`; `null` → `"Al azar"`.
  - `elegirVoz(seleccion, voz) -> {idioma, voz}` — `seleccion` es `{idioma, voz}` (voz = objeto o `null`); con
    `idioma === ""` y voz no nula, el idioma pasa a `idiomaBase(voz.idioma)`.
  - `elegirIdioma(seleccion, idioma) -> {idioma, voz}` — si la voz elegida no habla `idioma` (y `idioma !== ""`),
    la voz vuelve a `null`.
  - `faltante(nombre, link) -> string | null` — `"Falta el nombre"`, `"Falta el link de la playlist"` (tras `trim`).
  - `argumentosNueva(nombre, link, seleccion) -> string[]` — `["nueva", nombre, link]` + `["--voz", alias]` si hay voz
    + `["--idioma", idioma]` si `idioma !== ""`. Sin recortar ni escapar: la CLI recorta.
  - `mensajeDeError(codigo, stdout, stderr) -> string` — stderr sin espacios alrededor; si está vacío, la última línea
    no vacía de stdout; si tampoco hay, `"cassette nueva terminó con error (código N)"`.

- [ ] **Paso 1: tests que fallan** (en `logic.test.js`, con este fixture)

```js
const VOCES = [
  { alias: "puck", voz: "am_puck", idioma: "en", emisoras: ["Happy Eighties"] },
  { alias: "emma", voz: "bf_emma", idioma: "en-gb", emisoras: [] },
  { alias: "dora", voz: "ef_dora", idioma: "es", emisoras: ["Sing", "Otra"] },
];

test("parsearVoces", () => {
  assert.deepEqual(L.parsearVoces(JSON.stringify(VOCES) + "\n"), VOCES);
  assert.equal(L.parsearVoces("usage: cassette [-h]"), null);
  assert.equal(L.parsearVoces('{"alias": "x"}'), null);
  assert.equal(L.parsearVoces('[{"alias": "x"}]'), null);
  assert.equal(L.parsearVoces(null), null);
});

test("vocesDelIdioma: en-gb cuenta como inglés; Cualquiera las muestra todas", () => {
  assert.deepEqual(L.vocesDelIdioma(VOCES, "en").map(v => v.alias), ["puck", "emma"]);
  assert.deepEqual(L.vocesDelIdioma(VOCES, "es").map(v => v.alias), ["dora"]);
  assert.equal(L.vocesDelIdioma(VOCES, "").length, 3);
});

test("etiquetaDeVoz", () => {
  assert.equal(L.etiquetaDeVoz(VOCES[1]), "emma");
  assert.equal(L.etiquetaDeVoz(VOCES[2]), "dora · Sing, Otra");
  assert.equal(L.etiquetaDeVoz(null), "Al azar");
});

test("elegir una voz con Cualquiera fija su idioma; con idioma elegido no lo cambia", () => {
  assert.deepEqual(L.elegirVoz({ idioma: "", voz: null }, VOCES[1]), { idioma: "en", voz: VOCES[1] });
  assert.deepEqual(L.elegirVoz({ idioma: "es", voz: null }, VOCES[2]), { idioma: "es", voz: VOCES[2] });
  assert.deepEqual(L.elegirVoz({ idioma: "es", voz: VOCES[2] }, null), { idioma: "es", voz: null });
});

test("cambiar a un idioma que la voz no habla la vuelve a Al azar", () => {
  assert.deepEqual(L.elegirIdioma({ idioma: "", voz: VOCES[2] }, "en"), { idioma: "en", voz: null });
  assert.deepEqual(L.elegirIdioma({ idioma: "en", voz: VOCES[1] }, "en"), { idioma: "en", voz: VOCES[1] });
  assert.deepEqual(L.elegirIdioma({ idioma: "es", voz: VOCES[2] }, ""), { idioma: "", voz: VOCES[2] });
});

test("faltante", () => {
  assert.equal(L.faltante("  ", "x"), "Falta el nombre");
  assert.equal(L.faltante("Sing", " "), "Falta el link de la playlist");
  assert.equal(L.faltante("Sing", "x"), null);
});

test("argumentosNueva: cada dato es un argumento, sin shell", () => {
  const link = "https://open.spotify.com/playlist/4iH?si=b5";
  assert.deepEqual(L.argumentosNueva("Sing «2»", link, { idioma: "", voz: null }), ["nueva", "Sing «2»", link]);
  assert.deepEqual(L.argumentosNueva("S", link, { idioma: "es", voz: VOCES[2] }),
                   ["nueva", "S", link, "--voz", "dora", "--idioma", "es"]);
  assert.deepEqual(L.argumentosNueva("S", link, { idioma: "en", voz: null }), ["nueva", "S", link, "--idioma", "en"]);
});

test("mensajeDeError", () => {
  assert.equal(L.mensajeDeError(1, "", "la playlist está vacía\n"), "la playlist está vacía");
  assert.equal(L.mensajeDeError(1, "✓ Sing (3 temas)\nLa emisora quedó guardada…\n\n", ""), "La emisora quedó guardada…");
  assert.equal(L.mensajeDeError(2, "", ""), "cassette nueva terminó con error (código 2)");
});
```

- [ ] **Paso 2:** `node --test applet/tests/` → FAIL (`L.parsearVoces is not a function`).
- [ ] **Paso 3:** implementar las funciones en `logic.js` y sumarlas a `module.exports`.
- [ ] **Paso 4:** `node --test applet/tests/` → PASS; `pytest tests/test_applet_logic.py tests/test_applet_estructura.py -q` → PASS.
- [ ] **Paso 5: commit** `applet: lógica del modal de emisora nueva (voces por idioma, argumentos, errores)`
  (`git commit -- applet/cassette-fm@cassette-fm/logic.js applet/tests/logic.test.js`).

### Task 3: el modal en `applet.js`

**Files:**
- Modify: `applet/cassette-fm@cassette-fm/applet.js`
- Test: `tests/test_applet_estructura.py`

**Interfaces:**
- Consumes: todas las funciones de la Tarea 2 vía `AppletDir.logic.*`.

- [ ] **Paso 1: tests de estructura que fallan**

```python
def test_el_menu_tiene_nueva_emisora_y_corre_cassette_asincrono():
    js = _js()
    assert "Nueva emisora…" in js and "ModalDialog" in js
    assert "Gio.Subprocess" in js and "communicate_utf8_async" in js
    for sincronico in ("spawn_command_line_sync", "communicate_utf8(", ".wait(", "spawn_sync"):
        assert sincronico not in js, sincronico     # el panel nunca se congela


def test_el_modal_no_usa_el_combo_de_cinnamon():
    assert "PopupComboBoxMenuItem" not in _js()     # no funciona dentro de un ModalDialog
```

- [ ] **Paso 2:** `pytest tests/test_applet_estructura.py -q` → FAIL en los dos tests nuevos.

- [ ] **Paso 3: implementar**
  - Imports: `ModalDialog = imports.ui.modalDialog`, `St = imports.gi.St`.
  - `_reconstruirMenu`: después de las emisoras y antes de "Apagar", un `PopupMenuItem("Nueva emisora…")` que hace
    `new DialogoEmisora(this).open()`.
  - Al applet: `_correrCassette(argumentos, segundos, callback)` — busca `GLib.find_program_in_path("cassette")`,
    si no `GLib.get_home_dir() + "/.local/bin/cassette"` si existe (`GLib.file_test(…, GLib.FileTest.IS_EXECUTABLE)`);
    sin ninguno, `callback({error: "No encuentro el comando cassette (¿está instalado en ~/.local/bin?)"})`. Lanza
    `Gio.Subprocess.new([ruta, ...argumentos], STDOUT_PIPE | STDERR_PIPE)`, `communicate_utf8_async(null, null, …)`
    → `callback({codigo: get_exit_status(), stdout, stderr})`; un `Mainloop.timeout_add_seconds(segundos)` que
    hace `force_exit()` y `callback({error: "cassette tardó más de 60 s: se cortó"})`; solo el primero de los dos
    llama al callback (como `terminar` en `_pedir`).
  - `class DialogoEmisora extends ModalDialog.ModalDialog` (`super({destroyOnClose: true})`), en `contentLayout`:
    título "Emisora nueva"; `St.Entry` Nombre y Playlist (hint `https://open.spotify.com/playlist/…`); fila Idioma
    con tres `St.Button({toggle_mode: true})` Cualquiera / Español / Inglés (`""`, `"es"`, `"en"`); fila Voz con un
    `St.Button` cuyo label es `etiquetaDeVoz(seleccion.voz) + " ▾"` y debajo un `St.ScrollView` (alto máx. ~200 px,
    oculto) con un `St.Button` por voz de `vocesDelIdioma` más "Al azar" primero; elegir uno aplica `elegirVoz`,
    pliega la lista y refresca idioma y label; apretar un idioma aplica `elegirIdioma` y refresca. Un `St.Label`
    de error con `style: "color: #e66;"`, oculto si no hay error.
  - Botones: `addButton({label: "Cancelar", action: () => this.close(), key: Clutter.KEY_Escape})` y
    `addButton({label: "Crear", action: () => this._crear(), default: true})`; guardar los dos `St.Button` que
    devuelve `addButton`.
  - Al abrir: `_correrCassette(["voces", "--json"], 60, …)`; `parsearVoces(stdout)` nulo, código ≠ 0 o `error` →
    mostrar el error ("No pude leer las voces: " + `mensajeDeError`/`error`) y dejar solo "Al azar".
  - `_crear`: `faltante` → error y no corre; si no, label "Creando…", los dos botones `reactive = false`, corre
    `argumentosNueva(...)` con 60 s. Código 0 → `this.close()` y `applet._sondear()`; si no, error con
    `mensajeDeError(codigo, stdout, stderr)` (o el `error` del vencimiento), botones reactivos de nuevo, label
    "Crear", lo escrito queda.

- [ ] **Paso 4:** `pytest tests/test_applet_estructura.py tests/test_applet_logic.py -q` → PASS (incluye
  `node --check`). Después `pytest -q` entero → todo verde.
- [ ] **Paso 5: commit** `applet: botón Nueva emisora… con un modal que corre cassette nueva`
  (`git commit -- applet/cassette-fm@cassette-fm/applet.js tests/test_applet_estructura.py`).

### Task 4: prueba real en Cinnamon y contexto

- [ ] **Paso 1:** recargar el applet:
  `dbus-send --session --dest=org.Cinnamon --type=method_call /org/Cinnamon org.Cinnamon.ReloadXlet string:cassette-fm@cassette-fm string:APPLET`
  y revisar `~/.xsession-errors` (o `journalctl --user -b | grep -i cassette-fm`): Expected: sin errores de JS del
  applet.
- [ ] **Paso 2:** `cassette voces` y `cassette voces --json` contra la config real. Expected: los 12 alias con su
  idioma y "Sing" al lado de alex_santa.
- [ ] **Paso 3:** prueba con el usuario: abrir el modal, elegir idioma y voz, crear una emisora (la misma playlist de
  Sing con otro nombre sirve), y un error a propósito (nombre repetido). Lo que se pruebe sin el usuario se dice
  como tal.
- [ ] **Paso 4:** `docs/project-context.md`: una frase con el modal del applet y el enlace a la spec; commit
  `Contexto: crear emisoras desde el applet` (`git commit -- docs/project-context.md`).
