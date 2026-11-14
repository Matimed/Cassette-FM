# Etapa 3, parte 1: capa de intervenciones, segundo mpv y música bajada — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que la radio pueda reproducir un clip de voz en un hueco reservado de la agenda de una estación, con la
música bajada, entrando a mitad de frase si el usuario sintoniza con la intervención en curso, y probarlo con un
comando (`cassette dj probar`) y clips fijos, sin LLM ni servicio DJ todavía.

**Architecture:** La agenda de temas no cambia. Encima se agrega un registro persistente de intervenciones por
estación (`estacion, inicio, duracion, audio`). Un `Locutor` dispara la voz por el inicio **real** del tema en mpv
(evento `file-loaded`) o, al sintonizar, por el reloj si la ventana ya empezó; la voz sale por un **segundo mpv** y la
música se baja con una rampa de volumen en el `Reproductor`. Todos los números (retraso, duración máxima, nivel,
rampas, tolerancias) vienen de la configuración.

**Tech Stack:** Python 3.12, mpv 0.37 por JSON IPC (el `ClienteMpv` existente), `wave`/`mutagen` para los clips,
pytest. Sin ffmpeg.

**Spec:** [`docs/superpowers/specs/2026-11-13-etapa-3-dj-design.md`](../specs/2026-11-13-etapa-3-dj-design.md)
(secciones "Capa de intervenciones", "Reproducción de la voz y música bajada", "Cómo se construye", parte 1).

## Global Constraints

- Bean de esta parte: `CASSETTE-FM-hnhf`, bajo la épica `CASSETTE-FM-p6zn`. Al empezar, `beans update CASSETTE-FM-hnhf -s in-progress`; al terminar la Task 6, `-s completed` y se incluye `.beans/` en el commit. `CASSETTE-FM-wyvi` queda para la parte 2 (planificador y cliente del servicio).
- **Nada fijo en el código** (spec): todo valor que pueda querer cambiarse vive en `ConfigDJ` con su valor por defecto. Los defaults de esta parte, exactos: `activo=false`, `duracion_maxima_segundos=15`, `retraso_voz_segundos=1`, `nivel_musica_con_voz=0.35`, `rampa_bajada_segundos=0.4`, `rampa_subida_segundos=1`, `minimo_restante_segundos=1.5`, `tolerancia_desfase_segundos=60`, `desfase_aviso_segundos=5`, `margen_seguridad_voz_segundos=2`.
- **El DJ viene apagado** (`[dj] activo = false`): con eso no se crea el segundo mpv, no se lee ni escribe el registro, y los endpoints `/dj` responden 409.
- El segundo mpv (`voz.sock` en el directorio de runtime, mismo helper `ClienteMpv`, que ya usa `--no-config`) **no recibe `--af=dynaudnorm`**. Solo se arranca al reproducir el primer clip (el `ClienteMpv` arranca solo al primer comando).
- **La voz se dispara por el inicio real del tema en mpv; el reloj solo reserva el hueco y sirve para entrar a mitad de frase.** No se resincroniza la música durante una escucha continua (spec).
- El volumen del usuario manda: la voz suena al **100 % del volumen del usuario**; la música, durante la voz, a `volumen_usuario × nivel_musica_con_voz`. Volumen 0 = radio apagada = sin voz.
- Cambiar de estación, apagar la radio, o terminar el clip: corta la voz y devuelve la música a su nivel.
- Una intervención con `duracion > duracion_maxima_segundos` se rechaza (el spec la descarta).
- Los clips registrados viven en `~/.cache/cassette-fm/dj/`; el registro, en `~/.local/state/cassette-fm/intervenciones.json`. Solo se borran archivos que estén dentro del directorio de clips.
- Mensajes, nombres y comentarios en español. Commits en español, texto plano en imperativo, con la línea de atribución vigente de la sesión.
- Los tests no hacen sonar audio (mpv con `--ao=null`) ni tocan la sesión real del usuario. Esta parte **no** se instala ni se prueba con audio real sin que el usuario lo pida: queda instrucción en el README.
- Fixtures de audio: se agrega `crear_wav` a `tests/conftest.py` (usa `clips.generar_clip_de_prueba`, Task 4).
- Al terminar cada tarea: `.venv/bin/pytest -q` completo en verde (hoy 190 tests).

## Review Focus

1. **Cambiar de estación o apagar mientras habla la voz:** la voz se corta y la música vuelve a su nivel (no se queda al 35 %). → tests en Task 4 y Task 5.
2. **Cambiar el volumen (o llevarlo a 0) durante la voz:** música y voz respetan el volumen nuevo, y al terminar la música queda en el volumen nuevo, no en el viejo. → tests en Task 3 y Task 4.
3. **El clip no se puede reproducir** (archivo borrado o ilegible) **o el mpv de la voz muere:** la música se restaura y la radio sigue. → tests en Task 4.
4. **Reinicio con intervenciones guardadas:** se recargan las vigentes; las vencidas y las que perdieron su archivo se descartan; un JSON corrupto no impide arrancar. → tests en Task 2.
5. **Sintonizar justo dentro de la ventana, con menos de `minimo_restante_segundos` por delante, y no repetir:** la misma intervención no suena dos veces (anclaje + reloj) ni cuando se entra en los primeros segundos del tema destino. → tests en Task 4.

