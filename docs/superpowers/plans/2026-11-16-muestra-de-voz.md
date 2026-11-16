# Escuchar la voz antes de crear la emisora — plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Un botón ▶ en el modal de emisora nueva que hace decir a la voz elegida "Hola, soy dora y estás
escuchando Synthwave F.M.".

**Architecture:** El servicio DJ suma `POST /muestra` (la frase la arma y la sintetiza el `Productor`, con una función
compartida `decir` que también usan las intervenciones y `voz-prueba`). `cassette-dj muestra` la pide, la guarda en
caché e imprime la ruta; el applet corre ese comando y después `mpv` con el WAV.

**Tech Stack:** Python 3 (http.server, pytest), GJS de Cinnamon 6.4, Node (`node --test`).

**Spec:** `docs/superpowers/specs/2026-11-16-muestra-de-voz-design.md`

## Global Constraints

- Español rioplatense; commits en español, imperativo llano, `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`,
  con rutas explícitas (`git commit -- <archivos>`).
- Tests sin tocar la config real (XDG en `tmp_path`, fixture `entorno` de `tests/dj/test_cli.py`).
- Frases exactas: `Hola, soy {voz} y estás escuchando {radio}.` / `Hi, I'm {voz}, and you're listening to {radio}.`;
  sin radio: `Hola, soy {voz}, la voz de tu nueva radio.` / `Hi, I'm {voz}, the voice of your new station.`
  `{voz}`: el alias con `_` → espacio. Inglés para `en` y `en-gb`.
- `applet.js` sin `JSON.parse` ni nada sincrónico (tests existentes); `ReloadXlet` no recarga `logic.js` (reiniciar
  Cinnamon para la prueba real).

## Review Focus

- Una radio con `{`, `}`, comillas o `&` en el nombre no rompe el marcado (test en Task 2: `frase_muestra` con
  `"Rock {&} Roll"`).
- Una voz de Piper en la muestra y en `voz-prueba`: le llega el texto (test en Task 1).
- Pedir una muestra mientras el servicio produce una intervención: espera el candado del sintetizador, no falla (lo
  cubre el candado existente; Task 2 usa el mismo `Sintetizador`).
- Servicio DJ caído: `cassette-dj muestra` sale con 1 y una línea (test en Task 3).
- Cerrar el modal o elegir otra voz mientras suena: el mpv se corta (test de estructura en Task 5).

---

### Task 1: `decir`, compartida por producción y `voz-prueba`

**Files:**
- Modify: `src/cassette_fm/dj/sintetizador.py` (función nueva al final)
- Modify: `src/cassette_fm/dj/produccion.py` (las dos síntesis, líneas ~190 y ~214)
- Modify: `src/cassette_fm/dj/cli.py` (`_voz_prueba`)
- Test: `tests/dj/test_cli.py`, `tests/dj/test_sintetizador.py`

**Interfaces:**
- Produces: `decir(sintetizador, fonemizar, marcado: str, voz: str, lang: str, destino: Path,
  velocidad: float | None = None) -> tuple[Preparado, float]` en `sintetizador.py`: `preparar(marcado, lang,
  fonemizar)` y `sintetizador.sintetizar(prep.fonemas, voz, lang, destino, velocidad=velocidad,
  texto=texto_para_piper(prep.marcado))`.

- [ ] **Step 1: tests que fallan**

```python
# tests/dj/test_sintetizador.py
def test_decir_le_pasa_fonemas_y_texto_al_sintetizador(tmp_path):
    class Anota:
        def sintetizar(self, fonemas, voz, lang, salida, velocidad=None, texto=None):
            self.args = (fonemas, voz, lang, salida, velocidad, texto)
            return 1.5
    s = Anota()
    prep, duracion = decir(s, lambda t, l: f"<{l}:{t}>", "Hola, soy {es:dora} y nada más.", "dora", "es",
                           tmp_path / "x.wav", velocidad=1.1)
    assert duracion == 1.5 and prep.texto == "Hola, soy dora y nada más."
    assert s.args == (prep.fonemas, "dora", "es", tmp_path / "x.wav", 1.1, "Hola, soy dora y nada más.")
```

