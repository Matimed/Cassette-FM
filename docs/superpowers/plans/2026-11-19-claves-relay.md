# Claves del relay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Una clave maestra en el entorno del relay y claves de `escucha` o `completa` que se crean y borran desde la PC con `cassette claves`, aplicadas por el relay (permiso y corte inmediato al borrar).

**Architecture:** La lista vive en la PC (`claves.json`, solo huellas). El servicio la revisa cada 1 s y el puente la manda al relay por el control (`{"tipo": "claves", …}`) al conectar y cuando cambia. El relay la guarda en memoria; la cookie de sesión lleva `id` y `permiso` de la clave con que se entró, y el relay corta el audio de las claves que ya no están.

**Tech Stack:** Python 3.12, aiohttp 3.14.5 (relay), websockets (puente), pytest. Tests de la PC en `tests/`, del relay en `relay/tests/`; se corren con `.venv/bin/pytest`.

**Spec:** [`docs/superpowers/specs/2026-11-19-claves-relay-design.md`](../specs/2026-11-19-claves-relay-design.md)

## Global Constraints

- Claves fuera de logs, URLs y argv. Ni la PC ni el relay guardan una clave generada en claro: solo su huella (SHA-256 hex de la clave normalizada). Se muestra una sola vez, al crearla.
- Los nombres de las personas no salen de la PC: al relay llegan solo `id`, `permiso` y `huella`.
- Formato de clave: 16 caracteres del alfabeto `0123456789abcdefghjkmnpqrstvwxyz` (base32 de Crockford, minúscula), en grupos de 4 separados por `-`. Normalizar = pasar a minúscula y sacar espacios y guiones. La maestra no se normaliza.
- `claves.json` en `Rutas.claves` (`config.with_name("claves.json")`), modo 0600, escritura atómica (tmp + `os.replace`). Registro: `{"id" (8 hex), "nombre", "permiso", "huella", "creada" (ISO 8601 con zona)}`. Nombre: 1 a 40 caracteres, sin saltos de línea, único sin distinguir mayúsculas ni espacios de los bordes. Permisos: `"escucha"` o `"completa"`.
- Mensaje del control: `{"tipo": "claves", "claves": [{"id", "permiso", "huella"}, …]}`. Relay: a lo sumo 200, `id` de 8 hex sin repetir, `permiso` válido, `huella` de 64 hex; si algo no valida se ignora el mensaje entero y rige la lista anterior. `PROTOCOLO` sigue en 1.
- Cookie `sesion=<id>.<permiso>.<vence>.<hmac>`, 180 días, firmada con la llave derivada de la maestra. La maestra es `id = "maestra"`, siempre completa. Bloqueo por intentos: 5 fallos en 60 s, 60 s, global. Una cookie que no vale da 401 y no cuenta como intento.
- `APP_PASSWORD` pasa a `MASTER_PASSWORD` (mínimo 8 caracteres). `INGEST_TOKEN` no cambia.
- Logs del relay sin claves ni huellas; se puede registrar `id` y permiso, y la cantidad de claves.
- Español rioplatense en mensajes, commits en `main` con la línea `Co-Authored-By` que pida la sesión. No correr `cassette claves nueva` real contra la config del usuario ni mostrar `cassette nube`: imprimen claves en pantalla; los tests usan `tmp_path`.
- Cada tarea deja la suite completa (`.venv/bin/pytest`) en verde.

## Review Focus

1. La PC y el relay tienen que calcular la misma huella para la misma clave tipeada de cualquier forma (mayúsculas, guiones, espacios): están en dos paquetes y la fórmula está duplicada.
2. Una lista vacía y válida (se borró la última clave) revoca a todos menos la maestra: no es "lista ignorada".
3. `claves.json` roto en el servicio no pierde la última lista buena; ausente equivale a lista vacía.
4. Una cookie con basura (`²`, miles de dígitos, partes de más, permiso inventado, firma de otro permiso) da 401, nunca 500, y no suma al bloqueo.
5. Un mensaje `claves` mal formado (tipos raros, repetidos, de más de 200, huella corta) no desarma la lista vigente ni corta a nadie.

---

