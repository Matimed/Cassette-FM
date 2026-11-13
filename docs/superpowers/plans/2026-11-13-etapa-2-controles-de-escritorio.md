# Etapa 2: Controles de escritorio — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Acordado con el usuario (13/11), sobre el plan original:** los atajos de arriba/abajo son de **volumen** (de a 10 %), no de encender/apagar. Volumen en 0 = apagada (equivale a mutear) y subirlo estando apagada la enciende. Todo se instala con **un solo comando** (`scripts/instalar-todo.sh`); lo único manual es recargar Cinnamon.

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

- Beans: `CASSETTE-FM-nq19` (volumen 0 = apagada, Task 1), `CASSETTE-FM-1rqi` (atajos, Task 2) y `CASSETTE-FM-ryvn` (applet, Tasks 3 y 4), bajo la épica `CASSETTE-FM-zp3c`. Al empezar cada tarea, `beans update <id> -s in-progress`; al terminarla, `-s completed` y se incluye `.beans/` en el commit. La épica se cierra al final de la Task 4.
- Identificadores, mensajes y comentarios **en español**.
- Commits en español, texto plano en imperativo (sin prefijos), terminando con la línea de atribución vigente de la sesión.
- La API es la de la Etapa 1: `GET /estado`, `GET /estaciones`, `POST /siguiente|/anterior|/alternar|/sintonizar {"estacion"}`. `/estado` devuelve `{"encendida": bool, "estacion": str|null, "pista": str|null, "volumen": int, "estaciones": [str], "segundo": float|null}`. Los errores son `{"error": str}` con 400/404/409/503/500.
- Puerto por defecto **7710**, solo `127.0.0.1`.
- Teclas por defecto (verificadas libres en este Cinnamon): `<Super><Alt>Right` siguiente (`next`), `<Super><Alt>Left` anterior (`prev`), `<Super><Alt>Up` volumen +10 (`vol +10`), `<Super><Alt>Down` volumen −10 (`vol -10`).
- Carpeta de instalación de applets: `~/.local/share/cinnamon/applets/<uuid>/`. UUID del applet: `cassette-fm@cassette-fm`.
- Los tests no tocan `gsettings` ni el panel reales: los atajos se prueban con un `gsettings` falso inyectado.
- Los tests nunca tocan la sesión real. Durante el desarrollo **no se ejecuta** nada que modifique el panel, los atajos o el servicio del usuario (ni `instalar-todo.sh`): el usuario lo corre al final, él lo pidió así, con un solo comando.

## Review Focus

1. **Servicio caído o que se reinicia:** el applet no se cuelga ni lanza excepciones cada 2 s; muestra que no hay servicio y se recupera solo cuando vuelve. → test en Task 3 (`parsearRespuesta` de basura/vacío) y revisión en Task 4.
2. **Ráfagas de la rueda del mouse** (una vuelta genera decenas de eventos): una sola acción por ventana de 150 ms. → test del limitador en Task 3.
3. **Nombres con ñ y acentos por HTTP:** el `Content-Length` se calcula en bytes UTF-8, no en caracteres. → test en Task 3.
4. **Respuestas cortadas o JSON inválido** del servicio: se tratan como "sin servicio", sin excepción. → test en Task 3.
5. **Atajos:** `custom-list` vacía (`@as []`), tecla ya usada por otro atajo del usuario, y volver a correr el comando (no duplica ni pisa una tecla que el usuario cambió). → tests en Task 2.
6. **Volumen y encendido:** bajar de 10 a 0 apaga; subir estando apagada enciende con la estación de siempre (o la primera); bajar el volumen estando apagada **no** enciende; `cassette on` con el volumen en 0 no deja la radio muda; el volumen se guarda aunque se apague. → tests en Task 1.
7. **Instalación repetida:** correr `instalar-todo.sh` dos veces no duplica el applet en el panel, los atajos ni el enlace. → tests en Task 4.

---

## Estructura de archivos

```
src/cassette_fm/radio.py                       # Task 1 (modifica volumen)
src/cassette_fm/atajos.py                      # Task 2
tests/test_atajos.py
src/cassette_fm/applet.py                      # Task 4 (enlace + habilitar en el panel)
tests/test_applet_instalacion.py
applet/cassette-fm@cassette-fm/logic.js        # Task 3 (lógica pura)
applet/cassette-fm@cassette-fm/metadata.json   # Task 4
applet/cassette-fm@cassette-fm/applet.js       # Task 4
applet/cassette-fm@cassette-fm/settings-schema.json
applet/tests/logic.test.js                     # Task 3 (node --test)
tests/test_applet_logic.py                     # corre node --test desde pytest
scripts/instalar-todo.sh                       # Task 4 (servicio + atajos + applet)
```

