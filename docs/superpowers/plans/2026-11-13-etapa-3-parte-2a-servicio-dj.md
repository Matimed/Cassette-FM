# Etapa 3, parte 2a: servicio DJ — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Un servicio HTTP independiente (`cassette-dj`) que recibe un pedido de intervención, redacta una frase con
plantillas, la prepara para la voz (fonemas por idioma, "s" argentina, sin pausas raras), la sintetiza con Kokoro y
devuelve un clip de audio; y que deja registro permanente de cada guion para las pruebas de voz del final de la etapa.

**Architecture:** Subpaquete `cassette_fm.dj` con dependencias opcionales (extra `[dj]`). Un `Productor` encadena
`redactar → preparar → sintetizar → anotar guion`; una `Cola` con hilos de trabajo lo ejecuta de forma asíncrona y
sin estado entre pedidos (todo viaja en el pedido); un servidor HTTP de la biblioteca estándar expone el contrato.
La radio (planificador y cliente) es la parte 2b y no entra acá.

**Tech Stack:** Python 3.12, `kokoro-onnx` 0.6.x (+ `numpy`, `soundfile`), `http.server` de la stdlib, pytest.

**Spec:** [`docs/superpowers/specs/2026-11-13-etapa-3-dj-design.md`](../specs/2026-11-13-etapa-3-dj-design.md)
(secciones "Servicio DJ (HTTP)", "Contenido de una intervención", "Texto para voz", "Cómo se construye", parte 2) y
[`docs/relevamiento/texto-para-voz.md`](../../relevamiento/texto-para-voz.md) (reglas y hallazgos de Kokoro).

## Global Constraints

- Beans: `CASSETTE-FM-jd7u` (esta parte). Al empezar, `-s in-progress`; al terminar la Task 7, `-s completed` y se incluye `.beans/` en el commit. La parte 2b (`CASSETTE-FM-zuej`) depende de esta.
- **Nada fijo en el código**: todo valor que pueda querer cambiarse vive en la configuración del servicio con su valor por defecto (lista en Task 1).
- **El servicio no guarda estado entre pedidos**: todo lo que necesita viaja en el `POST` (`recientes` incluido). Lo único que persiste es el registro de guiones.
- Las dependencias pesadas van **solo** en el extra `dj` (`kokoro-onnx`, `soundfile`); la radio sigue instalándose sin ellas. Ninguna parte de `cassette_fm` fuera de `cassette_fm.dj` las importa.
- **No hay ffmpeg**. El clip es **WAV PCM de 16 bits, mono** (lo que devuelve Kokoro, 24 kHz).
- El modelo de Kokoro (326 MB + 28 MB de voces) **no está en el repo ni se descarga solo**: lo baja `cassette-dj modelos` (a pedido del usuario) a `modelos_dir`. Los tests que lo necesitan se saltean si faltan; se pueden apuntar con la variable de entorno `CASSETTE_DJ_MODELOS`.
- Idiomas aceptados en el pedido: `es`, `en`, `en-us`, `en-gb`. `es` → `lang="es"` de Kokoro; `en` → `en-us`. Voces de ejemplo del usuario (no una lista cerrada): `em_santa`, `am_michael`, `af_heart`.
- Reglas del texto para voz (del relevamiento): fonemizar por tramos con el idioma de cada nombre propio; español: `θ`→`s` **solo en los tramos en español** (el `θ` de "think" en inglés no se toca); quitar `¡ ¿`, `!`→`.`; pocas comas; ninguna oración corta suelta; las mayúsculas no importan.
- **El registro de guiones es permanente y es la fuente de los textos de las pruebas de voz** (lo pidió el usuario: las voces se vuelven a probar al final de la etapa con frases reales generadas). Esta parte lo escribe con `"fuente": "plantilla"`; la parte 4 (LLM) anota en el mismo archivo con `"fuente": "llm"`, **incluidas las pruebas manuales con el LLM**.
- Velocidad por defecto de la voz: 1,05 (la que el usuario aprobó en las pruebas).
- Los clips se escriben **solo** dentro de `rutas.clips`; el `id` del pedido se valida para que nunca pueda salir de ahí.
- Todo mensaje al usuario, nombres y comentarios en español. Commits en español, texto plano en imperativo, con la línea de atribución vigente de la sesión.
- Los tests no hacen sonar audio ni tocan `~/.config/cassette-dj`, `~/.local/share/cassette-dj` ni el servicio real. Instalar el servicio y bajar los modelos los hace el usuario (`scripts/instalar-dj.sh`, `cassette-dj modelos`).
- Al terminar cada tarea: `.venv/bin/pytest -q` completo en verde (hoy 293 tests).

## Review Focus

1. **Pedidos inválidos o hostiles:** campos faltantes o mal tipados, `momento` sin zona horaria, y un `id` con `../`, `/` o caracteres raros (se usa como nombre de archivo): 400 con un mensaje claro y **nunca** se escribe fuera de `rutas.clips`. → tests en Task 2 y Task 7.
2. **Nombres con comillas, `&`, llaves, acentos y ñ** (`Héctor "El Father"`, `Zion & Lennox`, `Tito "El Bambino"`, `Música Ñandú`) no rompen el marcado de tramos ni la fonetización. → tests en Task 3 y Task 4.
3. **Invariantes sobre TODAS las plantillas:** ninguna produce `¡ ! ¿`, ninguna deja una oración de menos de 4 palabras, todas respetan `palabras_maximas`, y la variedad es real (varias estructuras distintas). → tests en Task 4.
4. **Kokoro o modelos ausentes:** el servicio arranca igual, `/salud` lo informa, los pedidos terminan en estado `error` con un mensaje claro (no se cuelgan) y `cassette-dj modelos` explica cómo bajarlos. → tests en Task 5, 6 y 7.
5. **Concurrencia:** dos `POST` con el mismo `id` (idempotencia), cancelar mientras trabaja (no se puede) o antes (se puede), varios pedidos con un solo trabajador (orden de llegada), la retención borra los clips vencidos, `detener` no deja hilos vivos, y anotar guiones desde varios hilos no mezcla ni trunca líneas. → tests en Task 6.

---

## Estructura de archivos