### Task 1: Módulo de claves de la PC

**Files:**
- Create: `src/cassette_fm/claves.py`, `tests/test_claves.py`
- Modify: `src/cassette_fm/config.py` (`Rutas.claves`)

**Interfaces:**
- Produces (`cassette_fm.claves`):
  - `PERMISOS = ("escucha", "completa")`; `class ErrorClaves(Exception)` (el mensaje nunca lleva una clave).
  - `normalizar(clave: str) -> str`; `huella(clave: str) -> str` (SHA-256 hex de `normalizar(clave)` en UTF-8); `generar_clave() -> str` (`xxxx-xxxx-xxxx-xxxx`, con `secrets`).
  - `leer(ruta: Path) -> list[dict]`: `[]` si el archivo no existe; `ErrorClaves` si el JSON está roto o su estructura no es la del registro.
  - `crear(ruta: Path, nombre: str, permiso: str, ahora: Callable[[], datetime] = …) -> tuple[str, dict]`: devuelve `(clave en claro, registro)`; `ErrorClaves` si el nombre es inválido o repetido, o el permiso no es válido (sin tocar el archivo).
  - `borrar(ruta: Path, nombre: str) -> dict`: el registro borrado; `ErrorClaves` si no existe.
  - `para_relay(claves: list[dict]) -> list[dict]`: solo `id`, `permiso`, `huella`.
- `Rutas.claves -> Path`.

- [ ] **Step 1: Escribir los tests** (`tests/test_claves.py`, con `tmp_path`):
  - `test_generar_clave_formato`: coincide con `^[0-9a-hjkmnp-tv-z]{4}(-[0-9a-hjkmnp-tv-z]{4}){3}$`; dos claves seguidas difieren.
  - `test_huella_ignora_mayusculas_guiones_y_espacios`: `huella("K7QM-ABCD-2345-6789") == huella(" k7qmabcd 2345-6789 ")` y es un hex de 64 caracteres.
  - `test_crear_guarda_huella_no_la_clave`: tras `crear`, el texto del archivo no contiene la clave ni su forma normalizada; el registro tiene `id` de 8 hex, `huella == huella(clave)`, `creada` parseable; modo del archivo `0o600`; `leer` devuelve lo mismo.
  - `test_crear_validaciones`: nombre repetido (`"Mamá"` vs `" mamá "`), vacío, de 41 caracteres, con `\n`, permiso `"admin"` → `ErrorClaves`, y el archivo queda igual que antes.
  - `test_borrar` (por nombre sin distinguir mayúsculas; inexistente → `ErrorClaves`).
  - `test_leer_ausente_es_vacia` / `test_leer_roto` (JSON roto, `{"claves": 3}`, registro sin `huella`, `permiso` inválido → `ErrorClaves`).
  - `test_para_relay_sin_nombres`: `para_relay([reg]) == [{"id":…, "permiso":…, "huella":…}]` y ni el nombre ni la fecha aparecen.
  - `test_ids_unicos_en_muchas_claves`: 50 `crear` seguidos → 50 ids distintos.
- [ ] **Step 2:** Correr `.venv/bin/pytest tests/test_claves.py -q`. Expected: FAIL (`No module named 'cassette_fm.claves'`).
- [ ] **Step 3:** Implementar `claves.py` con las firmas de arriba y `Rutas.claves` en `config.py:158` (junto a `nube_token`). Escritura atómica con 0o600 como `lan_acceso._escribir`; el `id` se reintenta si choca.
- [ ] **Step 4:** Correr `.venv/bin/pytest tests/test_claves.py -q`, después `.venv/bin/pytest -q`. Expected: PASS y suite verde.
- [ ] **Step 5: Commit** `git add src/cassette_fm/claves.py src/cassette_fm/config.py tests/test_claves.py && git commit -m "Claves: registro de claves de la PC (formato, huella, claves.json)"`

---

### Task 2: Comando `cassette claves`

**Files:**
- Modify: `src/cassette_fm/cli.py` (parser en `_armar_parser`, función `_claves`, despacho en `main`)
- Test: `tests/test_cli.py` (usa `_rutas_tmp`)

