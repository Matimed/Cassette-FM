# Etapa 1: Radio local (MVP) — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Servicio local que hace sonar cada subcarpeta de `~/Música` como una radio continua (con reloj virtual,
entrando a mitad del tema) y se controla con la CLI `cassette`.

**Architecture:** Paquete Python `cassette_fm`. La agenda es una función pura (estación + instante → pistas con
desplazamiento). El reproductor alimenta a mpv (proceso hijo, JSON IPC) con esa secuencia. `Radio` orquesta
estaciones, encendido y volumen; una API HTTP (stdlib) la expone en 127.0.0.1 y la CLI es un cliente de esa API.

**Tech Stack:** Python 3.12, mutagen, mpv 0.37 (JSON IPC), `http.server`/`urllib` de la stdlib, pytest, systemd de usuario.

**Spec:** [`docs/superpowers/specs/2026-11-13-cassette-fm-design.md`](../specs/2026-11-13-cassette-fm-design.md)

## Global Constraints

- Python ≥ 3.12. Dependencia de runtime **solo `mutagen`**; de desarrollo, `pytest`. HTTP con la stdlib (sin frameworks).
- Entorno: `python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"` (no hay `uv` ni `pipx` en el equipo).
- Identificadores, mensajes y docstrings **en español**, como el resto del proyecto.
- mpv por JSON IPC usando **comandos con argumentos nombrados** para `loadfile` (`{"name": "loadfile", "url": …, "flags": …, "options": {"start": "12.345"}}`), verificado con mpv 0.37.
- El socket de mpv va en `$XDG_RUNTIME_DIR/cassette-fm/mpv.sock` (los sockets Unix admiten ~108 caracteres; en tests, usar un directorio corto creado con `tempfile.mkdtemp(dir=os.environ.get("XDG_RUNTIME_DIR", "/tmp"))`).
- La API escucha **solo en `127.0.0.1`**, puerto por defecto **7710**.
- Época del reloj virtual: `2026-01-01T00:00:00Z` = `1767225600.0`.
- Formatos de audio: `.mp3 .flac .ogg .m4a` (comparación sin distinguir mayúsculas).
- Rutas XDG: config `$XDG_CONFIG_HOME/cassette-fm/config.toml`, estado `$XDG_STATE_HOME/cassette-fm/estado.json`, caché `$XDG_CACHE_HOME/cassette-fm/duraciones.json` (con los defaults de XDG si las variables no están).
- El servicio **arranca en silencio**; sin pausa real (apagar/encender resintoniza "en vivo").
- Fixtures de audio: mp3 sintéticos generados en los tests (sin ffmpeg): frames MPEG-1 Layer III 128 kbps/44,1 kHz `b"\xff\xfb\x90\x64" + b"\x00" * 413` (1152 muestras c/u), tags con `mutagen.easyid3.EasyID3`. mutagen reporta la duración con ±0,05 s.
- Tests contra mpv real con `--ao=null`.
- Commits en español, texto plano en imperativo (sin prefijos tipo `feat:`), terminando con `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Al empezar cada tarea, `beans update <id> -s in-progress`; al terminarla, `-s completed` y se incluye `.beans/` en el commit de la tarea.

## Review Focus

1. **Nombres de estación con espacios, acentos y ñ** (`Regueton 2000`, `Música Ñandú`): tienen que viajar bien por JSON, URL y CLI (`cassette tune Regueton 2000` sin comillas). → test en Task 8 y Task 10.
2. **Archivo borrado o ilegible entre el escaneo y la reproducción**: la radio tiene que saltar al siguiente, no quedar muda. → test de integración en Task 6.
3. **mpv se cae** (crash, `kill`): el siguiente comando tiene que relanzarlo, no colgar al servicio. → test en Task 5.
4. **Biblioteca vacía o raíz inexistente**: el servicio arranca igual y `cassette on` dice claramente que no hay estaciones. → tests en Task 7 y Task 8.
5. **Cambios rápidos de estación** (rueda del mouse, flechas repetidas): termina sonando la última sintonizada, sin eventos viejos que pisen la pista actual. → test en Task 6 y Task 7.

---

## Estructura de archivos

```
pyproject.toml
src/cassette_fm/__init__.py      # __version__
src/cassette_fm/config.py        # Config, Estado, Rutas, carga/guardado
src/cassette_fm/biblioteca.py    # Pista, Estacion, leer_pista, escanear (+ caché de duraciones)
src/cassette_fm/agenda.py        # EPOCA, orden_ciclo, secuencia
src/cassette_fm/mpv.py           # ClienteMpv, ErrorMpv
src/cassette_fm/reproductor.py   # Reproductor
src/cassette_fm/radio.py         # Radio, EstacionInexistente, SinEstaciones
src/cassette_fm/avisos.py        # Notificador
src/cassette_fm/api.py           # crear_servidor
src/cassette_fm/servicio.py      # servir (arma todo y corre)
src/cassette_fm/cli.py           # main
tests/conftest.py                # fixtures: crear_mp3, dir_corto
tests/test_<módulo>.py
scripts/instalar.sh
packaging/cassette-fm.service.in
README.md
```

---

### Task 1: Esqueleto del proyecto (bean `CASSETTE-FM-na6t`)

**Files:**
- Create: `pyproject.toml`, `src/cassette_fm/__init__.py`, `src/cassette_fm/cli.py` (stub), `tests/conftest.py`, `tests/test_fixtures.py`

**Interfaces:**
- Produces:
  - `cassette_fm.__version__ = "0.1.0"`
  - entry point `cassette = "cassette_fm.cli:main"`; `main(argv: list[str] | None = None) -> int` (stub: `--version` imprime la versión, devuelve 0)
  - fixture `crear_mp3(ruta: Path, segundos: float = 3.0, titulo: str | None = None, artista: str | None = None) -> Path` (crea directorios padres)
  - fixture `dir_corto() -> Path` (directorio temporal de ruta corta para sockets; se borra al final)

- [ ] **Step 1:** `pyproject.toml` con build backend setuptools, layout `src/`, `requires-python = ">=3.12"`, `dependencies = ["mutagen"]`, extra `dev = ["pytest"]`, `[tool.pytest.ini_options] testpaths = ["tests"]`. Crear `.venv` e instalar con `pip install -e ".[dev]"`.
- [ ] **Step 2: Test que falla** — `tests/test_fixtures.py`:

```python
def test_crear_mp3_tiene_duracion_y_tags(tmp_path, crear_mp3):
    p = crear_mp3(tmp_path / "a" / "t.mp3", segundos=3, titulo="Tema", artista="Artista")
    f = mutagen.File(p, easy=True)
    assert abs(f.info.length - 3) < 0.05
    assert f["title"] == ["Tema"] and f["artist"] == ["Artista"]

