# Etapa 3, parte 2b: planificador y cliente del servicio DJ en la radio — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que la radio decida sola cuándo pedirle una intervención al servicio DJ (según una frecuencia configurable
por cantidad de temas o por tiempo), la reserve en el hueco justo de la agenda de la estación sintonizada, descargue el
clip cuando esté listo y lo registre para que suene (parte 1). Todo sin trabar nunca la música.

**Architecture:** Un `ClienteDJ` (HTTP, stdlib) habla con el servicio de la parte 2a. Funciones puras eligen el hueco
(`elegir_hueco`) y arman el pedido. Un `Planificador` con un hilo propio mantiene **un solo trabajo en curso**
("iniciado" = ya se hizo el `POST`), para la estación sintonizada, y lo guarda en disco para retomarlo si la radio se
reinicia. La `Radio` solo le avisa cuándo se sintoniza, se apaga o se re-escanea.

**Tech Stack:** Python 3.12, `urllib` de la stdlib, `threading`, pytest. Los tests usan el **servicio DJ real** de la
parte 2a (en un hilo, con un sintetizador falso que escribe WAV) y mpv con `--ao=null`.

**Spec:** [`docs/superpowers/specs/2026-11-13-etapa-3-dj-design.md`](../specs/2026-11-13-etapa-3-dj-design.md)
(secciones "Planificador y cola", "Servicio DJ (HTTP)", "Configuración"); lo acordado con el usuario el 13/11: **la
frecuencia por defecto es una configuración general** (`[dj.frecuencia]`) que cada estación puede pisar.

## Global Constraints

- Bean: `CASSETTE-FM-zuej`. Al empezar, `-s in-progress`; al terminar la Task 6, `-s completed` y se incluye `.beans/` en el commit.
- **Nada fijo en el código**: todo valor que pueda querer cambiarse vive en `ConfigDJ` (general y por estación) con su valor por defecto (lista exacta en Task 2).
- **El planificador solo se activa si `[dj] activo = true` y `[dj] url` no está vacía.** `url` no tiene valor por defecto (es `""`): con solo `activo = true` la radio se comporta como en la parte 1 (clips de prueba con `cassette dj probar`) y no intenta conectarse a nada.
- **Un solo trabajo a la vez; "iniciado" = ya se hizo el `POST`.** Antes de eso, a lo sumo un pedido pendiente: el de la estación sintonizada, que se **reemplaza** al cambiar de estación. Un trabajo ya iniciado **siempre termina** aunque se cambie de estación, y su clip se registra para **su** estación. Con la radio apagada no se planifica nada nuevo, pero lo ya iniciado termina.
- **La música nunca espera:** si el clip llega cuando ya pasó su hueco (más la gracia), se descarta; si el servicio no responde, la radio sigue igual, un solo aviso en el log por episodio, con espera creciente entre reintentos.
- El servicio DJ no guarda estado: **todo** va en el pedido, incluida la lista `recientes` (los ingredientes de las últimas intervenciones de esa estación, que la radio guarda).
- El **hueco** (`inicio_voz`) = inicio del tema destino en la agenda + `retraso_voz_segundos`; el `momento` del pedido es ese instante (no "ahora"), en ISO-8601 con la zona horaria local del sistema.
- Se planifica **como máximo una intervención por estación a la vez**: si la estación ya tiene una reservada que no terminó (registro) o hay un trabajo en curso para ella, no se pide otra.
- Los temas sin artista o sin título en los tags **no** se eligen como destino (no hay nombre que decir).
- Reglas de la frecuencia: nunca antes de `min` ni después de `max` temas (o minutos) desde la última intervención de esa estación, **salvo** que ese tramo no respete `margen_minutos`: entonces se toma la primera transición posterior que sí lo respete. Sin intervención previa, se cuenta desde "ahora".
- Todo mensaje al usuario, nombre y comentario en español. Commits en español, texto plano en imperativo, con la línea de atribución vigente de la sesión.
- Los tests no hacen sonar audio ni tocan `~/.config`, `~/.local` ni `~/.cache`, ni el servicio real. **Activar el planificador en la radio real (poner `url`) y arrancar el servicio DJ lo hacemos juntos al final.**
- Al terminar cada tarea: `.venv/bin/pytest -q` completo en verde (hoy 613 tests con `CASSETTE_DJ_MODELOS` apuntando a los modelos de prueba).

## Review Focus

1. **Cambiar de estación con un trabajo en curso o pendiente:** el en curso termina y se registra para su estación (suena si el usuario vuelve); el pendiente se reemplaza; saltar entre A, B, C y D deja un solo trabajo en curso. → tests en Task 5.
2. **Servicio DJ caído, lento, que se reinicia o que contesta basura:** la radio sigue, un solo aviso por episodio, espera creciente, se recupera sola, un clip a destiempo se descarta y no se acumulan pedidos. → tests en Task 3 y Task 5.
3. **Frecuencia:** respeta `min`/`max` en los dos modos, el margen, lo que pisa cada estación, los temas sin tags y las reservas existentes; la general configurada vale para todas. → tests en Task 2 y Task 4.
4. **Reinicio de la radio** con un trabajo en curso o intervenciones guardadas: se retoma por `id` si el hueco sigue vigente y se descarta si no; un `planificador.json` corrupto no impide arrancar. → tests en Task 5.
5. **Re-escaneo que cambia la agenda de una estación:** se descartan sus reservas y su trabajo en curso; no se usa un hueco calculado con la agenda vieja. → tests en Task 5.

