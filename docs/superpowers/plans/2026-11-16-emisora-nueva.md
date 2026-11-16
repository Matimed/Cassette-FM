# Crear una emisora de Spotify con un comando — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `cassette nueva NOMBRE LINK [--voz X] [--idioma es|en]` agrega una emisora de Spotify con un DJ de voz
propia, hace el rescan y la sintoniza.

**Architecture:** Un módulo puro `emisora_nueva.py` (leer el JSON crudo, validar el nombre, deducir el idioma de una
voz, elegir la voz, guardar) y el subcomando en `cli.py` que lo usa con el catálogo de Spotify y el servicio.

**Tech Stack:** Python 3, pytest (`.venv/bin/pytest -q -p no:cacheprovider`).

**Spec:** `docs/superpowers/specs/2026-11-16-emisora-nueva-design.md`

## Global Constraints

- Commits en español, imperativo llano, con `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Otro agente trabaja en paralelo (toca `dj/cli.py`, `tests/dj/test_cli.py`, plantillas, producción, README):
  commitear solo archivos propios con rutas explícitas.
- Idiomas válidos de una emisora: los de `config._IDIOMAS` (`es`, `en`, `en-us`, `en-gb`).
- Los tests no tocan el `estaciones.json` ni el config del DJ reales (XDG en `tmp_path`).

## Review Focus

1. Un `estaciones.json` roto o inexistente: error claro y el archivo no se toca.
2. Un nombre repetido con otras mayúsculas o espacios alrededor («happy eighties ») se rechaza antes de bajar nada.
3. La playlist ajena (403/404) o vacía: no se escribe nada en `estaciones.json`.
4. `--voz` con un alias inexistente o de un idioma que no coincide con `--idioma`: error con la lista de alias.
5. La radio apagada o el servicio caído después de guardar: la emisora queda guardada y el mensaje lo dice (código 0).

---

### Task 1: Módulo `emisora_nueva`

**Files:** Create `src/cassette_fm/emisora_nueva.py`; Test `tests/test_emisora_nueva.py`.

**Interfaces — Produces:**
- `leer_crudo(archivo: Path) -> list[dict]` — ErrorConfig si falta, no es JSON o no es una lista.
- `chequear_nombre(emisoras: list[dict], nombre: str) -> str` — el nombre sin espacios alrededor; ErrorConfig si
  vacío o repetido (comparación `unicodedata.normalize("NFC", n).casefold()`, como `emisoras._normalizar`).
- `idioma_de_voz(voz: str) -> str | None` — de una voz ya resuelta (sin alias), según la tabla de la spec.
- `elegir_voz(alias: Mapping[str, str], en_uso: list[str], idioma: str | None = None, voz: str | None = None,
  azar: random.Random | None = None) -> Eleccion` — `Eleccion(voz: str, idioma: str, repetida: bool)` (frozen
  dataclass); ErrorConfig con motivo legible si no se puede.
- `voces_en_uso(emisoras: list[dict]) -> list[str]` — los `dj.voz` (texto) de cada emisora.
- `guardar(archivo: Path, emisoras: list[dict], nueva: dict) -> None` — lista + nueva, `indent=2`,
  `ensure_ascii=False`, `\n` final, escritura atómica (tmp + `os.replace`).

- [ ] **Step 1: Tests que fallan** (en `tests/test_emisora_nueva.py`):

```python
ALIAS = {"puck": "am_puck", "sarah": "af_sarah", "dora": "ef_dora", "daniela": "piper:es_AR-daniela-high",
         "alex_santa": "em_alex+em_santa", "emma": "bf_emma", "siwis": "ff_siwis"}

@pytest.mark.parametrize("voz,idioma", [("am_puck", "en"), ("af_sarah", "en"), ("bf_emma", "en-gb"),
    ("ef_dora", "es"), ("em_alex+em_santa", "es"), ("piper:es_AR-daniela-high", "es"),
    ("piper:en_GB-alba-medium", "en-gb"), ("piper:en_US-amy-low", "en"), ("ff_siwis", None), ("raro", None)])
def test_idioma_de_voz(voz, idioma)

def test_elige_un_alias_libre_al_azar():
    # en_uso = ["puck", "dora", "daniela", "alex_santa"]; random.Random(1) → voz ∈ {"sarah", "emma"}, no repetida
def test_filtra_por_idioma():           # idioma="es", en_uso=["dora"] → voz ∈ {"daniela", "alex_santa"}, idioma "es"
def test_en_ingles_acepta_en_gb():      # idioma="en" con solo "emma" libre en inglés → "emma", idioma "en-gb"
def test_todas_en_uso_repite_la_menos_usada():
    # en_uso con cada alias en inglés 2 veces salvo "sarah" 1 vez, idioma="en" → "sarah", repetida True
