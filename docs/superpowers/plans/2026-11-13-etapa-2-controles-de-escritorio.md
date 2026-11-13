# Etapa 2: Controles de escritorio — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Controlar la radio desde Cinnamon sin abrir una terminal: un applet en el panel (rueda para cambiar de
estación, clic para encender/apagar) y atajos de teclado globales.

**Architecture:** Ambos son clientes livianos de la API local que ya existe (`127.0.0.1:7710`). Los atajos llaman a
la CLI `cassette`. El applet habla HTTP directo con sockets de GIO (sin Soup, para no mezclar versiones con
Cinnamon) y su lógica pura (etiquetas, armado y lectura de HTTP, limitador de rueda) vive en un módulo sin
dependencias de Cinnamon, así se prueba con Node.

**Tech Stack:** Cinnamon 6.4 (applets en JS/GJS), Node 18 (`node --test`) para la lógica del applet, Python 3.12 y
pytest para los atajos, `gsettings`.

**Spec:** [`docs/superpowers/specs/2026-11-13-cassette-fm-design.md`](../specs/2026-11-13-cassette-fm-design.md) (etapa 2)

## Global Constraints

- Beans: `CASSETTE-FM-1rqi` (atajos, Task 1) y `CASSETTE-FM-ryvn` (applet, Tasks 2 y 3), bajo la épica `CASSETTE-FM-zp3c`. Al empezar cada tarea, `beans update <id> -s in-progress`; al terminarla, `-s completed` y se incluye `.beans/` en el commit. La épica se cierra al final de la Task 3.
- Identificadores, mensajes y comentarios **en español**.
- Commits en español, texto plano en imperativo (sin prefijos), terminando con la línea de atribución vigente de la sesión.
- La API es la de la Etapa 1: `GET /estado`, `GET /estaciones`, `POST /siguiente|/anterior|/alternar|/sintonizar {"estacion"}`. `/estado` devuelve `{"encendida": bool, "estacion": str|null, "pista": str|null, "volumen": int, "estaciones": [str], "segundo": float|null}`. Los errores son `{"error": str}` con 400/404/409/503/500.
- Puerto por defecto **7710**, solo `127.0.0.1`.
- Teclas por defecto (verificadas libres en este Cinnamon): `<Super><Alt>Right` siguiente, `<Super><Alt>Left` anterior, `<Super><Alt>Up` alternar encendido.
- Carpeta de instalación de applets: `~/.local/share/cinnamon/applets/<uuid>/`. UUID del applet: `cassette-fm@cassette-fm`.
- Los tests no tocan `gsettings` ni el panel reales: los atajos se prueban con un `gsettings` falso inyectado.
- Los pasos que modifican la sesión del usuario (habilitar el applet en el panel, registrar los atajos reales, reiniciar Cinnamon) **no se ejecutan en esta etapa sin permiso**: se dejan como instrucciones.

## Review Focus

1. **Servicio caído o que se reinicia:** el applet no se cuelga ni lanza excepciones cada 2 s; muestra que no hay servicio y se recupera solo cuando vuelve. → test en Task 2 (`parsearRespuesta` de basura/vacío) y revisión en Task 3.
2. **Ráfagas de la rueda del mouse** (una vuelta genera decenas de eventos): una sola acción por ventana de 150 ms. → test del limitador en Task 2.
3. **Nombres con ñ y acentos por HTTP:** el `Content-Length` se calcula en bytes UTF-8, no en caracteres. → test en Task 2.
4. **Respuestas cortadas o JSON inválido** del servicio: se tratan como "sin servicio", sin excepción. → test en Task 2.
5. **Atajos:** `custom-list` vacía (`@as []`), tecla ya usada por otro atajo del usuario, y volver a correr el comando (no duplica ni pisa una tecla que el usuario cambió). → tests en Task 1.

---

## Estructura de archivos

```
src/cassette_fm/atajos.py                      # Task 1
tests/test_atajos.py
applet/cassette-fm@cassette-fm/logic.js        # Task 2 (lógica pura)
applet/cassette-fm@cassette-fm/metadata.json   # Task 3
applet/cassette-fm@cassette-fm/applet.js       # Task 3
applet/cassette-fm@cassette-fm/settings-schema.json
applet/tests/logic.test.js                     # Task 2 (node --test)
tests/test_applet_logic.py                     # corre node --test desde pytest
scripts/instalar-applet.sh                     # Task 3
```