def test_cli_version(capsys):
    assert main(["--version"]) == 0
    assert "0.1.0" in capsys.readouterr().out
```

- [ ] **Step 3:** Correr `.venv/bin/pytest -v` → FAIL (fixture inexistente).
- [ ] **Step 4:** Implementar fixtures en `conftest.py` (frames según Global Constraints; `n = ceil(segundos * 44100 / 1152)`) y el stub de `cli.main` con `argparse`.
- [ ] **Step 5:** `.venv/bin/pytest -v` → PASS. `.venv/bin/cassette --version` imprime `0.1.0`.
- [ ] **Step 6:** Commit `Esqueleto del proyecto Python con pytest y fixtures de audio`.

---

### Task 2: Configuración y estado (bean `CASSETTE-FM-dwgu`)

**Files:** Create `src/cassette_fm/config.py`, `tests/test_config.py`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True)
class Config:
    raiz_musica: Path = Path.home() / "Música"
    puerto: int = 7710
    avisos: bool = True

@dataclass
class Estado:
    estacion: str | None = None
    volumen: int = 70

@dataclass(frozen=True)
class Rutas:
    config: Path; estado: Path; cache: Path; runtime: Path   # runtime = dir del socket

def rutas() -> Rutas                      # lee XDG_* del entorno en cada llamada
def cargar_config(archivo: Path) -> Config
def cargar_estado(archivo: Path) -> Estado
def guardar_estado(archivo: Path, estado: Estado) -> None
```

Nota: "encendido" **no** se persiste, porque el servicio siempre arranca en silencio (decisión del diseño).

- [ ] **Step 1: Tests que fallan:**
  - `test_config_sin_archivo_usa_defaults`: archivo inexistente → `Config()`.
  - `test_config_lee_toml_y_expande_home`: `raiz_musica = "~/X"`, `puerto = 8000`, `avisos = false` → `Path.home()/"X"`, 8000, False.
  - `test_config_ignora_claves_desconocidas`.
  - `test_estado_ida_y_vuelta`: guardar `Estado("Regueton 2000", 55)` en un subdirectorio inexistente → cargar devuelve lo mismo.
  - `test_estado_corrupto_o_ausente_devuelve_default`: JSON inválido y archivo inexistente → `Estado()`.
  - `test_rutas_respeta_xdg`: con `monkeypatch.setenv` de `XDG_CONFIG_HOME`, `XDG_STATE_HOME`, `XDG_CACHE_HOME`, `XDG_RUNTIME_DIR` → rutas de Global Constraints; sin las variables → `~/.config/...`, `~/.local/state/...`, `~/.cache/...`, `/tmp/cassette-fm-<uid>`.
