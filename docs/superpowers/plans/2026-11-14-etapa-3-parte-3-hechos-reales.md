# Etapa 3, parte 3: hechos reales para el DJ — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que las frases del DJ dejen de ser calcadas: el servicio DJ junta datos verificados (clima de Buenos Aires, año del tema y país y comienzo del artista de MusicBrainz), elige con pesos de 1 a 3 ingredientes sin repetir los recientes y arma la frase con plantillas que los usan. Sin datos, dice lo básico.

**Architecture:** Dentro de `cassette_fm.dj`, un paquete `hechos/` con clientes chicos y tolerantes a fallos (nunca lanzan hacia afuera: sin dato = `None`), una caché SQLite que guarda también los "no se encontró", un selector de ingredientes puro y una redacción por **marco + extras** en vez de plantillas enteras. El `Productor` reúne los hechos antes de redactar y anota en el guion qué hechos usó y de dónde salieron.

**Tech Stack:** Python 3.12, `urllib`, `sqlite3`, `threading`, pytest. Los tests simulan open-meteo y MusicBrainz con un servidor HTTP local; las pruebas con los servicios reales son manuales.

**Spec:** [`docs/superpowers/specs/2026-11-13-etapa-3-dj-design.md`](../specs/2026-11-13-etapa-3-dj-design.md) (secciones "Ingredientes y frecuencia" y "Datos verificados", con la nota del 14/11: Wikipedia → parte 4).

## Global Constraints

- Bean: `CASSETTE-FM-ebyx`. Al empezar, `-s in-progress`; al terminar la Task 6, `-s completed` (y cerrar el bean viejo `CASSETTE-FM-432j`, que esta parte absorbe) y se incluye `.beans/` en el commit.
- **Nada fijo en el código:** pesos, caché, timeouts, coordenadas, URLs y el contacto viven en `ConfigServicioDJ` con su valor por defecto (lista exacta en Task 1).
- **Todo dato sale de una fuente verificada o no se dice.** Si MusicBrainz no devuelve un candidato inequívoco, o falla, o no hay `contacto` configurado, ese ingrediente no se ofrece; la frase usa lo demás. Nunca se inventa ni se completa con suposiciones.
- **MusicBrainz:** a lo sumo 1 pedido por segundo por proceso (`threading.Lock` + reloj inyectable) y `User-Agent: cassette-dj/<versión> (<contacto>)`. `contacto` no tiene valor por defecto: **vacío = no se consulta MusicBrainz** (un solo aviso en el log al arrancar). El mail del usuario no se escribe en ningún archivo del repo ni en ningún pedido: lo pone él en `~/.config/cassette-dj/config.toml`.
- **Año del tema** = el mínimo de `first-release-date` entre las grabaciones que coinciden exactamente (normalizadas) en título **y** artista, y solo si es ≥ al año de comienzo del artista cuando este se conoce. **Comienzo del artista** solo si `type == "Group"` (en una persona `life-span.begin` es el nacimiento). **País**: `country` del artista (código ISO) traducido con una tabla propia es/en; si el código no está en la tabla, no hay ingrediente.
- Las plantillas **no tienen dígitos** (la hora ya se escribe en palabras): temperaturas y años también se dicen en palabras (`numeros.py`).
- Toda red del servicio tiene `timeout_hechos_segundos`; un fallo de red se cachea unos minutos como "sin dato" para no reintentar en cada pedido.
- Todo mensaje, nombre y comentario en español. Commits en español, texto plano en imperativo, con la línea de atribución vigente.
- Los tests no tocan `~/.config`, `~/.local`, `~/.cache` ni la red real. **La verificación con servicios reales la hacemos juntos al final (Task 6).**
- Al terminar cada tarea: `.venv/bin/pytest -q` completo en verde (hoy 811 tests; `CASSETTE_DJ_MODELOS=~/.local/share/cassette-dj/modelos`).

## Review Focus

