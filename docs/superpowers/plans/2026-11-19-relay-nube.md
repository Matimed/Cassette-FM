# Relay en la nube — plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Un relay en Docker (aiohttp) que recibe al puente de la PC (control, audio por calidad, logos) y atiende a
los oyentes con una API privada, listo para publicar en Docker Hub y desplegar en Render gratis.

**Architecture:** Paquete `cassette_relay` en `relay/`, un proceso asyncio: `config` (variables de entorno),
`acceso` (clave de oyentes, cookie firmada, límite de intentos), `oyentes` (colas por oyente y demanda por calidad con
gracia), `casa` (WebSockets y logos de la PC, órdenes) y `app` (rutas, middleware, página de prueba). El puente de la
PC gana el mensaje `latido`. El relay de prueba se borra.

**Tech Stack:** Python 3.12, aiohttp 3.14.5 (relay); `websockets` síncrono y `http.client` en los tests; pytest;
Docker (`python:3.12-slim`).

**Spec:** [`docs/superpowers/specs/2026-11-19-relay-nube-design.md`](../specs/2026-11-19-relay-nube-design.md)
(protocolo: [`2026-11-19-puente-nube-design.md`](../specs/2026-11-19-puente-nube-design.md))

## Global Constraints

- Protocolo versión 1 sin cambios salvo `{"tipo": "latido"}` de la PC al relay. Rutas de la PC: `/casa/control`,
  `/casa/audio?calidad=K`, `PUT /casa/icono/<emisora url-encoded>?v=<versión>`, todas con `Authorization: Bearer <INGEST_TOKEN>`.
- Calidades: 64, 96, 160. Protocolo: 1.
- Variables: `INGEST_TOKEN` (obligatoria), `APP_PASSWORD` (obligatoria, ≥ 8 caracteres), `PORT` (por defecto 8080).
- Valores: gracia de demanda 10 s; cola 15 s de audio (`15 × kbps × 1000 / 8` bytes); oyente trabado 30 s; oyente sin
  audio 20 s; espera de una orden 10 s; `pedir_icono` pendiente vence a los 60 s o al reconectarse el control; ping del
  WebSocket 20 s; sesión 180 días; bloqueo tras el 5.º fallo en 60 s, por 60 s; latido del puente tras 120 s sin mandar.
- Logos: `image/png`, `image/jpeg`, `image/webp`, `image/gif`, hasta 4 MB.
- Nunca en logs, URLs ni la imagen: `INGEST_TOKEN`, `APP_PASSWORD`, la cookie, el encabezado `Authorization`. Log de
  accesos de aiohttp apagado.
- Errores de la API como `{"error": "texto en español"}`.
- `relay/` no importa `cassette_fm` (solo los tests de punta a punta lo hacen).
- Todo el estado en memoria; un solo proceso.
- Commits en español, en `main`, terminando con `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. Un oyente que cierra la conexión mientras no llega audio (PC caída o arrancando) tiene que salir de su calidad en
   segundos, no quedar contado para siempre (la PC seguiría subiendo audio). Test en Task 4.
2. Un oyente que no lee nunca no frena la lectura del audio de la PC ni a otro oyente de la misma calidad. Test en Task 4.
3. Si el control se cae o se reemplaza con órdenes esperando, esas órdenes contestan 503 enseguida (no a los 10 s).
   Test en Task 3.
4. Nombres de emisora con acentos, espacios, `/` y `?` funcionan de ida y vuelta en `/casa/icono/…`,
   `/api/icono/…` y `sintonizar`. Tests en Task 3 y Task 4.
5. Ninguna clave en el log aun con intentos fallidos, 401 de la PC y sesiones: fixture que lo afirma al final de cada
   test (Task 3).

---

### Task 1: Esqueleto, configuración y acceso

**Files:**
- Create: `relay/requirements.txt`, `relay/cassette_relay/__init__.py`, `relay/cassette_relay/config.py`,
  `relay/cassette_relay/acceso.py`
- Create: `relay/tests/test_relay_config.py`, `relay/tests/test_relay_acceso.py`
- Modify: `pyproject.toml` (dev: `aiohttp==3.14.5`; pytest `testpaths = ["tests", "relay/tests"]`,
  `pythonpath = ["relay", "tests"]`)

Los archivos de test del relay llevan el prefijo `test_relay_` (en `tests/` ya hay `test_config.py` y sin
`__init__.py` los nombres repetidos chocan).

**Interfaces:**
- Produces:
  - `config.CALIDADES = (64, 96, 160)`, `config.PROTOCOLO = 1`
  - `@dataclass(frozen=True) class Ajustes: ingest_token: str; app_password: str; puerto: int = 8080;
    gracia: float = 10.0; cola_segundos: float = 15.0; trabado: float = 30.0; sin_audio: float = 20.0;
    espera_orden: float = 10.0; vence_logo: float = 60.0; ping: float = 20.0`
  - `class ErrorConfig(Exception)`; `desde_entorno(env: Mapping[str, str]) -> Ajustes`
  - `acceso.DURACION_SESION = 180 * 24 * 3600`
  - `class Acceso(clave: str, reloj=time.time, max_fallos=5, ventana=60.0, bloqueo=60.0)` con
    `nueva_sesion() -> str`, `sesion_valida(valor: str | None) -> bool`, `probar(clave: str | None) -> str`
    (`"ok"`, `"mal"` o `"bloqueado"`)
  - `acceso.clave_igual(dada: str | None, esperada: str) -> bool` (tiempo constante; la usa también la PC)

- [ ] **Step 1: Tests de config**

```python
def test_lee_las_variables():
    a = desde_entorno({"INGEST_TOKEN": "t" * 40, "APP_PASSWORD": "clave-larga", "PORT": "10000"})
    assert (a.ingest_token, a.app_password, a.puerto) == ("t" * 40, "clave-larga", 10000)