---

## Estructura de archivos

```
src/cassette_fm/config.py          # Task 1: ConfigDJ, configuracion_dj, Rutas.intervenciones/.clips
src/cassette_fm/agenda.py          # Task 2: transiciones, desfase
src/cassette_fm/intervenciones.py  # Task 2: Intervencion, RegistroIntervenciones
src/cassette_fm/reproductor.py     # Task 3: atenuar
src/cassette_fm/clips.py           # Task 4: generar_clip_de_prueba
src/cassette_fm/locutor.py         # Task 4: Locutor
src/cassette_fm/radio.py           # Task 5: integración
src/cassette_fm/servicio.py        # Task 5: cableado
src/cassette_fm/api.py, cli.py     # Task 6: /dj y `cassette dj`
tests/test_<módulo>.py (+ tests/conftest.py: crear_wav)
```

---

### Task 1: Configuración del DJ

**Files:** Modify `src/cassette_fm/config.py`, `tests/test_config.py`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True)
class ConfigDJ:
    activo: bool = False
    duracion_maxima_segundos: float = 15.0
    retraso_voz_segundos: float = 1.0
    nivel_musica_con_voz: float = 0.35
    rampa_bajada_segundos: float = 0.4
    rampa_subida_segundos: float = 1.0
    minimo_restante_segundos: float = 1.5
    tolerancia_desfase_segundos: float = 60.0
    desfase_aviso_segundos: float = 5.0
    margen_seguridad_voz_segundos: float = 2.0   # el temporizador que restaura la música espera esto de más

# Config gana el campo:  dj: ConfigDJ = ConfigDJ()
# Config.estaciones_dj: Mapping[str, ConfigDJ]   -- overrides ya fusionados por estación (default vacío)
def configuracion_dj(config: Config, estacion: str) -> ConfigDJ   # la de la estación si existe, si no config.dj

# Rutas gana dos propiedades (el constructor no cambia):
#   Rutas.intervenciones -> estado.parent / "intervenciones.json"
#   Rutas.clips          -> cache.parent / "dj"
```

Reglas: `cargar_config` lee la tabla `[dj]` y las tablas `[dj.estaciones."<nombre>"]` (mismos campos; cada una se funde sobre la general). Las claves desconocidas (`url`, `frecuencia`, `voz`, `idioma`, `personalidad`, `margen_minutos`, `palabras_maximas`…) se **ignoran**: son de las partes siguientes. Los enteros valen como `float`. Errores con `ErrorConfig` que nombra el archivo y la clave, como los existentes.

- [ ] **Step 1: Tests que fallan** en `tests/test_config.py`:
  - `test_dj_por_defecto`: `Config().dj == ConfigDJ()` y `ConfigDJ().activo is False` y los 10 valores exactos de Global Constraints.
  - `test_dj_lee_la_tabla_y_acepta_enteros`: `[dj]` con `activo = true`, `duracion_maxima_segundos = 20` (entero), `nivel_musica_con_voz = 0.5` → `cargar_config(...).dj` con esos valores y `duracion_maxima_segundos == 20.0`.
  - `test_dj_por_estacion_pisa_a_la_general`: `[dj] duracion_maxima_segundos = 15` y `[dj.estaciones."Lentos"] duracion_maxima_segundos = 25` → `configuracion_dj(cfg, "Lentos").duracion_maxima_segundos == 25.0`, `configuracion_dj(cfg, "Otra").duracion_maxima_segundos == 15.0`, y el resto de los campos de "Lentos" son los generales.
  - `test_dj_ignora_claves_de_otras_partes`: `[dj]` con `url`, `frecuencia = {modo="temas", min=2, max=3}`, `margen_minutos`, y `[dj.estaciones."X"]` con `voz`/`idioma`/`personalidad` → carga sin error.
  - `test_dj_invalido_da_error_claro` (parametrizado; cada caso lanza `ErrorConfig` con la ruta del archivo en el mensaje): `nivel_musica_con_voz = 0`, `= 1.5`; `duracion_maxima_segundos = 0`, `= -3`; `rampa_bajada_segundos = -1`; `retraso_voz_segundos = "uno"`; `activo = "si"`; `[dj] estaciones = 5` (no es tabla); `[dj.estaciones] Lentos = 3` (cada estación debe ser una tabla).
  - `test_rutas_del_dj`: con `Rutas(config, estado=T/"s"/"estado.json", cache=T/"c"/"duraciones.json", runtime)`, `.intervenciones == T/"s"/"intervenciones.json"` y `.clips == T/"c"/"dj"`.
- [ ] **Step 2:** `.venv/bin/pytest tests/test_config.py -q` → FAIL.
- [ ] **Step 3:** Implementar en `config.py`. Validación: `nivel_musica_con_voz` en `(0, 1]`; `duracion_maxima_segundos`, `tolerancia_desfase_segundos` y `desfase_aviso_segundos` `> 0`; los demás tiempos `>= 0` (incluido `margen_seguridad_voz_segundos`). `bool` no vale como número.
- [ ] **Step 4:** Suite completa → PASS.
- [ ] **Step 5:** Commit `Configuración del DJ: parámetros por defecto y por estación`.

---

### Task 2: Transiciones de la agenda y registro de intervenciones

**Files:** Modify `src/cassette_fm/agenda.py`, `tests/test_agenda.py`; Create `src/cassette_fm/intervenciones.py`, `tests/test_intervenciones.py`

**Interfaces:**
- Consumes: `secuencia`, `EPOCA`, `Pista`, `Estacion` (Etapa 1).
- Produces:

```python
# agenda.py
def transiciones(estacion: Estacion, instante: float) -> Iterator[tuple[Pista, float]]
    # infinito: (tema que empieza, epoch de su inicio), todos POSTERIORES a `instante`, en orden.