1. **MusicBrainz ambiguo o equivocado:** mismo título de otro artista, artista con guion unicode (`a‐ha`), temas con "feat." o "Remastered" en el título, varias grabaciones con años distintos → el año correcto (el mínimo coincidente) o ningún dato; jamás el de otro tema. → Task 3.
2. **Servicios caídos, lentos o que contestan basura** (HTML, JSON sin los campos, 503/429 de MusicBrainz): la frase sale igual, sin dato y sin traceback; el fallo se cachea poco tiempo y se avisa una vez. → Tasks 2 y 3.
3. **Variedad real:** en cientos de pedidos con los mismos datos no se repiten siempre los mismos ingredientes ni el mismo marco, respetando `recientes`; con `recientes` saturado igual se produce una frase. → Tasks 4 y 5.
4. **Frases dentro del tope:** ninguna combinación de marco + extras supera `palabras_maximas` ni `duracion_maxima_segundos` (el `Productor` ya reintenta más corto). Sin dígitos, sin llaves sueltas, con los nombres propios marcados por idioma. → Task 5.
5. **Caché:** dos hilos pidiendo el mismo tema a la vez (una sola consulta a MusicBrainz), base corrupta o no escribible (se sigue sin caché), y vencimiento de los "no se encontró". → Task 2.

---

## Estructura de archivos

```
src/cassette_fm/dj/config.py             # Task 1: campos nuevos, [ingredientes], RutasDJ.hechos
src/cassette_fm/dj/hechos/__init__.py    # Task 1: Hechos (dataclass); Task 6: FuenteHechos
src/cassette_fm/dj/hechos/numeros.py     # Task 1: números y años en palabras (es/en)
src/cassette_fm/dj/hechos/paises.py      # Task 1: código ISO -> nombre es/en
src/cassette_fm/dj/hechos/cache.py       # Task 2: CacheHechos (SQLite)
src/cassette_fm/dj/hechos/clima.py       # Task 2: ClienteClima, Clima
src/cassette_fm/dj/hechos/musicbrainz.py # Task 3: ClienteMusicBrainz, DatosTema
src/cassette_fm/dj/selector.py           # Task 4: elegir_ingredientes
src/cassette_fm/dj/plantillas.py         # Task 5: marco + extras
src/cassette_fm/dj/produccion.py, servidor.py   # Task 6
tests/dj/hechos/, tests/dj/test_selector.py, ...
```

---

### Task 1: Configuración, números en palabras y países

**Files:** Modify `src/cassette_fm/dj/config.py`, `tests/dj/test_config.py`; Create `src/cassette_fm/dj/hechos/__init__.py` (con el dataclass `Hechos`, ver abajo), `hechos/numeros.py`, `hechos/paises.py`, `tests/dj/hechos/__init__.py`, `tests/dj/hechos/test_numeros.py`, `tests/dj/hechos/test_paises.py`

**Interfaces:**
- Produces, en `ConfigServicioDJ` (todos con estos valores por defecto):

```python
contacto: str = ""                       # va en el User-Agent de MusicBrainz; vacío = no se consulta
musicbrainz_url: str = "https://musicbrainz.org/ws/2"
open_meteo_url: str = "https://api.open-meteo.com/v1/forecast"
latitud: float = -34.6037
longitud: float = -58.3816
timeout_hechos_segundos: float = 5.0
cache_clima_minutos: float = 15.0
cache_datos_dias: float = 90.0           # dato encontrado
cache_sin_dato_dias: float = 14.0        # "no se encontró" (consulta que funcionó y no dio nada)
cache_error_minutos: float = 10.0        # la red falló: no reintentar enseguida
ingredientes_max: int = 3                # cuántos ingredientes combina una frase (el tema cuenta)
penalizacion_reciente: float = 0.3       # cada aparición en `recientes` multiplica el peso por esto
pesos_ingredientes: Mapping[str, float]  # default: ver tabla
# RutasDJ.hechos -> estado / "hechos.sqlite"
```

  Pesos por defecto (probabilidad base de ofrecer el ingrediente; `cancion` siempre va, no es configurable): `estacion 0.5`, `hora 0.35`, `momento 0.3`, `album 0.3`, `anterior 0.3`, `clima 0.12`, `dato 0.25`. Tabla `[ingredientes]` en el TOML del servicio (clave = nombre, valor número en [0, 1]; claves desconocidas → `ErrorConfig`; `cancion` no se acepta).
- Produce, `hechos/numeros.py`: `en_palabras(n: int, idioma: str) -> str` (idioma `"es"` o `"en"`; enteros de −99 a 99; fuera de rango `ValueError`; es: `veintidós`, `menos tres`, `uno` → se usa `un` solo donde corresponda lo decide el llamador; en: `twenty two`, `minus three`) y `anio_en_palabras(a: int, idioma: str) -> str` (1900–2099; es: `mil novecientos ochenta y cuatro`, `dos mil`, `dos mil veintiuno`; en: `nineteen eighty four`, `two thousand`, `two thousand twenty one`, `nineteen oh five`).
- Produce, `hechos/paises.py`: `nombre_de_pais(codigo: str, idioma: str) -> str | None` (≈ 60 códigos ISO-3166 alfa-2 más comunes en la música: `AR, US, GB, ES, MX, PR, CO, BR, CL, UY, PE, VE, DO, CU, PA, EC, BO, PY, CR, GT, FR, DE, IT, SE, NO, DK, FI, IE, NL, BE, CH, AT, PT, PL, RU, JP, KR, AU, NZ, CA, JM, TT, IS, GR, TR, IN, ZA, NG, CN, CZ, HU, UA, IL`…; `None` si no está; es: `"Noruega"`, `"Estados Unidos"`, `"Reino Unido"`; en: `"Norway"`, `"the United States"`, `"the United Kingdom"` con el artículo incluido).