**Interfaces:**
- Consumes: `claves.leer/crear/borrar/ErrorClaves/PERMISOS`, `Rutas.claves`, `cfg.nube.activo`, el `_SI` y el estilo de confirmación de `_borrar`.
- Produces: `cassette claves` (lista), `cassette claves nueva NOMBRE [--escucha | --completa]` (grupo mutuamente excluyente, por defecto escucha), `cassette claves borrar NOMBRE [--si]`. Nombre con espacios sin comillas no se soporta (un solo argumento).

- [ ] **Step 1: Escribir los tests:**
  - `test_claves_nueva_imprime_la_clave_una_vez`: `main(["claves","nueva","Mamá"]) == 0`; la salida trae una clave con el formato, el aviso de que no se vuelve a mostrar y el permiso `escucha`; el archivo tiene la huella de esa clave; después `main(["claves"])` no la vuelve a imprimir.
  - `test_claves_nueva_completa`: `--completa` guarda `completa`; `--escucha --completa` juntos → error de argparse (`SystemExit(2)`).
  - `test_claves_nueva_repetida_sale_con_1`: stderr con el mensaje, archivo intacto.
  - `test_claves_lista_vacia_recuerda_la_maestra` y `test_claves_lista_muestra_nombre_permiso_y_fecha` (sin huella ni id en la salida).
  - `test_claves_borrar_con_si`, `test_claves_borrar_sin_terminal_exige_si` (código 1, no borra), `test_claves_borrar_pregunta_y_responde_no` (monkeypatch de `input` y `sys.stdin.isatty`), `test_claves_borrar_inexistente`.
  - `test_claves_avisa_si_la_nube_esta_apagada`: con `[nube]` apagado la salida de `nueva` incluye una línea que dice que rigen al activar `[nube]`.
  - `test_claves_archivo_roto_sale_con_1`.
- [ ] **Step 2:** `.venv/bin/pytest tests/test_cli.py -q -k claves`. Expected: FAIL (argumentos inválidos).
- [ ] **Step 3:** Implementar `_claves(args, cfg, rutas) -> int` y el subparser (`claves` con `accion` opcional `nueva|borrar`, sin `parents=[comun]`: no habla con el servicio). La confirmación de `borrar` reutiliza el patrón de `_borrar`.
- [ ] **Step 4:** `.venv/bin/pytest tests/test_cli.py -q`, después la suite. Expected: PASS.
- [ ] **Step 5: Commit** `git add src/cassette_fm/cli.py tests/test_cli.py && git commit -m "CLI: cassette claves (nueva, borrar, lista)"`

---

### Task 3: El servicio y el puente mandan la lista

**Files:**
- Modify: `src/cassette_fm/puente_nube.py` (`PuenteNube.poner_claves`, `_sesion`), `src/cassette_fm/servicio.py` (`iniciar_nube`)
- Test: `tests/test_puente_nube.py`, `tests/test_servicio.py` (agregar `poner_claves` a `PuenteFalso` y que guarde las listas)

**Interfaces:**
- Consumes: `claves.leer`, `claves.para_relay`, `claves.ErrorClaves`, `Rutas.claves`.
- Produces: `PuenteNube.poner_claves(claves: list[dict]) -> None` (seguro entre hilos; `claves` ya en forma de `para_relay`). `_sesion` manda `{"tipo":"claves","claves":[…]}` justo después de `hola` si ya se llamó a `poner_claves` alguna vez (sin llamada, no manda nada: los tests existentes no cambian), y de nuevo por el control abierto cuando la lista cambia, sin reconectar. En `iniciar_nube`, la lista del archivo se pone antes de `iniciar()` y el hilo `revisar` la vuelve a leer en cada vuelta.