def test_puerto_por_defecto():
    assert desde_entorno({"INGEST_TOKEN": "t", "APP_PASSWORD": "12345678"}).puerto == 8080

@pytest.mark.parametrize("env, falta", [
    ({"APP_PASSWORD": "12345678"}, "INGEST_TOKEN"),
    ({"INGEST_TOKEN": "t"}, "APP_PASSWORD"),
    ({"INGEST_TOKEN": "  ", "APP_PASSWORD": "12345678"}, "INGEST_TOKEN"),
])
def test_falta_una_obligatoria(env, falta):
    with pytest.raises(ErrorConfig, match=falta):
        desde_entorno(env)

def test_clave_corta_sin_mostrarla():
    with pytest.raises(ErrorConfig, match="APP_PASSWORD") as e:
        desde_entorno({"INGEST_TOKEN": "t", "APP_PASSWORD": "corta12"})
    assert "corta12" not in str(e.value)

def test_puerto_invalido():
    with pytest.raises(ErrorConfig, match="PORT"):
        desde_entorno({"INGEST_TOKEN": "t", "APP_PASSWORD": "12345678", "PORT": "ochenta"})
```

- [ ] **Step 2: Tests de acceso** (con un reloj falso `ahora = [1000.0]`, `reloj=lambda: ahora[0]`)

```python
def test_sesion_de_ida_y_vuelta(): a.sesion_valida(a.nueva_sesion()) is True
def test_sesion_vencida(): tras avanzar DURACION_SESION + 1 → False
def test_sesion_adulterada(): cambiar un carácter de la firma o del vencimiento → False; None y "" y "basura" → False
def test_otra_clave_invalida_la_sesion(): Acceso("otra-clave-1").sesion_valida(a.nueva_sesion()) is False
def test_probar(): probar("clave-correcta") == "ok"; probar("mala") == "mal"; probar(None) == "mal"
def test_bloqueo_tras_cinco_fallos():
    # 5 × "mal" → probar(correcta) == "bloqueado"; reloj + 61 → "ok"
def test_fallos_viejos_no_cuentan():
    # 4 fallos, reloj + 61, 1 fallo → probar(correcta) == "ok"
def test_la_sesion_sigue_valida_durante_el_bloqueo():
    # sesion = nueva_sesion(); 5 fallos; sesion_valida(sesion) is True