- [ ] **Step 1: Tests que fallan.** `test_config.py`: `test_defaults_de_los_hechos` (los 12 valores exactos), `test_contacto_y_urls_se_leen`, `test_ingredientes_se_leen_y_validan` (`[ingredientes] clima = 0.5` vale; `cancion = 1`, `clima = 2`, `clima = "x"`, `inventado = 0.1`, `ingredientes = 3` dan `ErrorConfig` con la ruta), `test_valores_invalidos_de_los_hechos` (`timeout_hechos_segundos = 0`, `ingredientes_max = 0`, `penalizacion_reciente = 1.5`, `latitud = 200`, `musicbrainz_url = "ftp://x"`, `cache_datos_dias = -1`), `test_rutas_hechos`. `test_numeros.py`: tabla parametrizada con todos los ejemplos de arriba más `0`, `1`, `15`, `21`, `30`, `99`, `−1`, `1999`, `2010`, `2026`, `1900` en los dos idiomas, y `ValueError` en `100`/`1899`/`2100`. `test_paises.py`: los ejemplos, `None` para `"ZZ"`, insensible a mayúsculas, y que **cada** código de la tabla tenga nombre en los dos idiomas.
- [ ] **Step 2:** `.venv/bin/pytest tests/dj/test_config.py tests/dj/hechos -q` → FAIL.
- [ ] **Step 3:** Implementar (extender `_TIPOS`/`_validar` como las demás claves; los pesos se funden con los de fábrica).
- [ ] **Step 4:** Suite completa → PASS.
- [ ] **Step 5:** Commit `Servicio DJ: configuración de los hechos, números en palabras y países`.

---

### Task 2: Caché SQLite y clima

**Files:** Create `src/cassette_fm/dj/hechos/cache.py`, `hechos/clima.py`, `tests/dj/hechos/test_cache.py`, `tests/dj/hechos/test_clima.py`; Modify `tests/dj/conftest.py` (fixture `servidor_http`: servidor de pruebas que sirve respuestas fijas por ruta y cuenta pedidos)

**Interfaces:**
- Produces:

```python
class CacheHechos:
    def __init__(self, archivo: Path | None, reloj: Callable[[], float] = time.time): ...   # None = solo en memoria
    def obtener(self, clave: str) -> tuple[bool, object | None]    # (hay_entrada_vigente, valor); valor None = "sin dato" cacheado
    def guardar(self, clave: str, valor: object | None, vigencia_segundos: float) -> None   # valor JSON-serializable
    def consultar(self, clave: str, vigencia: Callable[[object | None], float], buscar: Callable[[], object | None]) -> object | None
        # obtener -> si hay vigente, devolverlo; si no, UNA sola llamada a buscar() aunque haya varios hilos esperando
        # (lock por clave); guardar con vigencia(valor) y devolver. Si buscar() lanza, no guarda y propaga.

@dataclass(frozen=True)
class Clima:
    temperatura: int            # °C redondeados
    cielo: str                  # "despejado" | "nublado" | "lluvia" | "tormenta" | "niebla" | "nieve"
    es_de_dia: bool

class ClienteClima:
    def __init__(self, config: ConfigServicioDJ, cache: CacheHechos, reloj=time.time): ...
    def actual(self) -> Clima | None     # nunca lanza; None si falla o la respuesta no sirve
```

