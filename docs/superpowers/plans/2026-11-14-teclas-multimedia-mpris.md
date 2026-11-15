# Teclas multimedia (MPRIS) — plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** que la radio se anuncie como reproductor MPRIS para que el botón del JBL y las teclas multimedia cambien de
emisora y la prendan o apaguen.

**Architecture:** un módulo `mpris.py` publica `org.mpris.MediaPlayer2.cassette_fm` en el bus de sesión con
`dbus-fast`, en un loop asyncio en su propio hilo. Los métodos llaman a la `Radio` (en un executor, para no frenar el
loop); la `Radio` avisa cada cambio con un callback `al_cambiar` que solo agenda la emisión de `PropertiesChanged` en
el loop. El servicio lo arma y lo cierra.

**Tech Stack:** Python 3, `dbus-fast`, pytest con un `dbus-daemon` privado por test.

**Spec:** `docs/superpowers/specs/2026-11-14-teclas-multimedia-design.md`

## Global Constraints

- Nombre en el bus: `org.mpris.MediaPlayer2.cassette_fm`; objeto `/org/mpris/MediaPlayer2`; Identity `cassette-fm`.
- Next → `radio.siguiente()`, Previous → `radio.anterior()`, PlayPause → `radio.alternar()`, Play → `radio.encender()`,
  Pause y Stop → `radio.apagar()`.
- `PlaybackStatus`: `"Playing"` con la radio prendida, `"Stopped"` apagada.
- `CanGoNext`, `CanGoPrevious`, `CanPlay`, `CanPause`, `CanControl` = true; `CanSeek`, `CanQuit`, `CanRaise`,
  `HasTrackList` = false. Seek/SetPosition/OpenUri/Raise/Quit no hacen nada.
- Sin bus de sesión o sin el nombre: la radio anda igual y queda un warning en el log.
- Los tests nunca tocan el bus de sesión real del usuario (aparecería en su applet y le robaría las teclas).
- Commits en español, imperativo llano, terminando en `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

- Una tecla con la radio sin emisoras (`SinEstaciones`) o con Spotify caído: el servicio MPRIS sigue vivo y contesta
  la próxima tecla (test en Task 3).
- `al_cambiar` se llama con el lock de la radio tomado: si hiciera algo bloqueante o tomara el lock desde otro hilo
  esperando, se traba la radio (test en Task 3: `cambio()` no bloquea aunque el loop esté ocupado).
- El cierre del servicio con el hilo de MPRIS colgado o sin bus no debe trabar el apagado de la radio (test en Task 4).
- Pista sin artista, sin `cancion` o con duración 0: la metadata no lleva claves vacías ni `mpris:length` 0
  (test en Task 3).
- Dos teclas seguidas rápido (dos toques que el parlante manda como dos Next): se procesan en orden, una por vez
  (test en Task 3).

---

### Task 1: Comprobar que Cinnamon le pasa la tecla a un reproductor nuevo, y sumar `dbus-fast`

**Files:**
- Modify: `pyproject.toml` (dependencies)
- Scratch (no se commitea): `<scratchpad>/prueba_mpris.py`

- [ ] **Step 1:** agregar `"dbus-fast>=2"` a `dependencies` e instalar: `.venv/bin/pip install -e .`
  Expected: `Successfully installed dbus-fast-…`.
- [ ] **Step 2:** escribir en el scratchpad un reproductor mínimo con `dbus-fast` que toma
  `org.mpris.MediaPlayer2.prueba_cassette`, exporta las dos interfaces con `PlaybackStatus="Playing"`, emite
  `PropertiesChanged` al arrancar e imprime `Next recibido` al recibir Next y termina.
- [ ] **Step 3:** correrlo en segundo plano y, a los 2 s, `xdotool key XF86AudioNext`.
  Expected: el script imprime `Next recibido`. Si no llega, parar: el diseño entero depende de esto.
- [ ] **Step 4: Commit** `pyproject.toml` («Dependencia dbus-fast para anunciar la radio por MPRIS»).

### Task 2: La radio avisa sus cambios y dice qué está sonando

**Files:**
- Modify: `src/cassette_fm/radio.py`
- Test: `tests/test_radio.py`

**Interfaces:**
- Produces: atributo `Radio.al_cambiar: Callable[[], None] | None` (default None), llamado después de un
  `_sintonizar` exitoso, al final de `_apagar` y al final de `_al_cambiar_pista`. Puede llamarse con el lock tomado:
  quien lo usa no debe bloquear. Una excepción del callback se loguea y no se propaga.
- Produces: `Radio.sonando() -> tuple[str, Pista] | None` — (nombre de la emisora, pista actual) si está prendida y
  el reproductor tiene pista; si no, None.

- [ ] **Step 1: tests**

```python
def test_al_cambiar_se_llama_al_sintonizar_apagar_y_cambiar_de_tema():
    radio, rep, _, _ = crear()
    cambios = []
    radio.al_cambiar = lambda: cambios.append(radio.encendida)
    radio.siguiente()
    radio.apagar()
    rep.al_cambiar_pista(est("A").pistas[0], est("A"))
    assert cambios == [True, False, False]