```
pyproject.toml                          # Task 1: extra [dj] y comando cassette-dj
src/cassette_fm/dj/__init__.py
src/cassette_fm/dj/config.py            # Task 1: ConfigServicioDJ, RutasDJ, cargar_config_dj
src/cassette_fm/dj/pedido.py            # Task 2: Tema, Pedido, leer_pedido
src/cassette_fm/dj/texto_voz.py         # Task 3: limpiar, tramos, aplicar_seseo, preparar, marcar
src/cassette_fm/dj/lexico.py            # Task 4: Lexico
src/cassette_fm/dj/plantillas.py        # Task 4: frase_hora, redactar
src/cassette_fm/dj/sintetizador.py      # Task 5: Sintetizador, fonemizador, faltan_modelos
src/cassette_fm/dj/guiones.py           # Task 6: RegistroGuiones
src/cassette_fm/dj/produccion.py        # Task 6: Productor, Resultado
src/cassette_fm/dj/cola.py              # Task 6: Cola, EstadoTrabajo
src/cassette_fm/dj/servidor.py          # Task 7: crear_servidor
src/cassette_fm/dj/cli.py               # Task 1 (stub) y Task 7: serve, modelos, voces, guiones, voz-prueba
packaging/cassette-dj.service.in, scripts/instalar-dj.sh   # Task 7
tests/dj/test_<módulo>.py (+ tests/dj/conftest.py)
```

---

### Task 1: Configuración, extra `[dj]` y comando base

**Files:** Modify `pyproject.toml`; Create `src/cassette_fm/dj/__init__.py`, `src/cassette_fm/dj/config.py`, `src/cassette_fm/dj/cli.py`, `tests/dj/__init__.py`, `tests/dj/test_config.py`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True)
class ConfigServicioDJ:
    host: str = "127.0.0.1"
    puerto: int = 7720
    trabajadores: int = 1
    retencion_minutos: float = 60.0          # cuánto se conserva un resultado terminado
    descargar_tras_minutos: float = 5.0      # Kokoro se descarga tras este tiempo sin trabajo
    modelos_dir: Path = Path.home() / ".local/share/cassette-dj/modelos"
    palabras_maximas: int = 45
    velocidad: float = 1.05
    pausa_oracion_segundos: float = 0.25     # `sentence_pause` de Kokoro
    pausa_coma_segundos: float = 0.1         # `clause_pause` de Kokoro
    continuo: bool = False                   # `continuous` de Kokoro
    zona_horaria: str = "America/Argentina/Buenos_Aires"

@dataclass(frozen=True)
class RutasDJ:
    config: Path      # $XDG_CONFIG_HOME/cassette-dj/config.toml
    estado: Path      # directorio: $XDG_STATE_HOME/cassette-dj
    clips: Path       # directorio: $XDG_CACHE_HOME/cassette-dj/clips
    @property guiones -> Path   # estado / "guiones.jsonl"
    @property lexico  -> Path   # config.parent / "lexico.toml"

def rutas_dj() -> RutasDJ                       # lee XDG_* en cada llamada, con los defaults de XDG
def cargar_config_dj(archivo: Path) -> ConfigServicioDJ   # ErrorConfig (de cassette_fm.config) con ruta y clave
# cli.py: main(argv: list[str] | None = None) -> int   (stub: --version imprime la versión del paquete)
```

Validación: `puerto` 1..65535; `trabajadores >= 1`; `palabras_maximas >= 5`; `velocidad` en `[0.5, 2.0]`; las pausas y tiempos `>= 0`; `retencion_minutos > 0`; `host` no vacío; `zona_horaria` debe existir en `zoneinfo`. `bool` no vale como número. Claves desconocidas: se ignoran. `modelos_dir` admite `~`.

`pyproject.toml`: `[project.optional-dependencies] dj = ["kokoro-onnx", "soundfile"]` (dev y dj se instalan juntos con `pip install -e ".[dev,dj]"`) y `[project.scripts] cassette-dj = "cassette_fm.dj.cli:main"`.

- [ ] **Step 1: Tests que fallan** en `tests/dj/test_config.py`: `test_defaults` (los 12 valores exactos de arriba); `test_lee_el_toml_y_acepta_enteros_como_float`; `test_ignora_claves_desconocidas`; `test_invalido_da_error_claro` (parametrizado, con la ruta en el mensaje: `puerto = 0`, `puerto = "x"`, `trabajadores = 0`, `palabras_maximas = 2`, `velocidad = 3`, `pausa_oracion_segundos = -1`, `retencion_minutos = 0`, `host = ""`, `zona_horaria = "Marte/Olimpo"`, `continuo = "si"`, `puerto = true`); `test_rutas_respetan_xdg_y_defaults` (con `monkeypatch` de `XDG_CONFIG_HOME`/`XDG_STATE_HOME`/`XDG_CACHE_HOME`, y sin ellas → `~/.config`, `~/.local/state`, `~/.cache`; `guiones` y `lexico` derivados); `test_cli_version` (`main(["--version"]) == 0` e imprime una versión).
- [ ] **Step 2:** `.venv/bin/pip install -e ".[dev,dj]"` (instala kokoro-onnx y soundfile en el entorno de desarrollo) y `.venv/bin/pytest tests/dj -q` → FAIL (módulos inexistentes).
- [ ] **Step 3:** Implementar `config.py`, `cli.py` (stub) y el extra/entry point en `pyproject.toml`.
- [ ] **Step 4:** Suite completa → PASS.
- [ ] **Step 5:** Commit `Servicio DJ: configuración, extra [dj] y comando cassette-dj`.

---

### Task 2: El pedido (contrato de entrada)

**Files:** Create `src/cassette_fm/dj/pedido.py`, `tests/dj/test_pedido.py`

**Interfaces:**
- Produces:

```python
IDIOMAS = {"es": "es", "en": "en-us", "en-us": "en-us", "en-gb": "en-gb"}   # idioma del pedido -> `lang` de Kokoro

@dataclass(frozen=True)
class Tema:
    artista: str
    titulo: str
    album: str | None = None
    isrc: str | None = None

