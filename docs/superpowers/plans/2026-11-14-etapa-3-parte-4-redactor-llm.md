# Etapa 3, parte 4: redactor con LLM, Wikipedia y modo plantillas/llm — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que el servicio DJ pueda redactar cada frase con un LLM local (Ollama en Docker) usando solo hechos verificados, incluida la Wikipedia del artista, y que un comando alterne el DJ entre `plantillas` (por defecto) y `llm` en caliente. Si el LLM falla o su frase no pasa la verificación, sale la frase de plantillas.

**Architecture:** En el servicio DJ: un objeto `ModoDJ` (hilo-seguro, no persistente) que el `Productor` consulta en cada pedido; en modo `llm` el productor reúne también la Wikipedia (MusicBrainz → Wikidata → Wikipedia, con caché), arma un prompt solo con los ingredientes elegidos, llama al LLM por la API compatible con OpenAI, **limpia y verifica** el texto y lo pasa por el mismo texto-para-voz de siempre. Todo lo que genera el LLM, aceptado o descartado, queda en el registro de guiones.

**Tech Stack:** Python 3.12, `urllib`, `sqlite3` (la caché de la parte 3), pytest; Ollama en Docker (`ollama/ollama`) con `gemma3:4b`. Los tests usan un servidor HTTP falso compatible con OpenAI y servidores falsos de Wikidata/Wikipedia; Docker y los servicios reales se prueban a mano.

**Spec:** [`docs/superpowers/specs/2026-11-13-etapa-3-dj-design.md`](../specs/2026-11-13-etapa-3-dj-design.md) (secciones "Datos verificados", "Verificación del texto generado", "Si el LLM falla o tarda demasiado", "LLM" y "Parte 4: decisiones del 14/11").

## Global Constraints

- Bean: `CASSETTE-FM-pnk2`. Al empezar, `-s in-progress`; al terminar la Task 7, `-s completed` (y cerrar el bean viejo `CASSETTE-FM-l02v`, que esta parte absorbe) y se incluye `.beans/` en el commit.
- **Por defecto siempre `plantillas`.** `modo` arranca con `ConfigServicioDJ.modo` (`"plantillas"` por defecto); el cambio en caliente **no se guarda**. En modo `plantillas` **no se hace ningún pedido** al LLM ni a Wikipedia/Wikidata (los tests lo comprueban contando pedidos).
- **El LLM redacta; nunca es la fuente de un hecho.** Solo ve los hechos de los ingredientes elegidos (tema, artista, estación, hora ya en palabras, momento, álbum, tema anterior, clima, y el resumen de Wikipedia del artista). Su frase se **verifica** antes de aceptarla (Task 4); si no pasa, se usa la plantilla.
- **Todo guion que sale del LLM se registra** (aceptado o descartado) con `fuente: "llm"`, el prompt (`sistema` y `usuario`), el texto crudo, `modelo`, `intentos` y, si se descartó, `descartado: true` y `motivo`. Las frases de plantilla por fallo llevan `fuente: "plantilla"` y `motivo`. Los guiones descartados no entran en `voz-prueba` (ya filtra `descartado`).
- Wikipedia es CC BY-SA: la URL del artículo y el título quedan en el guion (`hechos.wikipedia`).
- **Nada fijo en el código:** modelo, URL del LLM, timeouts, intentos, temperatura, URLs de Wikipedia/Wikidata y tope de palabras del resumen viven en `ConfigServicioDJ` (lista exacta en Task 1).
- El LLM corre en `127.0.0.1:11434` (solo local). Docker y la descarga del modelo los hacemos juntos con el usuario al final (Task 7); los tests no usan Docker ni la red real.
- Todo mensaje, nombre y comentario en español. Commits en español, texto plano en imperativo, con la línea de atribución vigente.
- Al terminar cada tarea: `.venv/bin/pytest -q` completo en verde (hoy 1038 tests; `CASSETTE_DJ_MODELOS=~/.local/share/cassette-dj/modelos`).

## Review Focus

1. **El LLM inventa:** años, cifras, nombres propios, ventas o premios que no están en los hechos; frases con URL, emojis, listas, comillas o "Aquí tienes:"; texto en otro idioma. → la frase se descarta y sale la plantilla; nada de eso llega a la voz. → Task 4.
2. **Ollama caído, lento, que responde basura o se queda sin memoria:** el pedido igual termina con una plantilla, sin traceback, dentro del tope de tiempo, y el guion lo cuenta. → Tasks 3 y 5.
3. **Cambiar de modo en caliente:** el pedido en curso termina con el modo con el que empezó; el siguiente usa el nuevo; modo inválido da 400; reiniciar vuelve al de la config; en `plantillas` cero pedidos de red. → Tasks 1, 5 y 6.
4. **Wikipedia equivocada:** página de desambiguación, artista sin artículo en el idioma, redirecciones, texto vacío o gigante, caracteres raros en el título. → solo se usa un resumen `standard`, recortado; si no, el artista no tiene dato de Wikipedia. → Task 2.
5. **Números y nombres hacia la voz:** dígitos en la frase del LLM ("1985", "22") se convierten a palabras o se descarta; nombres propios marcados por idioma con la pronunciación del léxico. → Task 4.

