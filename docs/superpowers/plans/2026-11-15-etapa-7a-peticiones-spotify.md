# Etapa 7a — Peticiones del público por la cola de Spotify — plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** que un tema encolado desde la app de Spotify mientras suena una emisora de Spotify sea una petición: el DJ
la anuncia (antes si hay tiempo, si no después) y la agenda de la emisora se corre sin perder temas.

**Architecture:** la agenda (`agenda.py`) aprende de pedidos: `Estacion` lleva `corrimiento` y `pedidos` en curso, y
`secuencia` los respeta. El reproductor de Spotify detecta los pedidos (URIs vistas en la cola), actualiza su
estación y avisa a la radio (`al_cambiar_agenda`, `al_encolado`); la radio guarda los pedidos en el estado y avisa al
planificador, que pide al servicio DJ un anuncio de petición (`"peticion": "antes" | "despues"`) que sobrevive a los
cambios de agenda que el mismo pedido provoca.

**Tech Stack:** Python 3.12, pytest. Sin dependencias nuevas.

**Spec:** `docs/superpowers/specs/2026-11-15-peticiones-spotify-design.md`

## Global Constraints

- Un pedido es lo que vino de la cola (`queue_changed` con `source == "queue"`), aunque el tema sea de la playlist de
  la emisora o justo el siguiente de la agenda. Un tema ajeno que no vino de la cola no toca la agenda.
- Sin pedidos ni corrimiento, la agenda da exactamente lo mismo que hoy (los tests actuales de `test_agenda.py` no
  se tocan).
- Al terminar un pedido con un evento, se pliega con su duración real (inicio del tema siguiente − inicio del pedido);
  sin evento (radio apagada o en otra emisora), con la nominal cuando vence por la agenda.
- Volver a una emisora a mitad de un pedido retoma el pedido en el segundo justo.
- Anuncio: «antes» si faltan al menos `peticion_margen_segundos` (default 30, en `ConfigDJ`) para que termine el tema
  actual; si no, o si la «antes» no está lista cuando empieza el pedido, «después».
- Las intervenciones de petición no se descartan por cambios de agenda, ni borran la última intervención.
- La firma de agenda del planificador = pistas + corrimiento total (pedidos en curso por su duración nominal); un
  cambio del total de hasta 2 s no cuenta como cambio de agenda.