---

### Task 1: El volumen en 0 apaga la radio (bean `CASSETTE-FM-nq19`)

**Files:** Modify `src/cassette_fm/radio.py`, `tests/test_radio.py`, `README.md`

**Interfaces:**
- Consumes: `Radio.volumen(valor=None, delta=None) -> int`, `Radio.encender()`, `Radio._apagar()`, `Radio._sintonizar()` de la Etapa 1.
- Produces: el mismo `Radio.volumen`, con estas reglas nuevas (sin cambiar firmas):
  - Después de aplicar y guardar el volumen: si el resultado es **0** y la radio está encendida → se apaga.
  - Si el resultado es **mayor que el volumen previo**, la radio está apagada y el resultado es > 0 → `encender()` (estación guardada, o la primera). Si falla con `SinEstaciones`, el volumen ya quedó guardado y el error se propaga.
  - Bajar (o dejar igual) el volumen con la radio apagada **no** la enciende.
  - `_sintonizar` con el volumen en 0 lo sube primero a `VOLUMEN_MINIMO = 10` (aplicado al reproductor y guardado), para que `on`/`next`/`tune` no dejen la radio muda.
  - `apagar()` por sí solo **no** toca el volumen guardado.

- [ ] **Step 1: Tests que fallan** — en `tests/test_radio.py` (con `ReproductorFalso`):
  - `test_volumen_cero_apaga`: encendida con volumen 10, `volumen(delta=-10) == 0` → `encendida` False, última llamada `("detener",)`.
  - `test_subir_volumen_enciende_la_estacion_guardada`: apagada, `Estado(estacion="B", volumen=0)`, `volumen(delta=10) == 10` → encendida, `sintonizadas() == ["B"]`.
  - `test_subir_volumen_enciende_la_primera_si_no_hay_guardada`.
  - `test_apagar_conserva_el_volumen_y_subir_lo_suma`: encendida con 70, `apagar()`, `volumen(delta=10) == 80` → encendida.
  - `test_bajar_volumen_apagada_no_enciende`: apagada con 50, `volumen(delta=-10) == 40` → sigue apagada, sin `sintonizar`.
  - `test_bajar_en_cero_apagada_sigue_apagada`: apagada con 0, `volumen(delta=-10) == 0` → sin cambios ni `sintonizar`.
  - `test_encender_con_volumen_cero_sube_a_minimo`: apagada con 0, `encender()` → `volumen() == 10` y el reproductor recibió `("volumen", 10)` antes de `sintonizar`.
  - `test_subir_sin_estaciones_guarda_el_volumen_y_falla`: sin estaciones, `volumen(delta=10)` lanza `SinEstaciones` y `volumen()` devuelve 10.
- [ ] **Step 2:** `.venv/bin/pytest tests/test_radio.py -v` → FAIL.
- [ ] **Step 3:** Implementar en `radio.py`.
- [ ] **Step 4:** Suite completa → PASS (los tests viejos de volumen siguen verdes).
- [ ] **Step 5:** README: una línea en "Uso": "el volumen en 0 apaga la radio y subirlo la enciende".
- [ ] **Step 6:** Commit `El volumen en 0 apaga la radio y subirlo la enciende`.

---

### Task 2: Atajos de teclado (bean `CASSETTE-FM-1rqi`)

**Files:** Create `src/cassette_fm/atajos.py`, `tests/test_atajos.py`; Modify `src/cassette_fm/cli.py` (subcomando `atajos`), `README.md`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True)
class Atajo:
    id: str            # "cassette-fm-siguiente"; es el nombre de la entrada en dconf
    nombre: str        # "cassette-fm: siguiente"
    accion: str        # argumentos de la CLI: "next" | "prev" | "vol +10" | "vol -10"
    tecla: str         # "<Super><Alt>Right"

ATAJOS: tuple[Atajo, ...]      # los 4 de Global Constraints; ids: cassette-fm-siguiente, -anterior, -volumen-mas, -volumen-menos
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
  - `test_instala_los_cuatro_atajos_con_su_comando`: tras `instalar("/home/u/.local/bin/cassette", gs)`, existen `cassette-fm-siguiente|anterior|volumen-mas|volumen-menos` con `command == "/home/u/.local/bin/cassette next"` (y `prev`, `vol +10`, `vol -10`) y `binding == ['<Super><Alt>Right']` (y `Left`, `Up`, `Down`).
  - `test_conserva_la_lista_y_el_orden`: `custom-list` resultante empieza con `['custom0', 'custom1', 'cassette-fm-siguiente', …]` y conserva `'__dummy__'`.
  - `test_lista_vacia_con_formato_as`: `custom-list` inicial `@as []` → queda con los 4 ids, sin error.
  - `test_es_idempotente`: dos llamadas seguidas dejan la misma lista (sin ids repetidos).
  - `test_no_pisa_la_tecla_que_el_usuario_cambio`: tras instalar, se cambia el `binding` de `cassette-fm-siguiente` a `['<Super>n']`; instalar de nuevo conserva `<Super>n` pero actualiza `command` si cambió el ejecutable.
  - `test_omite_tecla_ocupada_por_otro_atajo`: una entrada ajena con `['<Super><Alt>Right']` → no se instala `siguiente`, el mensaje lo dice nombrando la entrada, y los otros tres sí.
  - `test_cli_atajos_sin_cassette_en_el_path` (monkeypatch de `shutil.which` → `None`): código 1 y el mensaje.