---

### Task 1: Atajos de teclado (bean `CASSETTE-FM-1rqi`)

**Files:** Create `src/cassette_fm/atajos.py`, `tests/test_atajos.py`; Modify `src/cassette_fm/cli.py` (subcomando `atajos`), `README.md`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True)
class Atajo:
    id: str            # "cassette-fm-siguiente"; es el nombre de la entrada en dconf
    nombre: str        # "cassette-fm: siguiente"
    accion: str        # subcomando de la CLI: "next" | "prev" | "toggle"
    tecla: str         # "<Super><Alt>Right"

ATAJOS: tuple[Atajo, ...]      # los 3 de Global Constraints
RAIZ: str = "/org/cinnamon/desktop/keybindings/custom-keybindings/"

def instalar(ejecutable: str, gsettings: Callable[[list[str]], str]) -> list[str]
    # `gsettings(args)` ejecuta `gsettings *args` y devuelve su stdout.
    # Devuelve los mensajes para el usuario (uno por atajo: instalado / actualizado / omitido por tecla ocupada).
```

Comportamiento que fija el plan:
- Lee `org.cinnamon.desktop.keybindings custom-list` (formato `['custom0', '__dummy__']`, o `@as []` si está vacía) y agrega los ids que falten, **conservando el orden y el resto de las entradas** (incluido `__dummy__` si estaba).
- Cada entrada se escribe en el esquema `org.cinnamon.desktop.keybindings.custom-keybinding:<RAIZ><id>/` con las claves `name`, `command` (`"<ejecutable> <accion>"`) y `binding` (lista de GVariant: `['<Super><Alt>Right']`).
- **Idempotente:** si el id ya existe, actualiza `name` y `command` pero **no toca `binding`** (el usuario pudo cambiarlo).
- Si la tecla ya la usa **otra** entrada de `custom-list` (distinta de las nuestras), omite ese atajo y lo informa.
- `cli.py`: `cassette atajos` usa `shutil.which("cassette")` (ruta absoluta; si no está, error claro "instalá cassette en el PATH (scripts/instalar.sh)" y código 1) y un `gsettings` real con `subprocess.run(["gsettings", *args], capture_output=True, text=True, check=True).stdout`; imprime los mensajes.

- [ ] **Step 1: Tests que fallan** — `tests/test_atajos.py`, con un `GsettingsFalso` (dict `(esquema, clave) → valor`; `get`/`set` con el formato de texto de gsettings, `custom-list` inicial `['custom0', 'custom1', '__dummy__']`, y entradas `custom0`/`custom1` con teclas propias):
  - `test_instala_los_tres_atajos_con_su_comando`: tras `instalar("/home/u/.local/bin/cassette", gs)`, existen `cassette-fm-siguiente|anterior|alternar` con `command == "/home/u/.local/bin/cassette next"` (y `prev`, `toggle`) y `binding == ['<Super><Alt>Right']` (y `Left`, `Up`).
  - `test_conserva_la_lista_y_el_orden`: `custom-list` resultante empieza con `['custom0', 'custom1', 'cassette-fm-siguiente', …]` y conserva `'__dummy__'`.
  - `test_lista_vacia_con_formato_as`: `custom-list` inicial `@as []` → queda con los 3 ids, sin error.
  - `test_es_idempotente`: dos llamadas seguidas dejan la misma lista (sin ids repetidos).
  - `test_no_pisa_la_tecla_que_el_usuario_cambio`: tras instalar, se cambia el `binding` de `cassette-fm-siguiente` a `['<Super>n']`; instalar de nuevo conserva `<Super>n` pero actualiza `command` si cambió el ejecutable.
  - `test_omite_tecla_ocupada_por_otro_atajo`: una entrada ajena con `['<Super><Alt>Right']` → no se instala `siguiente`, el mensaje lo dice nombrando la entrada, y los otros dos sí.
  - `test_cli_atajos_sin_cassette_en_el_path` (monkeypatch de `shutil.which` → `None`): código 1 y el mensaje.
- [ ] **Step 2:** `.venv/bin/pytest tests/test_atajos.py -v` → FAIL (módulo inexistente).
- [ ] **Step 3:** Implementar `atajos.py` (parseo de la lista con `ast.literal_eval` tras sacar el prefijo `@as `) y el subcomando.
- [ ] **Step 4:** Suite completa → PASS.
- [ ] **Step 5:** README: sección "Atajos" con las 3 teclas y `cassette atajos`.
- [ ] **Step 6:** Commit `Atajos de teclado globales de Cinnamon (cassette atajos)`.

---

### Task 2: Lógica pura del applet (bean `CASSETTE-FM-ryvn`, parte 1)

**Files:** Create `applet/cassette-fm@cassette-fm/logic.js`, `applet/tests/logic.test.js`, `tests/test_applet_logic.py`

**Interfaces:**
- Produces (funciones sueltas en el módulo; al final `if (typeof module !== "undefined") module.exports = {...}` para Node; en GJS se usan como `AppletDir.logic.<función>`):

```js
function etiqueta(estado, mostrarEstacion)  // string: nombre de la estación si encendida y mostrarEstacion; '' en otro caso
function tooltip(estado)                    // string de varias líneas, ver abajo; estado null/undefined = servicio caído
function accionDeRueda(direccion)           // 'up' -> 'siguiente', 'down' -> 'anterior', otro -> null
function crearLimitador(esperaMs)           // devuelve (ahoraMs) => bool: true si pasó esperaMs desde la última vez que dio true
function pedidoHttp(metodo, ruta, cuerpo)   // string HTTP/1.0 con \r\n; cuerpo (objeto|undefined) como JSON UTF-8 con Content-Length en BYTES
function parsearRespuesta(texto)            // {codigo: number, datos: any|null}; basura o vacío -> {codigo: 0, datos: null}
```

Textos que fija el plan:
- `tooltip(estado)`: encendida → `"<estación>\n<pista>\nVolumen <n>"` (sin la línea de pista si es `null`); apagada → `"Apagada · volumen <n>"`; `null`/`undefined` → `"cassette-fm no responde"`.
- `pedidoHttp`: primera línea `"<METODO> <ruta> HTTP/1.0"`, cabeceras `Host: 127.0.0.1`, `Content-Type: application/json` y `Content-Length: <bytes>` (solo si hay cuerpo), línea en blanco y el cuerpo.

- [ ] **Step 1: Tests que fallan** — `applet/tests/logic.test.js` con `node:test` + `node:assert/strict`:
  - `etiqueta`: encendida → `"Regueton 2000"`; apagada → `""`; `mostrarEstacion=false` → `""`; `null` → `""`.
  - `tooltip`: encendida con pista; encendida sin pista (2 líneas menos una); apagada; `null`.
  - `accionDeRueda`: `'up'→'siguiente'`, `'down'→'anterior'`, `'left'→null`, `undefined→null`.
  - `crearLimitador(150)`: `(1000)` true; `(1100)` false; `(1160)` true; `(1200)` false (cuenta desde el último true).
  - `pedidoHttp("POST", "/sintonizar", {estacion: "Ñandú"})`: `Content-Length` es `Buffer.byteLength(JSON.stringify(...))` (mayor que la cantidad de caracteres); sin cuerpo no lleva `Content-Length`; empieza con `POST /sintonizar HTTP/1.0\r\n`.
  - `parsearRespuesta`: `"HTTP/1.0 200 OK\r\n...\r\n\r\n{\"encendida\":true}"` → `{codigo: 200, datos: {encendida: true}}`; un 409 con `{"error": "x"}` → `codigo 409` y `datos.error`; `""`, `"basura"` y una respuesta con cuerpo JSON cortado → `{codigo: 0, datos: null}` (sin lanzar).
  - `tests/test_applet_logic.py`: `subprocess.run(["node", "--test", "applet/tests/"])` debe devolver 0; `pytest.mark.skipif(shutil.which("node") is None, ...)`. Verifica que `pytest` cubre el JS.
- [ ] **Step 2:** `node --test applet/tests/` → FAIL (módulo inexistente).
- [ ] **Step 3:** Implementar `logic.js`.
- [ ] **Step 4:** `node --test applet/tests/` y la suite de pytest → PASS.
- [ ] **Step 5:** Commit `Lógica pura del applet de Cinnamon, probada con Node`.

---

### Task 3: Applet de Cinnamon (bean `CASSETTE-FM-ryvn`, parte 2)

**Files:** Create `applet/cassette-fm@cassette-fm/metadata.json`, `applet.js`, `settings-schema.json`, `scripts/instalar-applet.sh`; Modify `README.md`

**Interfaces:**
- Consumes: `logic.js` (Task 2) y la API HTTP (Global Constraints).
- Produces: el applet `cassette-fm@cassette-fm`.

Comportamiento que fija el plan (Cinnamon 6.4, clase `CassetteApplet extends Applet.TextIconApplet`, `main(metadata, orientation, panelHeight, instanceId)`):
- **Panel:** ícono simbólico de audio (`audio-x-generic-symbolic`) + etiqueta de `etiqueta()`; sin etiqueta cuando está apagada.
- **Tooltip:** `tooltip()` (`this.set_applet_tooltip`).
- **Rueda** (`on_applet_scrolled(event)`): `accionDeRueda(event.get_scroll_direction())` con `Clutter.ScrollDirection.UP/DOWN` → `'up'/'down'`, filtrada por `crearLimitador(150)`; hace `POST /siguiente` o `/anterior`.
- **Clic izquierdo** (`on_applet_clicked`): `POST /alternar`.
- **Menú contextual** (clic derecho): se agrega una sección con una entrada por estación (la actual marcada con `▶`) que hace `POST /sintonizar`; se reconstruye cuando cambia la lista o la estación. Más una entrada "Apagar".
- **Sondeo:** `GET /estado` cada 2 s con `GLib.timeout_add_seconds`, y de inmediato después de cada acción. Se detiene en `on_applet_removed_from_panel`.
- **Cliente HTTP:** `Gio.SocketClient` + `connect_to_host_async("127.0.0.1:<puerto>")` → escribir `pedidoHttp(...)` → leer hasta EOF → `parsearRespuesta`. Toda la E/S es asíncrona (nada bloquea el hilo de Cinnamon); cualquier error cae en el estado "sin servicio" (etiqueta vacía, tooltip "cassette-fm no responde") y **no lanza**.
- **Ajustes** (`settings-schema.json`): `puerto` (spinbutton, 7710) y `mostrar_estacion` (switch, true), con `Settings.AppletSettings`.
- `scripts/instalar-applet.sh` (idempotente): enlaza `applet/cassette-fm@cassette-fm` en `~/.local/share/cinnamon/applets/cassette-fm@cassette-fm` y muestra cómo agregarlo al panel (clic derecho en el panel → Applets) y cómo recargar Cinnamon (`Ctrl+Alt+Esc`). **No** edita `enabled-applets` ni reinicia Cinnamon.

- [ ] **Step 1:** `metadata.json` (`uuid`, `name`, `description`, `max-instances: 1`, `icon`) y `settings-schema.json`.
- [ ] **Step 2:** `applet.js` con lo de arriba, usando solo funciones de `logic.js` para todo texto o protocolo (el archivo no duplica lógica).
- [ ] **Step 3: Verificación estática:** `node --check applet/cassette-fm@cassette-fm/applet.js` sin errores; `python3 -m json.tool` sobre los dos JSON; `bash -n scripts/instalar-applet.sh`; un test de pytest (`tests/test_applet_estructura.py`) que verifica que `metadata.json` tiene `uuid == "cassette-fm@cassette-fm"` y coincide con el nombre de la carpeta, y que `applet.js` referencia solo funciones que `logic.js` exporta (`AppletDir.logic.<nombre>` ⊆ `module.exports`).
- [ ] **Step 4:** Ejecutar `scripts/instalar-applet.sh` solo si el usuario lo autorizó; si no, dejarlo como instrucción en el README. (No se puede probar el applet dentro de Cinnamon sin tocar el panel: la prueba real la hace el usuario.)
- [ ] **Step 5:** README: sección "Applet de Cinnamon" (instalar, agregar al panel, qué hace cada gesto, dónde mirar si falla: Looking Glass con `Alt+F2` → `lg` → pestaña Errors).
- [ ] **Step 6:** Suite completa → PASS. Commit `Applet de Cinnamon para controlar la radio`. Cerrar la épica `CASSETTE-FM-zp3c` si ambas tareas están completas.