```python
# tests/dj/test_cli.py (SintetizadorFalso de ese archivo: sumarle self.textos y anotar texto)
def test_voz_prueba_le_pasa_el_texto_a_piper(entorno, tmp_path):
    cargar_guiones(entorno, [guion("Seguimos con la mejor música para todos ustedes.")])
    sint = SintetizadorFalso()
    assert cli.main(["voz-prueba", "--voz", "piper:es_AR-daniela-high", "--salida", str(tmp_path / "s")],
                    sintetizador=sint, fonemizar=fon_falso) == 0
    assert sint.textos == ["Seguimos con la mejor música para todos ustedes."]
```

- [ ] **Step 2:** `.venv/bin/python -m pytest tests/dj/test_sintetizador.py tests/dj/test_cli.py -k "decir or piper" -q`
  → FAIL (`decir` no existe; `textos == [None]`).
- [ ] **Step 3:** implementar `decir` y usarla en `_voz_prueba` y en las dos síntesis de `produccion.py` (mismo
  comportamiento: `Preparado` y duración).
- [ ] **Step 4:** mismo comando → PASS; `pytest tests/dj -q` → verde.
- [ ] **Step 5: commit** `DJ: una sola función prepara y sintetiza (voz-prueba ya anda con Piper)`.

### Task 2: la frase y `POST /muestra`

**Files:**
- Create: `src/cassette_fm/dj/muestra.py`
- Modify: `src/cassette_fm/dj/produccion.py` (método `muestra`), `src/cassette_fm/dj/servidor.py` (`crear_servidor`
  con `productor=None`; `servir` se lo pasa), `src/cassette_fm/cliente_dj.py` (método `muestra`)
- Test: `tests/dj/test_muestra.py` (nuevo), `tests/dj/test_servidor.py` (`montar` pasa `productor=s.productor`),
  `tests/test_cliente_dj.py` si existe (si no, en `tests/dj/test_servidor.py` contra el servicio montado)

**Interfaces:**
- Produces: `frase_muestra(voz: str, idioma: str, radio: str, lexico: Lexico) -> str` (marcado; `idioma` es una
  clave de `IDIOMAS`; nombres con `marcar(lexico.pronunciacion(n), lexico.idioma_de(n, IDIOMAS[idioma]))` para la
  radio y `marcar(voz_hablada, IDIOMAS[idioma])` para la voz).
- Produces: `Productor.muestra(voz: str, idioma: str, radio: str, destino: Path) -> float` (usa `decir`).
- Produces: `POST /muestra {"voz": str, "idioma": str, "radio": str (opcional, "" si falta)}` → `200 audio/wav`;
  `400 {"error"}` si voz/idioma/radio no son válidos (voz: 1–64 caracteres; radio ≤ 100) o el sintetizador da
  `ValueError` (voz inexistente); `503` con `ErrorModelos` o sin productor.
- Produces: `ClienteDJ.muestra(voz: str, idioma: str, radio: str) -> bytes` (timeout 60 s: la primera vez carga el
  modelo).

- [ ] **Step 1: tests que fallan**

```python
# tests/dj/test_muestra.py
from cassette_fm.dj.lexico import Lexico
from cassette_fm.dj.muestra import frase_muestra

def test_frase_en_espanol_y_en_ingles():
    assert frase_muestra("dora", "es", "Synthwave F.M.", Lexico()) == \
        "Hola, soy {es:dora} y estás escuchando {es:Synthwave F.M.}."
    assert frase_muestra("alex_santa", "en-gb", "Sing", Lexico()) == \
        "Hi, I'm {en-gb:alex santa}, and you're listening to {en-gb:Sing}."

def test_frase_sin_radio():
    assert frase_muestra("dora", "es", "  ", Lexico()) == "Hola, soy {es:dora}, la voz de tu nueva radio."
    assert frase_muestra("puck", "en", "", Lexico()) == "Hi, I'm {en-us:puck}, the voice of your new station."

def test_una_radio_con_llaves_no_rompe_el_marcado():
    assert frase_muestra("dora", "es", "Rock {&} Roll", Lexico()) == \
        "Hola, soy {es:dora} y estás escuchando {es:Rock & Roll}."
```