- [ ] **Step 2:** `.venv/bin/pytest tests/test_atajos.py -v` → FAIL (módulo inexistente).
- [ ] **Step 3:** Implementar `atajos.py` (parseo de la lista con `ast.literal_eval` tras sacar el prefijo `@as `) y el subcomando.
- [ ] **Step 4:** Suite completa → PASS.
- [ ] **Step 5:** README: sección "Atajos" con las 4 teclas y `cassette atajos`.
- [ ] **Step 6:** Commit `Atajos de teclado globales de Cinnamon (cassette atajos)`.

---

### Task 3: Lógica pura del applet (bean `CASSETTE-FM-ryvn`, parte 1)

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

### Task 4: Applet de Cinnamon e instalación en un comando (bean `CASSETTE-FM-ryvn`, parte 2)

**Files:** Create `applet/cassette-fm@cassette-fm/metadata.json`, `applet.js`, `settings-schema.json`, `src/cassette_fm/applet.py`, `tests/test_applet_instalacion.py`, `tests/test_applet_estructura.py`, `scripts/instalar-todo.sh`; Modify `src/cassette_fm/cli.py` (subcomando `applet`), `README.md`

**Interfaces:**
- Consumes: `logic.js` (Task 3), la API HTTP (Global Constraints), `atajos.instalar` (Task 2).
- Produces: el applet `cassette-fm@cassette-fm`, y en Python:

```python
UUID = "cassette-fm@cassette-fm"

def instalar(origen: Path, applets_dir: Path, gsettings: Callable[[list[str]], str]) -> list[str]
    # origen = <repo>/applet/cassette-fm@cassette-fm ; applets_dir = ~/.local/share/cinnamon/applets
    # 1) enlace simbólico applets_dir/UUID -> origen (idempotente; si ya apunta a origen, no hace nada;
    #    si existe otra cosa en ese lugar, NO la pisa: lo informa y no sigue)
    # 2) agrega el applet a org.cinnamon enabled-applets (idempotente)
    # Devuelve los mensajes para el usuario.
```

Reglas de `enabled-applets` (lista de strings `panel:zona:posición:uuid:instancia`, p. ej. `panel1:right:4:weather@mockturtl:20`):
- Si alguna entrada ya tiene `uuid == UUID`, no se agrega nada ("ya estaba en el panel").
- Si no: se agrega `panel1:right:<pos>:<UUID>:<id>` con `pos = (máxima posición de la zona right de panel1) + 1` e `id = (máximo id de instancia de toda la lista) + 1`; el resto de la lista **se conserva tal cual y en el mismo orden**. Lista vacía (`@as []`) → `panel1:right:0:<UUID>:1`.
- `cli.py`: `cassette applet` llama a `applet.instalar` con `origen = Path(__file__).resolve().parents[2] / "applet" / UUID` (error claro y código 1 si no existe: "no se encuentra el applet; corré desde una instalación en modo editable") y un `gsettings` real (el mismo helper que `cassette atajos`).

Comportamiento del applet (Cinnamon 6.4, clase `CassetteApplet extends Applet.TextIconApplet`, `main(metadata, orientation, panelHeight, instanceId)`):
- **Panel:** ícono simbólico de audio (`audio-x-generic-symbolic`) + etiqueta de `etiqueta()`; sin etiqueta cuando está apagada.
- **Tooltip:** `tooltip()` (`this.set_applet_tooltip`).
- **Rueda** (`on_applet_scrolled(event)`): `accionDeRueda(event.get_scroll_direction())` con `Clutter.ScrollDirection.UP/DOWN` → `'up'/'down'`, filtrada por `crearLimitador(150)`; hace `POST /siguiente` o `/anterior`.
- **Clic izquierdo** (`on_applet_clicked`): `POST /alternar`.
- **Menú contextual** (clic derecho): una sección con una entrada por estación (la actual marcada con `▶`) que hace `POST /sintonizar`; se reconstruye cuando cambia la lista o la estación. Más una entrada "Apagar".
- **Sondeo:** `GET /estado` cada 2 s con `GLib.timeout_add_seconds`, y de inmediato después de cada acción. Se detiene en `on_applet_removed_from_panel`.
- **Cliente HTTP:** `Gio.SocketClient` + `connect_to_host_async("127.0.0.1:<puerto>")` → escribir `pedidoHttp(...)` → leer hasta EOF → `parsearRespuesta`. Toda la E/S es asíncrona; cualquier error cae en el estado "sin servicio" (etiqueta vacía, tooltip "cassette-fm no responde") y **no lanza**.
- **Ajustes** (`settings-schema.json`): `puerto` (spinbutton, 7710) y `mostrar_estacion` (switch, true), con `Settings.AppletSettings`.