- Tokens nunca en logs; no leer `~/.config/cassette-fm/soloist.key` ni `~/.local/state/cassette-fm/spotify-token.json`.
- No reiniciar servicios ni hacer sonar nada sin el OK del usuario.
- Commits en español, imperativo llano, terminando en `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

- Pedido salteado desde la app a los pocos segundos: el tema siguiente de la agenda no re-sintoniza y la agenda queda
  corrida solo lo que sonó el pedido (test en Task 6).
- Dos pedidos encolados seguidos: se encadenan, cada uno con su anuncio si entra, y el corrimiento suma las dos
  duraciones reales (tests en Tasks 1, 4 y 6).
- Reinicio de la radio a mitad de un pedido: al volver sintoniza el pedido en el segundo justo, y si ya terminó, la
  agenda sigue corrida (tests en Tasks 2 y 6).
- Rescan con pedidos guardados de una emisora que ya no existe o cambió de playlist: no rompe el arranque ni el rescan
  (test en Task 2).
- La metadata de `/tracks/{id}` falla o tarda: el pedido igual cuenta para la agenda; el anuncio usa lo que hay o no
  se hace, sin trabar la radio (test en Task 6).

---

### Task 1: La agenda con pedidos

**Files:**
- Modify: `src/cassette_fm/biblioteca.py` (`Estacion`), `src/cassette_fm/agenda.py`
- Test: `tests/test_agenda.py`

**Interfaces:**
- Produces: `@dataclass(frozen=True) class Pedido: pista: Pista; inicio: float` (en `biblioteca.py`, junto a
  `Estacion`, para no crear un import circular) y `Estacion.corrimiento: float = 0.0`,
  `Estacion.pedidos: tuple[Pedido, ...] = ()`.
- Produces en `agenda.py`:
  - `secuencia(estacion, instante)` respeta pedidos y corrimiento (ver abajo). `transiciones` y `desfase` heredan.
  - `con_pedido(estacion: Estacion, pista: Pista, inicio: float) -> Estacion`: pliega con duración real los pedidos
    que empezaron antes de `inicio` (real = inicio del siguiente pedido o `inicio` − su inicio, con tope en su
    duración nominal) y agrega el nuevo.
  - `plegar(estacion: Estacion, hasta: float) -> Estacion`: un tema de la agenda empezó en `hasta`: pliega con
    duración real todos los pedidos con `inicio < hasta`.
  - `plegar_vencidos(estacion: Estacion, ahora: float) -> Estacion`: pliega con duración nominal los pedidos cuyo
    `inicio + duracion <= ahora`.
  - `corrimiento_total(estacion: Estacion) -> float`: `corrimiento + suma de duraciones nominales de los pedidos`.
- Algoritmo de `secuencia` con pedidos (los pedidos están en orden y no se superponen): sea `t` el instante; si cae
  dentro de un pedido `p`, se da `(p.pista, t - p.inicio)`, después los pedidos que siguen pegados a él, y después la
  agenda base desde el instante base del borde. El instante base de un `x` fuera de pedidos es
  `x - corrimiento - suma(duración de los pedidos con inicio + duracion <= x)`. Si `t` está antes de un pedido
  futuro, la agenda base se recorre hasta el inicio del pedido y en ese borde se intercala (el tema de la agenda que
  esté sonando en `p.inicio` se corta: no pasa en la práctica porque los pedidos empiezan en un borde).

- [ ] **Step 1: tests**

```python
def test_sin_pedidos_ni_corrimiento_da_lo_mismo_que_antes(): ...   # misma secuencia que Estacion sin campos nuevos
def test_corrimiento_atrasa_la_agenda():                            # secuencia(e(corrimiento=30), t) == secuencia(e, t-30)
def test_durante_un_pedido_suena_el_pedido_desde_su_segundo(): ...  # (pedido, 42.0) a 42 s de su inicio
def test_despues_del_pedido_sigue_donde_estaba(): ...               # el tema que tocaba en p.inicio, desde 0
def test_volver_a_mitad_del_pedido_lo_retoma(): ...                 # secuencia en p.inicio+100 → (pedido, 100.0)
def test_dos_pedidos_seguidos_se_encadenan(): ...                   # p1, p2, y después la agenda
def test_con_pedido_pliega_el_anterior_con_su_duracion_real(): ...  # p1 cortado a 20 s → corrimiento += 20
def test_plegar_usa_la_duracion_real(): ...                         # pedido salteado a 10 s → corrimiento 10
def test_plegar_vencidos_usa_la_nominal(): ...
def test_desfase_del_tema_que_sigue_al_pedido_es_cero(): ...
def test_transiciones_incluyen_el_pedido(): ...                     # (pedido, inicio) y (siguiente, inicio+dur)
def test_corrimiento_total_cuenta_los_pedidos_en_curso(): ...
```

- [ ] **Step 2:** `.venv/bin/pytest tests/test_agenda.py -q` → Expected: los nuevos FAIL (`Pedido` no existe).
- [ ] **Step 3:** implementar.
- [ ] **Step 4:** `.venv/bin/pytest tests/test_agenda.py tests/test_planificacion.py -q` → Expected: PASS.
- [ ] **Step 5: Commit** («La agenda respeta pedidos en curso y un corrimiento por emisora»).

### Task 2: Pedidos guardados y la radio que los aplica

**Files:**
- Modify: `src/cassette_fm/config.py` (`Estado`, `cargar_estado`), `src/cassette_fm/radio.py`,
  `src/cassette_fm/reproductores.py`
- Test: `tests/test_config.py`, `tests/test_radio.py`, `tests/test_reproductores.py`

**Interfaces:**
- Consumes: Task 1.
- Produces:
  - `Estado.agendas: dict[str, dict] = field(default_factory=dict)` — por emisora `{"corrimiento": float,
    "pedidos": [{"inicio": float, "uri", "duracion", "titulo", "artista", "cancion", "album", "isrc"}]}`;
    `cargar_estado` lo lee tolerando basura (una emisora con datos inválidos se ignora).
  - `aplicar_agendas(estaciones: list[Estacion], agendas: dict, ahora: float) -> list[Estacion]` (en `radio.py`):
    por nombre, pone corrimiento y pedidos, y `plegar_vencidos`. Las emisoras sin datos quedan igual; datos de una
    emisora que no está se conservan en el estado (por si vuelve) pero no se aplican.
  - `Radio` aplica las agendas guardadas al crearse y en cada `rescan`.
  - `Radio._al_cambiar_agenda(estacion: Estacion, nuevo: Pedido | None) -> None`: reemplaza la emisora por nombre en
    su lista, guarda `estado.agendas[nombre]`, y llama `planificador.al_cambiar_agenda(estacion, nuevo)` (fuera del
    lock, como `al_rescan`). Se engancha como `reproductor.al_cambiar_agenda`.
  - `Radio._al_encolado(pista: Pista, estacion: Estacion, fin_actual: float)`: pasa a
    `planificador.al_encolado(pista, estacion, fin_actual)` si hay planificador. Se engancha como
    `reproductor.al_encolado`.
  - Antes de sintonizar, la radio hace `plegar_vencidos` de la emisora (y lo guarda) para que la lista que se manda
    empiece donde corresponde.
  - `Reproductores` reenvía `al_cambiar_agenda` y `al_encolado` del reproductor de Spotify (los atributos se
    propagan como `al_cambiar_pista`).

- [ ] **Step 1: tests**

```python
# test_config.py
def test_estado_guarda_y_lee_agendas(tmp_path): ...
def test_agendas_con_basura_se_ignoran(tmp_path): ...       # una emisora inválida no tira el estado entero
# test_radio.py
def test_al_crear_aplica_las_agendas_guardadas(): ...
def test_rescan_conserva_los_pedidos(): ...
def test_agendas_de_una_emisora_que_no_esta_no_rompen(): ...
def test_al_cambiar_agenda_reemplaza_guarda_y_avisa(): ...  # planificador falso registra (nombre, nuevo)
def test_al_sintonizar_pliega_los_pedidos_vencidos(): ...
def test_reinicio_a_mitad_del_pedido_lo_retoma(): ...       # estado con pedido en curso → la estación sintonizada
                                                            # tiene el pedido; secuencia da (pedido, segundo justo)