```

- [ ] **Step 3: Correr y verlos fallar**

Run: `.venv/bin/pip install -e ".[dev]" -q && .venv/bin/pytest relay/tests -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'cassette_relay'`

- [ ] **Step 4: Implementar `config.py` y `acceso.py`**

Cookie: `f"{vence}.{firma}"` con `vence` entero (segundos de `reloj`) y `firma = hmac.new(llave, str(vence).encode(),
sha256).hexdigest()`, `llave = hashlib.sha256(b"cassette-relay-sesion:" + clave.encode()).digest()`; validar con
`hmac.compare_digest` y `vence > reloj()`. Fallos: `deque` de instantes; al llegar a `max_fallos` dentro de `ventana`,
`bloqueado_hasta = reloj() + bloqueo` y se vacía la `deque`. `requirements.txt`: `aiohttp==3.14.5`.

- [ ] **Step 5: Correr y verlos pasar**

Run: `.venv/bin/pytest relay/tests -q`
Expected: todos PASS.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml relay/ docs/superpowers/specs/2026-11-19-relay-nube-design.md docs/superpowers/plans/2026-11-19-relay-nube.md
git commit -m "Relay: esqueleto, configuración por entorno y acceso de los oyentes"
```

---

### Task 2: Oyentes y demanda

**Files:**
- Create: `relay/cassette_relay/oyentes.py`, `relay/tests/test_relay_oyentes.py`

**Interfaces:**
- Consumes: `config.CALIDADES`
- Produces:
  - `class Oyente` con `kbps: int`, `saltos: int`, `cerrado: bool`, `async tomar(timeout: float) -> bytes | None`
    (todo lo encolado, o `None` si no llegó nada en `timeout`; si está cerrado devuelve `b""` enseguida),
    `cerrar() -> None`
  - `class Oyentes(al_cambiar_demanda: Callable[[list[int]], None], gracia: float = 10.0,
    cola_segundos: float = 15.0, reloj=time.monotonic)` con `agregar(kbps) -> Oyente`, `quitar(oyente) -> None`
    (idempotente), `repartir(kbps, datos: bytes) -> None`, `pedidas() -> list[int]` (ordenada), `cuantos(kbps) -> int`
  - Se usa dentro de un loop asyncio (la gracia es `loop.call_later`). `al_cambiar_demanda` se llama solo cuando
    cambia `pedidas()`.

Tests con `asyncio.run(escenario())` (sin plugin de pytest).

- [ ] **Step 1: Tests**

```python
def test_primer_oyente_pide_al_instante():         # agregar(96) → avisos == [[96]]
def test_segundo_oyente_no_repite_la_demanda():    # dos agregar(96) → avisos == [[96]]
def test_ultimo_que_se_va_espera_la_gracia():      # gracia=0.1: quitar → avisos sigue [[96]]; tras 0.2 s → [[96], []]
def test_volver_dentro_de_la_gracia_no_corta():    # quitar y agregar a los 0.05 s; tras 0.2 s avisos == [[96]]
def test_dos_calidades():                          # agregar(64), agregar(160) → último aviso [64, 160]
def test_reparte_a_todos_los_de_esa_calidad():     # 2 oyentes de 96 y 1 de 64; repartir(96, b"abc") → los de 96 toman b"abc", el de 64 tom a None (timeout 0.05)
def test_tomar_junta_lo_encolado():                # repartir b"a", b"b" → tomar() == b"ab"
def test_cola_llena_salta_al_vivo_una_vez():
    # cola_segundos=1.0, kbps=64 → tope 8000 bytes; repartir 5 × 2000 bytes (numerados) sin tomar
    # → saltos == 1 y tomar() == solo lo que llegó después del vaciado (los bytes del 5.º pedazo)
def test_tomar_sin_datos_devuelve_none():          # tomar(0.05) is None
def test_cerrar_despierta_al_que_espera():         # tarea en tomar(5); cerrar(); devuelve b"" en < 0.5 s
def test_quitar_dos_veces_no_rompe():
```

- [ ] **Step 2: Correr y verlos fallar**

Run: `.venv/bin/pytest relay/tests/test_relay_oyentes.py -q`
Expected: FAIL con `ModuleNotFoundError` / `ImportError` de `cassette_relay.oyentes`.

- [ ] **Step 3: Implementar `oyentes.py`**

Cada `Oyente` tiene un `bytearray` y un `asyncio.Event`. Al encolar: si `len(buffer) + len(datos) > tope`, vaciar el
buffer, `saltos += 1` y loguear (debug) antes de agregar. `tope = int(cola_segundos * kbps * 1000 / 8)`.

- [ ] **Step 4: Correr y verlos pasar**

Run: `.venv/bin/pytest relay/tests/test_relay_oyentes.py -q`
Expected: todos PASS.

- [ ] **Step 5: Commit**