`scripts/instalar-todo.sh` (idempotente; **el único comando que corre el usuario**), en este orden y parando ante el primer error (`set -euo pipefail`):
1. `scripts/instalar.sh` (venv, enlace `~/.local/bin/cassette`, unidad systemd).
2. `systemctl --user restart cassette-fm` (para que el servicio ya levantado tome el código nuevo; corta la música un instante).
3. `cassette atajos`.
4. `cassette applet`.
5. Mensaje final: "Listo. Recargá Cinnamon con Ctrl+Alt+Esc para ver el applet." (no reinicia Cinnamon por su cuenta).

- [ ] **Step 1: Tests que fallan** — `tests/test_applet_instalacion.py`, con un `GsettingsFalso` y `tmp_path` como `applets_dir` y como origen:
  - `test_crea_el_enlace_y_habilita_el_applet`: el enlace existe y apunta al origen; `enabled-applets` termina con `panel1:right:<pos>:cassette-fm@cassette-fm:<id>` con `pos` e `id` según la regla (probar con la lista de este escritorio: `['panel1:left:1:xapp-status@cinnamon.org:4', 'panel1:right:9:notifications@cinnamon.org:5', 'panel1:right:16:user@cinnamon.org:15', 'panel1:right:8:brightness-and-gamma-applet@cardsurf:16', 'panel1:center:0:calendar@cinnamon.org:13', 'panel1:right:2:multicore-sys-monitor@ccadeptic23:22']` → `pos == 17`, `id == 23`) y el resto de la lista idéntico y en el mismo orden.
  - `test_lista_vacia_con_formato_as`: `@as []` → `['panel1:right:0:cassette-fm@cassette-fm:1']`.
  - `test_es_idempotente`: dos llamadas dejan una sola entrada y el mismo enlace; la segunda informa "ya estaba".
  - `test_no_pisa_algo_ajeno_en_la_carpeta_de_applets`: si `applets_dir/UUID` es un directorio real con otro contenido, no se toca, no se modifica `enabled-applets` y el mensaje lo explica.
  - `test_reemplaza_un_enlace_roto_o_viejo`: un enlace a otra ruta que ya no existe se reapunta al origen.
  - `test_cli_applet_sin_la_carpeta_del_applet` (monkeypatch del origen inexistente): código 1 y el mensaje.
- [ ] **Step 2:** `.venv/bin/pytest tests/test_applet_instalacion.py -v` → FAIL. **Step 3:** implementar `applet.py` y el subcomando. **Step 4:** → PASS.
- [ ] **Step 5:** `metadata.json` (`uuid`, `name`, `description`, `max-instances: 1`, `icon`) y `settings-schema.json`; `applet.js` con lo de arriba, usando solo funciones de `logic.js` para todo texto o protocolo (no duplica lógica).
- [ ] **Step 6: Verificación estática:** `node --check applet/cassette-fm@cassette-fm/applet.js`; `python3 -m json.tool` sobre los dos JSON; `bash -n scripts/instalar-todo.sh`; `tests/test_applet_estructura.py`: `metadata.json` tiene `uuid == "cassette-fm@cassette-fm"` igual al nombre de la carpeta, y `applet.js` referencia solo funciones que `logic.js` exporta (`AppletDir.logic.<nombre>` ⊆ `module.exports`).
- [ ] **Step 7:** `scripts/instalar-todo.sh`, **sin ejecutarlo** (modifica la sesión real: lo corre el usuario). README: sección "Instalación del escritorio" con ese único comando, qué hace cada gesto del applet y cada atajo, y dónde mirar si algo falla (Looking Glass: `Alt+F2` → `lg` → pestaña Errors; `journalctl --user -u cassette-fm -e`). No se puede probar el applet dentro de Cinnamon sin tocar el panel: la prueba real la hace el usuario.
- [ ] **Step 8:** Suite completa → PASS. Commit `Applet de Cinnamon e instalación del escritorio en un comando`. Cerrar la épica `CASSETTE-FM-zp3c` si todas sus tareas están completas.