- [ ] **Step 2:** `.venv/bin/pytest tests/test_config.py -v` → FAIL.
- [ ] **Step 3:** Implementar con `tomllib`. `guardar_estado` escribe en un `.tmp` y hace `os.replace` (atómico).
- [ ] **Step 4:** → PASS.
- [ ] **Step 5:** Commit `Configuración y estado persistente`.

---

### Task 3: Biblioteca (bean `CASSETTE-FM-cbtc`)

**Files:** Create `src/cassette_fm/biblioteca.py`, `tests/test_biblioteca.py`

**Interfaces:**
- Produces:

```python
EXTENSIONES = frozenset({".mp3", ".flac", ".ogg", ".m4a"})

@dataclass(frozen=True)
class Pista:
    ruta: Path
    duracion: float          # segundos
    titulo: str              # "Artista - Título" | "Título" | nombre de archivo sin extensión
    fuente: str = "local"

@dataclass(frozen=True)
class Estacion:
    nombre: str
    pistas: tuple[Pista, ...]   # ordenadas por str(ruta)

def leer_pista(ruta: Path) -> Pista | None          # None si mutagen no lo lee o duración <= 0
def escanear(raiz: Path, cache: Path | None = None) -> list[Estacion]   # ordenadas por nombre.casefold()
```

- [ ] **Step 1: Tests que fallan:**
  - `test_leer_pista_con_tags`: título `"Artista - Tema"`, duración ≈ 3.
  - `test_leer_pista_sin_tags_usa_nombre_de_archivo` (solo título → `"Tema"`; sin tags → stem).
  - `test_leer_pista_ilegible_devuelve_none` (un `.mp3` con texto basura).
  - `test_escanear_subcarpetas_son_estaciones`: `raiz/Lentos/a.mp3`, `raiz/Regueton 2000/sub/b.mp3` (recursivo), `raiz/suelto.mp3` (ignorado), `raiz/.oculta/c.mp3` (ignorada), `raiz/Vacía/cover.jpg` (no es estación) → `["Lentos", "Regueton 2000"]` con 1 pista cada una.
  - `test_escanear_orden_alfabetico_sin_mayusculas`: `b`, `A`, `c` → `A, b, c`.
  - `test_escanear_ignora_ilegibles_y_no_audio`: `.txt`, `.jpg`, mp3 corrupto dentro de una estación con un mp3 bueno → 1 pista.
  - `test_escanear_raiz_inexistente_devuelve_vacio`.
  - `test_cache_evita_releer`: segundo `escanear` con el mismo `cache` y `monkeypatch` de `leer_pista` que cuenta llamadas → 0 lecturas; al cambiar el archivo (otra duración, reescrito) → se relee solo ese.
- [ ] **Step 2:** → FAIL.
- [ ] **Step 3:** Implementar. `leer_pista` usa `mutagen.File(ruta, easy=True)` (en mp3 da `title`/`artist`). La caché es un JSON `{str(ruta): {"mtime_ns", "tamano", "duracion", "titulo"}}`, cargada al empezar y reescrita al terminar `escanear`. Solo guarda lecturas exitosas. Ignora la caché corrupta.
- [ ] **Step 4:** → PASS.
- [ ] **Step 5:** Commit `Biblioteca: escaneo de estaciones y duraciones con caché`.

---

### Task 4: Agenda (reloj virtual) (bean `CASSETTE-FM-c0ll`)

**Files:** Create `src/cassette_fm/agenda.py`, `tests/test_agenda.py`

**Interfaces:**
- Consumes: `Pista`, `Estacion` (Task 3).
- Produces:

```python
EPOCA: float = 1767225600.0
def orden_ciclo(estacion: Estacion, k: int) -> list[Pista]
def secuencia(estacion: Estacion, instante: float) -> Iterator[tuple[Pista, float]]
    # infinito: primero (pista que suena en `instante`, segundo dentro de ella), después (pista, 0.0)...
    # ValueError si la estación no tiene pistas
```

Algoritmo de `orden_ciclo` (lo fija el plan; ni la firma ni los tests lo determinan del todo):

```python
base = sorted(estacion.pistas, key=lambda p: str(p.ruta))   # independiente del orden de entrada
if len(base) <= 2: return base          # con 2, a-b-a-b nunca repite; con 1, inevitable
orden = _mezcla(base, estacion.nombre, k)
if orden[0] == _mezcla(base, estacion.nombre, k - 1)[-1]:
    orden[0], orden[1] = orden[1], orden[0]   # con len >= 3 el swap no toca el último → no hay cascada
return orden

def _mezcla(base, nombre, k):
    semilla = int.from_bytes(hashlib.sha256(f"{nombre}\x00{k}".encode()).digest()[:8], "big")
    lista = list(base); random.Random(semilla).shuffle(lista); return lista
```