```bash
git add relay/cassette_relay/oyentes.py relay/tests/test_relay_oyentes.py
git commit -m "Relay: colas por oyente con salto al vivo y demanda por calidad con gracia"
```

---

### Task 3: Lado de la PC (control, audio, logos, órdenes)

**Files:**
- Create: `relay/cassette_relay/casa.py`, `relay/cassette_relay/app.py`, `relay/tests/conftest.py`,
  `relay/tests/test_relay_casa.py`

**Interfaces:**
- Consumes: `Ajustes`, `CALIDADES`, `PROTOCOLO`, `clave_igual`, `Oyentes`
- Produces:
  - `class Casa(ajustes: Ajustes, oyentes: Oyentes, reloj=time.monotonic)` con handlers aiohttp
    `control(request)`, `audio(request)`, `subir_icono(request)`; y para la API: propiedad `en_linea: bool`,
    `visto_hace() -> int | None`, `radio() -> dict | None`, `icono(nombre) -> tuple[str, str, bytes] | None`
    (versión, tipo, datos), `async orden(tipo: str, **campos) -> tuple[int, dict]` (código HTTP y cuerpo),
    `mandar_demanda(calidades: list[int]) -> None`
  - `app.crear_app(ajustes: Ajustes, web: Path | None = None) -> web.Application` con `app["casa"]`,
    `app["oyentes"]`, `app["acceso"]`; en esta tarea solo rutas `/casa/…` y `GET /salud`.
  - `conftest.py`:
    - `TOKEN = "token-de-la-casa-" + "x" * 30`, `CLAVE = "clave-de-oyentes"`
    - `class RelayEnHilo(**ajustes)`: levanta `crear_app` con `web.AppRunner` + `TCPSite("127.0.0.1", 0)` en un hilo
      con su propio loop. Expone:
      - `url` (`http://…`) y `ws` (`ws://…`)
      - `app`
      - `en_loop(funcion)`, que corre la función en el loop y devuelve su resultado
      - `pedir(metodo, ruta, cuerpo=None, headers=None) -> (status, headers, bytes)` con `http.client`
      - `cerrar()`
    - Fixture `relay` (con `gracia=0.2`, `espera_orden=1.0`, `vence_logo=0.5`, `trabado=0.5`, `sin_audio=1.0`), que al
      final afirma que ni `TOKEN` ni `CLAVE` aparecen en `caplog.text`.
    - Helper `casa(relay, ruta="/casa/control", token=TOKEN)`, que conecta con `websockets.sync.client.connect`.
    - Helper `recibir_tipo(ws, tipo, timeout=3)`.

Nota de diseño: el reemplazo del control cierra el anterior con código 1000 y falla sus órdenes pendientes con 503.
Un `estado` es válido si `seq` es entero y mayor al último de esa conexión.

- [ ] **Step 1: Tests**