# test_reproductores.py
def test_reenvia_al_cambiar_agenda_y_al_encolado(): ...
```

- [ ] **Step 2:** correr → Expected: FAIL.
- [ ] **Step 3:** implementar.
- [ ] **Step 4:** `.venv/bin/pytest tests/test_config.py tests/test_radio.py tests/test_reproductores.py -q` → PASS.
- [ ] **Step 5: Commit** («La radio guarda los pedidos de cada emisora y los aplica al arrancar y en el rescan»).

### Task 3: El servicio DJ sabe de peticiones

**Files:**
- Modify: `src/cassette_fm/dj/pedido.py`, `src/cassette_fm/dj/plantillas.py`, `src/cassette_fm/dj/redactor_llm.py`
- Test: `tests/dj/test_pedido.py`, `tests/dj/test_plantillas.py`, `tests/dj/test_redactor_llm.py`

**Interfaces:**
- Produces: `Pedido.peticion: str | None = None` (`"antes"` o `"despues"`); `leer_pedido` lo valida («campo
  'peticion': tiene que ser antes o despues»; `"despues"` exige `anterior`: «campo 'anterior': falta (peticion
  despues)»).
- Plantillas: una oración fija que nunca se descarta, delante de todo:
  - `antes`: es `["Llega una petición especial del público.", "Tenemos una petición especial para ustedes."]`,
    en `["Here comes a special request from a listener.", "We have a special request for you."]`.
  - `despues`: reemplaza a la de «anterior»: es `["Eso fue una petición especial: {titulo_ant} de {artista_ant}."]`,
    en `["That was a special request: {titulo_ant} by {artista_ant}."]`; el ingrediente «anterior» no se usa.
- LLM: en el prompt, una línea: antes → es «Este tema es una petición especial del público: presentalo como tal.» /
  en «This song is a special request from a listener: introduce it as such.»; después → es «El tema anterior fue una
  petición especial del público: mencionalo y presentá el siguiente.» / en «The previous song was a special request
  from a listener: mention it and introduce the next one.» En `despues` el tema anterior va siempre en los datos.

- [ ] **Step 1: tests**

```python
def test_peticion_valida_y_opcional(): ...                 # None, "antes", "despues"(con anterior)
def test_peticion_invalida_da_error(): ...                 # "x" y "despues" sin anterior
def test_plantilla_antes_empieza_con_la_peticion(): ...    # para varias semillas y es/en
def test_plantilla_despues_nombra_el_tema_pedido(): ...
def test_plantilla_peticion_entra_aunque_falten_palabras(): ...  # palabras_maximas chico: la oración fija queda
def test_prompt_llm_marca_la_peticion(): ...               # antes y después, es y en
```

- [ ] **Step 2:** `.venv/bin/pytest tests/dj -q` → Expected: los nuevos FAIL.
- [ ] **Step 3:** implementar.
- [ ] **Step 4:** `.venv/bin/pytest tests/dj -q` → PASS.
- [ ] **Step 5: Commit** («El DJ anuncia peticiones especiales, antes o después del tema pedido»).

### Task 4: El planificador pide los anuncios y los protege

**Files:**
- Modify: `src/cassette_fm/config.py` (`ConfigDJ.peticion_margen_segundos: float = 30.0`, positivo),
  `src/cassette_fm/intervenciones.py`, `src/cassette_fm/locutor.py`, `src/cassette_fm/planificacion.py`,
  `src/cassette_fm/planificador.py`
- Test: `tests/test_config.py`, `tests/test_intervenciones.py`, `tests/test_locutor.py`, `tests/test_planificacion.py`,
  `tests/test_planificador.py`

**Interfaces:**
- Consumes: Task 1 (`corrimiento_total`, `transiciones`), Task 3 (`"peticion"` en el pedido).
- Produces:
  - `Intervencion.peticion: str | None = None` (persistido; un JSON viejo sin el campo carga con None).
  - `RegistroIntervenciones.quitar_estacion(estacion, salvo_peticiones: bool = False)`.
  - `Locutor.descartar_estacion(estacion)` conserva las de petición: no las quita del registro, no cancela su anclaje
    ni corta su voz.
  - `armar_pedido(..., peticion: str | None = None)` agrega `"peticion"`.
  - `_firma` → (sha de pistas, `corrimiento_total`); cambio de agenda = sha distinto o total que difiere más de 2 s.
    Firmas viejas guardadas como texto se leen como (sha, 0.0).
  - `_descartar(nombre)` no borra la última intervención si vino de una petición, no cancela un trabajo de petición,
    y llama `descartar_estacion` (que ya conserva las de petición).
  - `Planificador.al_cambiar_agenda(estacion: Estacion, nuevo: Pedido | None)`: si es la sintonizada, la reemplaza;
    compara firma (→ `_descartar` si cambió). Si `nuevo` y no hay intervención «antes» registrada para
    `nuevo.pista.clave`, cancela el trabajo «antes» de ese pedido si está en curso y deja pendiente la «después».
  - `Planificador.al_encolado(pista: Pista, estacion: Estacion, fin_actual: float)`: si es la sintonizada y faltan
    `>= peticion_margen_segundos` hasta `fin_actual`, deja pendiente la «antes» (hueco: `pista` destino,
    `inicio_tema = fin_actual`, anterior = el tema actual de la agenda); si no, marca que ese pedido irá «después».
  - Una petición pendiente tiene prioridad en `paso()`: si hay un trabajo normal en curso de esa emisora, se cancela;
    se envía sin `margen_minutos` ni frecuencia. La «después» usa el hueco del tema que sigue al pedido en la agenda
    (que ya tiene el pedido) con `anterior` = el pedido. Pista sin artista y título → no se anuncia.
  - Al registrar una petición, `Ultima` se actualiza como cualquier otra y se recuerda que vino de una petición.

- [ ] **Step 1: tests**

```python
def test_intervencion_vieja_sin_peticion_carga(tmp_path): ...
def test_quitar_estacion_salvo_peticiones(tmp_path): ...
def test_locutor_no_corta_ni_desancla_una_peticion_al_descartar(): ...
def test_armar_pedido_con_peticion(): ...
def test_firma_tolera_dos_segundos_de_corrimiento(): ...         # plegar con real≈nominal no descarta
def test_empezar_un_pedido_descarta_las_normales_y_no_la_peticion(): ...
def test_encolado_con_tiempo_pide_la_antes(): ...               # cliente falso: pedido con "peticion": "antes",
                                                                 # siguiente = el pedido
