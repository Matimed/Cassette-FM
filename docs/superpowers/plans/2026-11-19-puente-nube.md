# Puente a la nube — plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que esta PC se conecte por WebSockets salientes a un relay en la nube: reporta el estado, recibe órdenes y sube el audio del bus en MP3 (64/96/160 kbps) solo mientras el relay pida cada calidad.

**Architecture:** Un módulo nuevo `puente_nube.py` con un hilo de control (WebSocket permanente, reconexión con espera creciente) y un hilo por conexión de audio, que es un oyente más del `Difusor` de la LAN. Los `Difusor` pasan a salir de un registro por calidad que comparten la LAN y la nube. Sección `[nube]` en la config, clave en `nube.token`, `cassette nube`, y un relay de prueba en `scripts/`.

**Tech Stack:** Python 3, `websockets` 17 (cliente y servidor síncronos, ya es dependencia), GStreamer (`gst-launch-1.0`, ya usado), pytest.

**Spec:** [`docs/superpowers/specs/2026-11-19-puente-nube-design.md`](../specs/2026-11-19-puente-nube-design.md)

## Global Constraints

- Todo sale desde esta PC: el puente no abre ningún puerto.
- `[nube] activo = false` por defecto; apagado no arranca hilos ni conexiones y no cambia nada de la radio local ni de la LAN.
- Una falla del puente nunca tira el servicio ni afecta a la radio local o a la LAN.
- Necesita `bus_audio = true`; sin bus se loguea un error y el puente no arranca (como `[lan]`).
- Rutas fijas: `/casa/control`, `/casa/audio?calidad=<kbps>`, `PUT /casa/icono/<emisora url-encoded>?v=<versión>`; todas con `Authorization: Bearer <clave>`.
- `url` base `wss://host[:puerto]`; `ws://` solo contra `127.0.0.1`/`localhost`; sin ruta, query ni credenciales. El logo va al mismo host con `https://` (o `http://` si la base es `ws://`).
- Calidades fijas `(64, 96, 160)`; protocolo `1`.
- `estado` a lo sumo uno cada 0,5 s (el último); `seq` crece por conexión.
- Reconexión: 1, 2, 4… hasta 30 s con azar; vuelve a 1 s tras una conexión de más de 60 s. Ping 20 s / timeout 20 s. 401 → error y reintento cada 300 s.
- Control caído más de 60 s → se cierran las conexiones de audio.
- La clave nunca en logs, URL ni línea de comandos. Primera caída = warning; reintentos siguientes = debug hasta reconectar (info con cuánto duró el corte).
- Órdenes desde la nube: `oir_aca=False` (no prenden los parlantes ni tocan el volumen de esta PC).
- Commits en español, terminan con `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Suite completa: `.venv/bin/python -m pytest -q` (y `node --test applet/tests/` si se toca el applet; este plan no lo toca).

## Review Focus

1. **TCP medio abierto** (el wifi se cae sin cerrar la conexión): el ping de 20 s tiene que detectar la caída y reconectar; un test lo simula con un servidor que deja de contestar pings.
2. **Ráfagas de cambios** (cambio de tema más el DJ más una sintonía en menos de 0,5 s): sale un solo `estado` con el último valor, y ninguno se pierde al final de la ráfaga.
3. **Nombres de emisora con espacios, acentos, `/` o `?`** en `sintonizar` y en el `PUT` del logo: se codifican bien en la URL y se buscan por nombre exacto.
4. **Clave regenerada con audio abierto**: se cortan todas las conexiones y vuelven con la clave nueva sin reiniciar.
5. **La nube pide 160 con la LAN apagada (y al revés)**: el registro crea un solo codificador de 160 y lo comparten; cerrar uno no corta al otro.

---

### Task 1: Config `[nube]` y ruta de la clave

**Files:**
- Modify: `src/cassette_fm/config.py` (dataclass `ConfigNube`, campo `Config.nube`, `_leer_nube`, `Rutas.nube_token`)
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `ConfigNube(activo: bool = False, url: str | None = None)`; `Config.nube: ConfigNube`; `Rutas.nube_token -> Path` (`<config>/nube.token`, junto a `lan.token`).

- [ ] **Step 1: Tests que fallan** en `tests/test_config.py`:
  - `test_nube_por_defecto_apagada`: sin `[nube]` → `ConfigNube(activo=False, url=None)`.
  - `test_nube_url_valida`: `wss://relay.ejemplo.com`, `wss://relay.ejemplo.com:8443`, `ws://127.0.0.1:9000`, `ws://localhost:9000` se aceptan; la barra final se saca.
  - `test_nube_url_invalida` (parametrizado, `match="nube.url"`): `"https://x.com"`, `"ws://relay.ejemplo.com"`, `"wss://x.com/ruta"`, `"wss://x.com?a=1"`, `"wss://user:pw@x.com"`, `""`, `3`.
  - `test_nube_activa_sin_url_es_error` (`match="nube.url"`); `test_nube_activo_no_booleano` (`match="nube.activo"`).
  - `test_ruta_nube_token`: `rutas().nube_token.name == "nube.token"` y mismo directorio que `lan_token`.
