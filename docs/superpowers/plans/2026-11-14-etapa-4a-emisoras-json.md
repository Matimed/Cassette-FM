# Etapa 4a: emisoras en JSON — plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Las emisoras salen de `~/.config/cassette-fm/estaciones.json` (fuente carpeta en cualquier ruta, ajustes del
DJ por emisora), con migración automática desde las subcarpetas actuales, sin cambiar la agenda de las emisoras locales.

**Architecture:** Un módulo nuevo `emisoras.py` lee y valida el JSON (reusando la validación de ajustes del DJ de
`config.py`), migra la primera vez y ofrece un `Catalogo` que el servicio usa para escanear (rescan incluido) y para
dar la configuración del DJ de cada emisora. `biblioteca.py` escanea una lista de (nombre, carpeta) sin saber del JSON.
La identidad de una pista pasa a ser `Pista.clave` (hoy `str(ruta)`), para que la parte 4b agregue Spotify.

**Tech Stack:** Python 3.12, `json`, `tomllib`, pytest.

**Spec:** `docs/superpowers/specs/2026-11-14-etapa-4-spotify-design.md` (secciones 1, 2 y 6; Spotify llega en 4b y 4c).
Queda para 4c: que `cassette estado` muestre la fuente de la emisora (con una sola fuente no aporta).

## Global Constraints

- TDD: cada test se escribe y se ve fallar antes del código. Suite: `CASSETTE_DJ_MODELOS=$HOME/.local/share/cassette-dj/modelos .venv/bin/pytest -q`.
- Commits en español, imperativo simple, terminando con `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Git local en `main`.
- Archivo: `~/.config/cassette-fm/estaciones.json` = `rutas.config.with_name("estaciones.json")` (respeta `XDG_CONFIG_HOME`).
- Formato: lista de objetos `{"nombre": str, "fuente": {"carpeta": str} | {"spotify": str}, "dj": {...}?}`; el orden del archivo es el orden de rotación.
- Para las pistas locales `Pista.clave == str(pista.ruta)`: el orden de la agenda y las firmas del planificador **no cambian**.
- Las claves de `dj` son las mismas de `[dj.estaciones."X"]`, validadas con las mismas reglas y mensajes; lo que falta sale de `[dj]` del `config.toml`.
- Una emisora que no se puede escanear (carpeta inexistente, fuente `spotify` en 4a) se omite con una advertencia; un JSON inválido es un error de configuración.
- La migración escribe las emisoras en orden alfabético (`biblioteca.clave_orden`), igual que hoy.

## Review Focus

1. JSON editado a mano con un error (coma de más, comillas) → error claro con el número de línea; la radio no arranca a ciegas. (Task 2)
2. Rescan con el JSON roto mientras la radio suena → sigue sonando con las emisoras que tenía y la API responde 400 con el motivo, no 500. (Task 5)
3. `carpeta` con `~` → se expande; ruta relativa → error (el servicio corre bajo systemd y no tiene un directorio de trabajo fijo). (Task 2)
4. Dos emisoras que solo difieren en mayúsculas ("Lentos" y "lentos") → error de nombre repetido (la búsqueda de la radio no las distinguiría). (Task 2)
5. Link de Spotify con `?si=…`, sin él, o como URI → la misma playlist; algo que no es una playlist → error. En 4a la emisora de Spotify se omite con una advertencia que dice que llega en la próxima parte, sin romper las demás. (Tasks 2 y 5)

---

### Task 1: Clave de la pista

**Files:**
- Modify: `src/cassette_fm/biblioteca.py` (`Pista`)
- Modify: `src/cassette_fm/agenda.py:20`, `src/cassette_fm/planificador.py:41,140,346`, `src/cassette_fm/locutor.py:96`, `src/cassette_fm/radio.py:289,293`, comentario de `src/cassette_fm/intervenciones.py:21`
- Test: `tests/test_biblioteca.py`

**Interfaces:**
- Produces: `Pista.clave -> str` (propiedad; hoy `str(self.ruta)`). Todo lo que usaba `str(pista.ruta)` como identidad usa `pista.clave`. `reproductor.py` sigue usando `pista.ruta` para cargar el archivo en mpv (eso no es identidad).

- [ ] **Step 1: Test que falla** en `tests/test_biblioteca.py`:

```python
def test_la_clave_de_una_pista_local_es_su_ruta(tmp_path, crear_mp3):
    p = leer_pista(crear_mp3(tmp_path / "x.mp3", 2, titulo="T", artista="A"))
    assert p.clave == str(tmp_path / "x.mp3")