def test_encolado_sobre_el_final_va_despues(): ...              # fin_actual - ahora < 30 → al empezar el pedido se
                                                                 # pide "despues" con anterior = el pedido
def test_antes_no_lista_al_empezar_pasa_a_despues(): ...        # trabajo antes cancelado, se pide la después
def test_peticion_desplaza_un_trabajo_normal_en_curso(): ...
def test_dos_pedidos_seguidos_cada_uno_con_su_anuncio(): ...
def test_peticion_no_borra_la_ultima(): ...
def test_encolado_en_otra_emisora_o_sin_dj_no_hace_nada(): ...
def test_peticion_margen_se_lee_del_toml(): ...
```

- [ ] **Step 2:** correr → Expected: FAIL.
- [ ] **Step 3:** implementar.
- [ ] **Step 4:** `.venv/bin/pytest tests -q` → Expected: suite completa PASS.
- [ ] **Step 5: Commit** («El planificador pide el anuncio de cada petición y lo protege de los cambios de agenda»).

### Task 5: Capturar los eventos reales de Soloist al encolar (con el usuario)

**Files:**
- Create: `scripts/capturar-cola-soloist.py` (escucha el WebSocket de Soloist, `ws://127.0.0.1:9787`, y escribe
  cada evento JSON en una línea; solo lectura: no manda comandos)