---

## Estructura de archivos

```
src/cassette_fm/dj/config.py          # Task 1: claves nuevas
src/cassette_fm/dj/modo.py            # Task 1: ModoDJ
src/cassette_fm/dj/servidor.py        # Task 1: GET/POST /modo; Task 5: cableado
src/cassette_fm/dj/cli.py             # Task 1: cassette-dj modo; Task 7: cassette-dj llm
src/cassette_fm/dj/hechos/wikipedia.py    # Task 2: ClienteWikipedia, Resumen
src/cassette_fm/dj/hechos/musicbrainz.py  # Task 2: wikidata en DatosTema
src/cassette_fm/dj/hechos/__init__.py     # Task 2: Hechos.wikipedia, FuenteHechos
src/cassette_fm/dj/llm.py             # Task 3: ClienteLLM, ErrorLLM
src/cassette_fm/dj/redactor_llm.py    # Task 4: prompt, limpieza, verificación, marcado
src/cassette_fm/dj/produccion.py      # Task 5: modo + LLM + respaldo + guiones
src/cassette_fm/cliente_dj.py, planificador.py, radio.py, api.py, cli.py   # Task 6
scripts/instalar-llm.sh               # Task 7
tests/dj/..., tests/test_cliente_dj.py, ...
```

---

### Task 1: Configuración y modo del servicio

**Files:** Modify `src/cassette_fm/dj/config.py`, `src/cassette_fm/dj/servidor.py`, `src/cassette_fm/dj/cli.py`, `tests/dj/test_config.py`, `tests/dj/test_servidor.py`, `tests/dj/test_cli.py`; Create `src/cassette_fm/dj/modo.py`, `tests/dj/test_modo.py`

**Interfaces:**
- Produces, en `ConfigServicioDJ` (todos con estos valores por defecto):

```python
modo: str = "plantillas"                           # "plantillas" | "llm": modo al arrancar
llm_url: str = "http://127.0.0.1:11434/v1"         # API compatible con OpenAI (Ollama)
llm_modelo: str = "gemma3:4b"
llm_timeout_segundos: float = 240.0                # tope por llamada al LLM
llm_intentos: int = 2                              # cuántas veces se pide una frase antes de usar la plantilla
llm_temperatura: float = 0.8
wikipedia_dias: float = 90.0                       # vigencia en caché de un resumen encontrado
wikipedia_palabras_maximas: int = 120              # el resumen se recorta (en un fin de oración) a esto
wikipedia_url: str = "https://{idioma}.wikipedia.org"       # lleva {idioma}
wikidata_url: str = "https://www.wikidata.org/w/api.php"
```

  Validación (`ErrorConfig` con la ruta): `modo` en las dos opciones; `llm_url`, `wikidata_url` `http(s)://…`; `wikipedia_url` `https?://` y con `{idioma}`; `llm_modelo` texto no vacío de hasta 100 caracteres sin espacios ni saltos; `llm_timeout_segundos > 0`; `llm_intentos` entero ≥ 1; `llm_temperatura` en [0, 2]; `wikipedia_dias ≥ 0`; `wikipedia_palabras_maximas` entero ≥ 20.
- Produce, `modo.py`:

```python
MODOS = ("plantillas", "llm")
class ModoDJ:
    def __init__(self, inicial: str = "plantillas"): ...    # ValueError si no es un modo válido
    def actual(self) -> str
    def poner(self, modo: str) -> str       # ValueError si inválido; devuelve el nuevo
```

- Produce, HTTP del servicio: `GET /modo` → `200 {"modo": "plantillas"}`; `POST /modo {"modo": "llm"}` → `200 {"modo": "llm", "llm": "ok" | "no responde"}` (el segundo campo sale de una prueba rápida —`GET {llm_url}/models`, 2 s— solo cuando el modo nuevo es `llm`; en `plantillas` no se consulta); `400` con el motivo si falta el campo o el modo es inválido; `GET /salud` agrega `"modo"`. `crear_servidor(..., modo: ModoDJ | None = None, probar_llm: Callable[[], bool] | None = None)` (parámetros nuevos al final, con default → modo `plantillas` y sin prueba).
- Produce, CLI: `cassette-dj modo [plantillas|llm]` (sin argumento muestra el actual) llama al servicio en marcha por HTTP (`config.host`/`config.puerto`); error claro si el servicio no responde.