```

- [ ] **Step 2:** correrlo → FAIL (`AttributeError: 'Pista' object has no attribute 'clave'`).
- [ ] **Step 3:** agregar la propiedad y reemplazar los usos de identidad listados arriba.
- [ ] **Step 4:** suite completa → PASS (los tests existentes de agenda y planificador fijan que el orden y las firmas no cambian).
- [ ] **Step 5: Commit** — `Pista: la identidad pasa a ser una clave de texto (la ruta, para las locales)`.

### Task 2: Leer y validar `estaciones.json`

**Files:**
- Create: `src/cassette_fm/emisoras.py`
- Modify: `src/cassette_fm/config.py` (renombrar `_campos_dj` → `campos_dj`, pública; mismos parámetros)
- Test: `tests/test_emisoras.py`

**Interfaces:**
- Consumes: `config.campos_dj(archivo: Path, tabla: dict, donde: str, base: ConfigDJ) -> dict`, `config.ErrorConfig`, `config.ConfigDJ`.
- Produces:
  - `@dataclass(frozen=True) class Fuente: tipo: str; valor: str` — `tipo` es `"carpeta"` (valor = ruta absoluta expandida, como texto) o `"spotify"` (valor = id de la playlist, 22 caracteres base62).
  - `@dataclass(frozen=True) class DefEmisora: nombre: str; fuente: Fuente; dj: ConfigDJ; dj_crudo: dict` — `dj` ya fusionado con el general; `dj_crudo` es la tabla tal como vino (la usa la migración y sirve para depurar).
  - `def leer_emisoras(archivo: Path, general: ConfigDJ) -> list[DefEmisora]` — lanza `ErrorConfig` con el archivo en el mensaje.
  - `def playlist_de(texto: str) -> str | None` — id de la playlist de un link `https://open.spotify.com/playlist/<id>` (con o sin `?…`, con o sin prefijo de idioma `intl-xx/`) o de `spotify:playlist:<id>`; `None` si no es una playlist.

- [ ] **Step 1: Tests que fallan** en `tests/test_emisoras.py` (helper `escribir(tmp_path, datos)` que vuelca JSON a `estaciones.json`):