- Create: `tests/spotify/eventos_cola.jsonl` (los eventos capturados que hacen falta, recortados a los campos que se
  usan; sin tokens)

- [ ] **Step 1:** pedirle al usuario que deje sonando una emisora de Spotify (puede ser con volumen bajo), correr el
  script y que encole dos temas desde la app: uno con tiempo, y después saltear el primero a los pocos segundos.
- [ ] **Step 2:** revisar la captura: forma de `queue_changed` (`upcoming[*].source`, `item.uri`, duración) y de
  `track_changed` del pedido (¿trae origen? ¿posición?). Anotar en el ledger cualquier diferencia con el diseño como
  Ruling y ajustar las Interfaces de Task 6.
- [ ] **Step 3: Commit** («Script y captura de los eventos de Soloist al encolar temas»).

### Task 6: El reproductor de Spotify detecta los pedidos

**Files:**
- Modify: `src/cassette_fm/spotify/control.py`, `src/cassette_fm/reproductor_spotify.py`
- Test: `tests/spotify/test_control.py`, `tests/test_reproductor_spotify.py`

**Interfaces:**
- Consumes: Tasks 1, 2 y 5.
- Produces:
  - `ControlSpotify.pista(uri: str) -> Pista | None`: `GET /tracks/{id}?market=from_token`, convertido con
    `pista_de({"item": datos})`; None si falla (sin lanzar).
  - `ReproductorSpotify.al_cambiar_agenda: Callable[[Estacion, Pedido | None], None] | None` y
    `al_encolado: Callable[[Pista, Estacion, float], None] | None`.
  - `queue_changed`: las URIs con `source == "queue"` se recuerdan (`_encolados`); si la primera de `upcoming` es
    nueva y de la cola, se busca su metadata en segundo plano (`en_segundo_plano`, con caché por URI) y se llama
    `al_encolado(pista, estacion, fin_actual)` con `fin_actual = reloj + duración del tema actual − posición`.
  - `track_changed` de una URI encolada → pedido: `self._estacion = con_pedido(...)` (con la pista con metadata si ya
    está), `al_cambiar_agenda(estacion, pedido)`, sin re-sintonía, y la URI sale de `_encolados`.
  - `track_changed` de la URI de un pedido en curso de la estación (la radio volvió a mitad del pedido): no es pedido
    nuevo ni desfase.
  - `track_changed` de un tema de la agenda con pedidos empezados: `self._estacion = plegar(...)` **antes** de
    medir el desfase, y `al_cambiar_agenda(estacion, None)`.
  - `actualizar(estacion: Estacion)`: si es la emisora sonando, la reemplaza (para el rescan con pedidos).