- [ ] **Step 1: Tests del puente** (con `RelayFalso`/`armar`):
  - `test_claves_salen_despues_del_hola`: `poner_claves(L)` antes de conectar → el primer mensaje es `hola` y el segundo `{"tipo":"claves","claves":L}`.
  - `test_sin_poner_claves_no_manda_nada`: con `armar()` simple, ni `hola`→`estado` cambia ni llega un `claves` (cubierto por `test_al_conectar_manda_hola_y_estado`, que debe seguir verde).
  - `test_cambio_de_claves_se_manda_sin_reconectar`: con el control abierto, `poner_claves(L2)` → llega `claves` con `L2` por la misma conexión (`len(relay.conexiones)` no sube).
  - `test_claves_se_reenvian_al_reconectar`: se corta el control → la conexión nueva recibe `claves` después de su `hola`.
  - `test_poner_claves_vacia_se_manda`: `[]` sale como `{"claves": []}`.
- [ ] **Step 2: Tests del servicio** (con `PuenteFalso`, `intervalo_revision=0.05`):
  - `test_nube_pone_las_claves_antes_de_iniciar`: con `claves.crear` previo, `PuenteFalso` recibe `para_relay(lista)` antes de `iniciado`; sin archivo recibe `[]`.
  - `test_nube_cambio_en_claves_json_llega_al_puente`: tras `crear` y luego `borrar`, el puente recibe cada lista nueva (esperar con `esperar`), y no recibe listas repetidas si el archivo no cambió.
  - `test_nube_archivo_roto_mantiene_la_ultima_lista`: se rompe el archivo → no llega nada nuevo, hay un error en `caplog` sin claves ni huellas, y cuando vuelve a ser válido llega la lista.
  - `test_nube_archivo_borrado_manda_lista_vacia`.
- [ ] **Step 3:** `.venv/bin/pytest tests/test_puente_nube.py tests/test_servicio.py -q -k "claves"`. Expected: FAIL.
- [ ] **Step 4:** Implementar. En el puente, la lista pendiente y un `threading.Event` de cambio (el bucle de `_sesion` ya sondea cada `_VUELTA_LECTURA`). En el servicio, comparar contra la última lista mandada; un archivo roto se loguea una sola vez por episodio.
- [ ] **Step 5:** `.venv/bin/pytest -q`. Expected: suite verde.
- [ ] **Step 6: Commit** `git add src/cassette_fm/puente_nube.py src/cassette_fm/servicio.py tests/test_puente_nube.py tests/test_servicio.py && git commit -m "Puente a la nube: la lista de claves sale al relay al conectar y cuando cambia"`

---

### Task 4: El relay entiende identidades (maestra y sesiones con id y permiso)

**Files:**
- Modify: `relay/cassette_relay/config.py`, `relay/cassette_relay/acceso.py`, `relay/cassette_relay/api.py` (middleware y `entrar`), `relay/tests/ayudas_relay.py`, `relay/tests/test_relay_config.py`, `relay/tests/test_relay_acceso.py`, `relay/tests/test_relay_api.py`, `relay/tests/test_relay_main.py`
- Test: `relay/tests/test_relay_acceso.py`

**Interfaces:**
- Produces:
  - `config.MAESTRA = "maestra"`; `Ajustes.clave_maestra` reemplaza a `app_password`; `desde_entorno` lee `MASTER_PASSWORD` (mensajes de error con ese nombre, sin valores).
  - `acceso.PERMISOS`, `@dataclass(frozen=True) Identidad(id: str, permiso: str)`, `normalizar(clave: str) -> str`, `huella(clave: str) -> str` (misma fórmula que `cassette_fm.claves`).
  - `Acceso(maestra, reloj, max_fallos, ventana, bloqueo)` con: `poner_claves(claves: list[dict]) -> None` (ya validadas; reemplaza la lista y marca que llegó una), `nueva_sesion(identidad: Identidad) -> str`, `identidad_de_sesion(valor: str | None) -> Identidad | None`, `probar(clave: str | None) -> tuple[str, Identidad | None]` (`"ok"`, `"mal"` o `"bloqueado"`).
  - Reglas de `identidad_de_sesion`: formato `<id>.<permiso>.<vence>.<hmac>` (`vence` solo dígitos ASCII, firma sobre `"<id>.<permiso>.<vence>"`, no vencida); `id == MAESTRA` vale con permiso completa; otro `id` vale si está en la lista recibida (y rige el permiso de la lista) o, mientras no haya llegado ninguna lista, con el permiso firmado de la cookie.
  - El middleware deja la `Identidad` en el pedido (mecanismo a elección del builder); `entrar` pone la cookie de `nueva_sesion(identidad)`. Sin permisos todavía en las rutas (Task 6).