```python
# tests/dj/test_servidor.py
def test_muestra_devuelve_el_wav_de_la_frase(servicio):
    sint = SintetizadorFalso()
    s = servicio(sint)
    codigo, cuerpo, cab = pedir(s, "POST", "/muestra", {"voz": "em_santa", "idioma": "es", "radio": "Sing"})
    assert codigo == 200 and cab["Content-Type"] == "audio/wav" and cuerpo[:4] == b"RIFF"

@pytest.mark.parametrize("cuerpo", [{"idioma": "es"}, {"voz": "x", "idioma": "fr"}, {"voz": "", "idioma": "es"},
                                    {"voz": "x", "idioma": "es", "radio": 3}])
def test_muestra_invalida_da_400(servicio, cuerpo):
    s = servicio(SintetizadorFalso())
    assert json_de(pedir(s, "POST", "/muestra", cuerpo))[0] == 400

def test_muestra_con_voz_inexistente_da_400(servicio):
    class Rechaza(SintetizadorFalso):
        def sintetizar(self, *a, **k):
            raise ValueError("la voz 'zz' no existe")
    s = servicio(Rechaza())
    codigo, d = json_de(pedir(s, "POST", "/muestra", {"voz": "zz", "idioma": "es"}))
    assert codigo == 400 and "zz" in d["error"]

def test_muestra_sin_modelos_da_503(servicio, tmp_path):
    s = servicio(Sintetizador(ConfigServicioDJ(modelos_dir=tmp_path / "vacio")), modelos_dir=tmp_path / "vacio")
    assert json_de(pedir(s, "POST", "/muestra", {"voz": "am_puck", "idioma": "en"}))[0] == 503

def test_cliente_pide_la_muestra(servicio):
    from cassette_fm.cliente_dj import ClienteDJ
    s = servicio(SintetizadorFalso())
    assert ClienteDJ(s.base).muestra("em_santa", "es", "Sing")[:4] == b"RIFF"
```

- [ ] **Step 2:** `.venv/bin/python -m pytest tests/dj/test_muestra.py tests/dj/test_servidor.py -k muestra -q` → FAIL.
- [ ] **Step 3:** implementar `muestra.py`, `Productor.muestra` (sintetiza a un archivo temporal que el servidor lee
  y borra), la ruta en `_post` (con `_leer_cuerpo`) y `ClienteDJ.muestra`.
- [ ] **Step 4:** mismo comando → PASS; `pytest tests/dj tests/test_cliente_dj.py -q` (el que exista) → verde.
- [ ] **Step 5: commit** `DJ: POST /muestra dice "Hola, soy dora y estás escuchando…"`.

### Task 3: `cassette-dj muestra`

**Files:**
- Modify: `src/cassette_fm/dj/cli.py` (parser + `_muestra`), `src/cassette_fm/dj/config.py` (`RutasDJ.muestras`:
  `~/.cache/cassette-dj/muestras`, al lado de `clips`)
- Modify: `README.md` (una línea en la sección de voces)
- Test: `tests/dj/test_cli.py`

**Interfaces:**
- Consumes: `ClienteDJ.muestra` (Task 2).
- Produces: `cassette-dj muestra --voz V --idioma {es,en,en-gb} [--radio R]` → imprime la ruta del WAV
  (`muestras/<sha256 de voz, idioma y radio>.wav`) y sale con 0; error del servicio → una línea por stderr y 1.

- [ ] **Step 1: tests que fallan** (con `monkeypatch.setattr(ClienteDJ, "muestra", …)`)