def desfase(estacion: Estacion, pista: Pista, instante: float) -> float | None
    # Cuánto se aparta la música real del reloj en el momento en que `pista` acaba de empezar a sonar:
    #  > 0: la agenda ya contó esos segundos de `pista` (la música real va atrasada);
    #  < 0: la agenda todavía está en el tema anterior y `pista` empieza en |valor| s (la real va adelantada);
    #  None: `pista` no es ni el tema actual ni el siguiente de la agenda.
    # Si coincide con ambos (estación de un tema), gana la interpretación de menor valor absoluto.

# intervenciones.py
@dataclass(frozen=True)
class Intervencion:
    id: str
    estacion: str
    inicio: float          # epoch en que empieza a sonar la voz (inicio del tema destino + retraso)
    duracion: float
    audio: Path
    texto: str
    pista_destino: str     # str(ruta) del tema que arranca justo antes de la voz
    @property
    def fin(self) -> float  # inicio + duracion

class RegistroIntervenciones:
    def __init__(self, archivo: Path, dir_clips: Path, reloj: Callable[[], float] = time.time): ...
    def agregar(self, i: Intervencion) -> None          # ValueError si se superpone con otra de la MISMA estación; persiste
    def todas(self) -> list[Intervencion]                # ordenadas por inicio
    def de_la_estacion(self, estacion: str) -> list[Intervencion]   # vigentes (fin > ahora), por inicio
    def activa(self, estacion: str, instante: float) -> Intervencion | None   # inicio <= instante < fin
    def limpiar(self) -> list[Intervencion]              # quita las vencidas (fin <= ahora), borra sus clips, persiste
