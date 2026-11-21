# Radio por oyentes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** La radio suena solo si hay oyentes: se duerme sola sin ellos, la despierta el primero que llega, y las interfaces (incluida la de esta PC) siguen las mismas reglas; `cassette stop`/`start` son el apagado y arranque definitivos.

**Architecture:** `Radio` pasa a conocer el conteo de oyentes (monitor local + suscriptores de `Difusores`). Un `Vigilante` (hilo del servicio) la duerme tras la gracia; `Difusores` avisa cada conexión nueva para despertarla. La CLI gana `stop`/`start` (listas de unidades en la CLI, sin tocar systemd) y pierde `off`/`/apagar`; el applet y el receptor remoto aplican "volumen 0 = dejé de escuchar".

**Tech Stack:** Python 3 (pytest, `.venv/bin/python -m pytest`), JS de Cinnamon (applet, tests con `node --test applet/tests/`), systemd de usuario, Docker (solo `cassette-ollama`).

**Spec:** [`docs/superpowers/specs/2026-11-20-radio-por-oyentes-design.md`](../specs/2026-11-20-radio-por-oyentes-design.md). Tarea: CASSETTE-FM-ta67.

## Global Constraints

- Idioma de trabajo y de commits: español rioplatense. Commits en español, rama `main`, solo local; terminar cada mensaje con `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- Gracia por defecto: **60 s**, configurable (`segundos_hasta_dormir` en `config.toml`). Volumen mínimo al volverse oyente: `VOLUMEN_MINIMO = 50` (ya existe en `radio.py`).
- Sin bus de audio (`router is None`) no hay conteo ni sueño automático: se conserva el comportamiento viejo (encender/apagar a mano, silenciar = apagar).
- `/status` y cualquier sondeo **no** despiertan la radio; solo abrir `/stream`/audio de la nube o elegir emisora.
- `/apagar` y `cassette off` se quitan; `Radio.apagar()` queda interno (cierre del servicio, sin bus, `rescan`). Lo administrativo (borrar emisoras, claves, `rescan`) sigue en la API local, fuera de este tema.
- Nunca mostrar los argumentos del proceso de Soloist: ni `systemctl status`/`ps` con args, ni `systemctl cat` de su unidad (la clave está en el `ExecStart`). Para saber si una unidad existe: `systemctl --user show -p LoadState --value <unidad>` (da `loaded`).
- `applet/cassette-fm@cassette-fm/applet.js` ya tiene un cambio sin commitear del usuario (`DIAL_CIERRE_MS` 3000→10000) y hay `.claude/skills/` sin seguimiento: no los mezcles; en `applet.js` commiteá solo tus hunks (`git add -p`) y nunca `git add -A`.
- `ReloadXlet` no recarga `logic.js` (queda en caché hasta reiniciar Cinnamon): al probar el applet en vivo, reiniciar Cinnamon.
- Al probar el dial con xdotool: verificar que esté abierto y no mandar Escape al final (corta la sesión).

## Review Focus

Entradas y condiciones que el spec implica y que ninguna tarea cubriría si no se las nombra (cada una tiene su test en la tarea indicada):

1. **Deadlock** al despertar por conexión: el aviso de `Difusor` no debe correr con el lock del difusor tomado (la radio toma su lock y consulta el conteo; el orden inverso trabaría). → Tarea 2.
2. **El aviso falla** (radio sin emisoras, error cualquiera): el stream igual se abre. → Tarea 2.
3. **Pedido de red dentro de la gracia:** un oyente que cambia de emisora cuando ya no hay nadie no debe encontrarse la radio dormida antes de abrir su stream. → Tarea 4.
4. **Arranque con `monitor_local = true` guardado** (después de `cassette stop`/`start`): el parlante de esta PC no suena solo cuando un teléfono despierta la radio, salvo en el reinicio de recuperación, que sí conserva el monitor. → Tarea 5.
5. **Radio dormida con el monitor "prendido" en el estado:** no cuenta como oyente local. → Tarea 3.
6. **Receptor remoto:** `volume` hacia abajo con mpv cerrado no lo abre; `on` con volumen guardado 0 arranca en 50. → Tarea 7.
7. **Despertar sin emisoras** (`/stream` con la biblioteca vacía): no se cae. → Tarea 3.

---

## File Structure

- Modify `src/cassette_fm/config.py` — opción `segundos_hasta_dormir`.
- Modify `src/cassette_fm/lan_stream.py` — conteo de oyentes y aviso de conexión.
- Modify `src/cassette_fm/radio.py` — modelo de oyentes, `dormir`, `despertar_para_red`, regla 3, campos de estado.
- Create `src/cassette_fm/vigilante.py` — el hilo que duerme la radio tras la gracia.
- Modify `src/cassette_fm/servicio.py` — cableado (conteo, aviso, vigilante, monitor apagado al arrancar).
- Modify `src/cassette_fm/lan_server.py` — `oyentes` en el estado público.
- Modify `src/cassette_fm/api.py`, `src/cassette_fm/cli.py` — quitar `apagar`/`off`; `stop`/`start`; `on` levanta el servicio; estado con oyentes.
- Modify `applet/cassette-fm@cassette-fm/lan_receiver.py` — volumen 0 = `off`.
- Modify `applet/cassette-fm@cassette-fm/logic.js`, `applet.js` — modo remoto y menú.
- Docs: `docs/project-context.md`, spec (dos desvíos), tarea ta67.

---

### Task 1: Opción `segundos_hasta_dormir`

**Files:**
- Modify: `src/cassette_fm/config.py` (`Config`, `cargar_config`)
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `Config.segundos_hasta_dormir: float = 60.0` (clave de primer nivel en `config.toml`, como `ajuste_volumen_db`).

- [ ] **Step 1: Tests** en `tests/test_config.py` (usar el patrón de los tests existentes de `ajuste_volumen_db`):
  - `test_gracia_sueno_por_defecto_es_60`: sin archivo, `cargar_config(...).segundos_hasta_dormir == 60.0`.
  - `test_gracia_sueno_se_lee_del_toml`: `segundos_hasta_dormir = 15` (entero en TOML) → `15.0`; `= 2.5` → `2.5`.
  - `test_gracia_sueno_invalida`: `= 0`, `= -5` y `= "mucho"` levantan `ErrorConfig` con el nombre de la clave en el mensaje.
- [ ] **Step 2:** correr `.venv/bin/python -m pytest tests/test_config.py -k gracia -v` → FAIL.
- [ ] **Step 3:** agregar el campo a `Config` y a `conocidas`; convertir con `_numero` como `ajuste_volumen_db`; rechazar valores `<= 0`.
- [ ] **Step 4:** correr `.venv/bin/python -m pytest tests/test_config.py -v` → todo PASS.
- [ ] **Step 5: Commit** — `Config: segundos_hasta_dormir (60 s) para dormir la radio sin oyentes`.

---

### Task 2: `Difusores` cuenta oyentes y avisa cada conexión

**Files:**
- Modify: `src/cassette_fm/lan_stream.py` (`Difusor.__init__`, `Difusor.suscribir`, `Difusores`)
- Test: `tests/test_lan_stream.py`

**Interfaces:**
- Produces:
  - `Difusor.__init__(..., al_conectarse: Callable[[], None] | None = None)` (parámetro nuevo, al final).
  - `Difusor.cantidad_oyentes() -> int`.
  - `Difusores.total_oyentes() -> int` (suma de todos los difusores creados).
  - `Difusores` pasa `al_conectarse` a cada `Difusor` que crea (ya reenvía `**opciones`; basta pasarlo en `__init__` como una opción más).
- Comportamiento: `suscribir()` llama a `al_conectarse()` **después de soltar su lock** y de agregar la cola, en cada suscripción exitosa; cualquier excepción del aviso se loguea (`_log.exception`) y no afecta a la suscripción.

- [ ] **Step 1: Tests** (usar `banco`, `Banco.difusor`, `esperar` del archivo):
  - `test_cantidad_oyentes_sube_y_baja_con_suscribir_y_desuscribir`: 0 → 2 suscripciones → 2 → una `desuscribir` → 1.
  - `test_total_oyentes_suma_las_calidades`: `Difusores(lambda: FUENTE_MONITOR, crear=banco.crear_difusor_con_kbps)`; (si hace falta, un `crear` que acepte `kbps` y `cola_max` y devuelva `banco.difusor(kbps=...)`) suscribir uno en 64 y dos en 160 → `total_oyentes() == 3`.
  - `test_al_conectarse_se_llama_una_vez_por_suscripcion`.
  - `test_al_conectarse_corre_sin_el_lock_del_difusor` (Review Focus 1): el aviso lanza un hilo que intenta `difusor._lock.acquire(timeout=1.0)` y guarda el resultado; el test hace `join` del hilo dentro del aviso y espera `True` (con un lock tomado daría `False`; un RLock no sirve de prueba en el mismo hilo, por eso el hilo aparte).
  - `test_un_al_conectarse_que_falla_no_impide_el_stream` (Review Focus 2): el aviso levanta `RuntimeError`; `suscribir()` devuelve la cola y `cantidad_oyentes() == 1`; `caplog` tiene el error.
- [ ] **Step 2:** `.venv/bin/python -m pytest tests/test_lan_stream.py -k "oyentes or conectarse" -v` → FAIL.
- [ ] **Step 3:** implementar. Dentro de `suscribir`, retener la cola en una variable, salir del `with` y recién ahí llamar al aviso con `try/except Exception`.
- [ ] **Step 4:** `.venv/bin/python -m pytest tests/test_lan_stream.py -v` → PASS.
- [ ] **Step 5: Commit** — `Difusores: conteo de oyentes y aviso de cada conexión`.

---

### Task 3: `Radio` conoce a sus oyentes (reglas 2, 3 y 5 del spec)

**Files:**
- Modify: `src/cassette_fm/radio.py` (`Radio.__init__`, `oyentes`, `dormir`, `despertar_para_red`, `monitor`, `_sintonizar`, `estado`)
- Test: `tests/test_radio.py` (usa `crear(...)`, `RouterFalso`, `ReproductorFalso` ya definidos allí)

**Interfaces:**
- Produces (todo en `Radio`):
  - `oyentes_red: Callable[[], int]` — atributo, por defecto `lambda: 0`; lo conecta el servicio.
  - `ultima_sintonia: float` — `self._reloj()` de la última vez que terminó `_sintonizar`; arranca en `0.0`.
  - `oyentes() -> int` — con bus: `(1 si self.encendida y router.local_monitor_enabled) + oyentes_red()`; sin bus: `1 if self.encendida else 0`.
  - `dormir() -> None` — con el lock, si está `encendida` hace lo de `_apagar()` y loguea `info` ("sin oyentes: la radio se duerme"); si no, nada.
  - `despertar_para_red() -> None` — con el lock: si ya está `encendida`, nada; si no hay emisoras, loguea `info` y vuelve **sin levantar**; si no, `_sintonizar(emisora_actual_o_primera, oir_aca=False)`.
  - `estado()` agrega, solo con bus (junto a `monitor_local`): `"oyentes": int` y `"oyentes_red": int`.
- Regla 3 en `_sintonizar(estacion, oir_aca, por_falla)`: antes de tocar nada, `ser_oyente = oir_aca and (self._router is None or self.oyentes() == 0)`; el sube-a-50 del volumen en 0 y el `_prender_monitor()` dependen de `ser_oyente` (no de `oir_aca`). Con `oyentes() >= 1` elegir emisora nunca toca el monitor ni el volumen.
- `monitor(True)` con la radio dormida delega en `encender()` (despierta y escucha); dormida y `False`, o despierta, como hoy.

- [ ] **Step 1: Tests** en `tests/test_radio.py`:
  - `test_oyentes_cuenta_el_monitor_local_solo_con_la_radio_sonando` (Review Focus 5): con bus, `estado=Estado(monitor_local=True)`, radio sin encender → `oyentes() == 0`; tras `encender()` → `1`.
  - `test_oyentes_suma_los_de_la_red`: `radio.oyentes_red = lambda: 2` → con monitor apagado y radio encendida (`sintonizar("A", oir_aca=False)`) `oyentes() == 2`; con monitor prendido, `3`.
  - `test_sin_bus_oyentes_es_1_si_suena_y_0_si_no`.
  - `test_elegir_emisora_con_cero_oyentes_te_vuelve_oyente`: bus, radio dormida, volumen 0, monitor apagado → `siguiente()` deja `router.local_monitor_enabled is True` y `estado.volumen == 50`.
  - `test_elegir_emisora_en_la_gracia_te_vuelve_oyente`: radio encendida con `oir_aca=False` y `oyentes_red = lambda: 0`, monitor apagado → `sintonizar("B")` prende el monitor.
  - `test_elegir_emisora_con_otro_oyente_no_toca_el_monitor_ni_el_volumen`: `oyentes_red = lambda: 1`, monitor apagado, volumen 0, radio encendida → `siguiente()`, `sintonizar("B")` y `anterior()` dejan `monitor_local False` y `volumen 0` y cambian la emisora.
  - `test_encender_con_radio_dormida_te_vuelve_oyente` (clic/dial/`on`): `encender()` prende el monitor.
  - `test_dormir_detiene_y_apaga_solo_si_estaba_sonando`: `dormir()` → `("detener",)` en las llamadas y `encendida False`; un segundo `dormir()` no agrega otro `detener`.
  - `test_despertar_para_red_sintoniza_la_actual_sin_tocar_el_monitor`: `Estado(estacion="B", monitor_local=False)` → `rep.sintonizadas() == ["B"]`, monitor sigue apagado; ya encendida → no re-sintoniza.
  - `test_despertar_para_red_sin_emisoras_no_levanta` (Review Focus 7): `crear(nombres=())` → no excepción, `encendida False`.
  - `test_monitor_true_con_la_radio_dormida_la_despierta`.
  - `test_estado_trae_oyentes_solo_con_bus`: con bus `estado()["oyentes"]` y `["oyentes_red"]`; sin bus, ninguna de las dos claves.
  - `test_sintonizar_marca_ultima_sintonia`: `crear(reloj=lambda: 123.0)` (si `crear` no reenvía `reloj`, pasarlo por `**extra`) → `radio.ultima_sintonia == 123.0` tras sintonizar.
- [ ] **Step 2:** correr `.venv/bin/python -m pytest tests/test_radio.py -v` → los nuevos FALLAN; anotar además qué tests viejos codifican la regla anterior (p. ej. `test_con_bus_sintonizar_con_el_monitor_apagado_lo_prende`, `test_rotar_con_volumen_cero_sube_a_50`, `test_sintonizar_normal_sigue_prendiendo_el_monitor`).
- [ ] **Step 3:** implementar según Interfaces. Los tests viejos que fallen solo porque asumían "siempre prende el monitor" se ajustan: o la radio queda dormida/sin oyentes en su preparación (la regla se cumple) o se reescriben con `oyentes_red = lambda: 1` si prueban justamente el caso con otro oyente. No se borra ninguno.
- [ ] **Step 4:** `.venv/bin/python -m pytest tests/test_radio.py tests/test_mpris.py tests/test_recuperacion.py -v` → PASS (MPRIS y recuperación no cambian de código: este paso lo confirma).
- [ ] **Step 5: Commit** — `Radio: conoce a sus oyentes; elegir emisora sin nadie escuchando te vuelve oyente`.

---

### Task 4: `Vigilante` duerme la radio tras la gracia

**Files:**
- Create: `src/cassette_fm/vigilante.py`
- Create: `tests/test_vigilante.py`

**Interfaces:**
- Consumes (de `Radio`): `encendida: bool`, `oyentes() -> int`, `ultima_sintonia: float`, `dormir() -> None`.
- Produces: `class Vigilante` con
  - `__init__(self, radio, gracia_segundos: float, reloj: Callable[[], float] = time.time)`
  - `revisar(self) -> None` — un paso: si la radio no suena, olvida la cuenta; si `radio.oyentes() > 0`, olvida la cuenta; si no hay oyentes, la cuenta arranca en el primer `revisar` (o en `radio.ultima_sintonia` si es más tardía: un pedido de red dentro de la gracia la reinicia) y cuando `reloj() - desde >= gracia_segundos` llama `radio.dormir()` y olvida la cuenta.
  - `iniciar(self, intervalo: float = 1.0) -> None` — hilo daemon `"vigilante-oyentes"` que llama `revisar()` cada `intervalo`, captura y loguea excepciones; `cerrar(self) -> None` lo detiene (idempotente).

- [ ] **Step 1: Tests** (`RadioFalsa` con los 4 miembros; reloj controlable `t = [0.0]`):
  - `test_con_oyentes_nunca_duerme`: `oyentes()==1`, avanzar 1000 s con `revisar()` → `dormir` no se llamó.
  - `test_sin_oyentes_duerme_pasada_la_gracia_y_no_antes`: gracia 60; `revisar()` en t=0, 59 → no; t=60 → `dormir` una vez.
  - `test_si_vuelve_un_oyente_antes_de_la_gracia_la_cuenta_se_reinicia`: sin oyentes t=0, oyente t=30, sin oyentes de nuevo t=40; en t=99 no duerme, en t=100 sí.
  - `test_radio_dormida_no_se_vuelve_a_dormir`: `encendida False` → nunca `dormir`.
  - `test_un_pedido_de_la_red_en_la_gracia_reinicia_la_cuenta` (Review Focus 3): sin oyentes desde t=0; en t=50 `radio.ultima_sintonia = 50`; t=100 → no duerme; t=110 → sí.
  - `test_el_hilo_revisa_y_se_cierra`: `Vigilante(radio, 0.0).iniciar(intervalo=0.01)` con `oyentes()==0` → espera (≤3 s) que `dormir` se llame; `cerrar()` dos veces sin error y el hilo ya no corre.
  - `test_una_excepcion_en_revisar_no_mata_el_hilo`: `oyentes()` levanta la primera vez; después `dormir` igual se llama.
- [ ] **Step 2:** `.venv/bin/python -m pytest tests/test_vigilante.py -v` → FAIL (módulo inexistente).
- [ ] **Step 3:** implementar `vigilante.py`.
- [ ] **Step 4:** `.venv/bin/python -m pytest tests/test_vigilante.py -v` → PASS.
- [ ] **Step 5: Commit** — `Vigilante: duerme la radio tras la gracia sin oyentes`.

---

### Task 5: Cableado en el servicio y estado público de la LAN

**Files:**
- Modify: `src/cassette_fm/servicio.py` (`servir`)
- Modify: `src/cassette_fm/lan_server.py` (`_CAMPOS`)
- Test: `tests/test_servicio.py`, `tests/test_lan_server.py`

**Interfaces:**
- Consumes: `Config.segundos_hasta_dormir` (Tarea 1), `Difusores(..., al_conectarse=...)`/`total_oyentes()` (Tarea 2), `Radio.oyentes_red`, `Radio.despertar_para_red` (Tarea 3), `Vigilante` (Tarea 4).
- Cableado en `servir`:
  1. Antes de construir `Radio`: `if recuperacion.a_retomar(rutas.reinicio) is None: estado.monitor_local = False` (el servicio arranca sin oyente local; el reinicio de recuperación conserva el monitor guardado).
  2. `Difusores(..., al_conectarse=radio.despertar_para_red)` (el lambda de fuente ya usa `radio.encendida`).
  3. `radio.oyentes_red = difusores.total_oyentes if difusores is not None else (lambda: 0)`.
  4. Con `router is not None`: `vigilante = Vigilante(radio, config.segundos_hasta_dormir)`; `vigilante.iniciar()` después de armar todo; en la secuencia de cierre, `vigilante.cerrar` va **antes** de `radio.apagar`.
- `lan_server._CAMPOS` suma `"oyentes"` (queda público el total, nada más).

- [ ] **Step 1: Tests**
  - `tests/test_lan_server.py::test_status_publica_oyentes`: una radio falsa cuyo `estado()` trae `"oyentes": 2` → `GET /status` devuelve `oyentes == 2`; sin la clave devuelve `None`.
  - `tests/test_servicio.py` (patrón de `test_servir_con_bus_de_audio_crea_el_bus_expone_el_monitor_y_lo_cierra`, con `RouterDeServicioFalso`):
    - `test_con_bus_la_radio_se_duerme_sola_sin_oyentes`: `Config(..., segundos_hasta_dormir=0.3)`; `POST /encender` → `encendida True`; `POST /silenciar`; en ≤ 5 s `GET /estado` da `encendida False`.
    - `test_con_bus_con_el_monitor_prendido_no_se_duerme`: `POST /encender`, esperar 1,5 s (> gracia), sigue `encendida True`.
    - `test_arranca_con_el_monitor_apagado_aunque_el_estado_guardado_lo_tenga_prendido` (Review Focus 4): escribir `estado.json` con `monitor_local: true` (usar el helper de rutas del archivo), arrancar → `GET /estado` trae `monitor_local False`.
    - `test_tras_un_reinicio_de_recuperacion_conserva_el_monitor_guardado`: además un marcador vigente en `rutas.reinicio` (formato de `recuperacion.pedir_reinicio`: `{"cuando": <ahora>, "estacion": "A", "retomado": False}`) → `monitor_local True`.
    - `test_sin_bus_no_hay_vigilante`: sin bus, `_nombres_de_hilos()` no incluye `vigilante-oyentes`.
- [ ] **Step 2:** `.venv/bin/python -m pytest tests/test_servicio.py tests/test_lan_server.py -k "oyentes or duerme or monitor or vigilante" -v` → FAIL.
- [ ] **Step 3:** implementar el cableado y el campo público.
- [ ] **Step 4:** `.venv/bin/python -m pytest tests/test_servicio.py tests/test_lan_server.py tests/test_lan_stream.py tests/test_puente_nube.py -v` → PASS.
- [ ] **Step 5: Commit** — `Servicio: vigilante de oyentes, despertar por conexión y arranque sin oyente local`.

---

### Task 6: API y CLI — sin `apagar`, con `stop`/`start`

**Files:**
- Modify: `src/cassette_fm/api.py` (`ACCIONES`)
- Modify: `src/cassette_fm/cli.py` (`ACCIONES`, `_linea_estado`, subcomandos `stop`/`start`, `on` con el servicio caído)
- Test: `tests/test_api.py`, `tests/test_cli.py`

**Interfaces:**
- API: `ACCIONES = ("siguiente", "anterior", "encender", "alternar", "silenciar", "rescan")`; `POST /apagar` → 404 `ruta desconocida: /apagar`.
- CLI (`cli.py`):
  - `ACCIONES` sin `"off"`; `cassette off` → argparse error (exit 2).
  - `UNIDADES_ARRANQUE = ("cassette-dj", "cassette-fm", "cassette-soloist")`, `CONTENEDOR_LLM = "cassette-ollama"`.
  - `def _ejecutar(argv: list[str]) -> tuple[int, str]` — `subprocess.run(argv, capture_output=True, text=True, timeout=60)`; devuelve `(returncode, stdout)`; `FileNotFoundError`/timeout → `(127, "")`. Nunca imprime lo que captura.
  - `def detener_servicios(ejecutar=_ejecutar) -> int` — en orden inverso a `UNIDADES_ARRANQUE` (soloist, fm, dj) hace `systemctl --user stop <u>` y después `docker stop cassette-ollama`; **saltea** (línea `· <nombre>: no instalada`) la unidad cuyo `systemctl --user show -p LoadState --value <u>` no dé `loaded`, y el contenedor si `docker inspect cassette-ollama` falla; una línea por paso (`✓ <nombre> detenida`); devuelve 0 si ningún paso existente falló, 1 si no.
  - `def levantar_servicios(ejecutar=_ejecutar) -> int` — inverso: `docker start cassette-ollama`, luego `systemctl --user start` de dj, fm, soloist, mismas reglas de saltear y de salida; idempotente.
  - `def _esperar_servicio(puerto: int, segundos: float = 30.0) -> bool` — sondea `GET /estado` cada 0,5 s hasta que responde.
  - Subcomandos `stop` y `start` (sin `--puerto`) que llaman a esas funciones y devuelven su código.
  - `on` con `_ServicioCaido`: `levantar_servicios()`, `_esperar_servicio(puerto)` y reintenta una vez; si no levanta, el error de siempre.
  - `_linea_estado`: con la clave `"oyentes"` en el estado: radio parada → `⏹ dormida (vol N)`; sonando → la línea de siempre + ` · N oyentes` (`1 oyente` en singular). Sin la clave (sin bus) queda `⏹ apagada (vol N)` como hoy.

- [ ] **Step 1: Tests**
  - `tests/test_api.py`: `test_apagar_ya_no_existe` (`POST /apagar` → 404 y `radio.llamadas == []`); ajustar los tests viejos que usaban `/apagar`.
  - `tests/test_cli.py`:
    - sacar `("off", "apagar")` de `test_acciones`; `test_off_ya_no_es_un_comando`: `main(["off"])` → `SystemExit` con código 2.
    - `test_stop_detiene_en_orden_y_saltea_lo_que_no_existe`: `ejecutar` falso que registra los `argv` y responde `loaded` salvo para `cassette-dj` (`not-found`) → orden exacto `systemctl --user stop cassette-soloist`, `... stop cassette-fm`, luego `docker stop cassette-ollama`; no hay `stop cassette-dj`; salida con `· cassette-dj: no instalada`; retorno 0.
    - `test_stop_devuelve_1_si_una_unidad_existente_falla`.
    - `test_start_levanta_en_orden_inverso`: `docker start cassette-ollama`, `start cassette-dj`, `start cassette-fm`, `start cassette-soloist`.
    - `test_stop_sin_docker_no_falla`: `ejecutar` devuelve `(127, "")` para los comandos `docker` → se saltea y sale 0.
    - `test_stop_y_start_no_imprimen_la_salida_capturada`: `ejecutar` devuelve stdout `"CLAVE-SECRETA"` para `show` y `stop`; `capsys` no la contiene.
    - `test_on_con_el_servicio_caido_lo_levanta_y_reintenta`: parchear `cli._llamar` (levanta `_ServicioCaido` la primera vez, después devuelve un estado), `cli.levantar_servicios` (cuenta) y `cli._esperar_servicio` (`True`) → `main(["on", "--puerto", "1"]) == 0`, `levantar_servicios` una vez.
    - `test_on_si_el_servicio_no_levanta_da_el_error_de_siempre`: `_esperar_servicio` → `False` → código distinto de 0 y mensaje de `cassette-fm no está corriendo`.
    - `test_status_con_oyentes_y_dormida`: estado falso con `"oyentes": 0, "encendida": False` → `⏹ dormida (vol 70)`; con `"oyentes": 2` y sonando → termina en `· 2 oyentes`; sin la clave → `⏹ apagada`.
- [ ] **Step 2:** `.venv/bin/python -m pytest tests/test_api.py tests/test_cli.py -v` → los nuevos FALLAN.
- [ ] **Step 3:** implementar (el `ejecutar` se inyecta con un parámetro por defecto; en `main`, `stop`/`start` se resuelven antes de abrir cualquier conexión).
- [ ] **Step 4:** `.venv/bin/python -m pytest tests/test_api.py tests/test_cli.py -v` → PASS.
- [ ] **Step 5: Commit** — `CLI y API: se quita apagar; cassette stop/start; on levanta el servicio; estado con oyentes`.

---

### Task 7: Receptor remoto — volumen 0 es "me desconecté"

**Files:**
- Modify: `applet/cassette-fm@cassette-fm/lan_receiver.py` (`_on`, `_volume`)
- Test: `tests/test_lan_receiver.py` (fixtures `entorno`, `servidor` existentes)

**Interfaces:**
- `_volume(env, pedido)`: calcula `nuevo` como hoy y lo guarda en `runtime/volumen`; luego
  - `nuevo == 0` → hace `_off(env)` (cierra mpv; el archivo de volumen queda en 0);
  - `nuevo > actual` y mpv **no** vivo → `_on(env)` (reabre con ese volumen);
  - cualquier otro caso → como hoy (`set_property volume` si hay mpv).
  Imprime `nuevo` y devuelve 0 en todos.
- `_on(env)`: si `_volumen_guardado(runtime) == 0` escribe `50` en `runtime/volumen` antes de arrancar.

- [ ] **Step 1: Tests**
  - `test_volume_0_cierra_el_mpv_como_off`: `on`, `volume 0` → `status` dice apagado y el socket de mpv ya no vive; el archivo `volumen` contiene `0`.
  - `test_volume_sube_desde_0_con_el_mpv_cerrado_lo_abre`: tras lo anterior, `volume +10` → `status` escuchando, volumen `10`.
  - `test_volume_hacia_abajo_con_el_mpv_cerrado_no_lo_abre` (Review Focus 6): `off`, guardar 70, `volume -10` → sigue sin mpv, archivo en `60`.
  - `test_volume_hacia_arriba_con_el_mpv_cerrado_por_off_lo_abre`: `off` con 70, `volume +10` → escuchando a `80` (regla 5 del spec).
  - `test_on_con_el_volumen_en_0_arranca_en_50` (Review Focus 6): archivo en `0`, `on` → `status --json` da `volumen 50`.
  - `test_volume_con_mpv_vivo_sigue_aplicandose_en_caliente`: `on`, `volume 40` → mpv vivo con volumen 40 (no se reabrió: mismo pid).
- [ ] **Step 2:** `.venv/bin/python -m pytest tests/test_lan_receiver.py -v` → los nuevos FALLAN; anotar los viejos que dependan de `volume` con mpv cerrado (`test_volume_se_aplica_se_recuerda_y_se_reaplica_en_el_proximo_on`, `test_volume_se_acota_a_0_100`): ajustarlos a la regla nueva (en 0 el mpv se cierra; subiendo con mpv cerrado se abre) sin cambiar lo que verifican.
- [ ] **Step 3:** implementar.
- [ ] **Step 4:** `.venv/bin/python -m pytest tests/test_lan_receiver.py -v` → PASS.
- [ ] **Step 5: Commit** — `Receptor remoto: volumen 0 deja de escuchar y subirlo vuelve a escuchar`.

---

### Task 8: Applet — sin "Apagar", modo remoto con las mismas reglas

**Files:**
- Modify: `applet/cassette-fm@cassette-fm/logic.js` (`planRemoto`)
- Modify: `applet/cassette-fm@cassette-fm/applet.js` (menú, `_pedirRemoto`, clic con el servicio caído, comentario del dial)
- Test: `applet/tests/logic.test.js`, `tests/test_applet_estructura.py`

**Interfaces:**
- `planRemoto(ruta, cuerpo, estado, receptor)`:
  - se quita el caso `"/apagar"` (devuelve `{ destino: "ninguno" }` como cualquier ruta desconocida);
  - en `"/sintonizar"`, `"/siguiente"` y `"/anterior"`, si `receptor.escuchando === false` y `estado && estado.oyentes === 0`, el plan de servidor lleva además `despues: ["on"]` (el receptor se prende después del pedido: la gracia del servidor cubre ese tiempo); en cualquier otro caso el plan queda igual que hoy (sin `despues`).
- `applet.js`:
  - se quita el ítem "Apagar" de `_reconstruirMenu` (y su comentario);
  - `_pedirRemoto`: si el pedido de servidor termina en 200 y `plan.despues` existe, corre `this._correrReceptor(plan.despues, ...)` y actualiza `this._receptor.escuchando = true` como ya hace con `"on"`;
  - `on_applet_clicked` (modo local): si `/alternar` falla con `codigo === 0` (servicio caído), corre `this._correr("cassette", ["on"], 60, ...)` y después `this._sondear()`; solo para el clic, no para la rueda ni el volumen;
  - el comentario de `_cambiarVolumen` ("en 0 la API apaga la radio…") pasa a decir que en 0 la API silencia.
  - El dial **no cambia**: `POST /encender` ya significa "escuchar acá" (ver "Desvíos del spec" en la tarea 9).

- [ ] **Step 1: Tests**
  - `applet/tests/logic.test.js`:
    - reemplazar `assert.deepEqual(args("/apagar"), ["off"])` por `assert.deepEqual(L.planRemoto("/apagar", {}, status.datos, receptor), { destino: "ninguno" })` y sumar `"/apagar"` a la lista de "lo que no existe".
    - `planRemoto: elegir emisora con cero oyentes y sin escuchar prende el receptor después`: con `{ ...status.datos, oyentes: 0 }` y `receptor = { escuchando: false, volumen: 70 }`, `/sintonizar` `{estacion:"C"}`, `/siguiente` y `/anterior` devuelven `despues` igual a `["on"]` y mantienen `destino/metodo/ruta`.
    - `planRemoto: con otros oyentes o ya escuchando no hay despues`: `oyentes: 1`, o `receptor.escuchando: true`, o `estado.oyentes` ausente → sin la clave `despues` (`assert.equal("despues" in plan, false)`).
  - `tests/test_applet_estructura.py` (patrón de lectura de fuentes que ya usa): `test_el_menu_ya_no_tiene_apagar` (`'"/apagar"'` ni `"Apagar"` en el fuente de `applet.js`); `test_el_clic_con_el_servicio_caido_corre_cassette_on` (el fuente de `on_applet_clicked`/su ayudante contiene `"cassette"` y `["on"]`); `test_el_remoto_corre_el_despues_del_plan` (`"plan.despues"` en `_pedirRemoto`).
- [ ] **Step 2:** `node --test applet/tests/` y `.venv/bin/python -m pytest tests/test_applet_estructura.py -v` → los nuevos FALLAN.
- [ ] **Step 3:** implementar (en `applet.js`, `git add -p`: no incluir el cambio previo de `DIAL_CIERRE_MS`).
- [ ] **Step 4:** `node --test applet/tests/` y `.venv/bin/python -m pytest tests/test_applet_estructura.py tests/test_applet_logic.py tests/test_applet_instalacion.py -v` → PASS.
- [ ] **Step 5: Commit** — `Applet: sin Apagar; el modo remoto prende el receptor al elegir sin oyentes; el clic levanta el servicio caído`.

---

### Task 9: Documentación, tareas y verificación en vivo

**Files:**
- Modify: `docs/project-context.md`, `docs/superpowers/specs/2026-11-20-radio-por-oyentes-design.md`, `.beans/CASSETTE-FM-ta67*.md`

- [ ] **Step 1: Suite completa:** `.venv/bin/python -m pytest -q` y `node --test applet/tests/` → todo PASS (anotar el total).
- [ ] **Step 2: Desvíos del spec** (agregar una sección "Desvíos al implementar" al final del spec): (a) el dial sigue usando `POST /encender`, que ya es "escuchar acá" (prende el monitor y despierta); no hace falta `POST /monitor`; (b) `Radio.monitor(True)` con la radio dormida ahora también la despierta; (c) el servicio arranca con el monitor local apagado salvo en el reinicio de recuperación (cierra el cabo suelto de `monitor_local` persistido); (d) el applet remoto prende su receptor *después* de pedir la emisora (`despues`).
- [ ] **Step 3: `docs/project-context.md`:** un párrafo en "Estado" (después del de la voz entre temas): radio por oyentes, regla de gracia, `cassette stop`/`start`, sin `off`/`/apagar`, enlace al spec y a este plan.
- [ ] **Step 4: Tarea ta67:** editar `.beans/CASSETTE-FM-ta67*.md` (título "Radio por oyentes: se duerme sola y la despierta el primero que llega", cuerpo con el alcance del spec, `status: completed` al terminar). Crear con `/beans:create` dos tareas nuevas: (1) "La web del relay cumple la regla de oyentes (volumen 0 / pausa cierra el audio)" y (2) "Que el servicio DJ descargue sus voces tras un rato sin pedidos (libera ~1 GB con la radio dormida)".
- [ ] **Step 5: Verificación en vivo en esta PC** (reiniciar Cinnamon antes por `logic.js`; reiniciar `cassette-fm` con `systemctl --user restart cassette-fm`; nunca `status`/`ps` de Soloist): (a) con el monitor apagado, `cassette next` cambia de emisora y **no** suena en esta PC; (b) `cassette mute` y, pasados ~60 s, `cassette status` dice `dormida`; (c) clic en el applet con la radio dormida → suena y `status` muestra 1 oyente; (d) rueda del applet con el monitor silenciado y otro oyente → cambia de emisora sin prender el sonido; (e) abrir el dial (Super+Alt+Espacio) con el monitor apagado → suena (verificar que esté abierto; no mandar Escape al final); (f) `cassette stop` → `cassette status` falla con "no está corriendo", memoria del DJ liberada (`ps -o rss= -p <pid del dj>` ya no existe); `cassette start` → levanta todo; `cassette on` con el servicio detenido lo levanta y suena.
- [ ] **Step 6: Commit** — `Docs: radio por oyentes (contexto, spec con desvíos, tarea ta67)` (agregar a la lista de archivos solo los míos).

---

## Self-review

- **Cobertura del spec:** definición de oyente (T3, T7), reglas 1 (T3/T4/T5), 2 (T2/T3/T5), 3 (T3), 4 (T8: el dial sigue con `/encender`), 5 (T3 + T7), 6 (T3 `alternar` sin cambios, T8 clic con servicio caído), 7 (T8 `despues`), 8 (T3 sin bus, T5), cambios de interfaz (T5–T8), ciclo de vida `stop`/`start` (T6), arranque de la máquina sin cambios, web del relay (T9 tarea aparte), documentación (T9).
- **Consistencia de nombres:** `oyentes()`, `oyentes_red`, `ultima_sintonia`, `dormir`, `despertar_para_red` (T3) son los que usan T4 y T5; `al_conectarse`/`total_oyentes` (T2) los usa T5; `segundos_hasta_dormir` (T1) lo usa T5; `levantar_servicios`/`detener_servicios`/`_esperar_servicio` (T6) son los de los tests de T6.
- **Orden:** T1→T2→T3→T4→T5 son dependientes en ese orden; T6, T7 y T8 dependen solo de T3/T5 por el campo `oyentes` en `/estado` y `/status` y pueden hacerse en cualquier orden después de T5.