```python
def test_salud_sin_clave(relay):                      # GET /salud → 200, b"ok"
def test_control_sin_clave_401(relay):                # connect sin header y con "Bearer otra" → InvalidStatus 401
def test_audio_e_icono_sin_clave_401(relay):          # /casa/audio?calidad=96 → 401; PUT /casa/icono/A sin header → 401
def test_hola_contesta_demanda(relay):                # mandar hola → recibir_tipo "demanda" con calidades == []
def test_protocolo_desconocido_cierra(relay):         # hola con protocolo 2 → la conexión se cierra
def test_en_linea_y_visto_hace(relay):                # tras hola: en_linea True, visto_hace None; cerrar → en_linea False y visto_hace >= 0; radio() conserva el último estado
def test_guarda_estado_y_descarta_seq_viejo(relay):   # estado seq 2 (estacion "B"), luego seq 1 (estacion "A") → radio()["estacion"] == "B"; radio() sin "tipo" ni "seq"
def test_seq_vuelve_a_empezar_al_reconectar(relay):   # conexión nueva con seq 1 se acepta
def test_tipo_desconocido_json_roto_y_latido(relay):  # no cortan: después de los tres, un estado se guarda
def test_pide_cada_logo_una_vez(relay):               # estado con iconos {"Más Gasolina F.M.": "v1"} dos veces → un solo pedir_icono
def test_logo_pendiente_vence_y_se_repide(relay):     # vence_logo=0.5: tras 0.6 s, un nuevo estado lo vuelve a pedir
def test_logo_se_repide_al_reconectar(relay):
def test_subir_logo(relay):                           # PUT /casa/icono/M%C3%A1s%20Gasolina%20F.M.?v=v1 image/png → 204; icono(...) == ("v1", "image/png", datos); ya no se pide
def test_logo_rechazado(relay):                       # emisora fuera del estado → 400; image/svg+xml → 415; > 4 MB → 413
def test_logos_de_emisoras_que_ya_no_estan_se_borran(relay):
def test_orden_ok_y_error(relay):                     # en_loop(orden("sintonizar", estacion="a/b?c")) mientras un hilo contesta resultado ok → (200, {"ok": True}); con ok False y error → (409, {"error": "esa emisora no existe"}); la PC recibe "estacion": "a/b?c"
def test_orden_fuera_de_linea(relay):                 # → (503, {"error": "la radio está fuera de línea"})
def test_orden_sin_respuesta(relay):                  # espera_orden=1 → (504, …) en ~1 s
def test_orden_pendiente_y_control_caido(relay):      # se cierra el control con la orden esperando → 503 en < 0.5 s
def test_control_nuevo_reemplaza(relay):              # segunda conexión: la primera se cierra; en_linea sigue True
def test_audio_calidad_invalida(relay):               # calidad=128 → cierre 1008
def test_audio_reparte_a_los_oyentes(relay):          # en_loop: o = oyentes.agregar(96); la PC manda b"mp3" por /casa/audio?calidad=96 → o.tomar() == b"mp3"
def test_audio_nuevo_reemplaza(relay):
def test_demanda_al_primer_oyente_y_al_vencer_la_gracia(relay):  # control conectado; agregar(64) → recibe demanda [64]; quitar → tras gracia, demanda []
```

- [ ] **Step 2: Correr y verlos fallar**

Run: `.venv/bin/pytest relay/tests/test_relay_casa.py -q`
Expected: FAIL con `ImportError` de `cassette_relay.casa` / `cassette_relay.app`.

- [ ] **Step 3: Implementar `casa.py` y `app.py` (rutas de la PC y `/salud`)**

Auth antes de `ws.prepare()` (401 JSON). `web.WebSocketResponse(heartbeat=ajustes.ping, max_msg_size=…)` del tamaño de
un pedazo de audio holgado (64 KB). Órdenes: `id` incremental en texto, `asyncio.Future` por `id`.
`mandar_demanda` es no bloqueante (`asyncio.create_task` del `send_json`) y no hace nada si no hay control.
Logos: `client_max_size` de la app en 4 MB + margen. Los logs no deben incluir nada de los encabezados.

- [ ] **Step 4: Correr y verlos pasar**

Run: `.venv/bin/pytest relay/tests -q`
Expected: todos PASS.

- [ ] **Step 5: Commit**

```bash
git add relay/
git commit -m "Relay: conexión de la PC (control, audio por calidad, logos y órdenes)"
```

---

### Task 4: API de los oyentes y página de prueba

**Files:**
- Modify: `relay/cassette_relay/app.py`
- Create: `relay/web/index.html`, `relay/tests/test_relay_api.py`

**Interfaces:**
- Consumes: `Casa` (Task 3), `Oyentes` (Task 2), `Acceso` (Task 1), fixtures de `conftest.py`
- Produces: rutas `POST /api/entrar`, `POST /api/salir`, `GET /api/estado`, `POST /api/sintonizar`,
  `POST /api/siguiente`, `POST /api/anterior`, `GET /api/escuchar`, `GET /api/icono/{nombre}`, `GET /` (página),
  según la tabla del spec. Cookie `sesion`.

Helpers de test: `bearer = {"Authorization": f"Bearer {CLAVE}"}`; `pc_en_linea(relay)` conecta el control y manda
`hola` + un estado con emisoras `["A", "B", "Más Gasolina F.M.", "a/b?c"]`.

- [ ] **Step 1: Tests**