```

Reglas del registro: al construirse carga el archivo y llama a `limpiar()`; descarta además las intervenciones cuyo `audio` ya no existe. JSON corrupto o ausente → registro vacío (se registra una advertencia con `logging.getLogger("cassette_fm")`). Se guarda de forma atómica (`.tmp` + `os.replace`) en cada cambio. `limpiar` borra el archivo de audio **solo si está dentro de `dir_clips`**. Superponerse = `[inicio, fin)` se cruzan con las de la misma estación; estaciones distintas pueden coincidir.

- [ ] **Step 1: Tests que fallan** — `tests/test_agenda.py` (estación `E` de 5 pistas del archivo):
  - `test_transiciones_son_posteriores_y_acumulan_duraciones`: con `(p, d) = next(secuencia(E, t))`, el primer elemento de `transiciones(E, t)` es `(p_siguiente, t + (p.duracion - d))` y el segundo `(p_siguiente2, ese_inicio + p_siguiente.duracion)`, donde `p_siguiente`/`p_siguiente2` son los siguientes de `secuencia`; todos los inicios son `> t`.
  - `test_transiciones_cruzan_ciclos`: 12 elementos consecutivos tienen inicios estrictamente crecientes.
  - `test_desfase_en_el_inicio_exacto_es_cero` (`≈ 0`), `test_desfase_positivo_si_la_agenda_ya_avanzo` (instante = inicio de `p` + 3 → `≈ 3.0`), `test_desfase_negativo_si_la_real_va_adelantada` (instante = inicio de `p` − 2 → `≈ -2.0`), `test_desfase_none_si_no_coincide` (otro tema cualquiera que no sea el actual ni el siguiente), `test_desfase_estacion_de_un_tema_elige_el_menor`.
  - `tests/test_intervenciones.py` (con `tmp_path`, un reloj falso mutable y una fábrica `iv(estacion, inicio, dur, audio)` que crea el clip en `dir_clips`):
    - `test_agregar_persiste_y_se_recarga`: agregar, crear un registro nuevo con el mismo archivo → mismas intervenciones.
    - `test_superposicion_en_la_misma_estacion_falla`: `[10,20)` y `[15,25)` → `ValueError`; `[10,20)` y `[20,30)` sí (borde); la misma ventana en otra estación sí.
    - `test_activa_incluye_inicio_y_excluye_fin`.
    - `test_de_la_estacion_filtra_vigentes_y_ordena`.
    - `test_limpiar_quita_vencidas_y_borra_sus_clips`: avanzar el reloj → `limpiar()` devuelve la vencida, su archivo ya no existe y el JSON no la tiene.
    - `test_limpiar_no_borra_archivos_fuera_de_dir_clips`: una intervención cuyo `audio` está fuera del directorio de clips vence → el archivo sigue existiendo.
    - `test_json_corrupto_o_ausente_da_registro_vacio`.
    - `test_al_cargar_descarta_vencidas_y_sin_archivo` (Review Focus 4): archivo con una vigente, una vencida y una vigente cuyo clip se borró → solo queda la primera.
- [ ] **Step 2:** `.venv/bin/pytest tests/test_agenda.py tests/test_intervenciones.py -q` → FAIL.
- [ ] **Step 3:** Implementar `transiciones` (iterar `secuencia` acumulando duraciones desde el instante), `desfase` y `intervenciones.py`.
- [ ] **Step 4:** Suite completa → PASS.
- [ ] **Step 5:** Commit `Agenda: transiciones y desfase; registro persistente de intervenciones`.

---

### Task 3: Música bajada en el Reproductor

**Files:** Modify `src/cassette_fm/reproductor.py`, `tests/test_reproductor.py`

**Interfaces:**
- Consumes: `Reproductor`, `MpvFalso` de `tests/test_reproductor.py` (registra `comando`, tiene `generacion`).
- Produces:

```python
Reproductor.atenuar(self, factor: float, segundos: float = 0.0) -> None
    # Lleva el volumen EFECTIVO de mpv a `volumen_usuario * factor` con una rampa lineal de `segundos`
    # (0 = de inmediato). Una rampa nueva reemplaza a la que esté en curso, partiendo del valor actual.
    # `volumen(valor)` sigue devolviendo y recordando el volumen del usuario, pero aplica `valor * factor_actual`.
```

El volumen efectivo se manda a mpv como `set_property volume <float>`. La rampa corre en un hilo propio que **no** mantiene el `_lock` mientras espera (pasos de ~50 ms); el valor final es exacto. Si mpv se relanzó (`_asegurar`), se reaplica el volumen efectivo y no el del usuario a secas.

- [ ] **Step 1: Tests que fallan** en `tests/test_reproductor.py` (con `MpvFalso`; ayudante `ultimo_volumen(mpv)` que lee el último `set_property volume`):
  - `test_atenuar_sin_rampa_aplica_el_volumen_por_el_factor`: `volumen(80)`, `atenuar(0.35, 0)` → último volumen `≈ 28.0`.
  - `test_atenuar_con_rampa_baja_en_pasos_y_llega_al_valor`: `volumen(80)`, `atenuar(0.5, 0.2)`; esperar ≤ 1 s a que llegue; los volúmenes aplicados durante la rampa no suben, hay más de 2 pasos, y el último es `≈ 40.0`.
  - `test_volumen_durante_la_atenuacion_respeta_el_factor`: atenuado a 0.35, `volumen(60)` → último `≈ 21.0`; `atenuar(1.0, 0)` → `≈ 60.0` (Review Focus 2).
  - `test_restaurar_devuelve_el_volumen_del_usuario`: `volumen(70)`, `atenuar(0.35, 0)`, `atenuar(1.0, 0)` → `≈ 70.0`.
  - `test_una_rampa_nueva_reemplaza_a_la_anterior`: `atenuar(0.2, 0.5)` y enseguida `atenuar(1.0, 0)`; esperar 0.7 s → el último volumen sigue siendo `≈ volumen_usuario` (la rampa vieja no lo pisó).
  - `test_volumen_cero_con_atenuacion_es_cero`.
  - `test_relanzamiento_reaplica_el_volumen_efectivo`: `volumen(80)`, `atenuar(0.5, 0)`, `mpv.generacion += 1`, `asegurar()` → `set_property volume ≈ 40.0`.
  - Los tests existentes de `volumen` (que comparan `("set_property", "volume", 100)`) siguen pasando: `100.0 == 100`.
- [ ] **Step 2:** `.venv/bin/pytest tests/test_reproductor.py -q -k "atenuar or volumen"` → FAIL (los nuevos).
- [ ] **Step 3:** Implementar. `self._factor: float = 1.0`; método privado `_aplicar_volumen()` que calcula `self._volumen * self._factor` (si `_volumen` es `None`, no hace nada); `volumen()` y `_asegurar()` lo usan. Rampa: hilo daemon con un contador de generación para cancelarla.
- [ ] **Step 4:** Suite completa → PASS.
- [ ] **Step 5:** Commit `Reproductor: música bajada con rampa (atenuar)`.

---

### Task 4: El Locutor y el clip de prueba

**Files:** Create `src/cassette_fm/clips.py`, `src/cassette_fm/locutor.py`, `tests/test_clips.py`, `tests/test_locutor.py`; Modify `tests/conftest.py` (fixture `crear_wav`)

**Interfaces:**
- Consumes: `Intervencion`, `RegistroIntervenciones` (Task 2), `ConfigDJ` (Task 1), `Reproductor.atenuar` (Task 3, se inyecta como `musica`), `ClienteMpv` (`comando`, `al_evento`, `cerrar`), `Pista` (`ruta`).
- Produces:

```python
# clips.py
def generar_clip_de_prueba(ruta: Path, segundos: float = 8.0) -> Path
    # WAV mono 16-bit 22050 Hz: 3 ráfagas de tono (400, 500, 600 Hz) con envolvente suave y silencios entre ellas,
    # para que se note la entrada a mitad de frase. Crea los directorios padre. Devuelve `ruta`.