---

## Estructura de archivos

```
src/cassette_fm/biblioteca.py        # Task 1: Pista con artista/cancion/album/isrc
src/cassette_fm/config.py            # Task 2: Frecuencia, ConfigDJ ampliado, Rutas.planificador
src/cassette_fm/cliente_dj.py        # Task 3: ClienteDJ, ErrorDJ
src/cassette_fm/planificacion.py     # Task 4: Ultima, Hueco, elegir_hueco, armar_pedido
src/cassette_fm/intervenciones.py    # Task 5: quitar_estacion
src/cassette_fm/locutor.py           # Task 5: descartar_estacion
src/cassette_fm/planificador.py      # Task 5: Planificador
src/cassette_fm/radio.py, servicio.py, api.py, cli.py   # Task 6
tests/conftest.py                    # Task 3: fixture servicio_dj (el servicio real de la parte 2a)
tests/test_<módulo>.py
```

---

### Task 1: La `Pista` con artista, canción, álbum e ISRC

**Files:** Modify `src/cassette_fm/biblioteca.py`, `tests/test_biblioteca.py`

**Interfaces:**
- Produces: `Pista` gana, **al final y con valor por defecto** (los tests y el código existentes no cambian):

```python
@dataclass(frozen=True)
class Pista:
    ruta: Path; duracion: float; titulo: str; fuente: str = "local"
    artista: str | None = None      # tag artist
    cancion: str | None = None      # tag title (solo el título; `titulo` sigue siendo "Artista - Título")
    album: str | None = None
    isrc: str | None = None
```

`leer_pista` los llena desde los tags (`artist`, `title`, `album`, `isrc`; texto sin espacios de más; vacío → `None`). El caché guarda los cuatro (`"artista"`, `"cancion"`, `"album"`, `"isrc"`) y una entrada **que no tenga la clave `"artista"`** (formato viejo) se considera ausente y se vuelve a leer.

- [ ] **Step 1: Tests que fallan** en `tests/test_biblioteca.py`: `test_leer_pista_separa_artista_cancion_album_e_isrc` (mp3 con los cuatro tags; `crear_mp3` solo escribe título y artista: ampliar la fixture para aceptar `album` e `isrc`); `test_leer_pista_sin_tags_deja_none` (los cuatro `None`, `titulo` = nombre de archivo); `test_tags_vacios_o_con_espacios_dan_none`; `test_el_cache_guarda_los_campos_nuevos_y_los_devuelve` (segundo `escanear` con el mismo caché, `leer_pista` parcheada para contar: 0 lecturas y las pistas traen los cuatro campos); `test_una_entrada_de_cache_en_formato_viejo_se_vuelve_a_leer` (caché escrito a mano sin `"artista"` con `mtime_ns`/`tamano` correctos → se relee y las pistas traen sus tags); y que los tests existentes que construyen `Pista(ruta, duracion, titulo)` siguen pasando.
- [ ] **Step 2:** `.venv/bin/pytest tests/test_biblioteca.py -q` → FAIL.
- [ ] **Step 3:** Implementar (en `tests/conftest.py`, `crear_mp3(ruta, segundos, titulo, artista, album=None, isrc=None)` con `EasyID3`).
- [ ] **Step 4:** Suite completa → PASS.
- [ ] **Step 5:** Commit `Biblioteca: la pista separa artista, canción, álbum e ISRC`.

---

### Task 2: Configuración del planificador

**Files:** Modify `src/cassette_fm/config.py`, `tests/test_config.py`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True)
class Frecuencia:
    modo: str = "temas"      # "temas" | "minutos"
    min: float = 2.0
    max: float = 3.0

# ConfigDJ gana (todos con estos valores por defecto; valen en [dj] y por estación en [dj.estaciones."X"]):
url: str = ""                                    # servicio DJ; vacío = sin planificador
margen_minutos: float = 6.0
frecuencia: Frecuencia = Frecuencia()
voz: str = "em_santa"
idioma: str = "es"
personalidad: str = ""
timeout_http_segundos: float = 10.0
espera_reintento_segundos: float = 5.0           # primera espera tras un fallo del servicio
espera_reintento_maxima_segundos: float = 300.0  # tope de la espera creciente
espera_trabajo_maxima_segundos: float = 600.0    # un trabajo que lleva más que esto sin terminar se cancela
recientes_cantidad: int = 6                      # cuántos ingredientes recordar por estación