def test_voz_elegida_da_su_idioma():    # voz="dora" → Eleccion("dora", "es", False)
def test_voz_cruda_sin_alias():         # voz="am_onyx" → Eleccion("am_onyx", "en", False)
def test_voz_que_no_coincide_con_el_idioma_es_error():   # voz="dora", idioma="en" → ErrorConfig
def test_voz_inexistente_o_de_otro_idioma_es_error():    # voz="siwis" y voz="nadie" → ErrorConfig que nombra alias
def test_sin_alias_es_error():          # alias={} → ErrorConfig con "[voces]"
def test_leer_crudo_roto_o_inexistente_es_error(tmp_path)   # "{", "{}" y archivo ausente → ErrorConfig
def test_chequear_nombre_repetido_sin_mayusculas_ni_espacios():
    # [{"nombre": "Happy Eighties"}], " happy eighties " → ErrorConfig; "  Nueva  " → "Nueva"
def test_guardar_agrega_al_final_y_es_json_legible(tmp_path):
    # guardar → json.loads(texto) == viejas + [nueva], texto con "Más" sin escapar y termina en "\n"
```

- [ ] **Step 2:** `.venv/bin/pytest tests/test_emisora_nueva.py -q -p no:cacheprovider` → FAIL (no existe el módulo).
- [ ] **Step 3: Implementar** según las interfaces. `elegir_voz`: si viene `voz`, resolverla por `alias` (o tomarla
  cruda si no es alias pero `idioma_de_voz` la reconoce), si no, candidatos = alias cuyo idioma resuelto no es None
  y coincide con `idioma` (comparando solo el prefijo `es`/`en`); libres = no en `en_uso`; si hay libres, `azar.choice`
  entre ellos (orden del config); si no, entre los de menos usos, con `repetida=True`.
- [ ] **Step 4:** test del archivo → PASS.
- [ ] **Step 5: Commit** `Emisora nueva: elegir la voz, deducir el idioma y guardar en estaciones.json`

### Task 2: Subcomando `cassette nueva`

**Files:** Modify `src/cassette_fm/cli.py`; Test `tests/test_cli.py`; README (sección Spotify, una viñeta).

**Interfaces — Consumes:** Task 1; `emisoras.playlist_de`; `servicio.catalogo_spotify(cfg, rutas)` (`.pistas(id)`,
`.nombre(id)`); `cassette_fm.dj.config.rutas_dj().config` y `cargar_config_dj(archivo).voces` (si el archivo no
existe, alias vacíos); `_llamar(puerto, "POST", "/rescan", timeout=120)` y `/sintonizar` con `{"estacion": nombre}`.

- [ ] **Step 1: Tests que fallan** (en `tests/test_cli.py`, con `_rutas_tmp`, `servidor_http` para Spotify y
  `XDG_CONFIG_HOME=tmp_path` con `cassette-dj/config.toml` que tiene `[voces]`; `_llamar` reemplazado por un falso que
  anota las rutas):

```python
def test_nueva_guarda_rescanea_y_sintoniza(...):
    # main(["nueva", "Synthwave F.M.", LINK]) == 0; estaciones.json termina con
    # {"nombre": "Synthwave F.M.", "fuente": {"spotify": LINK}, "dj": {"idioma": "en", "voz": <alias libre>}};
    # rutas llamadas == ["/rescan", "/sintonizar"]; salida con "✓ Synthwave F.M. (1 temas) · DJ: <voz> (en)"
def test_nueva_con_nombre_repetido_no_baja_nada(...):   # código 1, sin pedidos a Spotify, archivo igual
def test_nueva_con_link_que_no_es_playlist(...):        # código 1, mensaje con "playlist"
def test_nueva_con_playlist_ajena_no_guarda(...):       # items → 403: código 1, "no es tuya", archivo igual
def test_nueva_con_playlist_vacia_no_guarda(...):       # items vacíos: código 1, "vacía", archivo igual
def test_nueva_con_el_servicio_caido_queda_guardada(...):
    # _llamar lanza _ErrorCli("cassette-fm no está corriendo…"): código 0, emisora guardada,
    # salida dice que aparece al arrancar la radio
```

- [ ] **Step 2:** `.venv/bin/pytest tests/test_cli.py -q -p no:cacheprovider -k nueva` → FAIL.
- [ ] **Step 3: Implementar** `nueva` en `_armar_parser` (`nombre`, `link`, `--voz`, `--idioma` con choices
  `es`/`en`) y `_nueva(args, cfg, rutas, puerto) -> int` despachado desde `main` antes de `_ejecutar`. Orden:
  leer crudo → chequear nombre → `playlist_de` → elegir voz → bajar la playlist (`ErrorSpotify` → código 1; 0 temas →
  "la playlist está vacía") → guardar → imprimir `✓ …` (y "(repite la voz de otra emisora)" si `repetida`) →
  rescan y sintonizar imprimiendo `_linea_estado`; `_ErrorCli` ahí → aviso y código 0.
- [ ] **Step 4:** suite completa → PASS.
- [ ] **Step 5:** README: viñeta de `cassette nueva` en la sección Spotify.
- [ ] **Step 6: Commit** `cassette nueva: crea una emisora de Spotify, la rescanea y la sintoniza`

### Task 3: Prueba real

- [ ] Reiniciar `cassette-fm`, crear una emisora con una playlist propia del usuario (preguntarle cuál), verificar que
  suena con la voz elegida y dejar la radio como estaba.