@dataclass(frozen=True)
class Pedido:
    id: str
    estacion: str
    idioma: str                      # una de las claves de IDIOMAS, tal cual vino
    voz: str
    momento: datetime                # con zona horaria
    anterior: Tema | None
    siguiente: Tema
    recientes: tuple[str, ...] = ()
    personalidad: str = ""
    duracion_maxima_segundos: float | None = None
    @property lang -> str            # IDIOMAS[idioma]

def leer_pedido(datos: object) -> Pedido    # ValueError("campo 'x': motivo") ante cualquier defecto
```

Reglas: `id` es texto de 1 a 64 caracteres que cumple `^[A-Za-z0-9_-]+$` (se usa como nombre de archivo); `estacion` y `voz` son texto no vacío (voz también `^[A-Za-z0-9_+.-]+$`); `momento` es ISO-8601 **con zona** (`datetime.fromisoformat`; sin zona es error); `siguiente` es obligatorio y `anterior` puede faltar o ser `null`; cada tema exige `artista` y `titulo` no vacíos (`album`/`isrc` opcionales, texto o `null`); `recientes` es una lista de textos (opcional); `personalidad` texto (opcional); `duracion_maxima_segundos` número `> 0` (opcional; `bool` no vale). Los textos se recortan (`strip`) y se limitan a 300 caracteres. Campos desconocidos: se ignoran.

- [ ] **Step 1: Tests que fallan** en `tests/dj/test_pedido.py` (con un `pedido_valido()` completo como base): `test_pedido_minimo_y_completo` (con y sin `anterior`/`recientes`/`personalidad`/`duracion_maxima_segundos`/`album`/`isrc`; `lang` correcto para `es`, `en`, `en-gb`); `test_los_textos_se_recortan_y_limitan`; `test_ignora_campos_desconocidos`; `test_faltan_campos_obligatorios` (parametrizado por cada campo obligatorio: `ValueError` cuyo mensaje nombra el campo); `test_tipos_invalidos` (`estacion` número, `recientes` con un número adentro, `siguiente` texto, `duracion_maxima_segundos` `true`/`0`/`-5`, `idioma` `"fr"`); `test_momento_sin_zona_o_invalido_falla`; `test_id_peligroso_falla` (parametrizado: `"../x"`, `"a/b"`, `""`, `"a b"`, `"x"*65`, `"é"`, `".hidden"`); `test_voz_invalida_falla` (`"../voz"`); `test_no_es_un_objeto_falla` (lista, texto, `None`).
- [ ] **Step 2:** `.venv/bin/pytest tests/dj/test_pedido.py -q` → FAIL.
- [ ] **Step 3:** Implementar `pedido.py`.
- [ ] **Step 4:** Suite completa → PASS.
- [ ] **Step 5:** Commit `Servicio DJ: lectura y validación del pedido`.

---

### Task 3: Texto para voz

**Files:** Create `src/cassette_fm/dj/texto_voz.py`, `tests/dj/test_texto_voz.py`

**Interfaces:**
- Consumes: `IDIOMAS` (Task 2) para convertir el idioma del pedido en `lang`.
- Produces:

```python
@dataclass(frozen=True)
class Preparado:
    texto: str       # lo que se dice, limpio y SIN marcas de idioma (es lo que se guarda en el guion legible)
    marcado: str     # el texto limpio CON las marcas {lang:Nombre} (es lo que se puede volver a sintetizar tal cual)
    fonemas: str     # lo que se le pasa a Kokoro con is_phonemes=True

def marcar(nombre: str, lang: str) -> str
    # "{lang:nombre}": le quita al nombre llaves, comillas dobles/tipográficas y saltos de línea; ValueError si queda vacío
def tramos(marcado: str, lang_base: str) -> list[tuple[str, str]]
    # [(texto, lang)] en orden; el texto fuera de marcas va con lang_base; llaves sin cerrar -> se tratan como texto común;
    # tramos vacíos o solo espacios se omiten
def limpiar(marcado: str, lang_base: str, minimo_palabras: int = 4) -> str
def aplicar_seseo(fonemas: str) -> str       # "θ" -> "s"
def preparar(marcado: str, lang_base: str, fonemizar: Callable[[str, str], str],
             minimo_palabras: int = 4) -> Preparado
```

Reglas de `limpiar` (sobre texto con marcas; **no** toca el interior de las marcas salvo comillas y `&`):
1. Quita `¡` y `¿`; `!` pasa a `.`; quita comillas dobles (`"`, `“`, `”`) y simples tipográficas (`‘`, `’` **solo** si no están entre letras: "don't" se conserva).
2. `&` se lee como "y" si `lang_base` es `es` y como "and" si empieza con `en` (con espacios alrededor; dentro de nombres también).
3. Las comas, `;`, `:` y `—` se **quitan** (se reemplazan por un espacio) salvo que los fragmentos de ambos lados, dentro de su oración, tengan cada uno `>= minimo_palabras` palabras (entonces la coma se conserva; `;` `:` `—` pasan a coma).
4. Una oración con menos de `minimo_palabras` palabras se **une** a la anterior (se quita el punto que las separa y se pasa a minúscula su inicial salvo que sea un nombre marcado); si es la primera, se une a la siguiente. Si todo el texto es una sola oración corta, se deja.
5. Espacios normalizados; el texto termina en `.` (o `?`) si no tiene signo final.

`preparar`: `limpiar` → `tramos` → fonemizar cada tramo con su `lang` → en los tramos cuyo `lang == "es"` aplicar `aplicar_seseo` → unir con un espacio. `Preparado.texto` es el limpio sin llaves (`{en-us:Daddy Yankee}` → `Daddy Yankee`); `marcado` el limpio con llaves.