- [ ] **Step 2:** `.venv/bin/python -m pytest tests/test_config.py -q -k nube` → FAIL (`AttributeError` / `ErrorConfig` que no salta).
- [ ] **Step 3:** Implementar siguiendo `_leer_lan` (mensajes `"{archivo}: 'nube.url' …"`); validar con `urllib.parse.urlsplit`.
- [ ] **Step 4:** `.venv/bin/python -m pytest tests/test_config.py -q` → PASS.
- [ ] **Step 5: Commit** `Puente a la nube: sección [nube] en la config y ruta de su clave`.

### Task 2: `Difusor` por calidad y registro compartido

**Files:**
- Modify: `src/cassette_fm/lan_stream.py` (`Difusor(..., kbps=160)`, clase `Difusores`)
- Modify: `src/cassette_fm/servicio.py` (`iniciar_lan` recibe el registro)
- Test: `tests/test_lan_stream.py`, `tests/test_servicio.py`

**Interfaces:**
- Produces:
  - `Difusor(fuente_actual, ..., kbps: int = 160)`: lanza `comando_gst(fuente, kbps=kbps)`; `Difusor.kbps`.
  - `Difusores(fuente_actual: Callable[[], str], crear=Difusor, **opciones)`: `de(kbps: int) -> Difusor` (lo crea la primera vez, siempre el mismo después; thread-safe), `revisar_fuente() -> None` (de todos), `cortar_oyentes() -> None` (de todos), `cerrar() -> None`. Las `opciones` (p. ej. `max_oyentes`) van a cada `Difusor`.
  - `iniciar_lan(config, rutas, radio, router, difusores: Difusores | None = None, crear_difusor=Difusor, ...)`: usa `difusores.de(160)`; si no se lo pasan crea uno propio (los tests viejos siguen igual). No cierra un registro que no creó.

- [ ] **Step 1: Tests que fallan:** `test_difusor_codifica_a_su_calidad` (el comando lanzado contiene `bitrate=64`); `test_difusores_crea_uno_por_calidad_y_lo_reusa` (`de(96) is de(96)`, `de(64) is not de(96)`); `test_difusores_revisa_y_cierra_todos`; en `test_servicio.py`, `test_lan_usa_el_difusor_160_del_registro` (con un registro falso: `iniciar_lan` pide `de(160)` y al cerrar no cierra el registro).
- [ ] **Step 2:** `.venv/bin/python -m pytest tests/test_lan_stream.py tests/test_servicio.py -q` → FAIL.
- [ ] **Step 3:** Implementar. `max_oyentes` de la LAN pasa a ser opción del registro (lo arma `servir` con `config.lan.max_oyentes`).
- [ ] **Step 4:** Mismos tests → PASS.
- [ ] **Step 5: Commit** `Stream: un Difusor por calidad en un registro que comparten la LAN y la nube`.

### Task 3: La radio avisa a varios interesados; siguiente/anterior sin prender el monitor

**Files:**
- Modify: `src/cassette_fm/radio.py`
- Test: `tests/test_radio.py`

**Interfaces:**
- Produces: `Radio.escuchar_cambios(funcion: Callable[[], None]) -> None` (se suman; `al_cambiar` sigue andando como hasta ahora para MPRIS; una función que tira excepción se loguea y no frena a las demás); `Radio.siguiente(oir_aca: bool = True)`, `Radio.anterior(oir_aca: bool = True)`.

- [ ] **Step 1: Tests que fallan:** `test_varios_interesados_reciben_cada_cambio`; `test_un_interesado_que_falla_no_frena_a_los_otros`; `test_siguiente_desde_la_red_no_prende_el_monitor` (con router falso: monitor apagado y volumen 0 quedan así; la emisora cambia); `test_anterior_desde_la_red_no_prende_el_monitor`.
- [ ] **Step 2:** `.venv/bin/python -m pytest tests/test_radio.py -q` → FAIL.
- [ ] **Step 3:** Implementar (`_rotar(paso, oir_aca)` pasa `oir_aca` a `_sintonizar`).
- [ ] **Step 4:** `.venv/bin/python -m pytest tests/test_radio.py tests/test_mpris.py -q` → PASS.
- [ ] **Step 5: Commit** `Radio: varios interesados en los cambios y siguiente/anterior sin prender el monitor`.