def test_al_cambiar_que_falla_no_rompe_la_radio():
    radio, _, _, _ = crear()
    radio.al_cambiar = lambda: 1 / 0
    radio.encender()
    assert radio.encendida

def test_sonando_da_emisora_y_pista():
    radio, rep, _, _ = crear()
    assert radio.sonando() is None
    radio.sintonizar("B")
    rep.pista_actual = est("B").pistas[0]
    assert radio.sonando() == ("B", est("B").pistas[0])
    radio.apagar()
    assert radio.sonando() is None
```

- [ ] **Step 2:** `.venv/bin/pytest tests/test_radio.py -q` → Expected: los 3 nuevos FAIL (`AttributeError`).
- [ ] **Step 3:** implementar en `radio.py`.
- [ ] **Step 4:** `.venv/bin/pytest tests/test_radio.py -q` → Expected: PASS.
- [ ] **Step 5: Commit** («La radio avisa sus cambios y dice qué está sonando»).

### Task 3: Servicio MPRIS

**Files:**
- Create: `src/cassette_fm/mpris.py`
- Create: `tests/test_mpris.py`
- Modify: `tests/conftest.py` (fixture `bus_privado`)

**Interfaces:**
- Consumes: `Radio.al_cambiar`, `Radio.sonando()`, `Radio.estado()` (claves `encendida`, `volumen`, `segundo`),
  `siguiente/anterior/alternar/encender/apagar` (Task 2).
- Produces: `class ServicioMpris(radio, nombre: str = "org.mpris.MediaPlayer2.cassette_fm", direccion: str | None = None)`
  — `direccion` es la del bus (None = bus de sesión del entorno).
  - `iniciar(timeout: float = 5.0) -> bool`: arranca el hilo `mpris` con su loop, conecta, exporta y pide el nombre;
    False (y warning en el log) si no pudo; nunca lanza.
  - `cambio() -> None`: thread-safe y no bloqueante; agenda en el loop emitir `PropertiesChanged` de `PlaybackStatus`
    y `Metadata` en `org.mpris.MediaPlayer2.Player`. No-op si no está iniciado.
  - `cerrar(timeout: float = 2.0) -> None`: desconecta y para el loop; no lanza ni espera más que `timeout`.
- Metadata (`a{sv}`): `mpris:trackid` (ObjectPath `/org/cassette_fm/pista/<n>`, `n` sube con cada cambio de pista;
  sin pista `/org/mpris/MediaPlayer2/TrackList/NoTrack`), `xesam:title` (`pista.cancion` o, si falta, `pista.titulo`),
  `xesam:artist` (`[pista.artista]`, solo si hay), `xesam:album` (nombre de la emisora), `mpris:length` (µs, `x`, solo
  si `duracion > 0`). Apagada: solo el trackid NoTrack.
- Otras propiedades de Player: `Position` (`x`, µs de `estado()["segundo"]` o 0), `Volume` (`d`, `volumen/100`, solo
  lectura), `Rate`/`MinimumRate`/`MaximumRate` = 1.0.
- Los métodos corren la acción de la radio con `run_in_executor` sobre un executor de **un** hilo (orden garantizado);
  una excepción se loguea (`warning`, con el nombre de la acción) y el método contesta sin error.

- [ ] **Step 1: fixture** `bus_privado` en `tests/conftest.py`: levanta
  `dbus-daemon --session --nofork --print-address` (o `--config-file` con `<listen>unix:dir=…</listen>` en `tmp_path`),
  devuelve la dirección y lo mata al terminar. También fixture autouse que pone
  `DBUS_SESSION_BUS_ADDRESS=unix:path=<tmp_path>/sin-bus` para que ningún test toque el bus real.
- [ ] **Step 2: tests** con una `RadioFalsa` (registra acciones, `encendida`, `sonando()`, `estado()`, `al_cambiar`) y
  un cliente `dbus-fast` (`MessageBus(bus_address=…)`, `introspect` + `get_proxy_object`):

```python
def test_next_pasa_a_la_siguiente_emisora(bus_privado): ...      # acciones == ["siguiente"]
def test_cada_metodo_llama_a_su_accion(bus_privado): ...         # Previous/PlayPause/Play/Pause/Stop →
                                                                 # anterior/alternar/encender/apagar/apagar