```python
def test_lee_carpeta_y_dj_fusionado_con_el_general(tmp_path):
    a = escribir(tmp_path, [{"nombre": "Lentos", "fuente": {"carpeta": str(tmp_path / "m")},
                             "dj": {"voz": "af_nicole", "frecuencia": {"min": 1, "max": 1}}}])
    (e,) = leer_emisoras(a, ConfigDJ(idioma="en", duracion_maxima_segundos=25))
    assert e.nombre == "Lentos" and e.fuente == Fuente("carpeta", str(tmp_path / "m"))
    assert e.dj.voz == "af_nicole" and e.dj.idioma == "en" and e.dj.duracion_maxima_segundos == 25.0
    assert e.dj.frecuencia.min == 1 and e.dj_crudo == {"voz": "af_nicole", "frecuencia": {"min": 1, "max": 1}}

def test_respeta_el_orden_del_archivo(tmp_path): ...       # ["Zeta", "Alfa"] → mismos nombres en ese orden

def test_carpeta_con_tilde_se_expande_y_relativa_es_error(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    (e,) = leer_emisoras(escribir(tmp_path, [{"nombre": "A", "fuente": {"carpeta": "~/m"}}]), ConfigDJ())
    assert e.fuente.valor == str(tmp_path / "m")
    with pytest.raises(ErrorConfig, match="absoluta"):
        leer_emisoras(escribir(tmp_path, [{"nombre": "A", "fuente": {"carpeta": "m"}}]), ConfigDJ())

@pytest.mark.parametrize("link", ["https://open.spotify.com/playlist/4iHcTVQbU4QvIJV5Xao0fs?si=3572b2afcfa0465a",
                                  "https://open.spotify.com/playlist/4iHcTVQbU4QvIJV5Xao0fs",
                                  "https://open.spotify.com/intl-es/playlist/4iHcTVQbU4QvIJV5Xao0fs",
                                  "spotify:playlist:4iHcTVQbU4QvIJV5Xao0fs"])
def test_links_de_playlist(link):
    assert playlist_de(link) == "4iHcTVQbU4QvIJV5Xao0fs"

@pytest.mark.parametrize("link", ["https://open.spotify.com/album/4iHcTVQbU4QvIJV5Xao0fs",
                                  "spotify:track:4iHcTVQbU4QvIJV5Xao0fs", "hola", ""])
def test_lo_que_no_es_una_playlist(link):
    assert playlist_de(link) is None

def test_fuente_spotify_se_guarda_como_id(tmp_path): ...    # Fuente("spotify", "4iHcTVQbU4QvIJV5Xao0fs")

@pytest.mark.parametrize("datos, mensaje", [
    ({"nombre": "A", "fuente": {"spotify": "spotify:album:x"}}, "playlist"),
    ({"nombre": "A", "fuente": {"carpeta": "/m", "spotify": "spotify:playlist:4iHcTVQbU4QvIJV5Xao0fs"}}, "una sola"),
    ({"nombre": "A", "fuente": {}}, "una sola"),
    ({"nombre": "A", "fuente": {"cassette": "/m"}}, "carpeta"),
    ({"nombre": "", "fuente": {"carpeta": "/m"}}, "nombre"),
    ({"fuente": {"carpeta": "/m"}}, "nombre"),
    ({"nombre": "A"}, "fuente"),
    ({"nombre": "A", "fuente": {"carpeta": "/m"}, "color": "rojo"}, "color"),
    ({"nombre": "A", "fuente": {"carpeta": "/m"}, "dj": {"idioma": "fr"}}, "idioma"),
    ({"nombre": "A", "fuente": {"carpeta": "/m"}, "dj": "af_heart"}, "dj"),
])
def test_errores_de_una_emisora(tmp_path, datos, mensaje):
    with pytest.raises(ErrorConfig, match=mensaje):
        leer_emisoras(escribir(tmp_path, [datos]), ConfigDJ())

def test_el_mensaje_del_dj_dice_que_emisora(tmp_path):
    with pytest.raises(ErrorConfig, match='"Lentos".*idioma'):
        leer_emisoras(escribir(tmp_path, [{"nombre": "Lentos", "fuente": {"carpeta": "/m"}, "dj": {"idioma": "fr"}}]), ConfigDJ())

def test_nombres_repetidos_sin_importar_mayusculas(tmp_path):
    with pytest.raises(ErrorConfig, match="repetid"):
        leer_emisoras(escribir(tmp_path, [{"nombre": "Lentos", "fuente": {"carpeta": "/a"}},
                                          {"nombre": "lentos", "fuente": {"carpeta": "/b"}}]), ConfigDJ())

def test_json_roto_dice_la_linea(tmp_path):
    a = tmp_path / "estaciones.json"
    a.write_text('[\n  {"nombre": "A", "fuente": {"carpeta": "/m"}},\n]\n')
    with pytest.raises(ErrorConfig, match=r"estaciones\.json.*l[ií]nea 3"):
        leer_emisoras(a, ConfigDJ())

def test_la_raiz_tiene_que_ser_una_lista(tmp_path):
    with pytest.raises(ErrorConfig, match="lista"):
        leer_emisoras(escribir(tmp_path, {"nombre": "A"}), ConfigDJ())
```

- [ ] **Step 2:** correrlos → FAIL (no existe el módulo).
- [ ] **Step 3:** implementar en `emisoras.py`. Nombres repetidos: misma normalización que `radio._normalizar` (NFC + `casefold`). El prefijo `donde` para `campos_dj` es `f'"{nombre}".dj.'` (así el mensaje sale `…estaciones.json: '"Lentos".dj.idioma' tiene que ser…`). Campos permitidos por emisora: `nombre`, `fuente`, `dj`.
- [ ] **Step 4:** `tests/test_emisoras.py` y `tests/test_config.py` → PASS.
- [ ] **Step 5: Commit** — `Emisoras: lectura y validación de estaciones.json (carpeta o playlist de Spotify, ajustes del DJ)`.