- Reglas de `CacheHechos`: SQLite (`PRAGMA journal_mode=WAL`), una tabla `(clave PRIMARY KEY, valor TEXT JSON, vence REAL)`; base corrupta o no escribible → se avisa **una vez** en el log y sigue en memoria; seguro entre hilos; las entradas vencidas se ignoran y se borran al encontrarlas.
- Reglas de `ClienteClima`: `GET {open_meteo_url}?latitude=..&longitude=..&current=temperature_2m,weather_code,is_day&timezone=<zona_horaria>` (el contrato real de open-meteo, comprobado el 14/11: `current.temperature_2m`, `current.weather_code`, `current.is_day`); códigos WMO → cielo: `0,1 → despejado`; `2,3 → nublado`; `45,48 → niebla`; `51–67, 80–82 → lluvia`; `71–77, 85, 86 → nieve`; `95–99 → tormenta`; cualquier otro → `None`. Caché `cache_clima_minutos` con clave `clima`; un fallo de red o respuesta inválida se cachea `cache_error_minutos` como "sin dato" y se avisa una sola vez por episodio.

- [ ] **Step 1: Tests que fallan.** `test_cache.py`: `test_guarda_y_devuelve`, `test_vence_con_el_reloj`, `test_sin_dato_se_cachea_y_se_distingue_de_ausente`, `test_persiste_entre_instancias`, `test_consultar_llama_a_buscar_una_sola_vez_con_hilos` (8 hilos, `buscar` lento: 1 llamada), `test_si_buscar_lanza_no_guarda`, `test_base_corrupta_sigue_en_memoria_y_avisa_una_vez` (archivo con basura y directorio de solo lectura), `test_archivo_none_es_memoria`. `test_clima.py` (con `servidor_http`): `test_parsea_la_respuesta_real` (el JSON real de arriba, recortado), `test_cada_codigo_wmo` (parametrizada con la tabla), `test_codigo_desconocido_da_None`, `test_usa_cache` (dos `actual()`: 1 pedido), `test_servidor_caido_da_None_y_avisa_una_vez` (caplog), `test_respuestas_basura` (HTML, JSON sin `current`, temperatura que es texto, `null`), `test_timeout_da_None`, `test_un_fallo_se_cachea_poco_y_despues_reintenta` (reloj inyectado), `test_la_url_lleva_coordenadas_y_zona`.
- [ ] **Step 2:** `.venv/bin/pytest tests/dj/hechos -q` → FAIL (los nuevos).
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** Suite completa → PASS.
- [ ] **Step 5:** Commit `Servicio DJ: caché SQLite de hechos y clima de Buenos Aires (open-meteo)`.

---

### Task 3: MusicBrainz

**Files:** Create `src/cassette_fm/dj/hechos/musicbrainz.py`, `tests/dj/hechos/test_musicbrainz.py`

**Interfaces:**
- Consumes: `ConfigServicioDJ` (Task 1), `CacheHechos.consultar` (Task 2), `Tema` de `dj/pedido.py`.
- Produces:

```python
@dataclass(frozen=True)
class DatosTema:
    anio: int | None               # año de lanzamiento del tema (mínimo coincidente)
    pais: str | None               # código ISO del artista ("NO"), si tiene
    anio_inicio_artista: int | None  # solo si es un grupo
    es_grupo: bool
    fuente: str                    # URL del artista en MusicBrainz (https://musicbrainz.org/artist/<mbid>)

class ClienteMusicBrainz:
    def __init__(self, config: ConfigServicioDJ, cache: CacheHechos, reloj=time.time, dormir=time.sleep, version: str = ...): ...
    def datos_del_tema(self, artista: str, titulo: str, isrc: str | None = None) -> DatosTema | None   # nunca lanza
```

Algoritmo (lo fija el plan):
1. Sin `contacto` → `None` (un aviso al crear el cliente, no por pedido). Clave de caché: `mb:<artista normalizado>|<título normalizado>` (o `mb:isrc:<ISRC>`); vigencias: encontrado `cache_datos_dias`, sin dato `cache_sin_dato_dias`, error de red `cache_error_minutos`.
2. **Normalizar** para comparar: minúsculas, sin acentos, guiones unicode (`‐‑–—`) → `-`, `&` → `and`, sin signos, espacios colapsados; del título se descartan sufijos entre paréntesis o tras " - " del tipo `remaster`, `remastered`, `remix`, `radio edit`, `feat.`, `from ...`, `version`, `mono`, `stereo`, `single`, `live`, `soundtrack` **solo para la comparación** (el título buscado se arma limpio, no se manda el sufijo a MusicBrainz); "feat. X" del artista se ignora: se compara con el primer artista.
3. Con ISRC: `GET /isrc/<ISRC>?inc=artists&fmt=json` → grabaciones; sin ISRC: `GET /recording?query=recording:"<título limpio>" AND artist:"<primer artista>"&limit=25&fmt=json`. Se **filtran** las grabaciones cuyo título normalizado sea igual al buscado y cuyo `artist-credit` contenga (normalizado) al primer artista. **Sin ninguna → `None` (cacheado como sin dato).**
4. Del conjunto filtrado: todas deben compartir el mismo `artist.id` del primer artista; si hay dos ids distintos → ambiguo → `None`. `anio` = mínimo año de `first-release-date` (formatos `YYYY`, `YYYY-MM`, `YYYY-MM-DD`; ignorar vacíos) o `None`.
5. `GET /artist/<id>?fmt=json` → `country`, `type`, `life-span.begin`. `es_grupo = type == "Group"`; `anio_inicio_artista` = año de `begin` solo si es grupo; si `anio` < `anio_inicio_artista` → `anio = None` (inconsistente). Si no queda ningún dato útil (`anio`, `pais`, `anio_inicio_artista` todos `None`) → `None`.
6. **Ritmo:** antes de cada pedido HTTP se espera lo que falte para 1 s desde el anterior (`dormir`). `User-Agent: cassette-dj/<versión> (<contacto>)`, `Accept: application/json`. Errores 429/503 → `ErrorRed` interno → `None` cacheado `cache_error_minutos`, un aviso por episodio. Ni red ni parseo lanzan hacia afuera.