# Rutas gana la propiedad:  Rutas.planificador -> estado.parent / "planificador.json"
```

Validación (todas con `ErrorConfig` que nombra el archivo y la clave): `url` vacía o `http://…`/`https://…`; `voz` según `^[A-Za-z0-9_+.-]+$`; `idioma` en `es`, `en`, `en-us`, `en-gb`; `personalidad` texto de hasta 300 caracteres; `margen_minutos >= 0`; `timeout_http_segundos`, `espera_reintento_segundos`, `espera_reintento_maxima_segundos`, `espera_trabajo_maxima_segundos > 0` (y reintento ≤ máxima); `recientes_cantidad` entero `>= 0`. **Frecuencia:** una tabla `[dj.frecuencia]` (general) o `frecuencia = {…}` dentro de la estación, con claves opcionales `modo`, `min`, `max`; la de la estación **se funde** sobre la general (solo pisa las claves que da); `modo` en `temas`/`minutos`; `min` y `max` números `> 0`, `min <= max` después de fundir; en modo `temas` deben ser enteros `>= 1`. `bool` no vale como número. Las claves desconocidas se siguen ignorando.

- [ ] **Step 1: Tests que fallan** en `tests/test_config.py`: `test_dj_defaults_del_planificador` (los 11 valores exactos); `test_la_frecuencia_general_vale_para_todas` (`[dj.frecuencia] min = 3, max = 5` → `configuracion_dj(cfg, "Cualquiera").frecuencia == Frecuencia("temas", 3, 5)`, y también para una estación que no tiene tabla); `test_la_estacion_pisa_la_frecuencia_solo_en_lo_que_da` (general `temas 3..5`, estación `frecuencia = {min = 4}` → `temas 4..5`; otra con `{modo = "minutos", min = 8, max = 15}` → `minutos 8..15`); `test_voz_idioma_y_personalidad_por_estacion`; `test_dj_acepta_url_vacia_y_http`; `test_dj_invalido_da_error_claro` (parametrizado con la ruta en el mensaje: `url = "ftp://x"`, `url = 5`, `voz = "../x"`, `idioma = "fr"`, `personalidad = 3`, `margen_minutos = -1`, `timeout_http_segundos = 0`, `recientes_cantidad = -1`, `recientes_cantidad = 1.5`, `[dj.frecuencia] modo = "dias"`, `min = 0`, `min = 5, max = 3`, `min = 1.5` en modo temas, `min = "x"`, y una estación con `frecuencia = 5`); `test_las_claves_viejas_siguen_andando` (el test de la parte 1 de "claves de otras partes" se actualiza: `url`, `frecuencia`, `voz`, `idioma`, `personalidad`, `margen_minutos` ya **no** se ignoran; `palabras_maximas` sí); `test_rutas_planificador`.
- [ ] **Step 2:** `.venv/bin/pytest tests/test_config.py -q` → FAIL.
- [ ] **Step 3:** Implementar en `config.py` (extender `_campos_dj`/`_leer_dj`; la frecuencia se funde con `dataclasses.replace`).
- [ ] **Step 4:** Suite completa → PASS.
- [ ] **Step 5:** Commit `Configuración del DJ: frecuencia general y por estación, voz, idioma y servicio`.

---

### Task 3: Cliente del servicio DJ

**Files:** Create `src/cassette_fm/cliente_dj.py`, `tests/test_cliente_dj.py`; Modify `tests/conftest.py` (fixture `servicio_dj`)

**Interfaces:**
- Produces:

```python
class ErrorDJ(Exception): ...        # str(e): mensaje en español (no responde, error del servicio, respuesta ilegible)

class ClienteDJ:
    def __init__(self, url: str, timeout: float = 10.0): ...
    def enviar(self, pedido: dict) -> str                        # POST /intervenciones -> id; 400 y demás -> ErrorDJ con el mensaje del servicio
    def estado(self, id: str) -> dict | None                     # GET; None si 404; ErrorDJ en el resto
    def descargar_audio(self, id: str, destino: Path) -> Path    # GET .../audio a `<destino>.part` y renombra; ErrorDJ si no está listo o no existe
    def cancelar(self, id: str) -> bool                          # DELETE; False si 404 o si ya no se podía cancelar
    def salud(self) -> dict                                      # GET /salud
```

Reglas: `id` se valida con `^[A-Za-z0-9_-]{1,64}$` (si no, `ValueError`) y nunca se arma una URL con otra cosa; todo error de red, timeout, JSON roto o código inesperado se convierte en `ErrorDJ` (nunca escapa un `URLError`, `OSError` ni `JSONDecodeError`); el cuerpo de error `{"error": "..."}` del servicio se incluye en el mensaje; `descargar_audio` verifica que lo bajado empiece con `RIFF` y que el largo coincida con `Content-Length` (si no, `ErrorDJ` y sin archivo).

`tests/conftest.py` — fixture `servicio_dj` (fábrica): levanta el servicio real de la parte 2a en un hilo (`cassette_fm.dj.servidor.crear_servidor` con `Cola`, `Productor`, `Lexico`, `RegistroGuiones` en `tmp_path`, `fonemizar` falso `lambda t, l: t` y un `SintetizadorFalso` que escribe un WAV de `duracion` segundos —por defecto 3,0— y puede **bloquearse** con un `threading.Event`), devuelve un objeto con `.url`, `.sintetizador`, `.cola`, `.guiones` y lo apaga al terminar.