# locutor.py
class Locutor:
    hablando: bool   # propiedad
    def __init__(self, voz, musica, registro: RegistroIntervenciones,
                 configuracion: Callable[[str], ConfigDJ], reloj: Callable[[], float] = time.time): ...
        # `voz`: objeto con comando(*args, **nombrados), al_evento (atributo asignable) y cerrar().
        # `musica`: objeto con atenuar(factor: float, segundos: float).
    def registrar(self, i: Intervencion) -> None
        # ValueError si i.duracion > configuracion(i.estacion).duracion_maxima_segundos. Agrega al registro
        # (ValueError si se superpone). Si la estación está sintonizada y su ventana está activa, habla ya.
    def al_sintonizar(self, estacion: str) -> None
        # Corta la voz en curso, vacía el conjunto de "ya reproducidas" y, si la estación tiene una ventana activa
        # ahora, habla desde el segundo que corresponde.
    def pista_iniciada(self, pista: Pista, estacion: str) -> None
        # Anclaje al inicio real del tema: si la estación es la sintonizada, hay una intervención de esa estación
        # con pista_destino == str(pista.ruta), no reproducida en esta sintonía, y
        # abs(ahora - (inicio - retraso_voz_segundos)) <= tolerancia_desfase_segundos, habla desde 0
        # pasados retraso_voz_segundos.
    def volumen(self, valor: int) -> None   # volumen del usuario (0..100): se aplica a la voz
    def detener(self) -> None               # corta la voz, cancela temporizadores, restaura la música; olvida la sintonía
    def cerrar(self) -> None                # detener() + voz.cerrar()