- [ ] **Step 1: Tests que fallan** (con `servidor_http` que imita `/recording`, `/isrc/..`, `/artist/..`; JSON con la forma real vista el 14/11: `recordings[].{id,score,title,artist-credit[].artist.{id,name},first-release-date,releases[]}`, `artist.{name,type,country,life-span.begin}`): `test_take_on_me_da_1984_noruega_grupo_1983` (varias grabaciones con años 2019, 2012, 1984-10-19, 2001, `None` y el nombre `a‐ha` con U+2010 → 1984), `test_sin_contacto_no_consulta_y_avisa_una_vez`, `test_el_user_agent_lleva_el_contacto`, `test_homonimo_de_otro_artista_no_se_usa` (mismo título, artista distinto → `None`), `test_dos_artistas_con_el_mismo_nombre_es_ambiguo`, `test_titulo_con_remaster_y_feat_se_compara_limpio` (`"Waiting for a Girl Like You - 2008 Remaster"`, `"Gasolina (feat. X)"`; y la búsqueda manda el título limpio), `test_persona_no_usa_life_span_como_inicio`, `test_anio_anterior_al_inicio_del_grupo_se_descarta`, `test_pais_se_devuelve_como_codigo`, `test_isrc_tiene_prioridad_y_otra_clave_de_cache`, `test_cache_evita_repetir` (2 llamadas: 2 pedidos HTTP en total, uno al `/recording` y otro al `/artist`), `test_sin_resultados_se_cachea_como_sin_dato`, `test_el_ritmo_es_de_un_pedido_por_segundo` (`dormir` falso registra esperas; reloj inyectado), `test_503_y_429_dan_None_sin_traceback_y_se_cachean_poco`, `test_respuestas_basura` (HTML, JSON sin `recordings`, `score` texto, `first-release-date` raro como `"2026-13-99"`), `test_timeout_da_None`, `test_nombres_con_enie_acentos_y_comillas`.
- [ ] **Step 2:** `.venv/bin/pytest tests/dj/hechos/test_musicbrainz.py -q` → FAIL.
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** Suite completa → PASS.
- [ ] **Step 5:** Commit `Servicio DJ: cliente de MusicBrainz con año del tema, país y comienzo del artista`.

---

### Task 4: Selector de ingredientes

**Files:** Create `src/cassette_fm/dj/selector.py`, `tests/dj/test_selector.py`

**Interfaces:**
- Produces:

```python
def elegir_ingredientes(disponibles: Collection[str], pesos: Mapping[str, float], recientes: Sequence[str],
                        azar: random.Random, maximo: int = 3, penalizacion: float = 0.3) -> tuple[str, ...]
    # siempre incluye "cancion" primero; después, cada ingrediente de `disponibles` (excepto "cancion") se ofrece con
    # probabilidad pesos[i] * penalizacion ** recientes.count(i) (peso faltante = 0, no se ofrece); de los ofrecidos
    # se toman a lo sumo maximo-1, sin repetir, priorizando al azar ponderado por esa misma probabilidad
```