`secuencia`: `L = sum(duraciones)`; `t = instante - EPOCA`; `k = math.floor(t / L)`; `r = t - k * L`; recorrer
`orden_ciclo(k)` restando duraciones hasta ubicar `r`; después seguir con el resto del ciclo y con `k+1, k+2…`.

- [ ] **Step 1: Tests que fallan** (estación de 5 pistas de duraciones distintas construida a mano con `Pista(Path(f"/m/{i}.mp3"), d, f"t{i}")`):
  - `test_en_la_epoca_suena_la_primera_del_ciclo_0_desde_cero`
  - `test_desplazamiento_dentro_de_la_segunda_pista`: `EPOCA + dur(o[0]) + 10` → `(o[1], 10.0)` (con `pytest.approx`)
  - `test_ciclo_siguiente`: `EPOCA + L + 5` → `(orden_ciclo(e, 1)[0], 5.0)`
  - `test_instante_anterior_a_la_epoca`: `EPOCA - 1` → la última pista de `orden_ciclo(e, -1)`, en `dur - 1`
  - `test_siguientes_arrancan_en_cero_y_cruzan_ciclo`: desde `EPOCA + L - 1`, los 7 primeros elementos = `[(o0[-1], dur-1)] + [(p, 0.0) for p in o1] + [(o2[0], 0.0)]`
  - `test_orden_ciclo_es_permutacion`
  - `test_independiente_del_orden_de_entrada`: misma estación con pistas desordenadas → mismo `orden_ciclo`
  - `test_determinista_entre_procesos`: `subprocess` con `PYTHONHASHSEED=1` y `=2` imprime `orden_ciclo` → igual al del proceso de test
  - `test_no_repite_tema_en_el_borde_de_ciclo`: para estaciones de 2, 3 y 5 pistas, `orden_ciclo(e, k)[-1] != orden_ciclo(e, k+1)[0]` para `k in range(-50, 200)`
  - `test_estacion_de_una_pista`: `secuencia` devuelve siempre la misma, con desplazamiento correcto
  - `test_estacion_vacia_da_error`
- [ ] **Step 2:** → FAIL.
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** → PASS.
- [ ] **Step 5:** Commit `Agenda: reloj virtual por estación`.

---

### Task 5: Cliente de mpv por IPC (bean `CASSETTE-FM-mrm4`, parte 1)

**Files:** Create `src/cassette_fm/mpv.py`, `tests/test_mpv.py`

**Interfaces:**
- Produces:

```python
class ErrorMpv(Exception): ...

class ClienteMpv:
    al_evento: Callable[[dict], None] | None     # atributo asignable
    def __init__(self, socket: Path, extra_args: Sequence[str] = (), ejecutable: str = "mpv"): ...
    def iniciar(self) -> None
    def comando(self, *args: Any, **nombrados: Any) -> Any
        # sin nombrados: {"command": [*args]}; con nombrados: {"command": {"name": args[0], **nombrados}}
        # devuelve "data"; error != "success" → ErrorMpv; sin respuesta en 5 s → ErrorMpv
    def cerrar(self) -> None
```

Detalles que fija el plan:
- Argumentos de mpv: `--idle=yes --no-video --no-terminal --input-ipc-server=<socket>` + `extra_args`. Espera hasta 5 s a que aparezca el socket.
- Un **hilo lector** reparte respuestas por `request_id` (con `threading.Event` por pedido). Los eventos van a una `queue.Queue` que consume **otro hilo despachador**, que llama a `al_evento`. Así el callback puede llamar a `comando` sin trabarse (el lector nunca ejecuta callbacks).
- `comando` es thread-safe (lock para escribir en el socket).
- Si el proceso murió (`poll() is not None`) o el socket se cerró, `comando` llama a `iniciar()` una vez y reintenta (Review Focus 3).

- [ ] **Step 1: Tests que fallan** (mpv real, `extra_args=["--ao=null"]`, socket en `dir_corto`):
  - `test_propiedad_idle`: `comando("get_property", "idle-active") is True`
  - `test_loadfile_con_start_y_eventos`: `comando("loadfile", url=str(mp3), flags="replace", options={"start": "1.5"})`; llegan `start-file` y `file-loaded` a `al_evento`; luego `time-pos >= 1.5`
  - `test_callback_puede_mandar_comandos`: un `al_evento` que, ante `file-loaded`, hace `comando("get_property", "path")` y guarda el resultado → no se traba y obtiene la ruta
  - `test_error_de_mpv`: `get_property` de `"no-existe"` → `ErrorMpv`
  - `test_relanza_si_mpv_murio`: `os.kill(proceso.pid, SIGKILL)`, esperar, `comando("get_property", "idle-active") is True`
  - `test_cerrar_termina_el_proceso`