```python
def test_muestra_guarda_e_imprime_la_ruta_y_la_segunda_vez_no_pide(entorno, monkeypatch, capsys):
    from cassette_fm.cliente_dj import ClienteDJ
    pedidos = []
    monkeypatch.setattr(ClienteDJ, "muestra", lambda self, v, i, r: pedidos.append((v, i, r)) or b"RIFFwav")
    assert cli.main(["muestra", "--voz", "dora", "--idioma", "es", "--radio", "Sing"]) == 0
    ruta = Path(capsys.readouterr().out.strip())
    assert ruta.read_bytes() == b"RIFFwav" and ruta.parent == entorno.muestras
    assert cli.main(["muestra", "--voz", "dora", "--idioma", "es", "--radio", "Sing"]) == 0
    assert capsys.readouterr().out.strip() == str(ruta) and pedidos == [("dora", "es", "Sing")]

def test_muestra_con_el_servicio_caido_da_una_linea(entorno, monkeypatch, capsys):
    from cassette_fm.cliente_dj import ClienteDJ, ErrorDJ
    def caido(self, *a):
        raise ErrorDJ("el servicio DJ no responde en http://127.0.0.1:7720 (Connection refused)")
    monkeypatch.setattr(ClienteDJ, "muestra", caido)
    assert cli.main(["muestra", "--voz", "dora", "--idioma", "es"]) == 1
    error = capsys.readouterr().err
    assert "no responde" in error and error.count("\n") == 1
```

- [ ] **Step 2:** `.venv/bin/python -m pytest tests/dj/test_cli.py -k muestra -q` → FAIL (`invalid choice`).
- [ ] **Step 3:** implementar (URL como `_modo`: `0.0.0.0`/`::` → `127.0.0.1`; escritura atómica `.part` +
  `os.replace`). README: `cassette-dj muestra --voz dora --idioma es --radio "Sing"` deja la muestra e imprime la ruta.
- [ ] **Step 4:** mismo comando → PASS; `pytest tests/dj -q` → verde.
- [ ] **Step 5: commit** `cassette-dj muestra: pide la frase de muestra y la deja en caché`.

### Task 4: estados del botón en `logic.js`

**Files:**
- Modify: `applet/cassette-fm@cassette-fm/logic.js`, test `applet/tests/logic.test.js`

**Interfaces:**
- Produces: `argumentosMuestra(voz, nombre) -> string[]` → `["muestra", "--voz", voz.alias, "--idioma", voz.idioma,
  "--radio", nombre.trim()]`.
- Produces: `botonMuestra(voz, fase) -> {texto, activo}` con `fase` en `"quieto" | "generando" | "sonando"`:
  sin voz → `{texto: "▶", activo: false}`; quieto → `"▶"`, generando → `"…"` (activo false), sonando → `"■"`
  (activo true: corta).
- Produces: `rutaDeMuestra(stdout) -> string | null` — la última línea no vacía si termina en `.wav`.

- [ ] **Step 1: tests que fallan**

```js
test("argumentosMuestra: voz, su idioma y el nombre escrito", () => {
  assert.deepEqual(L.argumentosMuestra(VOCES[1], "  Sing 2 "),
                   ["muestra", "--voz", "emma", "--idioma", "en-gb", "--radio", "Sing 2"]);
});

test("botonMuestra", () => {
  assert.deepEqual(L.botonMuestra(null, "quieto"), { texto: "▶", activo: false });
  assert.deepEqual(L.botonMuestra(VOCES[2], "quieto"), { texto: "▶", activo: true });
  assert.deepEqual(L.botonMuestra(VOCES[2], "generando"), { texto: "…", activo: false });
  assert.deepEqual(L.botonMuestra(VOCES[2], "sonando"), { texto: "■", activo: true });
});

test("rutaDeMuestra", () => {
  assert.equal(L.rutaDeMuestra("/home/x/.cache/cassette-dj/muestras/ab.wav\n"), "/home/x/.cache/cassette-dj/muestras/ab.wav");
  assert.equal(L.rutaDeMuestra("algo raro"), null);
  assert.equal(L.rutaDeMuestra(""), null);
});
```