- [ ] **Step 1: Tests que fallan** en `tests/dj/test_texto_voz.py` (con un `fonemizar` falso que devuelve `f"<{lang}:{texto}>"`):
  - `marcar`/`tramos`: `test_marcar_limpia_el_nombre` (`marcar('Héctor "El Father"', "es")` → `{es:Héctor El Father}`; sin llaves ni saltos de línea dentro; nombre vacío → `ValueError`); `test_tramos_separa_por_idioma` (`"Seguimos con {en-us:Daddy Yankee} en vivo"` → 3 tramos con sus `lang`); `test_tramos_llaves_sin_cerrar_son_texto` y `test_tramos_vacios_se_omiten`; `test_tramos_nombre_con_ñ_y_acentos`.
  - `limpiar`: `test_quita_signos_de_pausa` (`"¡Qué tal gente! Son las nueve en Buenos Aires con calor."` → sin `¡`, `!`→`.`); `test_ampersand_segun_idioma` (`Zion & Lennox` → `Zion y Lennox` en `es`, `Zion and Lennox` en `en-us`); `test_comas_cortas_se_quitan_y_largas_se_conservan` (`"Son las nueve, dieciocho grados y todo bien"` → sin coma; `"Estamos escuchando la mejor música de la zona, con todos los temas que más te gustan"` → conserva la coma); `test_oracion_corta_se_une_a_la_anterior` (`"Son las nueve en Buenos Aires con mucho calor. Hay veinte grados."` → una sola oración); `test_oracion_corta_inicial_se_une_a_la_siguiente`; `test_una_sola_oracion_corta_se_deja`; `test_conserva_apostrofes_dentro_de_palabras` (`don't`); `test_termina_con_punto`; `test_no_toca_el_contenido_de_los_nombres_salvo_comillas`; y un test de propiedad: `limpiar(limpiar(x)) == limpiar(x)` para 6 textos de ejemplo (idempotente).
  - `aplicar_seseo`: `θ`→`s` en una cadena con varias; sin `θ` no cambia.
  - `preparar`: `test_el_seseo_solo_va_en_los_tramos_en_espanol` (con un `fonemizar` falso que devuelve `"θ"` para `es` y `"θ"` para `en-us`: el resultado tiene `s` en el tramo es y `θ` en el inglés); `test_texto_y_marcado_y_fonemas` (`texto` sin llaves, `marcado` con llaves, `fonemas` unidos con espacio); `test_el_idioma_base_en_usa_en_us`.
  - `test_integracion_con_el_fonemizador_real` (se saltea si `kokoro_onnx` no está): `preparar("Qué tal gente son las nueve en Buenos Aires con dieciocho grados y gracias a todos", "es", Tokenizer().phonemize)` → `fonemas` **sin** `θ`; `"... {en-us:Daddy Yankee} ..."` → los fonemas de ese tramo contienen `æ`; y para inglés `"Nine twenty here in {es:Buenos Aires} tonight"` → contiene `bwˈenos`.
- [ ] **Step 2:** `.venv/bin/pytest tests/dj/test_texto_voz.py -q` → FAIL.
- [ ] **Step 3:** Implementar `texto_voz.py`.
- [ ] **Step 4:** Suite completa → PASS.
- [ ] **Step 5:** Commit `Servicio DJ: capa de texto para voz`.

---

### Task 4: Léxico y plantillas

**Files:** Create `src/cassette_fm/dj/lexico.py`, `src/cassette_fm/dj/plantillas.py`, `tests/dj/test_lexico.py`, `tests/dj/test_plantillas.py`

**Interfaces:**
- Consumes: `Pedido`, `Tema` (Task 2), `marcar`, `limpiar` (Task 3).
- Produces:

```python
# lexico.py
class Lexico:
    def __init__(self, idiomas: Mapping[str, str] = {}): ...        # nombre (sin distinguir mayúsculas ni acentos) -> lang de Kokoro
    @classmethod
    def cargar(cls, archivo: Path) -> "Lexico"                        # TOML: [idiomas] "Daddy Yankee" = "en-us"; ausente -> vacío; inválido -> ErrorConfig
    def idioma_de(self, nombre: str, defecto: str) -> str             # `defecto` si no está
# plantillas.py
@dataclass(frozen=True)
class Redaccion:
    marcado: str                       # frase con marcas {lang:Nombre} en los nombres propios
    ingredientes: tuple[str, ...]      # p. ej. ("cancion", "estacion", "hora")
def frase_hora(momento: datetime, idioma: str) -> str     # ver abajo
def redactar(pedido: Pedido, lexico: Lexico, azar: random.Random, palabras_maximas: int) -> Redaccion
```

`frase_hora` (la hora del `momento` tal cual, sin convertir zonas; redondeada al múltiplo de 5 minutos más cercano; números en palabras, nunca dígitos):
- `es`: minuto 0 → "las nueve en punto" (con "la una en punto", "las doce en punto" para 0 y 12 h); 5/10/20/25 → "las nueve y cinco/diez/veinte/veinticinco"; 15 → "las nueve y cuarto"; 30 → "las nueve y media"; 35/40/50/55 → "las diez menos veinticinco/veinte/diez/cinco"; 45 → "las diez menos cuarto". Hora en formato de 12 (0 y 12 → "doce"; 1 → "la una"). Tras redondear a 60 pasa a la hora siguiente.
- `en`/`en-us`/`en-gb`: "nine o'clock", "five past nine", "ten past nine", "quarter past nine", "twenty past nine", "twenty five past nine", "half past nine", "twenty five to ten", "twenty to ten", "quarter to ten", "ten to ten", "five to ten".

`redactar`: elige al azar una plantilla de las del idioma (`es` y `en*`), la completa con `marcar(nombre, lexico.idioma_de(nombre, lang_base))` en cada nombre propio (artista, título, álbum, estación; tema anterior cuando la plantilla lo usa), y con `frase_hora(...)` cuando la usa. Mínimo **6 plantillas por idioma**, con **estructuras y conjuntos de ingredientes distintos** entre sí (algunas solo tema y artista; otras con la estación; con la hora; con el momento del día —"a la mañana/tarde/noche"/"morning/afternoon/evening" según `momento`—; con el tema anterior y el siguiente; con el álbum **solo si** el pedido lo trae). Una plantilla que necesita un dato que el pedido no trae (álbum, anterior) no se elige. Si el texto supera `palabras_maximas` se prueba con otras plantillas (hasta 10 intentos) y, si ninguna alcanza, se usa la más corta. `pedido.personalidad` no se usa todavía (llega con el LLM en la parte 4). Todas las oraciones tienen **≥ 5 palabras** y ninguna lleva `¡ ! ¿`.