- [ ] **Step 1: Tests que fallan.** `test_config.py`: `test_defaults_del_llm` (los 10 valores exactos), `test_claves_del_llm_se_leen`, `test_valores_invalidos_del_llm` (`modo = "otro"`, `llm_url = "x"`, `wikipedia_url = "https://es.wikipedia.org"` sin `{idioma}`, `llm_modelo = "a b"`, `llm_timeout_segundos = 0`, `llm_intentos = 0`, `llm_intentos = 1.5`, `llm_temperatura = 3`, `wikipedia_palabras_maximas = 5`). `test_modo.py`: `test_arranca_con_el_inicial`, `test_poner_cambia_y_devuelve`, `test_modo_invalido_da_ValueError_y_no_cambia`, `test_es_seguro_con_hilos` (8 hilos alternando; el valor final es uno válido). `test_servidor.py`: `test_get_modo`, `test_post_modo_cambia_y_se_refleja_en_salud`, `test_post_modo_llm_informa_si_el_llm_responde` (con `probar_llm` falso `True`/`False`) y `test_post_modo_plantillas_no_prueba_el_llm`, `test_post_modo_invalido_400` (falta el campo, `"otro"`, no es JSON, tipo erróneo). `test_cli.py`: `test_cassette_dj_modo_muestra_y_cambia` (servicio de prueba), `test_cassette_dj_modo_sin_servicio_da_error_claro`.
- [ ] **Step 2:** `.venv/bin/pytest tests/dj/test_config.py tests/dj/test_modo.py tests/dj/test_servidor.py tests/dj/test_cli.py -q` → FAIL (los nuevos).
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** Suite completa → PASS.
- [ ] **Step 5:** Commit `Servicio DJ: configuración del LLM, modo plantillas/llm y comando cassette-dj modo`.

---

### Task 2: Wikipedia (MusicBrainz → Wikidata → Wikipedia)

**Files:** Modify `src/cassette_fm/dj/hechos/musicbrainz.py`, `src/cassette_fm/dj/hechos/__init__.py`, `tests/dj/hechos/test_musicbrainz.py`, `tests/dj/hechos/test_reunir.py`; Create `src/cassette_fm/dj/hechos/wikipedia.py`, `tests/dj/hechos/test_wikipedia.py`

**Interfaces:**
- Consumes: `CacheHechos.consultar` (parte 3), `ConfigServicioDJ` (Task 1), `servidor_http` (fixture de la parte 3).
- Produce, `DatosTema` gana **al final y con default**: `wikidata: str | None = None` (el `Q…` del artista, de la relación `wikidata` de MusicBrainz). La consulta del artista pasa a `GET /artist/<id>?inc=url-rels&fmt=json` y la clave de caché de MusicBrainz cambia de prefijo (`mb:` → `mb2:`) para no usar entradas viejas sin ese campo.
- Produce, `wikipedia.py`:

```python
@dataclass(frozen=True)
class Resumen:
    texto: str       # el extracto, recortado a `wikipedia_palabras_maximas` en un fin de oración
    titulo: str
    idioma: str      # "es" | "en"
    url: str         # URL de la página (para el guion; CC BY-SA)

class ClienteWikipedia:
    def __init__(self, config: ConfigServicioDJ, cache: CacheHechos, version: str = "0.1"): ...
    def resumen(self, wikidata: str, idiomas: Sequence[str]) -> Resumen | None    # nunca lanza
```

- `Hechos` gana `wikipedia: Resumen | None = None`; `FuenteHechos.__init__(clima, musicbrainz, espera_segundos=6.0, wikipedia=None)` y `reunir(pedido, con_wikipedia: bool = False)`: solo con `con_wikipedia=True` y datos de MusicBrainz con `wikidata`, pide el resumen (en el mismo tope de tiempo, después de MusicBrainz) con `idiomas = [idioma del pedido, "en"]` sin repetir; `fuentes["wikipedia"]` = `{"url","titulo","idioma"}` o `None`.
- `ingredientes_disponibles` (plantillas) **no** cambia: el resumen solo lo usa el redactor LLM (Task 4).
- Algoritmo de `resumen`: 1. Q-id válido (`^Q\d+$`) o `None`. 2. Caché `wp:<Q>:<idiomas>` (`wikipedia_dias`, sin dato `cache_sin_dato_dias`, error `cache_error_minutos`, igual que en MusicBrainz). 3. `GET {wikidata_url}?action=wbgetentities&ids=<Q>&props=sitelinks&sitefilter=<idioma>wiki|…&format=json` → `entities[Q].sitelinks["<idioma>wiki"].title`; se toma el primer idioma de `idiomas` que tenga. 4. `GET {wikipedia_url con idioma}/api/rest_v1/page/summary/<título con quote(safe="")>` → solo se acepta `type == "standard"` y `extract` no vacío (descarta `disambiguation`, `no-extract`, 404). 5. Recorte: oraciones completas hasta `wikipedia_palabras_maximas` palabras (si la primera ya se pasa, se corta a esa cantidad de palabras y se termina en punto). 6. `User-Agent: cassette-dj/<versión> (<contacto>)`; sin `contacto` → `None` sin pedir nada. Ningún error de red ni de parseo se propaga; un aviso por episodio, como en las otras fuentes.