### Task 4: Puente — control (hola, estado, órdenes, reconexión)

**Files:**
- Create: `src/cassette_fm/puente_nube.py`
- Test: `tests/test_puente_nube.py` (relay falso con `websockets.sync.server.serve` en `127.0.0.1:0`, en un hilo; guarda los mensajes y los encabezados recibidos; puede mandar mensajes, cerrar, contestar 401 y dejar de responder pings)

**Interfaces:**
- Consumes: `Radio.estado()`, `Radio.estaciones()`, `Radio.sintonizar(nombre, oir_aca=False)`, `Radio.siguiente/anterior(oir_aca=False)`, `Radio.escuchar_cambios` (Task 3); `lan_server.estado_publico`, `lan_server._version_logo` (pasa a pública como `version_logo`).
- Produces:
  - `CALIDADES = (64, 96, 160)`, `PROTOCOLO = 1`.
  - `mensaje_estado(estado: dict, seq: int) -> dict` (campos de `estado_publico` + `iconos: {emisora: versión}` solo de logos servibles).
  - `Espera(minimo=1.0, maximo=30.0, azar=random.random)`: `siguiente() -> float`, `reiniciar() -> None`.
  - `PuenteNube(radio, difusores, url: str, token: Callable[[], str], conectar=websockets.sync.client.connect, subir=None, reloj=time.monotonic, ping_segundos=20.0, intervalo_estado=0.5, espera_401=300.0, gracia_control=60.0, espera=None)`: `iniciar()`, `cerrar()`, `reconectar()` (corta todo y reconecta, para la clave regenerada), `info() -> {"conectado": bool, "desde": float | None, "error": str | None, "subiendo": list[int]}`.

- [ ] **Step 1: Tests que fallan:**
  - `test_al_conectar_manda_hola_y_estado` (orden, `protocolo == 1`, `calidades == [64, 96, 160]`, `seq == 1`, encabezado `Authorization: Bearer <clave>`).
  - `test_estado_sin_volumen_ni_rutas` (no aparecen `volumen`, `monitor_local` ni rutas de archivos; `iconos` son versiones).
  - `test_rafaga_de_cambios_manda_un_estado_con_el_ultimo` (tres cambios en 0,1 s → un `estado` en ~0,5 s con el último valor; ninguno después).
  - `test_sintonizar_desde_la_nube` (`oir_aca=False`, `resultado ok`); `test_emisora_inexistente_devuelve_error`; `test_siguiente_y_anterior`; `test_nombre_con_acentos_y_barra`.
  - `test_tipo_desconocido_y_json_roto_no_cortan`.
  - `test_reconecta_si_el_relay_corta` (espera inyectada en 0,05 s; vuelve a mandar `hola` y `estado` con `seq` desde 1).
  - `test_ping_sin_respuesta_reconecta` (`ping_segundos=0.2`, servidor que no contesta pings).
  - `test_401_no_reintenta_en_bucle` (con `espera_401=60`, en 1 s hubo un solo intento; `info()["error"]` habla de la clave).
  - `test_la_clave_no_aparece_en_los_logs` (`caplog` en todos los tests de conexión).
  - `test_cerrar_termina_los_hilos`.
- [ ] **Step 2:** `.venv/bin/python -m pytest tests/test_puente_nube.py -q` → FAIL (`ModuleNotFoundError`).
- [ ] **Step 3:** Implementar el hilo de control: conectar con `additional_headers`, `ping_interval`/`ping_timeout`; `InvalidStatus` con 401 → espera de 401; órdenes en un hilo trabajador con una cola (de a una, en orden); el estado pendiente se marca desde `escuchar_cambios` y lo manda un temporizador.
- [ ] **Step 4:** Mismos tests → PASS.
- [ ] **Step 5: Commit** `Puente a la nube: canal de control con estado, órdenes y reconexión`.

### Task 5: Puente — audio bajo demanda

**Files:**
- Modify: `src/cassette_fm/puente_nube.py`
- Test: `tests/test_puente_nube.py` (con `Difusores` de verdad sobre el `ProcesoFalso` de `tests/test_lan_stream.py`, llevado a un helper compartido si hace falta)