- [ ] **Step 1: Tests que fallan.**
  - `tests/dj/test_lexico.py`: `test_busca_sin_mayusculas_ni_acentos` (`Lexico({"Daddy Yankee": "en-us"}).idioma_de("daddy yankee", "es") == "en-us"`; `"Música Ñandú"` buscado como `"musica nandu"`); `test_usa_el_defecto_si_no_esta`; `test_cargar_toml` (con `[idiomas]`), `test_cargar_ausente_es_vacio`, `test_cargar_invalido_da_error_claro` (TOML roto y un valor que no es texto → `ErrorConfig` con la ruta); `test_normaliza_unicode_nfd_y_nfc`.
  - `tests/dj/test_plantillas.py` (con un `pedido(...)` de ejemplo y `random.Random(n)`): `test_frase_hora_es` (parametrizado con la tabla: 9:00 "las nueve en punto", 9:02 "las nueve en punto", 9:03 "las nueve y cinco", 9:30 "las nueve y media", 9:47 "las diez menos diez", 9:53 "las diez menos cinco", 9:58 "las diez en punto", 13:00 "la una en punto", 0:00 "las doce en punto", 12:15 "las doce y cuarto", 23:50 "las doce menos diez"); `test_frase_hora_en` (9:00 "nine o'clock", 9:15 "quarter past nine", 9:30 "half past nine", 9:45 "quarter to ten", 21:50 "ten to ten", 23:58 "twelve o'clock"); `test_nunca_hay_digitos_en_la_hora`.
    - `test_redactar_marca_los_nombres_con_el_idioma_del_lexico`: con `Lexico({"Daddy Yankee": "en-us"})` y un pedido `es` cuyo siguiente es de Daddy Yankee, en las 200 redacciones de prueba **cada vez que aparece el artista** aparece como `{en-us:Daddy Yankee}`; y los demás nombres como `{es:...}`.
    - `test_invariantes_de_todas_las_plantillas` (Review Focus 3): para `es`, `en`, `en-gb` y 300 semillas (con y sin álbum, con y sin anterior, momentos de mañana, tarde y noche): el `marcado` no contiene `¡ ! ¿`; tras `limpiar(...)` el texto **no cambia** su cantidad de oraciones (ninguna se une) y cada oración tiene ≥ 4 palabras; la cantidad de palabras ≤ `palabras_maximas` (45); y `ingredientes` siempre contiene `"cancion"`.
    - `test_hay_variedad_real`: en 300 semillas se ven ≥ 5 `ingredientes` distintos y ≥ 5 textos "esqueleto" distintos (el texto con los nombres reemplazados) por idioma.
    - `test_una_plantilla_con_album_solo_si_el_pedido_lo_trae` y `test_una_plantilla_con_anterior_solo_si_hay_anterior`.
    - `test_respeta_palabras_maximas`: con `palabras_maximas = 12` todas las redacciones de 100 semillas tienen ≤ 12 palabras o son la plantilla más corta disponible.
    - `test_nombres_con_comillas_y_ampersand` (Review Focus 2): artista `Héctor "El Father"` y `Zion & Lennox` → el `marcado` no tiene `"`, y `limpiar` + `tramos` dan los tramos esperados sin romper.
    - `test_es_determinista_con_la_misma_semilla`.
- [ ] **Step 2:** `.venv/bin/pytest tests/dj/test_lexico.py tests/dj/test_plantillas.py -q` → FAIL.
- [ ] **Step 3:** Implementar `lexico.py` y `plantillas.py`.
- [ ] **Step 4:** Suite completa → PASS.
- [ ] **Step 5:** Commit `Servicio DJ: léxico de idiomas y frases de plantilla`.

---

### Task 5: Sintetizador (Kokoro)

**Files:** Create `src/cassette_fm/dj/sintetizador.py`, `tests/dj/test_sintetizador.py`, `tests/dj/conftest.py`

**Interfaces:**
- Consumes: `ConfigServicioDJ` (Task 1).
- Produces:

```python
ARCHIVOS_MODELO = ("kokoro-v1.0.onnx", "voices-v1.0.bin")
URL_MODELOS = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"

def faltan_modelos(modelos_dir: Path) -> list[Path]           # los de ARCHIVOS_MODELO que no existen o están vacíos
def descargar_modelos(modelos_dir: Path, url_base: str = URL_MODELOS,
                      progreso: Callable[[str], None] = print) -> list[Path]
    # baja los archivos que falten (según faltan_modelos) con urllib, escribiendo a `<nombre>.part` y renombrando al
    # terminar; no toca los que ya están; devuelve los que bajó; OSError/URLError se propagan (el comando los traduce)
def fonemizador() -> Callable[[str, str], str]                  # (texto, lang) -> fonemas; usa kokoro_onnx.Tokenizer, SIN cargar el modelo

class Sintetizador:
    def __init__(self, config: ConfigServicioDJ, fabrica: Callable[[], Any] | None = None,
                 reloj: Callable[[], float] = time.monotonic): ...
        # `fabrica()` devuelve un objeto con create(text, voice, speed, lang, is_phonemes, sentence_pause,
        # clause_pause, continuous) -> (audio, frecuencia) y get_voices() -> list[str];
        # por defecto carga Kokoro desde config.modelos_dir (ErrorModelos si faltan archivos)
    def sintetizar(self, fonemas: str, voz: str, lang: str, salida: Path) -> float
        # escribe WAV PCM_16 mono en `salida` (crea el directorio) y devuelve la duración en segundos;
        # ValueError (con la lista de voces disponibles en el mensaje) si la voz no existe
    def voces(self) -> list[str]                                  # ordenadas; NO carga el modelo (lee el archivo de voces)
    def descargar_si_ocioso(self) -> bool                         # descarga el modelo si pasó `descargar_tras_minutos` sin uso; True si lo descargó
    @property cargado -> bool
class ErrorModelos(Exception): ...                                # mensaje: qué faltan y "corré `cassette-dj modelos`"
```

Reglas: el modelo se carga **al primer uso** y se reutiliza; `descargar_si_ocioso` lo suelta (y libera la referencia) cuando `reloj() - ultimo_uso >= descargar_tras_minutos*60`; todo bajo un lock (una síntesis a la vez); pasa a Kokoro `speed`, `sentence_pause`, `clause_pause` y `continuous` de la configuración y `is_phonemes=True`.