- [ ] **Step 1: Tests que fallan.** `test_musicbrainz.py`: `test_el_artista_se_pide_con_url_rels_y_devuelve_el_wikidata` (relación `{"type":"wikidata","url":{"resource":"https://www.wikidata.org/wiki/Q156305"}}` → `wikidata == "Q156305"`; sin la relación → `None`; recurso raro (`/wiki/Lexeme:L1`, vacío) → `None`), `test_las_entradas_viejas_de_cache_no_se_usan` (caché con clave `mb:` previa no se lee). `test_wikipedia.py` (con `servidor_http` y las respuestas reales de Wikidata y del REST de Wikipedia para a-ha, recortadas): `test_resumen_del_artista_en_el_idioma_pedido`, `test_si_no_hay_articulo_en_el_primer_idioma_usa_el_ingles`, `test_sin_articulo_en_ninguno_da_None`, `test_una_pagina_de_desambiguacion_no_sirve`, `test_extracto_vacio_no_sirve`, `test_recorta_en_fin_de_oracion` (extracto largo; `wikipedia_palabras_maximas=40`), `test_primera_oracion_muy_larga_se_corta_en_palabras`, `test_titulo_con_espacios_barras_y_acentos_va_codificado`, `test_qid_invalido_no_hace_pedidos`, `test_sin_contacto_no_hace_pedidos`, `test_cache` (2 llamadas → 2 pedidos en total, y "sin dato" cacheado), `test_errores_y_basura_dan_None` (404, 503, HTML, JSON sin `entities`, timeout) sin traceback y con un solo aviso, `test_user_agent_con_el_contacto`. `test_reunir.py`: `test_sin_con_wikipedia_no_se_pide_nada` (cuenta de llamadas 0), `test_con_wikipedia_se_pide_despues_de_musicbrainz_y_se_anota_en_las_fuentes`, `test_sin_wikidata_no_hay_resumen`, `test_idiomas_del_pedido_y_ingles_sin_repetir`.
- [ ] **Step 2:** `.venv/bin/pytest tests/dj/hechos -q` → FAIL (los nuevos).
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** Suite completa → PASS.
- [ ] **Step 5:** Commit `Servicio DJ: resumen de Wikipedia del artista (MusicBrainz, Wikidata, Wikipedia) con caché`.

---

### Task 3: Cliente del LLM

**Files:** Create `src/cassette_fm/dj/llm.py`, `tests/dj/test_llm.py`; Modify `tests/dj/conftest.py` (fixture `llm_falso`: servidor HTTP que imita `POST /v1/chat/completions` y `GET /v1/models`, con respuestas, demoras y códigos configurables, y registro de los pedidos)

**Interfaces:**
- Produces:

```python
class ErrorLLM(Exception): ...        # str(e): mensaje en español (no responde, error HTTP, respuesta ilegible, vacía)

class ClienteLLM:
    def __init__(self, config: ConfigServicioDJ): ...
    def generar(self, sistema: str, usuario: str) -> str          # texto crudo; ErrorLLM si no hay uno usable
    def disponible(self) -> bool                                   # GET {llm_url}/models, 2 s; nunca lanza
```

  `generar` hace `POST {llm_url}/chat/completions` con `{"model", "messages": [{"role":"system"},{"role":"user"}], "temperature", "max_tokens": 300, "stream": false}`, timeout `llm_timeout_segundos`; toma `choices[0].message.content` (texto no vacío tras `strip`); cualquier otra cosa (HTTP ≠ 200, JSON roto, sin `choices`, contenido vacío o que no es texto, timeout, conexión rechazada) → `ErrorLLM` con la URL y el motivo; nunca escapa otra excepción.

- [ ] **Step 1: Tests que fallan** (con `llm_falso`): `test_genera_con_el_formato_de_openai` (el servidor recibe modelo, temperatura, mensajes y `stream: false`), `test_devuelve_el_texto_crudo`, `test_servidor_caido_da_ErrorLLM_claro` (puerto cerrado: "no responde" y la URL), `test_timeout_da_ErrorLLM` (`llm_timeout_segundos=0.3`), `test_http_500_y_404_dan_ErrorLLM`, `test_respuestas_basura` (HTML, JSON sin `choices`, `choices` vacío, `content` `null`/lista/vacío/solo espacios), `test_disponible` (200 → `True`; caído → `False` en < 3 s; 404 → `False`).
- [ ] **Step 2:** `.venv/bin/pytest tests/dj/test_llm.py -q` → FAIL.
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** Suite completa → PASS.
- [ ] **Step 5:** Commit `Servicio DJ: cliente del LLM (API compatible con OpenAI)`.

---

### Task 4: Redactor del LLM: prompt, limpieza, verificación y marcado

**Files:** Create `src/cassette_fm/dj/redactor_llm.py`, `tests/dj/test_redactor_llm.py`