### Task 3: Migración desde las subcarpetas

**Files:**
- Modify: `src/cassette_fm/biblioteca.py`
- Modify: `src/cassette_fm/emisoras.py`
- Test: `tests/test_biblioteca.py`, `tests/test_emisoras.py`

**Interfaces:**
- Produces:
  - `biblioteca.carpetas_de_estaciones(raiz: Path) -> list[Path]` — las subcarpetas que hoy forman una estación (no ocultas, nombre UTF-8 válido, con al menos un archivo de audio en cualquier nivel), ordenadas con `clave_orden(nombre)`. `escanear(raiz, cache)` pasa a usarla (mismo resultado que hoy).
  - `emisoras.migrar_emisoras(archivo: Path, raiz: Path, toml: Path) -> bool` — si `archivo` no existe y hay carpetas, escribe el JSON (escritura atómica, `indent=2`, `ensure_ascii=False`) y devuelve `True`; si ya existe o no hay carpetas, no escribe nada y devuelve `False`. La tabla `dj` de cada emisora es la `[dj.estaciones."<nombre de la carpeta>"]` del `toml` tal cual (cruda, vía `tomllib`); sin tabla, la emisora no lleva `dj`. Loguea (INFO) cuántas emisoras migró y adónde; loguea (WARNING) las `[dj.estaciones]` que no corresponden a ninguna carpeta.

- [ ] **Step 1: Tests que fallan:**

```python
# tests/test_biblioteca.py
def test_carpetas_de_estaciones(tmp_path, crear_mp3):
    crear_mp3(tmp_path / "b" / "x.mp3"); crear_mp3(tmp_path / "Árbol" / "sub" / "y.mp3")
    (tmp_path / "vacia").mkdir(); crear_mp3(tmp_path / ".oculta" / "z.mp3")
    assert [c.name for c in carpetas_de_estaciones(tmp_path)] == ["Árbol", "b"]
    assert carpetas_de_estaciones(tmp_path / "no-existe") == []

# tests/test_emisoras.py
def test_migra_las_carpetas_con_sus_ajustes(tmp_path, crear_mp3):
    musica = tmp_path / "Música"
    crear_mp3(musica / "Power F.M." / "a.mp3"); crear_mp3(musica / "Happy Eighties" / "b.mp3")
    toml = tmp_path / "config.toml"
    toml.write_text('[dj]\nactivo = true\n[dj.estaciones."Power F.M."]\nidioma = "en"\nvoz = "am_onyx"\n'
                    '[dj.estaciones."Power F.M.".frecuencia]\nmin = 1\nmax = 1\n')
    archivo = tmp_path / "estaciones.json"
    assert migrar_emisoras(archivo, musica, toml) is True
    assert json.loads(archivo.read_text()) == [
        {"nombre": "Happy Eighties", "fuente": {"carpeta": str(musica / "Happy Eighties")}},
        {"nombre": "Power F.M.", "fuente": {"carpeta": str(musica / "Power F.M.")},
         "dj": {"idioma": "en", "voz": "am_onyx", "frecuencia": {"min": 1, "max": 1}}}]
    (_, power) = leer_emisoras(archivo, ConfigDJ())
    assert power.dj.voz == "am_onyx" and power.dj.frecuencia.max == 1

def test_no_pisa_un_json_existente(tmp_path, crear_mp3): ...      # archivo con "[]" → False y sigue "[]"
def test_sin_carpetas_no_escribe(tmp_path): ...                    # raíz vacía o inexistente → False, no hay archivo
def test_sin_toml_migra_sin_dj(tmp_path, crear_mp3): ...           # toml inexistente → emisoras sin "dj"
def test_ajustes_de_una_estacion_sin_carpeta_avisan(tmp_path, crear_mp3, caplog): ...   # WARNING con el nombre
```