- [ ] **Step 1: Tests que fallan** en `tests/test_cliente_dj.py` (con `servicio_dj`): `test_enviar_y_consultar_hasta_listo` (pedido válido → id; `estado` pasa a `listo` con `duracion` 3.0 y `texto`); `test_estado_de_un_id_desconocido_es_None`; `test_descargar_audio_escribe_un_wav_valido` (y no deja `.part`); `test_descargar_un_trabajo_no_listo_da_ErrorDJ` (sintetizador bloqueado); `test_cancelar_pendiente_si_y_desconocido_no`; `test_pedido_invalido_da_ErrorDJ_con_el_mensaje_del_servicio` (falta un campo → el mensaje nombra el campo); `test_servicio_caido_da_ErrorDJ_claro` (puerto sin nadie escuchando: mensaje con "no responde" y la URL); `test_servicio_que_no_contesta_da_ErrorDJ_por_timeout` (un socket que acepta y calla, `timeout=0.3`); `test_respuesta_que_no_es_json_da_ErrorDJ` (servidor que devuelve HTML); `test_audio_truncado_o_que_no_es_wav_da_ErrorDJ_y_no_deja_archivo`; `test_id_peligroso_da_ValueError` (`"../x"`, `"a/b"`, `""`); `test_salud`.
- [ ] **Step 2:** `.venv/bin/pytest tests/test_cliente_dj.py -q` → FAIL.
- [ ] **Step 3:** Implementar (`urllib.request`, `json`).
- [ ] **Step 4:** Suite completa → PASS.
- [ ] **Step 5:** Commit `Cliente HTTP del servicio DJ`.

---

### Task 4: Elegir el hueco y armar el pedido (funciones puras)

**Files:** Create `src/cassette_fm/planificacion.py`, `tests/test_planificacion.py`

**Interfaces:**
- Consumes: `transiciones`, `secuencia` (agenda), `Estacion`, `Pista` (Task 1), `ConfigDJ`/`Frecuencia` (Task 2).
- Produces:

```python
MAX_CANDIDATAS = 200

@dataclass(frozen=True)
class Ultima:                      # la última intervención de una estación
    inicio_tema: float             # epoch en que arrancó el tema destino
    fin: float                     # epoch en que terminó la voz

@dataclass(frozen=True)
class Hueco:
    pista: Pista                   # el tema destino: arranca justo antes de la voz
    inicio_tema: float
    inicio_voz: float              # inicio_tema + cfg.retraso_voz_segundos
    anterior: Pista | None         # el tema que sonaba justo antes

def elegir_hueco(estacion: Estacion, ahora: float, cfg: ConfigDJ, ultima: Ultima | None,
                 azar: random.Random, ocupados: Sequence[tuple[float, float]] = ()) -> Hueco | None

def armar_pedido(id: str, estacion: str, hueco: Hueco, cfg: ConfigDJ, recientes: Sequence[str]) -> dict
    # {"id","estacion","idioma","voz","personalidad" (solo si no está vacía),"momento" (ISO-8601 con la zona local del
    #  sistema del inicio_voz),"anterior" (solo si hay y tiene artista y canción),"siguiente": {"artista","titulo","album","isrc"}
    #  (album/isrc solo si existen),"recientes": list(recientes),"duracion_maxima_segundos": cfg.duracion_maxima_segundos}
```

Algoritmo de `elegir_hueco` (lo fija el plan):
1. `minimo = ahora + cfg.margen_minutos * 60`. Candidatas = hasta `MAX_CANDIDATAS` transiciones. Una candidata exige `inicio_tema >= minimo`, `inicio_tema > ahora`, `pista.artista` y `pista.cancion` no vacíos, y que `[inicio_voz, inicio_voz + cfg.duracion_maxima_segundos)` no se cruce con ninguno de `ocupados`.
2. **Modo `temas`:** se sortea `k = azar.randint(int(min), int(max))`. Con `ultima`: la serie es `transiciones(estacion, ultima.inicio_tema - 0.001)` numerada desde `j = 0` (el propio destino de la última); sin `ultima`: `transiciones(estacion, ahora)` numerada desde `j = 1`. Se toma la **primera** candidata con `j >= k`. Si `k` cae antes del margen, naturalmente se elige la primera posterior que lo cumple.
3. **Modo `minutos`:** `objetivo = (ultima.fin si hay, si no ahora) + azar.uniform(min, max) * 60`; se toma la primera candidata con `inicio_tema >= max(objetivo, minimo)` (serie `transiciones(estacion, ahora)`).
4. `anterior = next(secuencia(estacion, inicio_tema - 0.001))[0]`. Sin candidatas, `None`.