**Interfaces:**
- Consumes: `Pedido`, `Hechos` (con `wikipedia`), `Resumen`, `Lexico`, `frase_hora`/`_este_momento`/`_grados`/`_artistas` y los textos de cielo de `plantillas.py` (se exportan sin guion bajo si hace falta: `grados_en_palabras`, `cielo_en_palabras`, `artistas_del_tag`), `anio_en_palabras`/`en_palabras` (parte 3), `marcar`.
- Produce:

```python
@dataclass(frozen=True)
class Peticion:
    sistema: str
    usuario: str
    permitido: str            # todo el texto de los hechos que se le pasaron (para verificar)

def construir_peticion(pedido: Pedido, ingredientes: Sequence[str], hechos: Hechos, campos_de_voz: Mapping[str, str],
                       palabras_maximas: int, zona: tzinfo | None = None) -> Peticion
    # campos_de_voz: hora en palabras, momento, grados, cielo… ya armados como en plantillas.redactar

def limpiar_salida(crudo: str) -> str
    # quita fences, comillas envolventes, encabezados tipo "Aquí tienes:" / "Here is…:", markdown (* _ # `), emojis,
    # saltos de línea (se queda con el primer párrafo), espacios dobles

def verificar(texto: str, pedido: Pedido, peticion: Peticion, palabras_maximas: int) -> str | None
    # None si pasa; si no, el motivo (texto corto en español) para el guion

def numeros_a_palabras(texto: str, idioma: str) -> str     # ValueError si hay un número que no se puede decir

def marcar_nombres(texto: str, pedido: Pedido, hechos: Hechos, lexico: Lexico) -> str
    # el texto con {lang:Nombre} en cada aparición exacta de artista(s), tema, estación, álbum y tema anterior
    # (con la pronunciación del léxico y su idioma, como plantillas.redactar)
```

**Reglas:**
- *Prompt* (es o en según el idioma del pedido; el texto lo fija este plan): el **sistema** dice, en una lista corta, que es el locutor de la radio `<estación>`; que escriba **una sola intervención hablada** de entre `palabras_maximas // 2` y `palabras_maximas` palabras; que use **solo** los hechos del mensaje y no invente nada (ni años, ni cifras, ni nombres); que nombre el tema y el artista **tal como están escritos**; que hable natural, con frases cortas, sin exclamaciones, emojis, comillas, listas, títulos ni explicaciones; que no empiece por "aquí tienes"; que use a lo sumo **un** dato del resumen de Wikipedia, reformulado en una frase corta, y que la `personalidad` del pedido (si hay) marca el tono. El **usuario** lista solo los hechos de `ingredientes`: tema y artista (siempre), estación, hora (en palabras), momento, álbum, tema anterior, clima (en palabras) y el resumen de Wikipedia (solo si `dato` está entre los ingredientes y hay resumen; si `dato` está pero solo hay datos de MusicBrainz, esos datos en frases: "salió en <año en palabras>", "es de <país>", "empezó en <año>").
- *Limpieza:* como arriba; si queda vacío → `""`.
- *Verificación* (en este orden; devuelve el primer motivo):
  1. vacío → `"vacío"`; más de `palabras_maximas * 1.3` palabras → `"demasiado largo"`; menos de 4 → `"demasiado corto"`.
  2. contiene URL, `@`, `#` → `"tiene enlaces o etiquetas"`.
  3. **no menciona** el tema (comparado sin acentos, mayúsculas ni puntuación) **o** el primer artista → `"no nombra el tema o el artista"`.
  4. **dígitos:** cada número debe aparecer en `permitido` (como cifra o como el número en palabras que se le pasó); si no → `"número que no está en los hechos"`; los que pasan se convierten con `numeros_a_palabras` (años 1900–2099 con `anio_en_palabras`; 0–99 con `en_palabras`; cualquier otro → `"número que no se puede decir"`).
  5. **nombres propios:** cada palabra con mayúscula inicial que **no** abre una oración debe estar (sin acentos ni mayúsculas) en el vocabulario de `permitido` + nombres del pedido + un conjunto chico de excepciones por idioma (días de la semana, meses, "Buenos Aires", "Argentina", "Dios" no; ver test) → si no, `"nombre propio que no está en los hechos: <palabra>"`.
  6. más de 3 oraciones → `"demasiadas oraciones"`.
- *Marcado:* se buscan las apariciones exactas (sin distinguir mayúsculas) de los nombres, de más larga a más corta, sin pisar marcas ya puestas; el nombre dicho es `lexico.pronunciacion(nombre)` y el idioma `lexico.idioma_de(nombre, lang)`.