- El helper `relay` y `CLAVE` de `ayudas_relay.py` siguen igual (ahora es la maestra); `RelayEnHilo` usa `clave_maestra=CLAVE`.

- [ ] **Step 1: Escribir/adaptar los tests** (`test_relay_acceso.py`; adaptar `sesion_valida`/`probar` viejos a la API nueva; en config y main, `MASTER_PASSWORD`):
  - `test_huella_igual_a_la_de_la_pc`: para varias entradas (`"K7QM-ABCD-2345-6789"`, `" k7qmabcd23456789 "`, `"ÁÉ ñ"`), `acceso.huella(x) == cassette_fm.claves.huella(x)`; y `generar_clave()` de la PC normalizada pasa por `normalizar` sin cambios.
  - `test_probar_maestra`, `test_probar_clave_generada` (tras `poner_claves`: `("ok", Identidad(id, permiso))` aun tipeada en mayúsculas y con guiones), `test_clave_generada_no_entra_antes_de_la_primera_lista`, `test_clave_borrada_no_entra`, `test_probar_clave_corta_o_enorme` (4 KB de basura → `"mal"` sin error).
  - `test_sesion_de_ida_y_vuelta_maestra_y_generada`, `test_sesion_de_clave_borrada_vale_solo_antes_de_la_primera_lista` (con lista sin el id → `None`; sin lista → la identidad firmada), `test_sesion_toma_el_permiso_de_la_lista` (cookie firmada `escucha`, lista dice `completa` → `completa`), `test_sesion_adulterada` (cambiar el permiso de `escucha` a `completa` sin refirmar → `None`; otra maestra → `None`), `test_sesion_vencida`.
  - `test_cookie_con_basura_es_none_no_500`: `"1.escucha.²3.ab"`, `"abcd1234.escucha." + "9"*5000 + ".x"`, `"a.b.c"`, `"abcd1234.root.99999999999.ff"`, cinco partes, `None`, `""` → `None` sin excepción.
  - Bloqueo (los existentes) con la API nueva; `test_cookie_invalida_no_suma_fallos`: cien cookies malas y la maestra sigue entrando.
  - API: el test de `entrar` + cookie ahora con formato nuevo; `test_api_cookie_con_basura_da_401` (por HTTP, con `²`).
- [ ] **Step 2:** `.venv/bin/pytest relay/tests -q`. Expected: FAIL.
- [ ] **Step 3:** Implementar. La comparación de huellas recorre toda la lista con `hmac.compare_digest`. Mantener `DURACION_SESION`, `clave_igual`.
- [ ] **Step 4:** `.venv/bin/pytest relay/tests -q`, después la suite completa. Expected: PASS.
- [ ] **Step 5: Commit** `git add relay && git commit -m "Relay: MASTER_PASSWORD e identidades (id y permiso) en la sesión"`

---

### Task 5: El relay recibe la lista y corta a las claves borradas

**Files:**
- Modify: `relay/cassette_relay/acceso.py` (`validar_claves`), `relay/cassette_relay/casa.py` (mensaje `claves`), `relay/cassette_relay/oyentes.py` (`id` por oyente, `cortar_fuera`), `relay/cassette_relay/app.py` (conexión), `relay/cassette_relay/api.py` (`escuchar` pasa el id)
- Test: `relay/tests/test_relay_acceso.py`, `relay/tests/test_relay_oyentes.py`, `relay/tests/test_relay_casa.py`, `relay/tests/test_relay_api.py`