- [ ] **Step 1: Tests que fallan** en `tests/test_planificacion.py` (estación `E` de varios temas con tags, duraciones de 200 s, reloj fijo; `random.Random(n)`):
  - `test_temas_sin_ultima_cae_entre_min_y_max_temas_desde_ahora` (con `margen_minutos=0`, para 200 semillas el hueco cae en `j ∈ [min, max]`, verificado contando transiciones; y se ven todos los valores del rango).
  - `test_temas_con_ultima_cuenta_desde_la_ultima` (la `Ultima` en el pasado: `j ∈ [min, max]` contado desde su `inicio_tema`).
  - `test_respeta_el_margen_y_toma_la_primera_posterior` (`margen_minutos=10`: ninguna con `inicio_tema < ahora + 600`; y cuando el rango `[min, max]` cae todo antes del margen, se devuelve la primera posterior que lo cumple aunque `j > max`).
  - `test_modo_minutos` (`minutos 8..15`: con `ultima.fin = ahora - 60` el `inicio_tema` cae entre `fin + 8·60` y la transición siguiente a `fin + 15·60`; sin `ultima`, desde `ahora`).
  - `test_la_frecuencia_de_la_config_manda` (`temas 5..5` siempre el 5.º; cambiar a `3..3` cambia).
  - `test_saltea_temas_sin_artista_o_cancion` (la candidata natural no tiene tags → se elige la siguiente con tags; si ninguno tiene tags → `None`).
  - `test_saltea_los_huecos_ocupados` (con `ocupados` cubriendo la candidata natural → la siguiente).
  - `test_anterior_es_el_tema_que_sonaba_antes` (verificado con `secuencia`).
  - `test_hueco_inicio_voz_suma_el_retraso` (`cfg.retraso_voz_segundos=2.5`).
  - `test_sin_candidatas_da_None` (estación de 1 tema sin tags; o todo ocupado).
  - `test_es_determinista_con_la_misma_semilla`.
  - `armar_pedido`: `test_pedido_completo` (todos los campos, `momento` parsea con `datetime.fromisoformat` y es aware, `duracion_maxima_segundos` de la config, `recientes` copiada); `test_pedido_minimo` (sin `personalidad`, sin `anterior`, sin `album`/`isrc`); `test_el_anterior_sin_artista_no_va`; `test_el_pedido_pasa_la_validacion_del_servicio` (`cassette_fm.dj.pedido.leer_pedido(armar_pedido(...))` no lanza, con nombres con comillas y acentos).
- [ ] **Step 2:** `.venv/bin/pytest tests/test_planificacion.py -q` → FAIL.
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** Suite completa → PASS.
- [ ] **Step 5:** Commit `Planificación: elección del hueco según la frecuencia y armado del pedido`.

---

### Task 5: El planificador

**Files:** Create `src/cassette_fm/planificador.py`, `tests/test_planificador.py`; Modify `src/cassette_fm/intervenciones.py`, `src/cassette_fm/locutor.py`, `tests/test_intervenciones.py`, `tests/test_locutor.py`

**Interfaces:**
- Consumes: `ClienteDJ`, `ErrorDJ` (Task 3), `elegir_hueco`, `armar_pedido`, `Ultima`, `Hueco` (Task 4), `ConfigDJ` (Task 2), `Locutor.registrar`, `RegistroIntervenciones` (parte 1), `Estacion`, `Pista`.
- Produces:

```python
# intervenciones.py
RegistroIntervenciones.quitar_estacion(self, estacion: str) -> list[Intervencion]   # quita todas las de esa estación y borra sus clips (solo dentro de dir_clips); persiste
# locutor.py
Locutor.descartar_estacion(self, estacion: str) -> None     # quita sus intervenciones del registro y, si la voz en curso es de esa estación, la corta

# planificador.py
class Planificador:
    def __init__(self, cliente, locutor, registro, configuracion: Callable[[str], ConfigDJ], archivo: Path,
                 dir_clips: Path, reloj: Callable[[], float] = time.time, azar: random.Random | None = None,
                 gracia_segundos: float = 60.0, intervalo_segundos: float = 1.0): ...
    def al_sintonizar(self, estacion: Estacion) -> None
    def al_apagar(self) -> None
    def al_rescan(self, estaciones: Sequence[Estacion]) -> None
    def pedir_ahora(self, en_segundos: float) -> dict      # {"id","estacion","inicio","en_segundos"}; ValueError("...") si no hay estación sintonizada, ya hay un trabajo en curso o no hay hueco
    def paso(self) -> None                                  # una vuelta (la usa el hilo y los tests)
    def iniciar(self) -> None                               # arranca el hilo que llama a paso() cada `intervalo_segundos`
    def cerrar(self) -> None                                # detiene el hilo; NO cancela el trabajo en curso (queda guardado para retomarlo)
    def estado(self) -> dict
        # {"estacion": str | None, "en_curso": {"id","estacion","estado","en_segundos"} | None,
        #  "servicio": "ok" | "no responde", "error": str | None, "proximo_intento_en": float | None}
```

Estado interno (se guarda en `archivo`, JSON, de forma atómica): `ultima` por estación (`Ultima`), `recientes` por estación (lista de ingredientes, recortada a `recientes_cantidad` de la estación), y `en_curso` (`id`, `estacion`, `inicio_tema`, `inicio_voz`, `pista_destino` —ruta—, `enviado_en`, `duracion_maxima`). JSON corrupto o ausente → estado vacío.