- [ ] **Step 1: Tests que fallan** — `tests/dj/conftest.py` con un `KokoroFalso` (cuenta cargas; `create` devuelve un `numpy` de ceros de `0.5 s` a 24000 Hz y registra los argumentos; `get_voices` devuelve `["em_santa", "am_michael"]`) y la fixture `fabrica_falsa`:
  - `test_sintetiza_y_escribe_un_wav_valido`: el archivo es un WAV mono de 16 bits legible con `wave`/`mutagen`, duración devuelta ≈ 0,5, y se crearon los directorios padre.
  - `test_pasa_los_parametros_de_la_configuracion`: `create` recibe `speed`, `sentence_pause`, `clause_pause`, `continuous`, `is_phonemes=True` y el `lang`.
  - `test_carga_una_sola_vez`: dos síntesis → una carga.
  - `test_descarga_tras_el_tiempo_ocioso`: con reloj falso: antes del límite `descargar_si_ocioso()` es `False` y `cargado` sigue `True`; pasado el límite es `True` y `cargado` es `False`; una síntesis posterior vuelve a cargar.
  - `test_voz_inexistente_da_ValueError_con_las_disponibles`.
  - `test_voces_no_carga_el_modelo` (con un archivo `voices-v1.0.bin` mínimo formato `npz` en un `modelos_dir` temporal y `fabrica` que cuenta cargas: `voces()` devuelve sus claves ordenadas y **no** se llamó a la fábrica).
  - `test_sin_modelos_da_ErrorModelos_claro`: con `modelos_dir` vacío y sin fábrica, `sintetizar` lanza `ErrorModelos` cuyo mensaje nombra los archivos que faltan y `cassette-dj modelos`; `faltan_modelos` devuelve esos dos; con archivos vacíos (0 bytes) también los marca como faltantes.
  - `test_es_seguro_con_hilos`: 4 hilos sintetizando a la vez con la fábrica falsa → los 4 WAV existen y una sola carga.
  - `test_descargar_modelos_baja_solo_los_que_faltan` (servidor HTTP local en un hilo que sirve dos archivos chicos; `url_base` apuntando a él; con uno ya presente solo baja el otro; no queda ningún `.part`; devuelve la lista de los bajados; el `progreso` recibe una línea por archivo); `test_descargar_modelos_con_error_de_red_no_deja_basura` (servidor que devuelve 404 → `URLError`/`HTTPError` propagado y sin `.part`); `test_descargar_no_hace_nada_si_estan_todos`.
  - `test_integracion_con_kokoro_real` (se saltea si `faltan_modelos(...)` no está vacío; el directorio sale de `CASSETTE_DJ_MODELOS` o del default): sintetiza los fonemas de "Qué tal gente son las nueve en Buenos Aires con dieciocho grados" con `em_santa` → duración entre 2 y 8 s y el WAV es legible; y `voces()` incluye `em_santa`.
- [ ] **Step 2:** `.venv/bin/pytest tests/dj/test_sintetizador.py -q` → FAIL.
- [ ] **Step 3:** Implementar `sintetizador.py` (escribir con `soundfile`, `subtype="PCM_16"`).
- [ ] **Step 4:** Suite completa → PASS (con la variable apuntando a los modelos de prueba, si existen, el test de integración corre).
- [ ] **Step 5:** Commit `Servicio DJ: sintetizador con Kokoro de carga a demanda`.

---

### Task 6: Guiones, productor y cola

**Files:** Create `src/cassette_fm/dj/guiones.py`, `src/cassette_fm/dj/produccion.py`, `src/cassette_fm/dj/cola.py`, `tests/dj/test_guiones.py`, `tests/dj/test_produccion.py`, `tests/dj/test_cola.py`

**Interfaces:**
- Consumes: `Pedido` (Task 2), `preparar`/`Preparado` (Task 3), `redactar`/`Lexico`/`Redaccion` (Task 4), `Sintetizador`/`ErrorModelos` (Task 5), `ConfigServicioDJ`, `RutasDJ` (Task 1).
- Produces:

```python
# guiones.py
class RegistroGuiones:
    def __init__(self, archivo: Path): ...
    def anotar(self, **campos) -> None          # agrega UNA línea JSON (UTF-8, ensure_ascii=False) con "ts" ISO-8601 con zona; crea directorios; nunca borra ni trunca; seguro entre hilos
    def ultimos(self, n: int) -> list[dict]     # los últimos n registros (los más viejos primero); líneas ilegibles se ignoran
# produccion.py
@dataclass(frozen=True)
class Resultado:
    texto: str; marcado: str; ingredientes: tuple[str, ...]; duracion: float; audio: Path; voz: str; idioma: str
class Productor:
    def __init__(self, config: ConfigServicioDJ, rutas: RutasDJ, sintetizador, fonemizar: Callable[[str, str], str],
                 lexico: Lexico, guiones: RegistroGuiones, azar: random.Random | None = None): ...
    def producir(self, pedido: Pedido) -> Resultado
        # redactar -> preparar -> sintetizar a rutas.clips/<id>.wav -> anotar guion. Si el clip dura más que
        # pedido.duracion_maxima_segundos, descarta el clip y reintenta con otra redacción (hasta 3 intentos);
        # si ninguno entra, ValueError("el clip dura X s y el máximo es Y s"). Los errores del sintetizador se propagan.
# cola.py
class EstadoTrabajo(str, Enum): PENDIENTE="pendiente"; TRABAJANDO="trabajando"; LISTO="listo"; ERROR="error"; CANCELADO="cancelado"
class Cola:
    def __init__(self, productor, trabajadores: int = 1, retencion_segundos: float = 3600.0,
                 reloj: Callable[[], float] = time.monotonic): ...      # arranca los hilos de trabajo
    def enviar(self, pedido: Pedido) -> str                # devuelve pedido.id; idempotente: un id ya conocido no se vuelve a encolar
    def estado(self, id: str) -> dict | None               # {"estado","duracion","texto","ingredientes","error"}; None si no existe
    def audio(self, id: str) -> Path | None                # solo si está LISTO y el archivo existe
    def cancelar(self, id: str) -> bool                    # True solo si estaba PENDIENTE
    def contadores(self) -> dict[str, int]                 # cantidad por estado
    def limpiar(self) -> int                               # quita los terminados que pasaron la retención y borra sus clips; devuelve cuántos
    def detener(self, espera: float = 5.0) -> None         # termina los hilos
```