- [ ] **Step 1: Tests que fallan** (todas puras, sin red): `construir_peticion`: `test_el_prompt_lleva_solo_los_ingredientes_elegidos` (con `["cancion","hora"]` aparecen tema, artista y hora y **no** clima, álbum ni Wikipedia), `test_el_prompt_pone_la_personalidad_y_el_idioma`, `test_el_resumen_de_wikipedia_solo_si_el_ingrediente_dato`, `test_los_datos_de_musicbrainz_van_en_palabras`, `test_permitido_incluye_nombres_y_hechos`. `limpiar_salida` (parametrizada): `"Aquí tienes: «Ahora suena X»"`, fences ```` ``` ````, comillas, `**negrita**`, emojis, dos párrafos, `""`, solo espacios. `verificar`: `test_una_frase_correcta_pasa`, `test_vacia_larga_y_corta`, `test_enlaces_y_etiquetas`, `test_sin_tema_o_sin_artista`, `test_un_anio_inventado_no_pasa_y_uno_de_los_hechos_si` (1984 permitido, 1985 no), `test_un_nombre_propio_inventado_no_pasa` ("Michael Jackson"), `test_nombres_del_pedido_y_de_wikipedia_si_pasan`, `test_las_excepciones_de_nombres_comunes` (lunes/sábado, meses, Buenos Aires), `test_inicio_de_oracion_no_cuenta_como_nombre`, `test_demasiadas_oraciones`, `test_cifras_raras_no_se_pueden_decir` (`"1,5 millones"`, `"3000"`). `numeros_a_palabras`: `"salió en 1984"` → `"salió en mil novecientos ochenta y cuatro"`, `"22 grados"` → `"veintidós grados"` (con `"es"`, `"en"` y el `"un grado"` de la parte 3), 100 → `ValueError`. `marcar_nombres`: `test_marca_los_nombres_con_el_idioma_del_lexico`, `test_usa_la_pronunciacion_del_lexico`, `test_no_pisa_marcas_ni_parte_palabras` ("Ken" dentro de "Kendrick"), `test_el_resultado_pasa_por_el_texto_para_voz` (con `preparar`, sin llaves sueltas).
- [ ] **Step 2:** `.venv/bin/pytest tests/dj/test_redactor_llm.py -q` → FAIL.
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** Suite completa → PASS.
- [ ] **Step 5:** Commit `Servicio DJ: prompt, limpieza y verificación de la frase del LLM`.

---

### Task 5: El productor con modo, LLM y respaldo por plantillas

**Files:** Modify `src/cassette_fm/dj/produccion.py`, `src/cassette_fm/dj/servidor.py`, `tests/dj/test_produccion.py`, `tests/dj/test_servidor.py`, `tests/conftest.py` (el fixture `servicio_dj` crea el `Productor` con modo y sin LLM)

**Interfaces:**
- Consumes: `ModoDJ` (Task 1), `FuenteHechos.reunir(pedido, con_wikipedia)` (Task 2), `ClienteLLM` (Task 3), `construir_peticion`/`limpiar_salida`/`verificar`/`numeros_a_palabras`/`marcar_nombres` (Task 4), `redactar`, `preparar`.
- Produce: `Productor.__init__` gana, al final y con default: `modo: ModoDJ | None = None` (`None` = siempre plantillas), `llm: ClienteLLM | None = None`. `Resultado` no cambia.
- Comportamiento de `_producir`:
  1. `modo_del_pedido = modo.actual()` **una sola vez al empezar** (el cambio en caliente no afecta al pedido en curso). Si es `llm` pero no hay `llm` → se comporta como `plantillas` y anota `motivo`.
  2. `plantillas`: exactamente como hoy (sin pedidos al LLM ni a Wikipedia: `reunir(pedido, con_wikipedia=False)`).
  3. `llm`: `reunir(pedido, con_wikipedia=True)`; ingredientes con `elegir_ingredientes` (el selector de siempre: pesos, recientes, máximo); se arma la `Peticion`; hasta `llm_intentos` veces: `generar` → `limpiar_salida` → `verificar`. Cada intento (aceptado o no) se anota en los guiones con `fuente: "llm"` (`sistema`, `usuario`, `crudo`, `modelo`, `intento`, `descartado` y `motivo` si no pasó). El primer texto que pasa: `numeros_a_palabras` → `marcar_nombres` → `preparar` → síntesis → si dura más que `duracion_maxima_segundos` se cuenta como intento descartado (`motivo: "el clip dura X s"`) y se vuelve a pedir más corto (`palabras_maximas` proporcional, como en las plantillas). Si ningún intento sirve (o hay `ErrorLLM`), se produce **con plantillas** reusando los mismos `hechos`/ingredientes, y ese guion lleva `fuente: "plantilla"` y `motivo` (el del último fallo). El resultado devuelve los ingredientes reales.
  4. Un `ErrorLLM` se avisa en el log **una sola vez por episodio** (`servidor` lo resetea al primer éxito) con el mensaje; nunca propaga.
- `servidor.servir`: arma `ModoDJ(config.modo)`, `ClienteLLM(config)`, `ClienteWikipedia(config, cache, __version__)`, pasa todo al `FuenteHechos`/`Productor` y `crear_servidor(..., modo=modo, probar_llm=llm.disponible)`.

- [ ] **Step 1: Tests que fallan** en `tests/dj/test_produccion.py` (con `ClienteLLMFalso`, `FuenteFalsa`, `SintetizadorFalso`): `test_en_plantillas_no_se_llama_al_llm_ni_a_wikipedia` (conteos 0 y `con_wikipedia=False`); `test_en_llm_usa_la_frase_del_llm_y_la_anota` (guion con `fuente="llm"`, prompt, crudo, modelo, `hechos.wikipedia` con la URL); `test_el_texto_del_llm_pasa_por_numeros_y_marcado` (`"salió en 1984"` → palabras; nombres marcados); `test_si_la_frase_no_pasa_la_verificacion_se_pide_otra_y_se_anota_la_descartada` (primer intento inventa un año, segundo bien: 2 guiones `llm`, el primero `descartado` con `motivo`); `test_agotados_los_intentos_sale_la_plantilla_con_el_motivo` (guion `fuente="plantilla"`, `motivo`, y los intentos del LLM anotados como descartados); `test_error_del_llm_cae_a_plantillas_y_avisa_una_vez` (caplog, dos pedidos seguidos con `ErrorLLM`: un solo aviso); `test_llm_pedido_sin_cliente_usa_plantillas`; `test_el_clip_demasiado_largo_del_llm_se_reintenta_mas_corto_y_si_no_cae_a_plantillas`; `test_el_modo_se_lee_una_sola_vez_por_pedido` (el modo cambia a mitad de la producción: el pedido termina con el modo inicial); `test_el_selector_y_los_ingredientes_reales_se_devuelven` (`Resultado.ingredientes` coincide con los del prompt); `test_los_guiones_descartados_no_entran_en_voz_prueba`. `tests/dj/test_servidor.py`: `test_de_punta_a_punta_en_modo_llm_con_servidores_falsos` (servicio con `servidor_http` para Wikipedia/Wikidata/MusicBrainz y `llm_falso`: `POST /modo llm` → `POST /intervenciones` → el `texto` es el del LLM verificado y el guion trae `hechos.wikipedia`; luego `POST /modo plantillas` → el siguiente pedido no suma pedidos al `llm_falso` ni a Wikipedia) y `test_en_modo_llm_con_el_llm_caido_igual_hay_frase`.
- [ ] **Step 2:** `.venv/bin/pytest tests/dj/test_produccion.py tests/dj/test_servidor.py -q` → FAIL (los nuevos).
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** Suite completa → PASS; repetir `tests/dj` 3 veces seguidas sin fallos.
- [ ] **Step 5:** Commit `Servicio DJ: modo llm con verificación, respaldo por plantillas y guiones del LLM`.

---

### Task 6: El comando en la radio (`cassette dj modo`)

**Files:** Modify `src/cassette_fm/cliente_dj.py`, `src/cassette_fm/planificador.py`, `src/cassette_fm/radio.py`, `src/cassette_fm/api.py`, `src/cassette_fm/cli.py`, `README.md`, `tests/test_cliente_dj.py`, `tests/test_planificador.py`, `tests/test_radio.py`, `tests/test_api.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: HTTP `GET/POST /modo` del servicio (Task 1).
- Produces:

```python
# cliente_dj.py
ClienteDJ.modo(self) -> str                                # GET /modo
ClienteDJ.poner_modo(self, modo: str) -> dict              # POST /modo -> {"modo", "llm"?}; ErrorDJ con el mensaje del servicio si es 400
# planificador.py
Planificador.modo(self, nuevo: str | None = None) -> dict  # {"modo": ..., "llm"?: ...}; ValueError(str(ErrorDJ)) si el servicio no responde o rechaza
# radio.py
Radio.dj_modo(self, nuevo: str | None = None) -> dict      # DJInactivo si no hay planificador; ValueError con el mensaje
# API: GET /dj/modo -> 200 {"modo"}; POST /dj/modo {"modo": "llm"|"plantillas"} -> 200 {"modo", "llm"?};
#      DJInactivo -> 409 (mismo mensaje del `url`); ValueError -> 400; falta/tipo inválido -> 400
# CLI: cassette dj modo [llm|plantillas]
```

  Salida del CLI: sin argumento `Modo del DJ: plantillas.`; al cambiar a `llm`: `Modo del DJ: llm (el LLM responde).` o `Modo del DJ: llm (¡el LLM no responde! las frases van a salir por plantillas hasta que arranque Ollama).`; al cambiar a `plantillas`: `Modo del DJ: plantillas.` y en las dos formas una segunda línea `(vuelve a plantillas al reiniciar el servicio DJ)` solo cuando el modo es `llm`.