- [ ] **Step 2:** `node --test applet/tests/` → FAIL. **Step 3:** implementar y exportar. **Step 4:** PASS.
- [ ] **Step 5: commit** `applet: lógica del botón de muestra de voz`.

### Task 5: el botón ▶ en el modal

**Files:**
- Modify: `applet/cassette-fm@cassette-fm/applet.js`; test `tests/test_applet_estructura.py`

**Interfaces:**
- Consumes: Task 4 vía `AppletDir.logic.*`; `cassette-dj muestra` (Task 3).

- [ ] **Step 1: tests de estructura que fallan**

```python
def test_el_modal_tiene_muestra_de_voz_y_la_corta():
    js = _js()
    assert "argumentosMuestra" in js and "botonMuestra" in js and "rutaDeMuestra" in js
    assert '"cassette-dj"' in js and '"mpv"' in js
    for donde in ("_cerrar()", "_alElegirVoz(voz)", "_ocupado(si)"):
        cuerpo = js[js.index("    " + donde + " {"):]
        assert "this._cortarMuestra()" in cuerpo[:cuerpo.index("\n    }\n")], donde
```

- [ ] **Step 2:** `pytest tests/test_applet_estructura.py -q` → FAIL.
- [ ] **Step 3: implementar**
  - `_correrCassette` pasa a `_correr(programa, argumentos, segundos, callback)` (busca `programa` en el PATH o en
    `~/.local/bin`; mensaje "No encuentro el comando <programa>…"); los usos existentes pasan `"cassette"`.
    Devuelve el `Gio.Subprocess` (o `null`) para poder cortarlo.
  - Botón `St.Button` ▶ (style_class `dialog-button`) en la fila Voz, después del desplegable. `_fase` = quieto /
    generando / sonando; `_refrescar` aplica `botonMuestra(this._seleccion.voz, this._fase)` (label y `reactive`).
  - Clic: si suena → `_cortarMuestra()`; si quieto → `_correr("cassette-dj", argumentosMuestra(...), 60, …)` en fase
    generando; con ruta (`rutaDeMuestra`) → `_correr("mpv", ["--no-video", "--really-quiet", ruta], 120, …)` en fase
    sonando; al terminar → quieto. Error → `_mostrarError("No pude reproducir la muestra: " + …)` y quieto.
  - `_cortarMuestra()`: `force_exit()` del proceso en curso (si hay), fase quieto, refrescar; un callback de un
    proceso ya cortado no cambia nada (contador de muestra).
  - Llaman a `_cortarMuestra()`: `_cerrar`, `_alElegirVoz`, `_ocupado(true)`.
- [ ] **Step 4:** `pytest tests/test_applet_estructura.py tests/test_applet_logic.py -q` → PASS; `pytest -q` → verde.
- [ ] **Step 5: commit** `applet: botón ▶ para escuchar la voz elegida`.

### Task 6: prueba real y contexto

- [ ] **Step 1:** `systemctl --user restart cassette-dj`; `cassette-dj muestra --voz dora --idioma es --radio Sing` y
  `--voz daniela` (Piper): Expected: una ruta `.wav` cada una; reproducirlas con `mpv` (suena por encima de la radio).
- [ ] **Step 2:** reiniciar Cinnamon (cambió `logic.js`), abrir el modal por Eval, elegir dora, apretar ▶ y leer el
  label del botón (… → ■ → ▶); captura; cerrar el modal mientras suena y comprobar que no queda un `mpv` de la muestra
  (`pgrep -x mpv` cuenta, sin argumentos).
- [ ] **Step 3:** `docs/project-context.md`: una frase y el enlace a la spec; commit `Contexto: muestra de voz`.