- [ ] **Step 1: Tests que fallan:** `test_siempre_incluye_la_cancion_primero`, `test_nunca_pasa_del_maximo` (maximo 1 → solo canción; 2, 3), `test_solo_elige_entre_los_disponibles`, `test_frecuencias_cercanas_a_los_pesos` (5000 corridas con `Random(1)`: cada ingrediente aparece en una fracción dentro de ±0,05 de su peso cuando no hay tope, con `maximo=9`), `test_la_penalizacion_baja_lo_reciente` (con `recientes=["hora","hora"]` la frecuencia de `hora` ≈ `0.35 * 0.09`), `test_con_recientes_saturado_igual_devuelve_la_cancion`, `test_pesos_en_cero_no_se_ofrecen`, `test_es_determinista_con_la_misma_semilla`, `test_ingrediente_desconocido_sin_peso_no_se_ofrece`.
- [ ] **Step 2:** `.venv/bin/pytest tests/dj/test_selector.py -q` → FAIL.
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** Suite completa → PASS.
- [ ] **Step 5:** Commit `Servicio DJ: selector ponderado de ingredientes`.

---

### Task 5: Plantillas por marco y extras

**Files:** Modify `src/cassette_fm/dj/plantillas.py`, `tests/dj/test_plantillas.py`

**Interfaces:**
- Consumes: `elegir_ingredientes` (Task 4), `en_palabras`, `anio_en_palabras` (Task 1), `nombre_de_pais` (Task 1), `Clima`, `DatosTema` (Tasks 2 y 3), `Pedido`, `Lexico`.
- Produces, en `plantillas.py`:

```python
# Hechos se importa de cassette_fm.dj.hechos (Task 1)

@dataclass(frozen=True)
class Redaccion:
    marcado: str
    ingredientes: tuple[str, ...]   # los que de verdad entraron en la frase (sin los que no cupieron)

def ingredientes_disponibles(pedido: Pedido, hechos: Hechos) -> set[str]
    # "cancion" siempre; "estacion", "hora", "momento" siempre; "album" si el tema trae álbum; "anterior" si hay;
    # "clima" si hechos.clima; "dato" si hechos.tema tiene anio, pais o anio_inicio_artista utilizable

def redactar(pedido, lexico, azar, palabras_maximas, zona=None, hechos: Hechos = Hechos(),
             pesos: Mapping[str, float] = PESOS_POR_DEFECTO, maximo: int = 3, penalizacion: float = 0.3) -> Redaccion
```

  `PESOS_POR_DEFECTO` es el mismo diccionario que el de fábrica de `ConfigServicioDJ` (una sola definición, importada).

**Estructura de la frase (la fija el plan):** `redactar` elige los ingredientes con el selector; la frase = **extras de apertura** (0 o 1 oración corta: hora y/o estación y/o momento y/o clima) + **marco** (una oración con el tema y el artista) + **extras de cierre** (0 o 1 oración: álbum, anterior, dato). Reparto: `estacion`, `hora`, `momento`, `clima` abren; `album`, `anterior`, `dato` cierran o se enganchan al marco. Cada oración sale de un pool por idioma (≥ 4 variantes por slot; las listas de abajo son el contenido mínimo, se pueden agregar más). Si la frase supera `palabras_maximas`, se descartan primero `dato`, `clima`, `anterior`, `album` (en ese orden) y se reintenta; el marco nunca se descarta. Los nombres propios siempre pasan por `m()` (marca de idioma + pronunciación del léxico). `Redaccion.ingredientes` lista los que quedaron.