- [ ] **Step 2:** correrlos → FAIL.
- [ ] **Step 3:** implementar `carpetas_de_estaciones` (y que `escanear` la use) y `migrar_emisoras`.
- [ ] **Step 4:** `tests/test_biblioteca.py tests/test_emisoras.py` → PASS.
- [ ] **Step 5: Commit** — `Emisoras: migración automática desde las subcarpetas y [dj.estaciones]`.

### Task 4: Escanear una lista de carpetas

**Files:**
- Modify: `src/cassette_fm/biblioteca.py`
- Test: `tests/test_biblioteca.py`

**Interfaces:**
- Produces:
  - `Estacion` gana `fuente: str = "carpeta"` (al final, con valor por defecto: los usos existentes no cambian).
  - `biblioteca.escanear_carpetas(pares: Sequence[tuple[str, Path]], cache: Path | None = None) -> list[Estacion]` — una `Estacion` por par, **en el orden recibido**, con las pistas de esa carpeta ordenadas por clave (como hoy) y la misma caché de duraciones (una sola caché para todas: se guarda una vez al final con las entradas de todas las carpetas). Una carpeta inexistente o ilegible se omite con WARNING `"la emisora %r: no se puede leer %s"`; una carpeta sin audio, con WARNING `"la emisora %r no tiene música en %s"`. `escanear(raiz, cache)` queda como `escanear_carpetas([(c.name, c) for c in carpetas_de_estaciones(raiz)], cache)`.

- [ ] **Step 1: Tests que fallan:**

```python
def test_escanear_carpetas_es_igual_que_la_raiz(tmp_path, crear_mp3):
    crear_mp3(tmp_path / "A" / "1.mp3", titulo="uno"); crear_mp3(tmp_path / "A" / "2.mp3", titulo="dos")
    crear_mp3(tmp_path / "B" / "3.mp3")
    viejo = escanear(tmp_path)
    nuevo = escanear_carpetas([("A", tmp_path / "A"), ("B", tmp_path / "B")])
    assert nuevo == viejo                      # mismas pistas, mismo orden: la agenda no cambia
    assert [secuencia_nombres(e) for e in nuevo] == [secuencia_nombres(e) for e in viejo]

def test_respeta_el_orden_y_permite_carpetas_fuera_de_la_raiz(tmp_path, crear_mp3): ...   # ("Zeta", /x), ("Alfa", /y)
def test_carpeta_inexistente_o_vacia_se_omite_y_avisa(tmp_path, crear_mp3, caplog): ...
def test_una_sola_cache_para_todas(tmp_path, crear_mp3): ...      # caché con las claves de las dos carpetas
```

(`secuencia_nombres(e)` = títulos de los primeros 10 temas de `agenda.secuencia(e, EPOCA + 12345)`.)

- [ ] **Step 2:** correrlos → FAIL.
- [ ] **Step 3:** implementar.
- [ ] **Step 4:** `tests/test_biblioteca.py tests/test_agenda.py` → PASS.
- [ ] **Step 5: Commit** — `Biblioteca: escanear una lista de emisoras con carpetas en cualquier ruta`.

### Task 5: Catálogo, servicio, rescan y documentación