**Interfaces:**
- Consumes: `Difusores.de(kbps)`, `Difusor.suscribir() -> queue.Queue` / `desuscribir(cola)` (Task 2); el `None` en la cola significa "te cortaron".
- Produces: el manejo de `demanda` en `PuenteNube`; `info()["subiendo"]`.

- [ ] **Step 1: Tests que fallan:**
  - `test_demanda_abre_audio_en_esa_calidad` (`/casa/audio?calidad=96`, con la clave; los bytes del codificador falso llegan como mensajes binarios en orden).
  - `test_demanda_vacia_cierra_y_el_codificador_se_apaga` (tras la gracia del `Difusor`).
  - `test_dos_calidades_a_la_vez`; `test_calidad_desconocida_se_ignora`.
  - `test_oyente_lento_se_reabre_en_vivo` (la cola llena → el `Difusor` lo descarta → se abre otra conexión de la misma calidad).
  - `test_control_caido_mantiene_el_audio_y_a_los_60_s_lo_cierra` (`gracia_control=0.3`).
  - `test_demanda_al_reconectar_corrige` (al volver el control, una `demanda` sin 96 cierra la de 96).
  - `test_reconectar_corta_y_reabre_audio` (clave nueva en el encabezado).
  - `test_nube_160_y_lan_comparten_codificador` (un solo proceso lanzado para 160 con un oyente de cada uno).
- [ ] **Step 2:** `.venv/bin/python -m pytest tests/test_puente_nube.py -q` → FAIL.
- [ ] **Step 3:** Implementar un hilo por calidad abierta: suscribe, manda cada bloque con `send(bytes)`, reintenta con su propia `Espera` mientras la calidad siga pedida y el control no lleve más de `gracia_control` caído. Bajar el `SO_SNDBUF` del socket de la conexión de audio a 8 KB, como `_BUFFER_ENVIO_BYTES` de la LAN.
- [ ] **Step 4:** Mismos tests → PASS.
- [ ] **Step 5: Commit** `Puente a la nube: audio por calidad solo mientras el relay lo pide`.

### Task 6: Puente — logos

**Files:**
- Modify: `src/cassette_fm/puente_nube.py`
- Test: `tests/test_puente_nube.py`

**Interfaces:**
- Produces: `url_icono(base: str, emisora: str, version: str) -> str` (`wss→https`, `ws→http`, nombre con `quote(safe="")`); `subir_icono(url: str, token: str, datos: bytes, tipo: str) -> None` (`urllib.request`, `PUT`, timeout 15 s; un error se loguea y no corta el control). `PuenteNube(subir=...)` lo usa por defecto.

- [ ] **Step 1: Tests que fallan:** `test_url_icono` (con `"Más Gasolina F.M."` y `"a/b?c"`); `test_pedir_icono_sube_el_logo` (subidor falso: tipo `image/png`, bytes del archivo, versión igual a la del `estado`); `test_pedir_icono_de_emisora_sin_logo_no_sube`; `test_logo_que_falla_al_subir_no_corta_el_control`.
- [ ] **Step 2:** `.venv/bin/python -m pytest tests/test_puente_nube.py -q -k icono` → FAIL.
- [ ] **Step 3:** Implementar; reusar `_TIPOS_IMAGEN` y `version_logo` de `lan_server` (el mismo tope de 4 MB). La subida corre en el hilo trabajador de órdenes.
- [ ] **Step 4:** `.venv/bin/python -m pytest tests/test_puente_nube.py -q` → PASS.
- [ ] **Step 5: Commit** `Puente a la nube: los logos se suben cuando el relay los pide`.

### Task 7: Integración — servicio, `/estado` y `cassette nube`

**Files:**
- Modify: `src/cassette_fm/servicio.py` (`iniciar_nube`, registro `Difusores` en `servir`), `src/cassette_fm/api.py` (`crear_servidor(..., extra_estado: Callable[[], dict] | None = None)`), `src/cassette_fm/cli.py` (`cassette nube [regenerar]`)
- Test: `tests/test_servicio.py`, `tests/test_api.py` (o donde estén los tests de `/estado`), `tests/test_cli.py`

**Interfaces:**
- Consumes: `PuenteNube` (Tasks 4–6), `Difusores` (Task 2), `lan_acceso.leer_o_crear_token/regenerar_token/TokenVivo`, `Rutas.nube_token`, `ConfigNube` (Task 1).
- Produces: `iniciar_nube(config, rutas, radio, router, difusores, crear_puente=PuenteNube, intervalo_revision=1.0) -> tuple[Callable[[], None], Callable[[], dict]] | None` (cerrar, info); `None` si `activo = false` o sin bus. `/estado` agrega `"nube": {"conectado": bool, "subiendo": [..]}` solo con el puente activo.