`paso()`:
- **A. Si hay trabajo en curso:**
  - Si `reloj() > inicio_voz + duracion_maxima + gracia_segundos` (el hueco ya pasó) o lleva más de `espera_trabajo_maxima_segundos` desde `enviado_en`: `cliente.cancelar(id)` (mejor esfuerzo), se limpia y se registra en el log.
  - Si no: `cliente.estado(id)`: `None` (el servicio no lo conoce) → se limpia; `pendiente`/`trabajando` → no hace nada; `cancelado` → se limpia; `error` → se registra una advertencia con el mensaje, se limpia y se aplica la espera creciente (no se vuelve a pedir enseguida); `listo` → `descargar_audio` a `dir_clips/<id>.wav`, se arma `Intervencion(id, estacion, inicio_voz, duracion del estado, audio, texto del estado, pista_destino)` y `locutor.registrar(...)`; si `registrar` lanza `ValueError` (se superpone o excede la duración) el clip se borra y se registra una advertencia; si sale bien se actualizan `ultima` (`Ultima(inicio_tema, inicio_voz + duracion)`) y `recientes` (los `ingredientes` del estado), se limpia y se reinicia la espera.
  - `ErrorDJ` en cualquier llamada → `_fallo(e)`; el trabajo en curso se conserva.
- **B. Si no hay trabajo en curso** y hay estación sintonizada y `reloj() >= no_antes_de`: si el registro tiene una intervención vigente (`de_la_estacion`) de esa estación → nada; si no, `hueco = elegir_hueco(...)` con `ocupados` = las del registro de esa estación; `None` → nada; si no, `cliente.enviar(armar_pedido(...))` con `id = uuid4().hex`; éxito → `en_curso` guardado. `ErrorDJ` → `_fallo(e)`.
- `_fallo(e)`: guarda el mensaje; **el primer fallo de un episodio** se registra con `logging.warning` y los siguientes no (al recuperarse se registra un `info`); la espera arranca en `espera_reintento_segundos` y se duplica hasta `espera_reintento_maxima_segundos`; `servicio = "no responde"`. Cualquier llamada exitosa vuelve `servicio` a `"ok"` y reinicia la espera.

Hooks: `al_sintonizar(estacion)` fija la estación sintonizada (esto **reemplaza** al pedido pendiente: no hay otra cola) y guarda su firma de agenda (`tuple((str(p.ruta), p.duracion) for p in pistas)`); `al_apagar()` deja de haber estación sintonizada (el trabajo en curso sigue); `al_rescan(estaciones)`: para cada estación cuya firma cambió respecto de la guardada → `locutor.descartar_estacion`, se olvida su `ultima` y, si el trabajo en curso es de esa estación, se cancela y se limpia; se actualizan las firmas y el objeto de la estación sintonizada (si desapareció, como si se apagara). `pedir_ahora(en)` hace lo de B para la estación sintonizada **ignorando la frecuencia y el registro** (usa `margen = en_segundos` en vez de `margen_minutos` y sin `ultima`), pero **no** puede haber un trabajo en curso.