**Files:**
- Modify: `src/cassette_fm/emisoras.py`, `src/cassette_fm/config.py` (`Rutas.emisoras`), `src/cassette_fm/servicio.py`, `src/cassette_fm/api.py`, `src/cassette_fm/cli.py`, `README.md`, `docs/project-context.md`
- Test: `tests/test_emisoras.py`, `tests/test_servicio.py`, `tests/test_api.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: Tasks 2–4.
- Produces:
  - `Rutas.emisoras -> Path` (propiedad: `self.config.with_name("estaciones.json")`).
  - `class Catalogo` en `emisoras.py`: `__init__(self, config: Config, rutas: Rutas)`; `escanear(self) -> list[Estacion]` (si no existe el JSON, `migrar_emisoras(rutas.emisoras, config.raiz_musica, rutas.config)`; después `leer_emisoras(rutas.emisoras, config.dj)`; escanea las de fuente `carpeta` con `biblioteca.escanear_carpetas(…, rutas.cache)`; las de fuente `spotify` se omiten con WARNING `"la emisora %r es de Spotify: llega en la próxima parte (4b)"`; recién si todo salió bien reemplaza los ajustes del DJ vigentes; un `ErrorConfig` se propaga y deja todo como estaba); `configuracion_dj(self, nombre: str) -> ConfigDJ` (la de la emisora, o `config.dj` si no está). Si el JSON ya existía y `config.estaciones_dj` no está vacío, WARNING una sola vez: `"[dj.estaciones] del config.toml se ignora: los ajustes de cada emisora están en estaciones.json"`.
  - `servir` usa `Catalogo`: `escanear=catalogo.escanear` y `configuracion_dj=catalogo.configuracion_dj` (en el locutor, la radio y el planificador). El log de arranque dice `"%d estaciones (de %s)"` con el archivo.
  - `api.py`: un `ErrorConfig` en un POST (el rescan) → 400 con el mensaje. `crear_servidor(…, raiz=…)` pasa a recibir el archivo de emisoras y el mensaje de `SinEstaciones` dice `"No hay estaciones: revisá {archivo}"`.
  - `cli.py`: `serve` atrapa `ErrorConfig` de `servir` (JSON inválido al arrancar) → mensaje a stderr y código 1.

- [ ] **Step 1: Tests que fallan:**

```python
# tests/test_emisoras.py
def test_catalogo_migra_escanea_y_da_el_dj(tmp_path, crear_mp3): ...
    # raíz con "A" y "B", toml con [dj.estaciones."B"] voz = "am_onyx" → escanear() da ["A", "B"],
    # crea estaciones.json, configuracion_dj("B").voz == "am_onyx", configuracion_dj("X") == config.dj
def test_catalogo_relee_el_json_en_cada_escaneo(tmp_path, crear_mp3): ...   # cambio el orden y el dj → se refleja
def test_catalogo_con_json_roto_lanza_y_conserva_lo_anterior(tmp_path, crear_mp3): ...
    # 1.º escanear() OK; rompo el JSON; escanear() lanza ErrorConfig; configuracion_dj sigue dando lo de antes
def test_catalogo_omite_spotify_con_aviso(tmp_path, crear_mp3, caplog): ...  # emisora spotify + una carpeta → 1 estación, WARNING "4b"
def test_catalogo_avisa_que_dj_estaciones_del_toml_se_ignora(tmp_path, crear_mp3, caplog): ...

# tests/test_servicio.py
def test_servir_migra_y_usa_el_json(tmp_path, dir_corto, crear_mp3): ...
    # como test_servir_de_punta_a_punta; después de arrancar existe rutas.emisoras con A y B;
    # reescribo el JSON con solo ["B", "A"] y una carpeta nueva fuera de la raíz; POST /rescan → estaciones == ["B", "A", ...]

# tests/test_api.py
def test_rescan_con_config_rota_es_400(...): ...   # el falso de radio.rescan lanza ErrorConfig("x.json: línea 3") → 400 con ese texto

# tests/test_cli.py
def test_serve_con_estaciones_json_roto_sale_con_1(...): ...   # monkeypatch servicio.servir para lanzar ErrorConfig → rc 1, mensaje en stderr
```

- [ ] **Step 2:** correrlos → FAIL.
- [ ] **Step 3:** implementar. README: reemplazar "cada subcarpeta es una estación" por la sección "Emisoras" (formato del JSON con un ejemplo de carpeta y uno de Spotify marcado "desde la parte 4b", migración automática, que el orden es el del archivo, que `cassette rescan` lo relee y que `[dj.estaciones]` del `config.toml` ya no se usa). `docs/project-context.md`: una línea con el cambio y el enlace al diseño de la etapa 4.
- [ ] **Step 4:** suite completa → PASS.
- [ ] **Step 5: Commit** — `Radio: las emisoras salen de estaciones.json (migración, rescan y ajustes del DJ por emisora)`.

## Verificación con el usuario (al final)

Reiniciar `cassette-fm` con la config real: tiene que crear `~/.config/cassette-fm/estaciones.json` con sus 6 emisoras y
voces, sonar igual que antes (misma emisora, mismo tema en el mismo segundo) y el DJ seguir con sus voces. Después,
reordenar dos emisoras en el JSON y hacer `cassette rescan`.