- [ ] **Step 1: Tests que fallan:** `test_nube_apagada_no_arranca_nada` (no se llama a `crear_puente`, no hay hilos nuevos); `test_nube_sin_bus_no_arranca` (error en el log); `test_nube_clave_regenerada_reconecta` (el `TokenVivo` revisado cada `intervalo_revision` llama a `puente.reconectar`); `test_falla_de_la_nube_no_tira_el_servicio`; `test_estado_incluye_nube_solo_si_esta_activa`; `test_cli_nube_muestra_url_estado_y_clave` (con el servicio falso que ya usan los tests del CLI) y `test_cli_nube_regenerar`; `test_cli_nube_apagada_explica_como_prenderla`.
- [ ] **Step 2:** `.venv/bin/python -m pytest tests/test_servicio.py tests/test_cli.py tests/test_api.py -q` → FAIL.
- [ ] **Step 3:** Implementar; `servir` crea `Difusores(lambda: FUENTE_MONITOR if radio.encendida else FUENTE_ESTATICA, max_oyentes=config.lan.max_oyentes)` solo si hay router y (`[lan]` o `[nube]` activo), se lo pasa a ambos, revisa sus fuentes en un solo hilo y lo cierra al final (después del puente y la LAN). El arranque de la nube va envuelto en `try/except` como la LAN.
- [ ] **Step 4:** Suite completa `.venv/bin/python -m pytest -q` → PASS.
- [ ] **Step 5: Commit** `Puente a la nube: lo arranca el servicio, se ve en /estado y en cassette nube`.

### Task 8: Relay de prueba, documentación y prueba en real

**Files:**
- Create: `scripts/relay-de-prueba.py`
- Modify: `README.md` (sección "Radio desde cualquier lado (relay en la nube)"), `docs/project-context.md` (estado), `tests/test_relay_de_prueba.py`

**Interfaces:**
- Consumes: el protocolo de la spec.
- Produces: `relay-de-prueba.py --host 0.0.0.0 --puerto 9000 --clave-archivo ~/.config/cassette-fm/nube.token`: WebSocket `/casa/control` y `/casa/audio`, `PUT /casa/icono/…`, y para oyentes `GET /escuchar?calidad=96` (MP3 por HTTP, sin clave: es solo para la LAN de casa), `GET /estado`, `POST /sintonizar/<emisora>`, `GET /icono/<emisora>`. Manda `demanda` al llegar el primer oyente de una calidad y al irse el último.

- [ ] **Step 1: Test que falla:** `tests/test_relay_de_prueba.py::test_de_punta_a_punta` — levanta el relay de prueba en `127.0.0.1:0` y un `PuenteNube` contra él con una radio y un `Difusores` falsos; un `GET /escuchar?calidad=64` recibe los bytes del codificador falso; `POST /sintonizar/<emisora>` llega a la radio; al cortar el oyente, el relay manda `demanda` vacía y el puente cierra el audio.
- [ ] **Step 2:** `.venv/bin/python -m pytest tests/test_relay_de_prueba.py -q` → FAIL.
- [ ] **Step 3:** Implementar el relay (lo mínimo: un proceso, todo en memoria; servidor `websockets` con `process_request` para las rutas HTTP).
- [ ] **Step 4:** Suite completa → PASS. README y project-context actualizados.
- [ ] **Step 5: Prueba en real** (radio del usuario, autorizado en sesiones anteriores; dejar la radio como estaba): `[nube] activo = true`, `url = "ws://127.0.0.1:9000"`, reiniciar `cassette-fm`, levantar el relay de prueba; `mpv http://127.0.0.1:9000/escuchar?calidad=64` suena; `curl -X POST …/sintonizar/<emisora>` cambia la emisora sin prender los parlantes; `cassette nube` muestra conectado y `[64]`; cortar el relay de prueba y volver a levantarlo → el puente reconecta solo (y mpv vuelve a sonar al relanzarlo); opcional: relay con `--host 0.0.0.0` y el navegador del teléfono en el wifi de casa; cerrar mpv → a los ~5 s no queda `gst-launch` de 64. Volver la config a `activo = false` al terminar (el relay real todavía no existe).
- [ ] **Step 6: Commit** `Puente a la nube: relay de prueba, documentación y prueba de punta a punta`.