El guion que anota el `Productor` (por cada clip producido, y también por cada intento descartado marcado con `"descartado": true`): `{"ts", "id", "estacion", "idioma", "voz", "momento", "anterior", "siguiente", "fuente": "plantilla", "ingredientes", "texto", "marcado", "fonemas", "duracion", "audio"}`. **`texto` y `marcado` son los que se usan "tal cual" en las pruebas de voz** (Task 7, `voz-prueba`). Los errores de un trabajo se anotan con `"error"` en vez de `duracion`/`audio`.

La `Cola` ejecuta `producir` en hilos de trabajo (FIFO). Un error del productor deja el trabajo en `ERROR` con `str(e)` (`ErrorModelos` incluido); una excepción inesperada también, con un mensaje genérico y el detalle en el log. `limpiar` corre periódicamente en un hilo de mantenimiento (cada minuto) y también se puede invocar.

- [ ] **Step 1: Tests que fallan.**
  - `tests/dj/test_guiones.py`: `test_anota_una_linea_json_con_ts_y_acentos`; `test_crea_los_directorios`; `test_no_trunca_ni_borra_lo_anterior` (reabrir y seguir anotando); `test_desde_varios_hilos_no_mezcla_lineas` (8 hilos × 50 anotaciones → 400 líneas JSON válidas); `test_ultimos_devuelve_los_ultimos_en_orden_e_ignora_lineas_rotas`.
  - `tests/dj/test_produccion.py` (con `SintetizadorFalso` que escribe un WAV de duración configurable en la ruta pedida y devuelve esa duración, un `fonemizar` falso, un `Lexico` y `random.Random(1)`): `test_produce_el_clip_en_clips_y_anota_el_guion` (el audio es `rutas.clips/<id>.wav`; el guion tiene todos los campos, `fuente == "plantilla"`, y `texto` no tiene llaves mientras `marcado` sí tiene al menos una marca); `test_el_guion_alcanza_para_volver_a_sintetizar` (a partir de `marcado` y `idioma` del guion, `preparar` reproduce los mismos `fonemas` anotados); `test_reintenta_si_el_clip_es_demasiado_largo` (el falso devuelve 20 s las dos primeras veces y 5 la tercera con `duracion_maxima_segundos=10` → éxito al tercer intento, los dos clips descartados no quedan en disco y su guion tiene `"descartado": true`); `test_falla_si_ningun_intento_entra` (`ValueError` con las duraciones; sin clips sobrantes); `test_propaga_ErrorModelos`; `test_el_id_no_puede_escapar_de_clips` (un `Pedido` armado a mano con `id="../fuera"` salteando `leer_pedido` → `ValueError` y no se crea nada fuera); `test_usa_el_idioma_y_la_voz_del_pedido` (el falso recibe `lang` correcto y la `voz`).
  - `tests/dj/test_cola.py` (con un `ProductorFalso` controlable: puede bloquearse con un `Event`, fallar, tardar): `test_un_pedido_termina_en_listo_con_su_resultado`; `test_es_idempotente_por_id` (dos `enviar` del mismo id → un solo `producir`); `test_orden_de_llegada_con_un_trabajador` (3 pedidos con el primero bloqueado → se producen en orden 1, 2, 3); `test_cancelar_un_pendiente_si_y_uno_en_trabajo_no`; `test_un_error_deja_el_trabajo_en_error_con_mensaje` (también con `ErrorModelos`); `test_una_excepcion_inesperada_no_mata_al_hilo` (un pedido que lanza `RuntimeError` seguido de otro que sale bien); `test_estado_de_un_id_desconocido_es_None`; `test_audio_solo_si_esta_listo`; `test_contadores`; `test_la_retencion_borra_terminados_y_sus_clips` (reloj falso); `test_detener_no_deja_hilos_vivos` (`threading.enumerate()` antes/después); `test_dos_trabajadores_procesan_en_paralelo` (dos pedidos bloqueados al mismo tiempo).
- [ ] **Step 2:** `.venv/bin/pytest tests/dj/test_guiones.py tests/dj/test_produccion.py tests/dj/test_cola.py -q` → FAIL.
- [ ] **Step 3:** Implementar los tres módulos.
- [ ] **Step 4:** Suite completa → PASS; repetir `tests/dj/test_cola.py` 5 veces seguidas sin fallos (hay hilos).
- [ ] **Step 5:** Commit `Servicio DJ: guiones, productor y cola de trabajos`.

---

### Task 7: Servidor HTTP, comandos e instalación

**Files:** Create `src/cassette_fm/dj/servidor.py`, `packaging/cassette-dj.service.in`, `scripts/instalar-dj.sh`, `tests/dj/test_servidor.py`, `tests/dj/test_cli.py`; Modify `src/cassette_fm/dj/cli.py`, `README.md`

**Interfaces:**
- Consumes: `Cola`, `EstadoTrabajo` (Task 6), `leer_pedido` (Task 2), `Sintetizador`, `faltan_modelos`, `fonemizador`, `URL_MODELOS`, `ARCHIVOS_MODELO` (Task 5), `RegistroGuiones`, `Productor` (Task 6), `Lexico` (Task 4), config y rutas (Task 1).
- Produces:

```python
def crear_servidor(cola: Cola, sintetizador: Sintetizador, host: str, puerto: int,
                   modelos_dir: Path) -> ThreadingHTTPServer      # `puerto=0` elige uno libre
def servir(config: ConfigServicioDJ, rutas: RutasDJ, parar: threading.Event | None = None,
           fabrica_sintetizador=None) -> None                     # arma todo y bloquea hasta SIGTERM/SIGINT o `parar`
```