**Interfaces:**
- Consumes: `Acceso.poner_claves`, `Identidad`, `config.MAESTRA`.
- Produces:
  - `acceso.validar_claves(datos: object) -> list[dict] | None`: la lista (de dicts con solo `id`, `permiso`, `huella`) si cumple las reglas del Global Constraints, si no `None`. `[]` es válida.
  - `Oyentes.agregar(kbps: int, id: str = MAESTRA) -> Oyente` (el `Oyente` guarda `id`); `Oyentes.cortar_fuera(vigentes: set[str]) -> int`: cierra (`oyente.cerrar()`) los oyentes cuyo `id` no es `MAESTRA` y no está en `vigentes`; devuelve cuántos.
  - `Casa(ajustes, oyentes, reloj=…, al_recibir_claves: Callable[[list[dict]], None] | None = None)`: ante `{"tipo":"claves"}` válido llama a `al_recibir_claves(lista)`; inválido → aviso en el log sin contenidos y no llama. `crear_app` conecta ese callback a `acceso.poner_claves(lista)` + `oyentes.cortar_fuera({c["id"] for c in lista})`.
  - `GET /api/escuchar` anota el oyente con el `id` de la identidad del pedido.

- [ ] **Step 1: Escribir los tests:**
  - `validar_claves`: lista válida; `[]` válida; `None`, `{}`, `"x"`, `3` → `None`; 201 elementos → `None`; 200 → válida; `id` repetido, `id` de 7 o 9 hex o con mayúsculas, `permiso` `"admin"`, `huella` de 63 o con no-hex, elemento que no es dict, campo extra (se descarta, no invalida) → los inválidos dan `None`; ninguno lanza excepción.
  - Oyentes: `cortar_fuera({"a"})` cierra los de `id` `"b"`, deja los de `"a"` y los de `MAESTRA`, devuelve la cantidad; los cerrados dejan de recibir `repartir`.
  - Casa (`relay` + `pc_en_linea`): mandar `claves` válido → `Acceso` lo conoce (`relay.app[ACCESO]`); mandar uno inválido (tipos raros, repetido, 201) deja la lista anterior y no corta a nadie; el log del relay no contiene ninguna huella (la fixture `relay` ya verifica que no estén `TOKEN` ni la maestra; agregar las huellas del test).
  - API de punta a punta con el relay real y un control de mentira: (a) tras mandar `claves` con una clave `escucha` (huella de la `generar_clave` del test) `POST /api/entrar` con esa clave da 204; antes de mandarla da 401; (b) una clave en audio (`GET /api/escuchar` abierto con su Bearer) se corta (lectura termina) cuando llega una lista sin su `id`; con **lista vacía** también; el audio abierto con la maestra sigue; (c) una sesión creada por la gracia (relay sin lista) con un `id` que la primera lista no trae queda cortada.
- [ ] **Step 2:** `.venv/bin/pytest relay/tests -q -k "claves or cortar or validar"`. Expected: FAIL.
- [ ] **Step 3:** Implementar. La validación es estricta y total (cualquier tipo raro devuelve `None`, no excepción).
- [ ] **Step 4:** `.venv/bin/pytest relay/tests -q` y la suite. Expected: PASS.
- [ ] **Step 5: Commit** `git add relay && git commit -m "Relay: recibe la lista de claves por el control y corta a las borradas"`

---

### Task 6: Permisos en la API y en la página

**Files:**
- Modify: `relay/cassette_relay/api.py` (403 en órdenes, `permiso` en `/api/estado`), `relay/web/index.html`
- Test: `relay/tests/test_relay_api.py`

**Interfaces:**
- Consumes: la `Identidad` del pedido (Task 4), la lista conectada (Task 5).
- Produces: `POST /api/sintonizar|siguiente|anterior` con permiso `escucha` → 403 `{"error": "esta clave es solo para escuchar"}` (se decide antes de leer el cuerpo y de hablar con la PC); `GET /api/estado` suma `"permiso": "escucha" | "completa"`. La página lee `permiso` y esconde `#emisoras` interactivas, `#anterior` y `#siguiente` con `escucha` (muestra emisora actual y logos), y escribe el error si una orden da 403.