Pools mínimos (es / en; `{x}` son campos; sin dígitos):
- **Marcos** (siempre `cancion`): "Seguimos con {artista} y su tema {titulo} para acompañar este momento de la mejor manera." · "Ahora suena {titulo} de {artista}." · "Llega {titulo}, de {artista}, para vos." (sin coma real: se escribe sin comas) · "Con ustedes {artista} y {titulo}." · "Sigue {artista} con {titulo} para que no pares." / "Coming up next we have {artista} with {titulo}." · "Now playing {titulo} by {artista}." · "Here comes {artista} with {titulo}." · "Stay with us for {titulo} from {artista}."
- **hora**: "{son} {hora}." / "It is {hora}." — **estacion**: "Esto es {estacion}." · "Estás escuchando {estacion}." · "Acá en {estacion}." / "This is {estacion}." · "You are listening to {estacion}." · "Right here on {estacion}." — **hora+estacion** combinadas: "En {estacion} {son_min} {hora}." / "On {estacion} it is {hora}." — **momento**: "Seguimos {este_momento}." / "Let us spend {este_momento} together." (el momento del día ya existe; agregar variantes con el día de la semana: "este sábado", "this Saturday", usando `momento.weekday()`; el fin de semana y la madrugada tienen frases propias).
- **clima** (temperatura en palabras, `menos` para negativas): es "Afuera hay {temp} grados y {cielo_es}." con cielo_es ∈ {despejado: "el cielo está despejado", nublado: "está nublado", lluvia: "está lloviendo", tormenta: "hay tormenta", niebla: "hay niebla", nieve: "está nevando"}; en "It is {temp} degrees outside and {cielo_en}." con cielo_en ∈ {"the sky is clear", "it is cloudy", "it is raining", "there is a storm", "it is foggy", "it is snowing"}; si `es_de_dia` es `False` y el cielo es `despejado`: "la noche está despejada" / "the night is clear". No se menciona "en Buenos Aires" salvo en una variante ("En Buenos Aires hay {temp} grados.").
- **album**: "Del disco {album}." / "From the album {album}." — **anterior**: "Veníamos de {artista_ant} con {titulo_ant}." / "We just heard {artista_ant} with {titulo_ant}."
- **dato** (cada variante exige sus campos; si ninguna aplica, el ingrediente no entra): `anio` → es "Este tema salió en {anio}." · "{titulo} es de {anio}." / en "This one came out in {anio}." · "{titulo} dates from {anio}."; `pais` → es "{artista} viene de {pais}." / en "{artista} comes from {pais}."; `anio_inicio_artista` y `es_grupo` → es "{artista} es una banda que empezó en {anio_inicio}." / en "{artista} is a band that started in {anio_inicio}."; los años van con `anio_en_palabras`, el país con `nombre_de_pais` (si es `None`, esa variante no se ofrece).

- [ ] **Step 1: Tests que fallan** en `tests/dj/test_plantillas.py` (se actualizan los de la parte 2a que dependían de las 9 plantillas fijas; se conservan sus invariantes): `test_siempre_hay_cancion_y_nombres_marcados`, `test_ingredientes_disponibles_segun_los_datos`, `test_sin_hechos_nunca_dice_clima_ni_dato`, `test_con_hechos_a_veces_los_usa` (con clima y dato verdaderos y pesos altos, en 200 semillas aparecen ambos; con pesos en cero, nunca), `test_el_clima_se_dice_en_palabras_y_con_menos` (−3 → "menos tres grados"), `test_el_dato_usa_solo_lo_que_hay` (sin `pais` ninguna frase dice "viene de"; sin `anio` ninguna dice "salió en"), `test_el_anio_va_en_palabras`, `test_solo_un_grupo_tiene_comienzo` (`es_grupo=False` con `anio_inicio_artista` → nunca "empezó en"), `test_invariantes_de_todas_las_combinaciones` (parametrizada por idioma, con/sin álbum, anterior, clima, dato; 300 semillas: sin dígitos, sin `{`/`}` sueltos fuera de las marcas, ≤ `palabras_maximas`, termina en punto, el marco presente), `test_si_no_entra_se_descartan_primero_dato_clima_anterior_album` (`palabras_maximas` chico: `ingredientes` no incluye los descartados y siempre queda `cancion`), `test_la_variedad_en_cientos_de_pedidos` (500 semillas con los mismos datos: ≥ 6 marcos distintos, ≥ 20 frases distintas, ningún marco > 40 %), `test_respeta_los_recientes` (con `recientes=["hora"]*4` la hora aparece mucho menos), `test_la_hora_conserva_su_formato` (los tests existentes de `frase_hora`), `test_los_nombres_usan_el_lexico_y_la_pronunciacion` (los de la parte 2a/pronunciación).
- [ ] **Step 2:** `.venv/bin/pytest tests/dj/test_plantillas.py -q` → FAIL.
- [ ] **Step 3:** Implementar (se reemplazan `_ES`/`_EN` por los pools; `frase_hora` y `_este_momento` se conservan; `m()` igual).
- [ ] **Step 4:** Suite completa → PASS.
- [ ] **Step 5:** Commit `Servicio DJ: plantillas por marco y extras con clima y datos del tema`.

---

### Task 6: Reunir los hechos, integrar en el productor y probar con los servicios reales

**Files:** Modify `src/cassette_fm/dj/hechos/__init__.py`, `src/cassette_fm/dj/produccion.py`, `src/cassette_fm/dj/servidor.py`, `src/cassette_fm/dj/cli.py`, `README.md`, `tests/dj/test_produccion.py`, `tests/dj/test_servidor.py`, `tests/conftest.py` (el fixture `servicio_dj` arma el `Productor` con el nuevo parámetro); Create `tests/dj/hechos/test_reunir.py`