- [ ] **Step 2:** → FAIL.
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** → PASS (y sin hilos colgados: el suite termina).
- [ ] **Step 5:** Commit `Cliente de mpv por IPC`.

---

### Task 6: Reproductor (bean `CASSETTE-FM-mrm4`, parte 2)

**Files:** Create `src/cassette_fm/reproductor.py`, `tests/test_reproductor.py`

**Interfaces:**
- Consumes: `ClienteMpv` (Task 5: `comando`, `al_evento`), `secuencia` (Task 4), `Estacion`/`Pista` (Task 3).
- Produces:

```python
class Reproductor:
    pista_actual: Pista | None
    al_cambiar_pista: Callable[[Pista], None] | None      # atributo asignable
    def __init__(self, mpv, reloj: Callable[[], float] = time.time, cola: int = 2): ...
        # se registra: mpv.al_evento = self.manejar_evento
    def manejar_evento(self, evento: dict) -> None
    def sintonizar(self, estacion: Estacion) -> None
    def detener(self) -> None
    def volumen(self, valor: int) -> int       # recorta a 0..100, lo aplica y lo devuelve
```

Comportamiento que fija el plan:
- `sintonizar`: genera `secuencia(estacion, reloj())`. La primera pista se carga con `loadfile` `flags="replace"` y `options={"start": f"{desde:.3f}"}`; las `cola` siguientes con `flags="append"`. Guarda `playlist_entry_id → Pista` a partir de las respuestas, y **reemplaza** ese mapa en cada `sintonizar`.
- `start-file` con un id que no está en el mapa → se ignora (eventos viejos, Review Focus 5).
- `start-file` del primer id de la sintonización → `pista_actual`, `al_cambiar_pista`.
- `start-file` de un id posterior → además, `playlist-remove 0` y `append` de **una** pista más de la secuencia (la playlist queda siempre en `[actual, +cola]`).
- `detener` → `stop`, `pista_actual = None`, mapa vacío.
- Todos los métodos públicos y `manejar_evento` usan un mismo `threading.Lock`.

- [ ] **Step 1: Tests unitarios que fallan** (con `MpvFalso` que registra comandos y devuelve `{"playlist_entry_id": n}` incremental; reloj fijo; estación de 4 pistas):
  - `test_sintonizar_carga_con_desplazamiento_y_encola`: comandos = `loadfile` replace de `s[0]` con `start` del desplazamiento esperado (`secuencia` con el mismo instante) + 2 `append` de `s[1]`, `s[2]`
  - `test_primer_start_file_fija_pista_actual_y_avisa`
  - `test_start_file_siguiente_rota_la_cola`: → `playlist-remove 0` + `append` de `s[3]`; `pista_actual == s[1]`
  - `test_eventos_de_sintonizacion_vieja_se_ignoran`: sintonizar A, sintonizar B, evento `start-file` con id de A → `pista_actual` no cambia, sin comandos extra
  - `test_volumen_se_recorta`: `volumen(150) == 100`, `volumen(-5) == 0`, manda `set_property volume`
  - `test_detener`
- [ ] **Step 2:** → FAIL.
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** → PASS.
- [ ] **Step 5: Tests de integración que fallan** (mpv real `--ao=null`, mp3 de 2 s, reloj = `EPOCA + 1.5` para entrar cerca del final):
  - `test_integracion_entra_a_mitad_y_avanza`: tras sintonizar, `pista_actual` es la primera; esperar ≤ 4 s a que `al_cambiar_pista` reporte la segunda
  - `test_integracion_salta_archivo_borrado` (Review Focus 2): estación de 3 pistas; borrar del disco la segunda de la secuencia después de sintonizar → `al_cambiar_pista` termina reportando la tercera en ≤ 6 s
- [ ] **Step 6:** Correrlos → FAIL si falta algo, ajustar, → PASS.
- [ ] **Step 7:** Commit `Reproductor: sintonía con reloj virtual y cola en mpv`.

---

### Task 7: Radio (bean `CASSETTE-FM-jcrq`, parte 1)

**Files:** Create `src/cassette_fm/radio.py`, `tests/test_radio.py`

**Interfaces:**
- Consumes: `Reproductor` (Task 6: `sintonizar`, `detener`, `volumen`, `pista_actual`, `al_cambiar_pista`), `Estado` (Task 2), `Estacion` (Task 3).
- Produces:

```python
class EstacionInexistente(Exception): ...
class SinEstaciones(Exception): ...

class Radio:
    def __init__(self, reproductor, estaciones: list[Estacion], estado: Estado,
                 guardar: Callable[[Estado], None], escanear: Callable[[], list[Estacion]],
                 avisar: Callable[[str, str], None] | None = None): ...
    encendida: bool
    def estaciones(self) -> list[Estacion]
    def sintonizar(self, nombre: str) -> None
    def siguiente(self) -> None
    def anterior(self) -> None
    def encender(self) -> None
    def apagar(self) -> None
    def alternar(self) -> None
    def volumen(self, valor: int | None = None, delta: int | None = None) -> int
    def rescan(self) -> None
    def estado(self) -> dict
        # {"encendida": bool, "estacion": str | None, "pista": str | None, "volumen": int,
        #  "estaciones": [str, ...]}
```

Reglas que fija el plan (decisiones mías, coherentes con el diseño):
- Nace **apagada**. Al construirse aplica `estado.volumen` al reproductor.
- `sintonizar(nombre)`: coincidencia exacta sin distinguir mayúsculas; si no hay, por **prefijo único** (`"reg"` → `"Regueton 2000"`). Ninguna o ambigua → `EstacionInexistente`. **Enciende** si estaba apagada (como apretar un preset). Guarda el estado.
- `siguiente`/`anterior`: orden alfabético de `estaciones()`, con vuelta. Sin estación actual: la primera o la última. Encienden si estaba apagada.
- `encender`: sintoniza `estado.estacion` si existe; si no, la primera. Sin estaciones → `SinEstaciones`.
- `apagar` → `reproductor.detener()`.
- `rescan`: reemplaza la lista. Si sigue existiendo la estación actual, **no** interrumpe. Si desapareció y la radio está encendida, sintoniza la primera (o apaga si no queda ninguna).
- Avisos: `Radio` se asigna como `reproductor.al_cambiar_pista` y llama a `avisar(nombre_estacion, pista.titulo)`.
- Lock propio para todas las operaciones públicas.

- [ ] **Step 1: Tests que fallan** (`ReproductorFalso` que registra llamadas; estaciones `A`, `B`, `Regueton 2000`):
  - `test_nace_apagada_y_aplica_volumen`
  - `test_encender_sin_estado_sintoniza_la_primera` / `test_encender_recuerda_la_ultima`
  - `test_siguiente_y_anterior_dan_la_vuelta`
  - `test_siguiente_estando_apagada_enciende`
  - `test_sintonizar_por_prefijo_y_sin_mayusculas`: `"reg"`, `"REGUETON 2000"`
  - `test_sintonizar_inexistente_o_ambiguo`: `"x"` y, con estaciones `Rock` y `Rap`, `"r"` → `EstacionInexistente`
  - `test_sin_estaciones` (Review Focus 4): `encender` y `siguiente` → `SinEstaciones`
  - `test_guarda_estado_al_sintonizar_y_al_cambiar_volumen`
  - `test_volumen_delta_y_valor`
  - `test_rescan_conserva_o_reubica`
  - `test_avisa_al_cambiar_pista`: disparar `reproductor.al_cambiar_pista(p)` → `avisar("A", p.titulo)`
  - `test_cambios_rapidos` (Review Focus 5): 10 × `siguiente` desde hilos concurrentes → la última llamada a `reproductor.sintonizar` coincide con `estado()["estacion"]`
- [ ] **Step 2:** → FAIL.
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** → PASS.
- [ ] **Step 5:** Commit `Radio: estaciones, rotación, encendido y volumen`.

---

### Task 8: API HTTP y servicio (bean `CASSETTE-FM-jcrq`, parte 2)

**Files:** Create `src/cassette_fm/api.py`, `src/cassette_fm/servicio.py`, `tests/test_api.py`, `tests/test_servicio.py`; Modify `src/cassette_fm/cli.py` (subcomando `serve`)

**Interfaces:**
- Consumes: `Radio`, `EstacionInexistente`, `SinEstaciones` (Task 7); `Config`, `Rutas`, `cargar_*`, `guardar_estado` (Task 2); `escanear` (Task 3); `ClienteMpv` (Task 5); `Reproductor` (Task 6).
- Produces:

```python
def crear_servidor(radio, host: str = "127.0.0.1", puerto: int = 7710) -> ThreadingHTTPServer
def servir(config: Config, rutas: Rutas, avisar: Callable[[str, str], None] | None = None,
           parar: threading.Event | None = None, extra_args_mpv: Sequence[str] = ()) -> None
    # bloquea hasta SIGTERM/SIGINT o hasta que se setee `parar` (para tests);
    # al salir: apaga, cierra mpv, cierra el servidor. `extra_args_mpv` solo para tests (--ao=null)
```