```python
def test_api_sin_acceso_401(relay):                   # GET /api/estado sin nada → 401 JSON con "error"
def test_entrar_pone_cookie(relay):                   # POST /api/entrar {"clave": CLAVE} json → 204; Set-Cookie sesion=…; HttpOnly; SameSite=Lax; Max-Age=15552000; sin Secure; con esa cookie GET /api/estado → 200
def test_cookie_secure_detras_del_proxy(relay):      # entrar con X-Forwarded-Proto: https → Set-Cookie con Secure
def test_entrar_clave_mala_y_bloqueo(relay):          # 5 × clave mala → 401; la 6.ª (correcta) → 429; Bearer correcto → 429; la cookie obtenida antes sigue con 200
def test_entrar_exige_json(relay):                    # Content-Type text/plain → 415
def test_salir_borra_la_cookie(relay):                # Set-Cookie sesion=""; Max-Age=0
def test_estado_fuera_de_linea(relay):                # {"en_linea": False, "visto_hace": None, "calidades": [64, 96, 160], "radio": None}
def test_estado_en_linea(relay):                      # radio["estacion"] == "A", sin "tipo"/"seq"
def test_sintonizar(relay):                           # POST /api/sintonizar {"estacion": "a/b?c"}; la PC contesta ok → 200 {"ok": True}
def test_sintonizar_invalido(relay):                  # {"estacion": ""} y {"estacion": 3} → 400; sin JSON → 415
def test_siguiente_fuera_de_linea(relay):             # 503 {"error": "la radio está fuera de línea"}
def test_icono(relay):                                # tras subir "Más Gasolina F.M." v1: GET /api/icono/M%C3%A1s%20Gasolina%20F.M.?v=v1 → 200 image/png, Cache-Control con immutable; sin ?v → no-cache; desconocido → 404
def test_escuchar_fuera_de_linea_503(relay):
def test_escuchar_calidad_invalida_400(relay):        # calidad=128 y calidad=abc
def test_escuchar_recibe_audio(relay):                # PC en línea; GET /api/escuchar?calidad=64 (Bearer) → 200 audio/mpeg, no-store; la PC recibe demanda [64]; manda b"x" * 1000 por /casa/audio?calidad=64 → el oyente lee esos bytes
def test_oyente_que_se_va_sin_audio_sale_de_la_cuenta(relay):   # Review Focus 1: escuchar, cerrar el socket sin que haya llegado audio → cuantos(64) == 0 en < 3 s y, tras la gracia, demanda []
def test_oyente_lento_no_frena_a_los_demas(relay):    # Review Focus 2: oyente A con socket de SO_RCVBUF 4096 que no lee; oyente B lee; la PC manda 400 KB en pedazos de 4 KB → B recibe los 400 KB completos, en orden; A termina cortado (trabado=0.5) o con saltos
def test_oyente_sin_audio_se_corta(relay):            # sin_audio=1: escuchar y no mandar nada → la respuesta termina en < 2,5 s
def test_pagina_publica(relay):                       # GET / sin clave → 200 text/html, contiene "/api/entrar" y "/api/escuchar"
```

- [ ] **Step 2: Correr y verlos fallar**

Run: `.venv/bin/pytest relay/tests/test_relay_api.py -q`
Expected: FAIL (404 en las rutas `/api/…` y `/`).

- [ ] **Step 3: Implementar la API en `app.py` y la página `relay/web/index.html`**

Middleware para `/api/` (salvo `entrar`): primero la cookie (`sesion_valida`); si no, Bearer con `probar` (`"mal"` →
401, `"bloqueado"` → 429); sin nada, 401 sin contar fallo. Escuchar: `agregar` → `StreamResponse` preparado →
bucle `tomar(timeout=1)` acumulando el tiempo sin datos hasta `sin_audio`, `asyncio.wait_for(resp.write(…),
trabado)`, y en cada vuelta comprobar si el oyente se fue (transporte cerrado) → `quitar` en `finally`. Página: un solo
HTML con JS inline: formulario de clave (`POST /api/entrar`), estado cada 3 s, botones de emisoras con logo
`/api/icono/<n>?v=<versión>`, selector de calidad, `<audio>` que reabre `/api/escuchar?calidad=K&t=<ahora>` en
`error`/`ended` mientras el usuario quiere escuchar, y reabre al cambiar de emisora.

- [ ] **Step 4: Correr y verlos pasar**

Run: `.venv/bin/pytest relay/tests -q`
Expected: todos PASS.

- [ ] **Step 5: Commit**

```bash
git add relay/
git commit -m "Relay: API privada de los oyentes, reparto del audio y página de prueba"
```

---

### Task 5: Latido del puente, punta a punta y fuera el relay de prueba