**Interfaces:**
- Consumes: `ClienteClima` (Task 2), `ClienteMusicBrainz` (Task 3), `redactar`/`Hechos`/`ingredientes_disponibles` (Task 5), `ConfigServicioDJ`.
- Produces:

```python
# hechos/__init__.py
class FuenteHechos:
    def __init__(self, clima: ClienteClima | None, musicbrainz: ClienteMusicBrainz | None): ...
    def reunir(self, pedido: Pedido) -> tuple[Hechos, dict]
        # (Hechos para redactar, `fuentes`: {"clima": {...}|None, "musicbrainz": {"fuente": url, "anio":..., ...}|None}
        # para el guion). Pide el clima y el dato del tema EN PARALELO (2 hilos, join con timeout_hechos+1); nunca lanza.
# Productor.__init__ gana `hechos: FuenteHechos | None = None` (al final, default None = sin hechos, como hasta ahora)
```

- `Productor._producir`: `hechos, fuentes = self._hechos.reunir(pedido)` (si hay), se pasa a `redactar` junto con `pesos`, `maximo` (`ingredientes_max`) y `penalizacion` de la config y `recientes=pedido.recientes` (el selector recibe los recientes del pedido); el guion anota `hechos` (`fuentes`) y `ingredientes` reales. En los reintentos por duración se reusan los mismos hechos (no se vuelve a pedir nada).
- `servidor.servir`: arma `CacheHechos(rutas.hechos)`, `ClienteClima`, `ClienteMusicBrainz` y `FuenteHechos`, y se los pasa al `Productor`. Con `contacto` vacío se avisa una vez en el log (`cassette-dj: sin 'contacto' en config.toml no se consulta MusicBrainz`).
- `cassette-dj hechos` (CLI): imprime el clima actual y, con `--artista A --titulo T [--isrc X]`, los datos que MusicBrainz devolvería, sin tocar el servicio en marcha (uso manual para probar).

- [ ] **Step 1: Tests que fallan.** `test_reunir.py`: `test_junta_clima_y_tema_en_paralelo` (los dos clientes falsos duermen 0,5 s: total < 0,9 s), `test_un_cliente_que_falla_no_afecta_al_otro`, `test_clientes_none_dan_hechos_vacios`, `test_si_un_cliente_se_cuelga_se_sigue_sin_su_dato` (se cuelga 5 s, `timeout_hechos_segundos=0.3`: vuelve < 1 s), `test_fuentes_para_el_guion_incluye_la_url_de_musicbrainz`. `test_produccion.py`: `test_el_guion_anota_los_hechos_y_sus_fuentes`, `test_sin_fuente_de_hechos_funciona_como_antes`, `test_los_recientes_del_pedido_llegan_al_selector`, `test_los_reintentos_por_duracion_no_vuelven_a_pedir_hechos`. `test_servidor.py`: `test_servicio_con_hechos_falsos_de_punta_a_punta` (servidores HTTP de prueba para open-meteo y MusicBrainz; con pesos en 1 aparecen clima y dato en el `texto` del trabajo y en el guion; con los servidores caídos igual hay frase). `tests/dj/test_cli.py`: `test_cassette_dj_hechos_imprime_clima_y_tema` (con clientes inyectados).
- [ ] **Step 2:** `.venv/bin/pytest tests/dj -q` → FAIL (los nuevos).
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** Suite completa → PASS.
- [ ] **Step 5:** README (sección "Servicio DJ"): hechos reales, `contacto`, las claves nuevas con sus valores por defecto, `[ingredientes]` con la tabla de pesos, `cassette-dj hechos`, el comportamiento sin datos, y la **verificación con servicios reales (la hacemos juntos)**: (1) poner `contacto = "..."` en `~/.config/cassette-dj/config.toml` y reiniciar `cassette-dj`; (2) `cassette-dj hechos --artista "a-ha" --titulo "Take On Me"` → 1984, Noruega, grupo desde 1983, y `cassette-dj hechos` → el clima de ahora; (3) subir temporalmente los pesos de `clima` y `dato` a 1 en `[ingredientes]`, correr `cassette dj pedir --en 30` en 4 o 5 estaciones y **escuchar**; (4) volver los pesos a los de fábrica y dejarlo andar: tienen que aparecer variantes distintas y de vez en cuando clima o un dato; (5) mirar `cassette-dj guiones` para ver los hechos y sus fuentes.
- [ ] **Step 6:** Commit `Servicio DJ: hechos reales en las frases (clima, MusicBrainz) y comando cassette-dj hechos`. Cerrar los beans `CASSETTE-FM-ebyx` y `CASSETTE-FM-432j`.