- [ ] **Step 1: tests** (con los eventos de `tests/spotify/eventos_cola.jsonl`)

```python
def test_pista_por_uri_con_la_web_api(servidor_http): ...
def test_pista_por_uri_que_falla_da_none(servidor_http): ...
def test_encolar_avisa_con_metadata_y_fin_del_tema_actual(): ...
def test_tema_encolado_que_empieza_es_un_pedido_sin_resintonia(): ...
def test_encolado_que_es_de_la_playlist_igual_es_pedido(): ...
def test_tema_de_la_agenda_tras_el_pedido_pliega_y_no_resintoniza(): ...
def test_pedido_salteado_pliega_lo_que_sono(): ...
def test_dos_pedidos_seguidos(): ...
def test_volver_a_mitad_del_pedido_no_es_pedido_nuevo(): ...
def test_tema_ajeno_que_no_vino_de_la_cola_no_toca_la_agenda(): ...
def test_metadata_que_falla_igual_cuenta_el_pedido(): ...
```

- [ ] **Step 2:** correr → Expected: FAIL.
- [ ] **Step 3:** implementar.
- [ ] **Step 4:** `.venv/bin/pytest tests -q` → suite completa PASS.
- [ ] **Step 5: Commit** («Spotify: los temas encolados son peticiones; la agenda se corre y el DJ las anuncia»).

### Task 7: Documentación y prueba real (después de la revisión final)

- [ ] README: sección «Peticiones» (encolar desde la app, qué dice el DJ, la agenda se corre, `peticion_margen_segundos`).
  project-context: estado.
- [ ] Con el OK del usuario: reiniciar `cassette-fm` y `cassette-dj`; encolar con tiempo (anuncio antes), encolar sobre
  el final (anuncio después), cambiar de emisora a mitad del pedido y volver (sigue el pedido), saltear el pedido desde
  la app (sin re-sintonía), reiniciar la radio a mitad del pedido (lo retoma).
- [ ] Beans: tarea «Peticiones por la cola de Spotify» completada bajo la épica de la etapa 7.