- [ ] **Step 1: Tests que fallan.**
  - `tests/test_intervenciones.py`: `test_quitar_estacion_quita_y_borra_sus_clips` (solo las de esa estación; los clips fuera de `dir_clips` no se borran; persiste); `test_quitar_estacion_sin_intervenciones_no_hace_nada`.
  - `tests/test_locutor.py`: `test_descartar_estacion_quita_sus_intervenciones`; `test_descartar_estacion_corta_la_voz_si_es_de_esa_estacion` (música restaurada); `test_descartar_otra_estacion_no_corta_la_voz`.
  - `tests/test_planificador.py`, con un `ClienteFalso` (guarda lo enviado, devuelve `estado` según un guion por `id`, `descargar_audio` escribe un WAV de `tests` con `generar_clip_de_prueba`, puede lanzar `ErrorDJ`), un `LocutorFalso` (registra `registrar`/`descartar_estacion`, puede lanzar `ValueError`), un `RegistroIntervenciones` real en `tmp_path`, reloj mutable y `random.Random(1)`; estación `E`/`F` de temas de 200 s con tags; `paso()` llamado a mano (nunca el hilo):
    - `test_planifica_para_la_estacion_sintonizada_y_envia_el_pedido` (el pedido tiene `estacion`, `siguiente`, `momento` del hueco, `duracion_maxima_segundos`, `recientes` vacía, `voz`/`idioma` de la config; `estado()["en_curso"]` presente).
    - `test_sin_estacion_sintonizada_no_planifica` y `test_con_la_radio_apagada_no_planifica_pero_lo_iniciado_termina`.
    - `test_no_pide_otra_si_la_estacion_ya_tiene_una_reservada` (registro con una vigente → ningún `enviar`).
    - `test_un_solo_trabajo_a_la_vez` (con uno en curso, otros `paso()` no envían nada aunque cambie la estación) y `test_saltar_entre_estaciones_deja_un_solo_trabajo` (A→B→C→D antes de que termine el primero: un solo `enviar` hasta que termine, y después uno solo para la estación final).
    - `test_el_trabajo_en_curso_termina_y_se_registra_para_su_estacion` (se pide para A, se cambia a B, el servicio dice `listo`: `registrar` recibe una `Intervencion` con `estacion == "A"`, `inicio == hueco.inicio_voz`, `pista_destino` = ruta del destino, `duracion` y `texto` del estado, y `audio` dentro de `dir_clips`).
    - `test_listo_actualiza_ultima_y_recientes_y_el_proximo_pedido_los_usa` (el segundo pedido lleva `recientes` con los ingredientes del primero y su hueco respeta `min` temas desde la última).
    - `test_si_registrar_falla_se_borra_el_clip` (`ValueError` del `LocutorFalso`: el WAV ya no está y se registra una advertencia; no se actualiza `ultima`).
    - `test_error_del_servicio_en_el_trabajo_espera_antes_de_reintentar` (estado `error` → advertencia con el mensaje, y los `paso()` siguientes no envían hasta pasar la espera; la espera crece con fallos seguidos).
    - `test_servicio_caido_avisa_una_sola_vez_y_se_recupera` (`enviar` lanza `ErrorDJ` 5 veces con reloj que avanza: una sola advertencia, `estado()["servicio"] == "no responde"` con `proximo_intento_en` y la espera duplica hasta el tope; al volver, un `info`, `"ok"` y se envía).
    - `test_trabajo_demasiado_viejo_se_cancela` (el reloj pasa `inicio_voz + duracion_maxima + gracia` con el trabajo `trabajando` → `cancelar` y se limpia); `test_trabajo_que_tarda_demasiado_se_cancela` (`espera_trabajo_maxima_segundos`).
    - `test_el_servicio_olvida_el_trabajo_se_limpia` (`estado` → `None`).
    - `test_se_retoma_un_trabajo_en_curso_tras_reiniciar` (un `Planificador` nuevo con el mismo `archivo`: sigue consultando el `id`, y al `listo` lo registra); `test_se_descarta_un_trabajo_guardado_cuyo_hueco_ya_paso`; `test_archivo_corrupto_o_ausente_arranca_vacio`.
    - `test_rescan_que_cambia_la_agenda_descarta_reservas_y_trabajo` y `test_rescan_sin_cambios_no_toca_nada`.
    - `test_pedir_ahora_ignora_la_frecuencia_y_usa_el_margen_dado`, `test_pedir_ahora_falla_sin_estacion_o_con_trabajo_en_curso_o_sin_hueco`.
    - `test_la_configuracion_por_estacion_manda` (voz e idioma distintos por estación en el pedido).
    - `test_el_hilo_arranca_y_se_detiene_sin_dejar_hilos` (con `intervalo_segundos` chico; `cerrar()` no cancela el trabajo en curso; `threading.enumerate()` antes/después).
  - `test_integracion_con_el_servicio_dj_real` (fixture `servicio_dj`, `ClienteDJ` real, `LocutorFalso`, reloj real y temas de 3 s con `margen_minutos=0`, `frecuencia temas 1..1`): `al_sintonizar` + `paso()` en bucle hasta que `registrar` reciba la intervención; el clip descargado es un WAV de 3 s; el pedido que vio el servicio es válido y el guion queda anotado en el registro de guiones del servicio con `fuente == "plantilla"`.
- [ ] **Step 2:** `.venv/bin/pytest tests/test_intervenciones.py tests/test_locutor.py tests/test_planificador.py -q` → FAIL (los nuevos).
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** Suite completa → PASS; repetir `tests/test_planificador.py` 5 veces seguidas sin fallos.
- [ ] **Step 5:** Commit `Planificador: pide intervenciones al servicio DJ según la frecuencia y las reserva en la agenda`.

---

### Task 6: Integración en la radio, API, comando y prueba de punta a punta

**Files:** Modify `src/cassette_fm/radio.py`, `src/cassette_fm/servicio.py`, `src/cassette_fm/api.py`, `src/cassette_fm/cli.py`, `README.md`, `tests/test_radio.py`, `tests/test_api.py`, `tests/test_cli.py`, `tests/test_servicio.py`