Contrato HTTP (cuerpos JSON UTF-8, `Content-Type: application/json; charset=utf-8`):

| Método y ruta | Cuerpo | 200 devuelve |
|---|---|---|
| `GET /estado` | — | `radio.estado()` |
| `GET /estaciones` | — | `[{"nombre": str, "pistas": int}, …]` |
| `POST /sintonizar` | `{"estacion": str}` | `radio.estado()` |
| `POST /siguiente`, `/anterior`, `/encender`, `/apagar`, `/alternar`, `/rescan` | — | `radio.estado()` |
| `POST /volumen` | `{"valor": int}` o `{"delta": int}` | `radio.estado()` |

Errores: `{"error": "<mensaje en español>"}` con 404 (ruta desconocida o `EstacionInexistente`), 400 (JSON inválido o
faltan campos), 409 (`SinEstaciones`, mensaje que nombre la carpeta raíz).

- [ ] **Step 1: Tests de API que fallan** (servidor con puerto 0 en un hilo, `RadioFalsa`, `urllib`):
  - `test_get_estado`, `test_get_estaciones`
  - `test_post_sintonizar_con_espacios_y_acentos` (Review Focus 1): `{"estacion": "Música Ñandú"}` llega intacto a `RadioFalsa`
  - `test_post_acciones_simples` (parametrizado por las 6 rutas)
  - `test_volumen_valor_y_delta`
  - `test_estacion_inexistente_404`, `test_json_invalido_400`, `test_sin_estaciones_409` (Review Focus 4)
  - `test_ruta_desconocida_404`
- [ ] **Step 2:** → FAIL. **Step 3:** implementar `crear_servidor` con `BaseHTTPRequestHandler` (silenciar `log_message`). **Step 4:** → PASS.
- [ ] **Step 5: Test de servicio que falla** — `test_servir_de_punta_a_punta`: `servir` en un hilo con `Config(raiz_musica=tmp con 2 estaciones de mp3, puerto=puerto libre)`, `Rutas` en `tmp_path`/`dir_corto`, `extra_args_mpv=["--ao=null"]` y un `parar = threading.Event()`. `POST /encender` → `estado` encendida con estación `A`; `POST /siguiente` → `B`; `estado.json` guardado con `B`; `POST /apagar`; `parar.set()` → el hilo de `servir` termina en ≤ 3 s y el proceso mpv ya no existe.
- [ ] **Step 6:** → FAIL. **Step 7:** implementar `servir` (cachés y estado desde `rutas`, socket en `rutas.runtime / "mpv.sock"`, crea el directorio) y el subcomando `cassette serve`. **Step 8:** → PASS.
- [ ] **Step 9:** Commit `API HTTP de control y servicio`.

---

### Task 9: Avisos de escritorio (bean `CASSETTE-FM-wyn5`)

**Files:** Create `src/cassette_fm/avisos.py`, `tests/test_avisos.py`; Modify `src/cassette_fm/servicio.py` (usa `Notificador` si `config.avisos`)

**Interfaces:**
- Produces: `class Notificador: def __call__(self, estacion: str, titulo: str) -> None`. Firma compatible con `avisar` de `Radio`.

Comportamiento: ejecuta `notify-send --app-name=cassette-fm --replace-id=<id> -p <estacion> <titulo>`. Toma el id que
devuelve `-p` para que cada aviso **reemplace** al anterior en vez de apilarse. Si `notify-send` no existe o falla, se
ignora en silencio (nunca corta la música). Se ejecuta sin bloquear (`subprocess.Popen` + hilo que lee el id).

- [ ] **Step 1: Tests que fallan** (con `monkeypatch` de `subprocess` o un `notify-send` falso en un `PATH` temporal que escribe sus argumentos en un archivo y devuelve `42`):
  - `test_primer_aviso_sin_replace_y_luego_reemplaza`: segundo llamado incluye `--replace-id=42`
  - `test_sin_notify_send_no_falla`
  - `test_servir_sin_avisos_si_config_lo_desactiva` (el `avisar` que recibe `Radio` es `None`)
- [ ] **Step 2:** → FAIL. **Step 3:** implementar. **Step 4:** → PASS.
- [ ] **Step 5:** Commit `Avisos de escritorio al cambiar de estación y de tema`.

---

### Task 10: CLI `cassette` (bean `CASSETTE-FM-5yhz`)

**Files:** Modify `src/cassette_fm/cli.py`; Create `tests/test_cli.py`