**Files:**
- Modify: `src/cassette_fm/puente_nube.py` (`PuenteNube(..., latido_segundos: float = 120.0)`), `tests/test_puente_nube.py`
- Create: `relay/tests/test_relay_punta_a_punta.py`
- Delete: `scripts/relay-de-prueba.py`, `tests/test_relay_de_prueba.py`
- Modify: `README.md` (sección del relay), `docs/superpowers/specs/2026-11-19-puente-nube-design.md` (agrega `latido`),
  `docs/project-context.md`

**Interfaces:**
- Consumes: `RelayEnHilo`, `TOKEN`, `CLAVE` (conftest del relay); `RadioFalsa`, `Codificadores`, `EsperaCorta` de
  `test_puente_nube` (importable por `pythonpath = ["relay", "tests"]`); `PuenteNube`.
- Produces: el puente manda `{"tipo": "latido"}` cuando pasaron `latido_segundos` desde su último mensaje por el control.

- [ ] **Step 1: Tests**

```python
# tests/test_puente_nube.py
def test_latido_si_no_hay_nada_que_mandar(relay, armar):
    armar(latido_segundos=0.3)
    c = relay.control()
    relay.recibir_tipo(c, "estado")
    assert relay.recibir_tipo(c, "latido", timeout=1.5) == {"tipo": "latido"}

# relay/tests/test_relay_punta_a_punta.py — PuenteNube real (RadioFalsa, gst.registro(), url=relay.ws, token=lambda: TOKEN, espera=EsperaCorta())
def test_estado_y_orden_de_punta_a_punta(relay, puente):   # GET /api/estado (Bearer) → en_linea y estacion "A"; POST sintonizar "B" → 200; radio.ordenes == [("sintonizar", "B", False)]
def test_audio_de_punta_a_punta(relay, puente, gst):       # GET /api/escuchar?calidad=64 → aparece gst.de(64); emitir b"\xff\xfb" * 2000 → el oyente lo lee; cerrar el oyente → tras la gracia el codificador de 64 termina
def test_logo_de_punta_a_punta(relay, puente, tmp_path):   # radio con iconos {"A": logo.png} → GET /api/icono/A → 200 con esos bytes
```

- [ ] **Step 2: Correr y verlos fallar**

Run: `.venv/bin/pytest tests/test_puente_nube.py::test_latido_si_no_hay_nada_que_mandar relay/tests/test_relay_punta_a_punta.py -q`
Expected: el del latido FAIL (`TypeError` por `latido_segundos` o `no llegó un 'latido'`). Los de punta a punta pueden
pasar ya, porque prueban piezas hechas. Si pasan, anotarlo en el ledger: son de integración, no de comportamiento nuevo.

- [ ] **Step 3: Implementar el latido**

`_mandar` registra `self._ultimo_envio = self._reloj()`. El bucle de `_sesion` manda `latido` cuando
`reloj() - _ultimo_envio >= latido_segundos`.

- [ ] **Step 4: Borrar el relay de prueba y actualizar docs**

Borrar `scripts/relay-de-prueba.py` y `tests/test_relay_de_prueba.py`. En el README, "Probarlo en casa" pasa a
apuntar a `relay/README.md` (relay real en local con `url = "ws://127.0.0.1:8080"`). En el spec del puente, sumar
`latido` a los mensajes de la PC al relay. En `project-context.md`, el relay ya existe (`relay/`) y lo que falta es la
web.

- [ ] **Step 5: Correr toda la suite**

Run: `.venv/bin/pytest -q 2>&1 | tail -3`
Expected: todo PASS, sin tests del relay de prueba.

- [ ] **Step 6: Commit**

```bash
git add -A src tests relay scripts README.md docs
git commit -m "Puente a la nube: latido para que Render no duerma el relay; pruebas de punta a punta; fuera el relay de prueba"
```

---

### Task 6: Imagen Docker, guía de despliegue y prueba en real

**Files:**
- Create: `relay/cassette_relay/__main__.py`, `relay/Dockerfile`, `relay/.dockerignore`, `relay/README.md`
- Create: `relay/tests/test_relay_main.py`

**Interfaces:**
- Consumes: `desde_entorno`, `ErrorConfig`, `crear_app`
- Produces: `python -m cassette_relay`. Con la config mala, sale con código 2 y una línea `error: …` en stderr. Si no,
  escucha en `0.0.0.0:$PORT` con `access_log=None` y logging INFO.

- [ ] **Step 1: Test**