def test_estado_y_metadata(bus_privado): ...                     # Playing + title/artist/album/length/trackid
def test_apagada_esta_stopped_sin_metadata(bus_privado): ...     # Stopped, solo trackid NoTrack
def test_metadata_sin_artista_ni_duracion(bus_privado): ...      # sin xesam:artist ni mpris:length; title = titulo
def test_cambio_emite_properties_changed(bus_privado): ...       # señal con PlaybackStatus y Metadata nuevos
def test_cambio_no_bloquea_con_el_loop_ocupado(bus_privado): ... # acción lenta (1 s) en curso: cambio() < 0,1 s
def test_una_accion_que_falla_no_mata_el_servicio(bus_privado, caplog): ...  # SinEstaciones → warning; el
                                                                 # siguiente Next igual llega
def test_dos_next_seguidos_se_procesan_en_orden(bus_privado): ... # dos Next sin esperar → 2 "siguiente", sin solaparse
def test_capacidades(bus_privado): ...                            # CanGoNext… true, CanSeek/CanQuit/CanRaise false,
                                                                 # Identity "cassette-fm"
def test_sin_bus_iniciar_da_false_y_avisa(tmp_path, caplog): ...  # direccion inexistente → False + warning, sin lanzar
def test_cerrar_termina_el_hilo(bus_privado): ...                 # ningún hilo "mpris" vivo al rato
```

- [ ] **Step 3:** `.venv/bin/pytest tests/test_mpris.py -q` → Expected: FAIL (`ModuleNotFoundError: cassette_fm.mpris`).
- [ ] **Step 4:** implementar `mpris.py` con `dbus_fast.service.ServiceInterface` (`@method`, `@dbus_property`).
- [ ] **Step 5:** `.venv/bin/pytest tests/test_mpris.py -q` → Expected: PASS. Suite completa verde.
- [ ] **Step 6: Commit** («Servicio MPRIS: la radio responde a las teclas multimedia»).

### Task 4: Armado en el servicio y documentación

**Files:**
- Modify: `src/cassette_fm/servicio.py`, `README.md`, `docs/project-context.md`
- Test: `tests/test_servicio.py`

**Interfaces:**
- Consumes: `ServicioMpris` (Task 3), `Radio.al_cambiar` (Task 2).
- Produces: `servir(..., bus_mpris: str | None = None)`; el servicio crea `ServicioMpris(radio, direccion=bus_mpris)`
  después de la `Radio`, conecta `radio.al_cambiar = mpris.cambio`, llama `iniciar()` y agrega `mpris.cerrar` a los
  pasos de apagado antes de `radio.apagar`.

- [ ] **Step 1: tests**

```python
def test_servir_publica_mpris_y_next_cambia_de_emisora(tmp_path, dir_corto, crear_mp3, bus_privado): ...
    # dos emisoras; se prende por la API; Next por D-Bus → /estado muestra la otra; al parar no queda hilo "mpris"
def test_servir_sin_bus_igual_arranca(tmp_path, dir_corto, caplog): ...
    # bus_mpris inexistente → la API responde y hay un warning de MPRIS
```

- [ ] **Step 2:** correr → Expected: FAIL (`servir()` no acepta `bus_mpris`).
- [ ] **Step 3:** implementar en `servicio.py`.
- [ ] **Step 4:** `.venv/bin/pytest -q` → Expected: suite completa PASS.
- [ ] **Step 5:** README: sección corta «Teclas multimedia y parlantes Bluetooth» (qué hace cada botón; que el control
  lo tiene el reproductor que empezó a sonar último). project-context: una línea en el estado.
- [ ] **Step 6: Commit** («La radio se anuncia por MPRIS: teclas multimedia y botones del parlante»).

### Task 5: Prueba real con el usuario (después de la revisión final)

- [ ] `systemctl --user restart cassette-fm` (con su OK: corta la música un momento).
- [ ] `busctl --user list | grep cassette_fm` → aparece el nombre.
- [ ] Con la radio sonando: dos toques en el JBL → siguiente emisora (con aviso); un toque → se apaga; otro → vuelve.
- [ ] La radio aparece en el applet de sonido con tema, artista y emisora.