**Interfaces:**
- Consumes: `Planificador` (Task 5), `ClienteDJ` (Task 3), `ConfigDJ` (Task 2).
- Produces:
  - `Radio.__init__` gana `planificador=None` (al final, con default). Con planificador: `_sintonizar` (después de `dj.al_sintonizar`) llama `planificador.al_sintonizar(estacion)`; `_apagar` llama `planificador.al_apagar()`; `rescan` llama `planificador.al_rescan(estaciones)` **fuera del lock** de la radio. Con `None` nada de esto hace nada.
  - `Radio.dj_estado()` agrega la clave `"planificador"` (el `estado()` del planificador, o `None` si no hay).
  - `Radio.dj_pedir(en_segundos: float = 20.0) -> dict` → `planificador.pedir_ahora(en_segundos)`; `DJInactivo` si no hay planificador (DJ apagado o sin `url`); `RadioApagada` si no hay estación sintonizada; `ValueError` con el mensaje del planificador en los demás casos.
  - API: `POST /dj/pedir {"en_segundos": número?}` → 200 con lo que devuelve `dj_pedir`; `DJInactivo` → 409 ("…poné `activo = true` y la `url` del servicio en la sección [dj]…"); `RadioApagada` → 409; `ValueError` → 400; tipo inválido → 400. `GET /dj` incluye `planificador`.
  - CLI: `cassette dj pedir [--en SEGUNDOS]` (por defecto 20) imprime `Se le pidió una intervención al servicio DJ para «<tema>» en <estación>: va a hablar en N s si está lista a tiempo.`; `cassette dj estado` agrega, si hay planificador, una línea `servicio DJ: ok` o `servicio DJ: no responde (<error>) · reintento en N s`, y `pedido en curso: <estación> (<estado>)` cuando lo hay.
  - `servicio.servir`: con `config.dj.activo` **y** `config.dj.url` no vacía, crea `ClienteDJ(url, timeout)` y el `Planificador` (archivo `rutas.planificador`, `dir_clips=rutas.clips`, `gracia_segundos=config.dj.tolerancia_desfase_segundos`), llama `iniciar()`, se lo pasa a la `Radio` y en el apagado llama `cerrar()` **antes** de cerrar el locutor y mpv. Sin `url` no se crea nada de esto.

- [ ] **Step 1: Tests que fallan.**
  - `tests/test_radio.py` (con un `PlanificadorFalso` que registra llamadas): `test_sintonizar_avisa_al_planificador_despues_del_locutor`; `test_apagar_avisa_al_planificador`; `test_rescan_avisa_al_planificador_fuera_del_lock` (el `al_rescan` del falso consulta `radio.estado()` desde otro hilo sin bloquearse); `test_sin_planificador_todo_sigue_andando`; `test_dj_estado_incluye_el_planificador`; `test_dj_pedir_sin_planificador_da_DJInactivo`, `test_dj_pedir_con_la_radio_apagada_da_RadioApagada`, `test_dj_pedir_delega_en_el_planificador`.
  - `tests/test_api.py` y `tests/test_cli.py`: `test_post_dj_pedir_*` (pasa `en_segundos`, valor por defecto, 409 por `DJInactivo` con el mensaje de `url`, 409 por `RadioApagada`, 400 por `ValueError`, 400 por tipos inválidos); `test_dj_pedir_imprime_cuando_hablara`, `test_dj_pedir_error_de_la_api_da_codigo_1`, `test_dj_estado_muestra_el_servicio_y_el_pedido_en_curso`, `test_dj_estado_sin_planificador_no_agrega_lineas`.
  - `tests/test_servicio.py`: `test_con_dj_activo_sin_url_no_hay_planificador` (no se conecta a nada: no hay conexiones al puerto del servicio de prueba; `GET /dj` sin clave `planificador` útil); `test_con_url_se_crea_el_planificador_y_se_cierra_limpio` (sin hilos ni mpv colgados); y **`test_dj_de_punta_a_punta_con_el_servicio_real`** (fixture `servicio_dj` en un hilo + `servir` de la radio con `ConfigDJ(activo=True, url=<la del servicio>, margen_minutos=0.02, retraso_voz_segundos=0.1, rampas chicas, frecuencia temas 1..1)`, estación de 3 mp3 de 3 s con tags y mpv `--ao=null`): `POST /encender`; en ≤ 20 s `GET /dj` lista una intervención de la estación con `texto` del servicio; en ≤ 25 s `hablando` pasa a `true` y luego a `false`; el guion quedó anotado en el servicio; `POST /apagar` y el cierre terminan limpios y sin `mpv` colgado de `mpv.sock`/`voz.sock`. Y `test_el_servicio_dj_caido_no_afecta_a_la_radio` (url a un puerto cerrado: la radio sintoniza, cambia de estación y apaga normalmente; `GET /dj` informa `servicio: "no responde"`).
- [ ] **Step 2:** `.venv/bin/pytest tests/test_radio.py tests/test_api.py tests/test_cli.py tests/test_servicio.py -q` → FAIL (los nuevos).
- [ ] **Step 3:** Implementar en `radio.py`, `servicio.py`, `api.py` y `cli.py`.
- [ ] **Step 4:** Suite completa → PASS; repetir el test de punta a punta 5 veces seguidas sin fallos.
- [ ] **Step 5:** README: actualizar la sección "DJ": cómo activar el planificador (`[dj] activo = true` + `url = "http://127.0.0.1:7720"`), la configuración nueva (frecuencia general y por estación, ejemplos de las dos modalidades, `voz`/`idioma`/`personalidad` por estación, `margen_minutos`, timeouts y esperas) con sus valores por defecto, `cassette dj pedir` y las líneas nuevas de `cassette dj estado`, y la **verificación con audio real para hacer juntos**: instalar y arrancar el servicio (`scripts/instalar-dj.sh`, `cassette-dj modelos`), poner la `url`, reiniciar la radio, `cassette dj pedir --en 30` y escuchar; después dejarlo solo y comprobar que habla cada 2–3 temas.
- [ ] **Step 6:** Commit `Radio: planificador del DJ, comando cassette dj pedir y prueba de punta a punta`. Cerrar el bean `CASSETTE-FM-zuej`.