**Interfaces:**
- Consumes: contrato HTTP de Task 8; `cargar_config`/`rutas` (Task 2).
- Produces: `main(argv) -> int` con los subcomandos `serve`, `next`, `prev`, `tune NOMBRE...`, `on`, `off`, `toggle`, `status`, `list`, `vol N|+N|-N`, `rescan`, y la opción global `--puerto` (si no está, sale de la config).

Salida que fija el plan:
- `status` y las acciones imprimen una línea: `▶ <estación> — <pista> (vol <n>)`, o `⏹ apagada (vol <n>)`.
- `list`: una estación por línea, `<nombre> (<n> temas)`, con `▶ ` delante de la actual y `  ` delante del resto.
- `tune` une sus argumentos con espacios (`cassette tune Regueton 2000`).
- `vol +5`/`vol -5` → `delta`; `vol 70` → `valor`. argparse acepta `-5` como posicional porque no hay opciones con forma de número.
- Servicio caído (`URLError`/conexión rechazada) → stderr `cassette-fm no está corriendo. Arrancalo con: systemctl --user start cassette-fm (o cassette serve)` y código 1.
- Error de la API → stderr con el `"error"` del JSON y código 1.

- [ ] **Step 1: Tests que fallan** (servidor real de Task 8 con `RadioFalsa` en puerto 0, `main([... , "--puerto", str(p)])`, `capsys`):
  - `test_status_encendida` y `test_status_apagada`
  - `test_tune_con_espacios_sin_comillas` (Review Focus 1): `["tune", "Regueton", "2000"]` → `RadioFalsa` recibe `"Regueton 2000"`
  - `test_vol_relativo_y_absoluto`: `+5`, `-5`, `70`
  - `test_list_marca_la_actual`
  - `test_acciones` (parametrizado: next, prev, on, off, toggle, rescan → la ruta correcta)
  - `test_servicio_caido`: puerto sin nadie escuchando → código 1 y el mensaje
  - `test_error_de_api`: estación inexistente → código 1 y el mensaje del servidor
- [ ] **Step 2:** → FAIL. **Step 3:** implementar con `urllib.request`. **Step 4:** → PASS.
- [ ] **Step 5:** Commit `CLI cassette`.

---

### Task 11: systemd de usuario, instalación y verificación real (bean `CASSETTE-FM-1v8d`)

**Files:** Create `packaging/cassette-fm.service.in`, `scripts/instalar.sh`, `README.md`

Unidad (plantilla; `@CASSETTE@` se reemplaza por la ruta absoluta al ejecutable):

```ini
[Unit]
Description=cassette-fm: radios continuas desde ~/Música

[Service]
ExecStart=@CASSETTE@ serve
Restart=on-failure

[Install]
WantedBy=default.target
```

`WantedBy=default.target` porque Cinnamon no activa `graphical-session.target` (verificado: solo está activo `default.target`).

`scripts/instalar.sh` (idempotente):
1. Crea `.venv` si falta e instala el proyecto (`pip install -e .`).
2. Crea el enlace `~/.local/bin/cassette` → `<repo>/.venv/bin/cassette`.
3. Genera `~/.config/systemd/user/cassette-fm.service` desde la plantilla.
4. Ejecuta `systemctl --user daemon-reload && systemctl --user enable --now cassette-fm`.

- [ ] **Step 1:** Escribir la plantilla y el script. Verificar con `bash -n scripts/instalar.sh` y `systemd-analyze --user verify ~/.config/systemd/user/cassette-fm.service` (después de instalar) → sin errores.
- [ ] **Step 2:** `README.md`: qué es, instalación (`scripts/instalar.sh`), uso de la CLI, configuración (`config.toml` con sus 3 claves), cómo ver logs (`journalctl --user -u cassette-fm -f`).
- [ ] **Step 3: Verificación real en la PC del usuario** (no automatizable, con evidencia en el commit o en el bean):
  - `scripts/instalar.sh` → `systemctl --user status cassette-fm` activo y **sin sonido**.
  - `cassette list` → `Lentos (12 temas)`, `Regueton 2000 (…)`.
  - `cassette on` → suena a mitad de un tema y llega la notificación. `cassette next`, `cassette prev`, `cassette tune reg`, `cassette vol -10`, `cassette off`.
  - `cassette off` + esperar 1 minuto + `cassette on` → el tema avanzó ("en vivo").
  - `systemctl --user restart cassette-fm` → arranca en silencio y `cassette on` vuelve a la última estación.
  - Consumo: `ps -o rss,pcpu -C mpv,python3` mientras suena (referencia: decenas de MB y pocos % de CPU).
- [ ] **Step 4:** `.venv/bin/pytest -v` completo → PASS.
- [ ] **Step 5:** Commit `Instalación como servicio de usuario y README`. Cerrar la épica `CASSETTE-FM-u2yr` si las 9 tareas están completas.