- [ ] **Step 1: Escribir los tests** (relay real + `pc_en_linea` + `acceso.poner_claves` directo con `relay.en_loop`):
  - `test_escucha_no_puede_dar_ordenes`: con Bearer y con cookie de una clave `escucha`, las tres órdenes dan 403 y la PC (control falso) **no** recibe ningún mensaje `sintonizar/siguiente/anterior`; un cuerpo que no es JSON también da 403 (no 415).
  - `test_completa_si_puede`: `completa` sintoniza (200) usando el `_contestar` ya existente.
  - `test_estado_trae_el_permiso`: maestra → `completa`; escucha → `escucha`; escucha ve `radio`, logos y puede abrir `/api/escuchar`.
  - `test_la_maestra_sigue_con_la_pc_desconectada`: sin control, la maestra entra y `estado` dice `en_linea: false`.
  - `test_pagina_usa_el_permiso`: `GET /` contiene la lectura de `permiso` (control mínimo: el proyecto no prueba JS).
- [ ] **Step 2:** `.venv/bin/pytest relay/tests/test_relay_api.py -q -k "permiso or escucha or completa or maestra"`. Expected: FAIL.
- [ ] **Step 3:** Implementar el chequeo como paso común a las tres órdenes; actualizar `index.html` (`textContent`, nada de `innerHTML`).
- [ ] **Step 4:** `.venv/bin/pytest -q`. Expected: suite verde.
- [ ] **Step 5: Commit** `git add relay && git commit -m "Relay: las claves de solo escucha no pueden cambiar de emisora"`

---

### Task 7: Punta a punta con el puente real y documentación

**Files:**
- Modify: `relay/tests/test_relay_punta_a_punta.py`, `relay/README.md`, `relay/Dockerfile` (comentario), `README.md`, `docs/superpowers/specs/2026-11-19-puente-nube-design.md`, `docs/superpowers/specs/2026-11-19-relay-nube-design.md` (nota al tope), `docs/project-context.md`

**Interfaces:**
- Consumes: todo lo anterior; `armar_puente` y `RadioFalsa` de las pruebas existentes, `claves.crear/borrar/para_relay`.

- [ ] **Step 1: Escribir los tests:**
  - `test_claves_de_punta_a_punta`: con `claves.crear(tmp_path/"claves.json", "Mamá", "escucha")` y `puente.poner_claves(para_relay(leer(...)))`, esperar a que `POST /api/entrar` con esa clave dé 204; `estado.permiso == "escucha"`; `sintonizar` da 403 y la radio no recibe órdenes; la maestra sí sintoniza.
  - `test_borrar_la_clave_corta_el_audio`: la clave abre `/api/escuchar` (se ve en `relay.app[OYENTES].cuantos`), `claves.borrar` + `poner_claves(para_relay([]))` → la conexión de audio termina y la API con su cookie da 401; un oyente con la maestra sigue.
  - `test_relay_reiniciado_recibe_la_lista_de_nuevo`: el relay despierta sin lista, la PC reconecta (`puente.reconectar()`), la clave vuelve a entrar.
- [ ] **Step 2:** `.venv/bin/pytest relay/tests/test_relay_punta_a_punta.py -q`. Expected: los tres pasan (la funcionalidad ya existe); si alguno falla, es un defecto de tareas anteriores: arreglarlo con su test en la tarea que lo causó.
- [ ] **Step 3: Documentación.** `relay/README.md`: variable `MASTER_PASSWORD` (en la tabla y en los comandos de fish), una sección "Claves" (`cassette claves nueva/borrar/lista`, qué es escucha y qué completa, que la lista se aplica en segundos, que sin la PC conectada solo entra la maestra y las sesiones abiertas siguen), la API con `403` y `permiso`, y corregir la frase de que quien ya entró sigue durante el bloqueo. `README.md`: el comando `cassette claves`. Spec del puente: el mensaje `claves`. Spec del relay: nota arriba que apunta a este diseño y dice que `APP_PASSWORD` pasó a `MASTER_PASSWORD`. `project-context.md`: estado actual. Dockerfile: el comentario nombra `MASTER_PASSWORD`.
- [ ] **Step 4:** `grep -rn "APP_PASSWORD" . --include="*" --exclude-dir=.git --exclude-dir=.venv` solo debe aparecer en el spec de claves, la nota del spec del relay y los planes viejos. Después `.venv/bin/pytest -q`. Expected: suite verde.
- [ ] **Step 5: Commit** `git add -A relay README.md docs && git commit -m "Claves del relay: pruebas de punta a punta y documentación"`