```

Comportamiento que fija el plan:
- `hablar(i, desde)`: si `i.duracion - desde < minimo_restante_segundos`, no hace nada. Si no: `musica.atenuar(nivel_musica_con_voz, rampa_bajada_segundos)`; fija el volumen de la voz (`set_property volume <volumen del usuario>` si se conoce); `voz.comando("loadfile", url=str(i.audio), flags="replace", options={"start": f"{desde:.3f}"})`; marca la intervención como reproducida en esta sintonía; arma un temporizador de seguridad a `(i.duracion - desde) + margen_seguridad_voz_segundos`.
- Fin de la voz: evento `end-file` de `voz` (cualquier motivo) o el temporizador de seguridad → `musica.atenuar(1.0, rampa_subida_segundos)` y `hablando = False`. Es idempotente.
- Cualquier excepción al hablar (`ErrorMpv`, archivo ilegible) se registra con `logging` y **restaura la música**; nunca se propaga.
- Todos los métodos públicos usan un mismo `threading.Lock`; las llamadas a `musica`/`voz` pueden hacerse dentro del lock (la voz no llama de vuelta a la radio).
- "Ya reproducida en esta sintonía" se reinicia en cada `al_sintonizar`: si el usuario sale y vuelve a la estación con la ventana aún abierta, **retoma** la frase desde el segundo del reloj.

- [ ] **Step 1: Tests que fallan.**
  - `tests/test_clips.py`: `test_el_clip_de_prueba_dura_lo_pedido_y_tiene_sonido` (`mutagen.File(ruta).info.length ≈ 8` y alguna muestra distinta de cero leída con `wave`); `test_crea_los_directorios_padre`; `test_hay_silencios_entre_rafagas` (hay una corrida de ≥ 0,2 s de muestras ≈ 0).
  - `tests/conftest.py`: fixture `crear_wav(ruta, segundos=4.0)` que delega en `generar_clip_de_prueba`.
  - `tests/test_locutor.py` con `MusicaFalsa` (registra `atenuar(factor, segundos)`), `VozFalsa` (registra `comando(...)`, guarda `al_evento`, permite simular `end-file`, puede configurarse para lanzar `ErrorMpv`), un reloj falso mutable, `ConfigDJ(retraso_voz_segundos=0.05, rampa_bajada_segundos=0.01, rampa_subida_segundos=0.01, minimo_restante_segundos=1.5, nivel_musica_con_voz=0.35, duracion_maxima_segundos=15, tolerancia_desfase_segundos=60)` y clips reales de `crear_wav`:
    - `test_registrar_con_la_ventana_activa_habla_desde_el_segundo_que_corresponde`: estación sintonizada (`al_sintonizar("E")`), intervención con `inicio = ahora - 3`, `duracion = 10` → `loadfile` con `options["start"] ≈ "3.000"`, `url == str(audio)`, y `musica.atenuar(0.35, 0.01)`.
    - `test_no_habla_si_quedan_menos_del_minimo`: `duracion - desde = 1.0` → sin `loadfile` ni `atenuar` (Review Focus 5).
    - `test_ventana_futura_no_habla_todavia` y `test_ventana_pasada_no_habla`.
    - `test_registrar_rechaza_un_clip_demasiado_largo`: `duracion = 20` con máximo 15 → `ValueError`, y no queda en el registro.
    - `test_la_voz_se_ancla_al_inicio_real_del_tema`: intervención con `pista_destino = "/m/t.mp3"`, `inicio = ahora + 20`; `pista_iniciada(Pista("/m/t.mp3"…), "E")` → pasado `retraso` (~0,05 s) `loadfile` con `start ≈ "0.000"`.
    - `test_pista_iniciada_ignora_otro_tema_otra_estacion_o_fuera_de_tolerancia`: ruta distinta; estación distinta de la sintonizada; `inicio = ahora + 300` (fuera de los 60 s) → nada suena.
    - `test_no_suena_dos_veces_en_la_misma_sintonia` (Review Focus 5): sintonizar con la ventana ya activa (habla desde el reloj) y luego llegar `pista_iniciada` del tema destino → un solo `loadfile`; sintonizar a 0,3 s del inicio del tema destino (ventana todavía no empezada) y llegar `pista_iniciada` → habla por el anclaje, una vez.
    - `test_volver_a_la_estacion_dentro_de_la_ventana_retoma_la_frase`: `al_sintonizar("E")`, `detener()`, avanzar el reloj 2 s, `al_sintonizar("E")` → segundo `loadfile` con `start` mayor que el primero.
    - `test_detener_corta_la_voz_y_restaura_la_musica` (Review Focus 1): durante la voz, `detener()` → `voz.comando("stop")` y `musica.atenuar(1.0, 0.01)`; `hablando` pasa a `False`.
    - `test_al_sintonizar_otra_estacion_corta_la_voz_en_curso`.
    - `test_el_fin_del_clip_restaura_la_musica`: simular `end-file` → `atenuar(1.0, 0.01)` y `hablando == False`; un segundo `end-file` no repite la llamada.
    - `test_si_no_llega_el_evento_el_temporizador_de_seguridad_restaura`: con `minimo_restante_segundos=0.1`, `margen_seguridad_voz_segundos=0.1`, una intervención de `duracion = 0.5` hablada desde 0 y sin enviar `end-file`, en ≤ 1,5 s la música se restaura (`atenuar(1.0, …)`).
    - `test_error_al_cargar_el_clip_restaura_la_musica_y_no_propaga` (Review Focus 3): `VozFalsa` lanza `ErrorMpv` en `loadfile` → `atenuar(1.0, …)` y sin excepción.
    - `test_el_volumen_del_usuario_se_aplica_a_la_voz` (Review Focus 2): `volumen(40)` y luego hablar → `set_property volume 40` en la voz antes del `loadfile`; con `volumen(0)` no se habla.
  - `test_integracion_la_voz_entra_a_mitad_de_frase` (mpv real con `--ao=null` como `voz`, `MusicaFalsa`): clip real de 4 s, intervención con `inicio = ahora - 1` → `get_property time-pos` de la voz `≥ 1.0` poco después, y en ≤ 6 s `musica` recibió `atenuar(1.0, …)` por el fin del clip.
- [ ] **Step 2:** `.venv/bin/pytest tests/test_clips.py tests/test_locutor.py -q` → FAIL.
- [ ] **Step 3:** Implementar `clips.py` y `locutor.py`.
- [ ] **Step 4:** Suite completa → PASS; repetir `tests/test_locutor.py` 5 veces seguidas sin fallos (hay temporizadores).
- [ ] **Step 5:** Commit `Locutor: voz en un segundo mpv, anclada al inicio real del tema, con la música bajada`.

---

### Task 5: Integración en la Radio y el servicio

**Files:** Modify `src/cassette_fm/radio.py`, `src/cassette_fm/servicio.py`, `tests/test_radio.py`, `tests/test_servicio.py`

**Interfaces:**
- Consumes: `Locutor` (Task 4), `desfase`/`transiciones` (Task 2), `ConfigDJ`/`configuracion_dj`/`Rutas.intervenciones`/`.clips` (Task 1), `generar_clip_de_prueba` (Task 4).
- Produces:

```python
class DJInactivo(Exception): ...        # el DJ está apagado en la configuración
class RadioApagada(Exception): ...      # no hay estación sintonizada para probar