| Método y ruta | Cuerpo | Respuesta |
|---|---|---|
| `POST /intervenciones` | el pedido (JSON) | `202 {"id": ...}`; `400 {"error": "campo 'x': ..."}` (JSON inválido o `ValueError` de `leer_pedido`) |
| `GET /intervenciones/<id>` | — | `200 {"estado","duracion","texto","ingredientes","error"}`; `404` si no existe |
| `GET /intervenciones/<id>/audio` | — | `200` con `Content-Type: audio/wav` y los bytes; `404` si no existe; `409 {"error": "todavía no está listo"}` si existe y no está `listo` |
| `DELETE /intervenciones/<id>` | — | `200 {"cancelado": bool}`; `404` si no existe |
| `GET /voces` | — | `200 {"voces": [...]}` |
| `GET /salud` | — | `200 {"ok": true, "modelo_cargado": bool, "faltan_modelos": [nombres], "trabajos": {estado: cantidad}}` |

Errores: JSON de la forma `{"error": "<mensaje en español>"}`; 404 para rutas desconocidas; excepciones inesperadas → 500 con mensaje genérico y el detalle en el log; cuerpos de más de 64 KB → 413. El `id` de la URL se valida con la misma regla que el pedido (si no cumple, 404).

Comandos de `cassette-dj` (`main(argv)`):
- `serve`: llama a `servir` con la configuración de `rutas_dj().config`; si faltan modelos, **arranca igual** y lo avisa en el log una vez.
- `modelos`: llama a `descargar_modelos` (Task 5) con `modelos_dir`; si ya están, lo dice y no baja nada; error de red → mensaje claro y código 1.
- `voces`: lista las voces (`Sintetizador.voces()`); sin archivo de voces, explica que hay que correr `modelos`.
- `guiones [--ultimos N]` (por defecto 10): imprime los guiones (`2026-11-13 21:47 · Power · em_santa · texto`).
- `voz-prueba --voz V [--voz V2 …] [--ultimos N] [--salida DIR] [--idioma es|en]`: toma los últimos N guiones (por defecto 5, filtrables por idioma), los vuelve a **preparar y sintetizar tal cual** (`marcado` + `idioma` del guion) con cada voz y deja los WAV en `DIR` (por defecto `./voz-prueba/`) con nombres `NN-<voz>.wav`, e imprime el texto de cada uno. Es lo que se usa para las pruebas de voz del final de la etapa.

`scripts/instalar-dj.sh` (idempotente, lo corre el usuario): instala el extra en el entorno (`.venv/bin/pip install -e ".[dj]"`), genera `~/.config/systemd/user/cassette-dj.service` desde `packaging/cassette-dj.service.in` (`ExecStart=@CASSETTE_DJ@ serve`, `Restart=on-failure`), hace `systemctl --user daemon-reload && enable --now cassette-dj` y recuerda correr `cassette-dj modelos`. **Cierra el `README`** con la sección "Servicio DJ".

- [ ] **Step 1: Tests que fallan.**
  - `tests/dj/test_servidor.py` (servidor real en un hilo con `puerto=0`, una `Cola` con `Productor` verdadero y un `SintetizadorFalso` que escribe WAV, y `urllib`): `test_post_y_consulta_hasta_listo_y_descarga_del_audio` (POST → 202 → polling del estado hasta `listo` → `GET .../audio` devuelve bytes de un WAV legible con `Content-Type: audio/wav`); `test_post_es_idempotente`; `test_pedido_invalido_da_400_con_el_campo` (campo faltante; JSON roto; `id` con `../`); `test_cuerpo_demasiado_grande_413`; `test_estado_y_audio_de_id_desconocido_404`; `test_audio_de_un_trabajo_no_listo_409` (productor bloqueado); `test_delete_cancela_un_pendiente_y_no_uno_en_trabajo`; `test_voces`; `test_salud_informa_modelos_faltantes_y_contadores`; `test_un_pedido_sin_modelos_termina_en_error_claro` (sintetizador real con `modelos_dir` vacío → el estado llega a `error` con un mensaje que menciona `cassette-dj modelos`); `test_id_con_caracteres_raros_en_la_url_da_404`; `test_ruta_desconocida_404`; `test_error_inesperado_500_y_se_loguea`.
  - `tests/dj/test_cli.py`: `test_voz_prueba_resintetiza_los_guiones_tal_cual` (con un archivo de guiones armado a mano y un sintetizador falso inyectado, se generan `NN-<voz>.wav` por guion y voz, y el sintetizador recibió los **mismos fonemas** que `preparar(marcado, ...)` da para ese guion); `test_voz_prueba_sin_guiones_explica_que_hacer`; `test_guiones_imprime_los_ultimos`; `test_modelos_dice_que_ya_estan` (con los dos archivos presentes no se llama a la descarga) y `test_modelos_error_de_red_da_codigo_1` (con `descargar_modelos` parchada para lanzar `URLError`: código 1 y mensaje claro); `test_voces_sin_archivo_explica`; `test_serve_arranca_aunque_falten_modelos` (con `servir` en un hilo y `parar`).
  - `tests/dj/test_servidor.py::test_de_punta_a_punta_con_kokoro_real` (se saltea si faltan modelos): POST de un pedido `es` con voz `em_santa` y un siguiente de "Daddy Yankee" → llega a `listo`; el audio es un WAV legible de entre 3 y 15 s; el guion anotado tiene `texto`, `marcado` y `fonemas` con el tramo en inglés; y el mismo flujo con `en` y `am_michael`.
- [ ] **Step 2:** `.venv/bin/pytest tests/dj/test_servidor.py tests/dj/test_cli.py -q` → FAIL.
- [ ] **Step 3:** Implementar `servidor.py` y completar `cli.py`; escribir `packaging/cassette-dj.service.in` y `scripts/instalar-dj.sh` (`bash -n` sin errores; **no se ejecutan** durante el desarrollo).
- [ ] **Step 4:** Suite completa → PASS; repetir `tests/dj/test_servidor.py` 5 veces seguidas sin fallos.
- [ ] **Step 5:** README: sección "Servicio DJ" con instalación (`scripts/instalar-dj.sh`, `cassette-dj modelos`), el contrato HTTP en una tabla, `curl` de ejemplo (POST y consulta), la configuración con sus valores por defecto, los guiones (`cassette-dj guiones`) y `voz-prueba`. Aclarar que **no tiene autenticación** y que para usarlo desde otra máquina hay que poner `host = "0.0.0.0"` en una red de confianza.
- [ ] **Step 6:** Commit `Servicio DJ: servidor HTTP, comandos y script de instalación`. Cerrar el bean `CASSETTE-FM-jd7u`.