- [ ] **Step 1: Tests que fallan.** `test_cliente_dj.py` (con `servicio_dj` real —el servicio de la parte 2a/4—; el fixture arma `crear_servidor` con un `ModoDJ`): `test_modo_y_poner_modo`, `test_poner_un_modo_invalido_da_ErrorDJ_con_el_mensaje`, `test_modo_con_el_servicio_caido_da_ErrorDJ`. `test_planificador.py`: `test_modo_delega_en_el_cliente_y_convierte_errores` (ClienteFalso ampliado). `test_radio.py`: `test_dj_modo_sin_planificador_da_DJInactivo`, `test_dj_modo_delega`. `test_api.py` y `test_cli.py`: `test_get_dj_modo`, `test_post_dj_modo_*` (pasa el modo, 409 por `DJInactivo`, 400 por `ValueError`, 400 por falta/tipo), `test_dj_modo_imprime_el_estado`, `test_dj_modo_llm_avisa_si_el_llm_no_responde`, `test_dj_modo_plantillas`, `test_dj_modo_error_de_la_api_da_codigo_1`, `test_dj_modo_argumento_invalido` (argparse).
- [ ] **Step 2:** `.venv/bin/pytest tests/test_cliente_dj.py tests/test_planificador.py tests/test_radio.py tests/test_api.py tests/test_cli.py -q` → FAIL (los nuevos).
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** Suite completa → PASS.
- [ ] **Step 5:** README: sección "DJ con LLM" (qué hace el modo `llm`, que por defecto es `plantillas`, `cassette dj modo llm|plantillas`, que no se guarda al reiniciar y que se puede dejar `modo = "llm"` en `~/.config/cassette-dj/config.toml`).
- [ ] **Step 6:** Commit `Radio: comando cassette dj modo para alternar entre plantillas y LLM`.

---

### Task 7: Ollama en Docker y prueba con el LLM real

**Files:** Create `scripts/instalar-llm.sh`; Modify `src/cassette_fm/dj/cli.py`, `tests/dj/test_cli.py`, `README.md`

**Interfaces:**
- `scripts/instalar-llm.sh [modelo]` (no se ejecuta en los tests; se corre con el usuario): comprueba que `docker` responda (si no, explica cómo agregar al usuario al grupo `docker`), crea la carpeta `~/.local/share/cassette-dj/ollama`, arranca (o reusa) el contenedor `cassette-ollama` con `docker run -d --name cassette-ollama --restart unless-stopped -p 127.0.0.1:11434:11434 -v ~/.local/share/cassette-dj/ollama:/root/.ollama ollama/ollama`, espera a que la API responda y hace `docker exec cassette-ollama ollama pull <modelo>` (por defecto el `llm_modelo` de la config, que el script lee con `cassette-dj llm modelo`). Idempotente; imprime qué hizo y cómo borrar todo (`docker rm -f cassette-ollama` y la carpeta). Usa `set -euo pipefail` y cita todas las variables.
- `cassette-dj llm estado`: imprime la URL, el modelo configurado, si la API responde y si el modelo está descargado (`GET {llm_url}/models`); `cassette-dj llm modelo`: imprime solo el nombre del modelo (para el script).

- [ ] **Step 1: Tests que fallan** (`tests/dj/test_cli.py`, con `llm_falso`): `test_llm_estado_con_el_modelo_descargado`, `test_llm_estado_con_el_llm_caido`, `test_llm_estado_sin_el_modelo`, `test_llm_modelo_imprime_solo_el_nombre`. Más un test de forma del script: `test_el_script_de_instalacion_es_bash_valido` (`bash -n scripts/instalar-llm.sh`) y `test_el_script_cita_las_variables` (no hay `$var` sin comillas en los comandos de docker).
- [ ] **Step 2:** `.venv/bin/pytest tests/dj/test_cli.py -q` → FAIL (los nuevos).
- [ ] **Step 3:** Implementar el comando y el script.
- [ ] **Step 4:** Suite completa → PASS.
- [ ] **Step 5:** README, sección "DJ con LLM": instalación (`scripts/instalar-llm.sh`), configuración (`llm_url`, `llm_modelo`, `llm_timeout_segundos`, `llm_intentos`, `llm_temperatura`, `wikipedia_*` con sus valores por defecto), qué se registra en los guiones del LLM y la **verificación con el LLM real (la hacemos juntos)**: (1) correr `scripts/instalar-llm.sh` (baja ~3 GB); (2) `cassette-dj llm estado`; (3) `cassette dj modo llm` y `cassette dj pedir --en 30` en varias estaciones; escuchar; (4) mirar `cassette-dj guiones` y `~/.local/state/cassette-dj/guiones.jsonl` (prompts, crudos, descartados y motivos); (5) medir la latencia por frase; (6) `cassette dj modo plantillas` para volver. Si `gemma3:4b` se queda corto, probar otro modelo cambiando `llm_modelo`.
- [ ] **Step 6:** Commit `DJ con LLM: instalación de Ollama en Docker, comando cassette-dj llm y documentación`. Cerrar los beans `CASSETTE-FM-pnk2` y `CASSETTE-FM-l02v`.