# Radio.__init__ gana (al final, con default): dj: Locutor | None = None,
#   configuracion_dj: Callable[[str], ConfigDJ] | None = None, dir_clips: Path | None = None
Radio.dj_estado(self) -> dict
    # {"activo": bool, "hablando": bool, "desfase_segundos": float | None,
    #  "intervenciones": [{"estacion","inicio","duracion","texto"}, ...]}   # las vigentes, por inicio
Radio.dj_probar(self, audio: Path | None = None, en_segundos: float = 20.0) -> dict
    # Registra una intervención de prueba en la próxima transición de la estación sintonizada que cumpla
    # `inicio >= ahora + en_segundos`. Devuelve {"estacion","inicio","duracion","pista_destino","en_segundos"}.
    # DJInactivo si dj es None; RadioApagada si no hay estación sintonizada;
    # ValueError (mensaje claro) si el audio no existe, no se puede leer, o dura más que duracion_maxima_segundos.
```

Comportamiento que fija el plan:
- `Radio._sintonizar` (después de que `reproductor.sintonizar` salió bien) llama `dj.al_sintonizar(nombre)`. `_apagar` llama `dj.detener()`. `Radio.volumen` llama `dj.volumen(<volumen resultante>)` (también cuando el resultado es 0). Con `dj=None` nada de esto hace nada y no falla.
- `_al_cambiar_pista(pista, estacion)` (el callback `file-loaded` que ya existe) además llama `dj.pista_iniciada(pista, estacion.nombre)` y **mide el desfase**: `agenda.desfase(estacion, pista, ahora)`; guarda el último valor en `self._desfase`, y si `abs(valor) > desfase_aviso_segundos` lo registra como advertencia en el log. El **primer** `file-loaded` tras sintonizar (el tema en el que se entró, a mitad de camino) no se mide.
- `dj_probar` copia el clip (el dado o uno generado con `generar_clip_de_prueba`) a `dir_clips/<uuid>.wav`, calcula `duracion` con `mutagen`, recorre `transiciones(...)` saltando las que se superponen con una intervención ya registrada de esa estación (hasta 20 candidatas; si ninguna, `ValueError`), y llama `dj.registrar(...)` con `inicio = inicio_del_tema + retraso_voz_segundos`, `texto = "(clip de prueba)"`.
- `servicio.servir`: con `config.dj.activo`, crea `ClienteMpv(rutas.runtime / "voz.sock", extra_args=extra_args_mpv)` (sin `--af`), `RegistroIntervenciones(rutas.intervenciones, rutas.clips)`, `Locutor(voz, reproductor, registro, lambda n: configuracion_dj(config, n))` y construye la `Radio` con `dj=locutor`, `configuracion_dj=lambda n: configuracion_dj(config, n)` y `dir_clips=rutas.clips`; al apagar: `locutor.cerrar()`. Con `activo = false` no se crea nada de eso.

- [ ] **Step 1: Tests que fallan.**
  - `tests/test_radio.py` con un `LocutorFalso` (registra `al_sintonizar`, `detener`, `volumen`, `pista_iniciada`, `registrar`; propiedad `hablando`) y `crear(..., dj=...)`:
    - `test_sintonizar_avisa_al_locutor_despues_del_reproductor`, `test_apagar_detiene_al_locutor`, `test_el_volumen_llega_al_locutor_incluso_en_cero`, `test_pista_iniciada_llega_al_locutor_con_el_nombre_de_la_estacion`.
    - `test_sin_locutor_todo_sigue_andando` (`dj=None`).
    - `test_el_desfase_se_mide_menos_en_el_primer_tema_de_la_sintonia`: simular dos `file-loaded` seguidos con estaciones de la agenda → `dj_estado()["desfase_segundos"]` es `None` tras el primero y un número tras el segundo; con un desfase mayor que `desfase_aviso_segundos`, `caplog` registra una advertencia.
    - `test_dj_probar_sin_dj_da_DJInactivo`, `test_dj_probar_con_la_radio_apagada_da_RadioApagada`.
    - `test_dj_probar_registra_en_la_proxima_transicion_con_margen`: el `Intervencion` pasado a `registrar` tiene `inicio >= ahora + en_segundos`, `inicio == inicio_del_tema + retraso`, `pista_destino` igual a la ruta del tema, `duracion` ≈ la del clip y `audio` dentro de `dir_clips`.
    - `test_dj_probar_salta_huecos_ocupados`: con una intervención ya registrada en la primera candidata, usa la siguiente.
    - `test_dj_probar_rechaza_audio_inexistente_o_demasiado_largo` (`ValueError`).
    - `test_dj_estado_lista_las_intervenciones_vigentes`.
  - `tests/test_servicio.py`: `test_con_el_dj_apagado_no_se_crea_nada` (tras `servir` con `activo=false`: no existe `intervenciones.json` ni un proceso mpv de `voz.sock`); `test_con_el_dj_activo_arranca_y_cierra_limpio` (`activo=true`, `parar.set()` → el hilo termina en ≤ 3 s, sin mpv colgado de `voz.sock`).
- [ ] **Step 2:** `.venv/bin/pytest tests/test_radio.py tests/test_servicio.py -q` → FAIL (los nuevos).
- [ ] **Step 3:** Implementar en `radio.py` y `servicio.py`.
- [ ] **Step 4:** Suite completa → PASS.
- [ ] **Step 5:** Commit `Radio y servicio: integración de la capa de intervenciones`.

---

### Task 6: API, comando `cassette dj` y prueba de punta a punta

**Files:** Modify `src/cassette_fm/api.py`, `src/cassette_fm/cli.py`, `README.md`, `tests/test_api.py`, `tests/test_cli.py`, `tests/test_servicio.py`

**Interfaces:**
- Consumes: `Radio.dj_estado`, `Radio.dj_probar`, `DJInactivo`, `RadioApagada` (Task 5).
- Produces:

| Método y ruta | Cuerpo | 200 devuelve |
|---|---|---|
| `GET /dj` | — | `radio.dj_estado()` |
| `POST /dj/probar` | `{"audio": str?, "en_segundos": number?}` (ambos opcionales) | `radio.dj_probar(...)` |

Errores: `DJInactivo` → 409 con "El DJ está apagado: poné `activo = true` en la sección `[dj]` de config.toml y reiniciá el servicio"; `RadioApagada` → 409 "No hay una estación sintonizada: encendé la radio primero"; `ValueError` de `dj_probar` → 400 con su mensaje; `audio`/`en_segundos` con tipo inválido → 400. `GET /dj` con el DJ apagado devuelve 200 con `{"activo": false, ...}` (no es un error).

CLI (mismo `--puerto` y mismos errores que el resto): `cassette dj estado` imprime `DJ apagado` o `DJ activo · habla: no · desfase: 0.4 s` seguido de una línea por intervención (`  Lentos · en 312 s · 9.8 s · (clip de prueba)`); `cassette dj probar [--audio RUTA] [--en SEGUNDOS]` imprime `El DJ va a hablar en N s, justo después de que arranque «<tema>» en <estación>.` (RUTA se manda como ruta absoluta).

- [ ] **Step 1: Tests que fallan.**
  - `tests/test_api.py` (con `RadioFalsa` ampliada): `test_get_dj`, `test_post_dj_probar_pasa_audio_y_en_segundos`, `test_post_dj_probar_sin_cuerpo_usa_los_valores_por_defecto`, `test_dj_inactivo_409`, `test_radio_apagada_409`, `test_dj_probar_valueerror_400`, `test_dj_probar_tipos_invalidos_400` (`{"en_segundos": "x"}`, `{"audio": 5}`).
  - `tests/test_cli.py`: `test_dj_estado_apagado`, `test_dj_estado_con_intervenciones`, `test_dj_probar_imprime_cuando_hablara`, `test_dj_probar_con_audio_manda_ruta_absoluta`, `test_dj_probar_error_de_la_api_da_codigo_1`.
  - `tests/test_servicio.py::test_dj_de_punta_a_punta` (mpv real con `--ao=null`, estación de 3 mp3 de 3 s, `ConfigDJ(activo=True, retraso_voz_segundos=0.1, rampa_bajada_segundos=0.05, rampa_subida_segundos=0.05)`): `POST /encender`, `POST /dj/probar {"en_segundos": 1}` → 200; `GET /dj` lista la intervención; en ≤ 10 s `GET /dj` informa `hablando: true` alguna vez y después vuelve a `false`; `POST /apagar` y `parar.set()` terminan limpios.
- [ ] **Step 2:** `.venv/bin/pytest tests/test_api.py tests/test_cli.py tests/test_servicio.py -q` → FAIL (los nuevos).
- [ ] **Step 3:** Implementar rutas en `api.py` y el subcomando anidado `dj` en `cli.py` (`estado`, `probar`).
- [ ] **Step 4:** Suite completa → PASS; repetir `test_dj_de_punta_a_punta` 5 veces seguidas sin fallos.
- [ ] **Step 5:** README: sección "DJ (en desarrollo)": que viene apagado; cómo activarlo (`[dj] activo = true` en `config.toml` y `systemctl --user restart cassette-fm`); `cassette dj probar` y `cassette dj estado`; la tabla de parámetros con sus valores por defecto; y la verificación con audio real, **para que la haga el usuario**: sintonizar una estación, `cassette dj probar --en 20`, y comprobar que (a) la voz entra ~1 s después del tema siguiente con la música bajada, (b) sintonizar otra estación y volver con la ventana abierta retoma la frase, (c) bajar el volumen a 0 la corta, (d) `cassette dj estado` informa el desfase.
- [ ] **Step 6:** Commit `API y comando cassette dj: probar y ver las intervenciones`. Cerrar el bean `CASSETTE-FM-hnhf`.