```python
def test_sin_variables_sale_con_error():
    r = subprocess.run([sys.executable, "-m", "cassette_relay"], env={"PATH": os.environ["PATH"]},
                       cwd=RELAY_DIR, capture_output=True, text=True, timeout=10)
    assert r.returncode == 2 and "INGEST_TOKEN" in r.stderr

def test_arranca_y_contesta_salud(tmp_path):
    # PORT libre, INGEST_TOKEN y APP_PASSWORD de prueba → Popen; esperar GET /salud == 200 (≤ 5 s); terminar el proceso
    # y afirmar que ni el token ni la clave aparecen en su salida
```

- [ ] **Step 2: Correr y verlo fallar**

Run: `.venv/bin/pytest relay/tests/test_relay_main.py -q`
Expected: FAIL (`No module named cassette_relay.__main__`).

- [ ] **Step 3: Implementar `__main__.py`, `Dockerfile`, `.dockerignore`**

`Dockerfile`: `FROM python:3.12-slim`, `PYTHONUNBUFFERED=1`, `pip install --no-cache-dir -r requirements.txt`, copia
`cassette_relay/` y `web/`, usuario sin privilegios, `EXPOSE 8080`, `CMD ["python", "-m", "cassette_relay"]`.
`.dockerignore`: todo afuera salvo `requirements.txt`, `cassette_relay/`, `web/`.

- [ ] **Step 4: Correr y verlo pasar**

Run: `.venv/bin/pytest relay/tests/test_relay_main.py -q`
Expected: PASS.

- [ ] **Step 5: Construir y probar la imagen**

Run:
```bash
docker build -t cassette-relay:prueba relay/ \
  && docker run -d --rm --name relay-prueba -p 18080:8080 -e INGEST_TOKEN=prueba-token-larga-1234567890 \
       -e APP_PASSWORD=prueba-clave cassette-relay:prueba \
  && sleep 2 && curl -s localhost:18080/salud && docker image ls cassette-relay:prueba --format '{{.Size}}' \
  && docker stats --no-stream --format '{{.MemUsage}}' relay-prueba; docker stop relay-prueba
```
Expected: `ok`, imagen de menos de ~200 MB, memoria de menos de ~80 MB.

- [ ] **Step 6: `relay/README.md`**

Debe cubrir:
- Qué es y qué variables usa.
- Correrlo en local: venv o `docker run`. `INGEST_TOKEN` es el contenido de `~/.config/cassette-fm/nube.token`, que
  no hay que pegar en la línea de comandos: se pasa con `--env-file` o con `-e INGEST_TOKEN` tomado del entorno.
- Apuntar el puente con `[nube] url = "ws://127.0.0.1:8080"` y reiniciar el servicio.
- Publicar con `docker build -t <usuario>/cassette-relay:latest relay/` y `docker push`.
- Crear el servicio en Render: "Existing Image", plan Free, variables, health check `/salud`, y redesplegar tras cada
  push.
- `[nube] url = "wss://<servicio>.onrender.com"`.
- Escuchar con VLC/mpv con el encabezado Bearer y reconexión (`mpv --loop` / VLC "Repetir").
- Qué esperar del plan gratis: se duerme sin la PC y despierta en ~1 min; corte a los 100 min.

- [ ] **Step 7: Prueba en real con la PC (con el usuario al tanto)**

1. Respaldar `~/.config/cassette-fm/config.toml` en el scratchpad.
2. Agregar `[nube] activo = true`, `url = "ws://127.0.0.1:8080"`.
3. Correr el relay en local con `INGEST_TOKEN` leído del archivo (sin mostrarlo).
4. Reiniciar `cassette-fm`.
5. Verificar con `curl` + Bearer:
   - `GET /api/estado`: `en_linea: true` con la emisora real.
   - `GET /api/escuchar?calidad=64` durante 5 s: el MP3 es válido (`ffprobe` o `file`).
   - Al cortar, el codificador de la PC se apaga (`cassette nube` sin "subiendo").
6. Ofrecer al usuario abrir `http://<ip-lan>:8080/` en el teléfono.
7. Restaurar la config y reiniciar el servicio.

Expected: todo lo de arriba. Si algo falla, debuggear antes de cerrar.

- [ ] **Step 8: Commit**

```bash
git add relay/
git commit -m "Relay: imagen Docker, arranque por entorno y guía de despliegue en Render"
```
