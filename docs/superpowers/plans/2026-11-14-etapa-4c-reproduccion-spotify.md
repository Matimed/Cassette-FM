# Etapa 4c: emisoras de Spotify que suenan (Soloist) — plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Las emisoras de Spotify suenan por Spotify Soloist con la agenda de la radio: estática al sintonizar, temas
encadenados por Spotify, DJ con ducking suave, volumen parejo con las locales, y la radio se apaga y avisa si otro
dispositivo toma Spotify o si algo falla.

**Architecture:** Un `ReproductorSpotify` con la misma interfaz que el `Reproductor` de mpv: le habla a la Web API
(`PUT /me/player/play` con la lista `uris` de la agenda y `position_ms`, shuffle y repeat apagados) y al WebSocket de
Soloist (eventos de tema, posición y dispositivo; `set_volume` para el volumen y las rampas). Un `Reproductores` (en la
radio) elige el de mpv o el de Spotify según `Estacion.fuente` y detiene al otro; la estática de sintonía la toca el mpv
de la música. Soloist corre como servicio systemd de usuario.

**Tech Stack:** Python 3.12, `websockets` (cliente síncrono, `websockets.sync.client`), urllib, mpv, systemd de usuario.

**Spec:** `docs/superpowers/specs/2026-11-14-etapa-4-spotify-design.md` — secciones 4, 5, 6 y 7 (y lo que quedó de 4a: `cassette estado` muestra la fuente).

## Global Constraints

- TDD; suite: `CASSETTE_DJ_MODELOS=$HOME/.local/share/cassette-dj/modelos .venv/bin/pytest -q`. Los tests no tocan Spotify ni Soloist reales: Web API con `servidor_http`, Soloist con un WebSocket falso (`websockets.sync.server`).
- Commits en español, imperativo, con `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Git local en `main`.
- **No se usa la cola de Spotify** (es de la cuenta): se manda una lista `uris` larga (hasta `uris_por_pedido`, por defecto 100) y se re-manda en un borde de tema cuando quedan pocos.
- Antes de cada sintonía: `PUT /me/player/shuffle?state=false` y `PUT /me/player/repeat?state=off` sobre el dispositivo de Soloist (medido en el spike: si no, suena otro tema).
- `position_ms` va por la Web API (Soloist lo respeta, medido); volumen y eventos por el WebSocket.
- Rampas como el `Reproductor` local: pasos de 0,05 s; el factor es una fracción de la escala cúbica (la curva de Soloist medida es ~cúbica: 80→40 ≈ −15 dB, 80→20 ≈ −35 dB, 80→5 ≈ −72 dB).
- Un tema que no es el esperado (el usuario lo encoló desde la app) **se deja sonar**: no se corta ni se re-sintoniza en el medio.
- Otro dispositivo toma Spotify mientras suena una emisora de Spotify → la radio se apaga y avisa "Spotify se está escuchando en otro dispositivo". Fallas (sin red, sin sesión, Soloist caído o vencido, no suena en 10 s) → se apaga y avisa con el motivo.
- La API key de Soloist se lee de `~/.config/cassette-fm/soloist.key` al arrancar el servicio de Soloist; nunca se loguea ni va en la unidad systemd.

## Review Focus

1. Sintonizar Spotify con Soloist apagado, vencido o sin emparejar → aviso claro en segundos (no 10 s de estática muda sin explicación) y la radio apagada, lista para sintonizar otra emisora. (Tasks 4 y 6)
2. Pasar rápido de una emisora de Spotify a una local y otra vez a Spotify (atajos de teclado) → nunca suenan dos cosas a la vez; la estática no queda sonando; el evento tardío de la sintonía vieja no pisa a la nueva. (Tasks 4 y 6)
3. El usuario encola un tema desde la app → suena; el DJ no habla encima de un tema equivocado; cuando vuelve la agenda, el desfase se corrige en el borde. (Task 5)
4. El WebSocket de Soloist se corta (Soloist reiniciado por systemd) mientras suena → se reconecta solo; si no vuelve, se avisa y se apaga. (Tasks 3 y 4)
5. El DJ baja el volumen justo cuando cambia el tema o cuando el usuario mueve el volumen → la rampa termina en el valor correcto (como en mpv: una rampa nueva reemplaza a la anterior). (Task 5)

---

### Task 1: Verificación del protocolo real (con el usuario, sin código de producción)

**Files:** `spikes/spotify/protocolo.py` (descartable, ignorado por git); resultado anotado en el ledger y, si cambia algo, en el spec.

- [ ] **Step 1:** con Soloist del spike corriendo y la sesión del spike, verificar contra la cuenta real y anotar cada respuesta:
  - `PUT /me/player/play` con 100 `uris` y `position_ms` → 204 y suena el primero en esa posición; con 200 `uris` → ¿204 o 400? (fija `uris_por_pedido`).
  - Encadenado de los temas de la lista sin pasar por la cola (`queue_changed` con `source: context`).
  - `GET /me/player/devices` lista "cassette-fm (soloist)" con su `id` estable entre reinicios.
  - WebSocket: `set_volume` (0–100) → `volume_changed`; tomar Spotify desde el celular → `device_changed` con `is_active: false`.
  - Un tema encolado desde la app suena antes que el resto de la lista (`source: queue`).
- [ ] **Step 2:** ledger: `Task 1: Ruling: <lo medido>` por cada punto que cambie el plan; si `uris` máximo < 100, poner ese valor como default de `uris_por_pedido`.

### Task 2: Control de reproducción por la Web API

**Files:** Modify `src/cassette_fm/spotify/api.py`; Create `src/cassette_fm/spotify/control.py`; Test `tests/spotify/test_control.py`, `tests/spotify/test_api.py`.

**Interfaces:**
- Produces:
  - `ClienteSpotify.put(ruta: str, params: dict | None = None, cuerpo: dict | None = None) -> None` (mismas reglas de 401/429/errores que `get`; acepta 200/202/204).
  - `class ControlSpotify(cliente: ClienteSpotify, nombre_dispositivo: str)`: `dispositivo() -> str` (id del dispositivo con ese nombre en `GET /me/player/devices`, cacheado; `ErrorSpotify("Soloist no aparece como dispositivo de Spotify: ¿está corriendo y emparejado? (cassette spotify estado)")` si no está); `reproducir(uris: list[str], posicion_ms: int) -> None` (shuffle off, repeat off y play, todo con `device_id`; si el play da 404 "device not found", olvida el id cacheado, lo vuelve a buscar y reintenta una vez).

- [ ] Tests (fallan primero): `put` manda cuerpo JSON y token; 204 sin cuerpo no rompe; `dispositivo` por nombre exacto y cacheado (un solo GET para dos llamadas); sin el dispositivo → mensaje con "cassette spotify estado"; `reproducir` hace los tres PUT en orden (shuffle, repeat, play) con `device_id` y el cuerpo `{"uris": [...], "position_ms": N}`; play 404 → rebusca el dispositivo y reintenta.
- [ ] Implementar, suite de `tests/spotify` en verde, commit `Spotify: control de reproducción por la Web API (dispositivo, shuffle y repeat apagados, play con posición)`.

### Task 3: Cliente del WebSocket de Soloist

**Files:** Modify `pyproject.toml` (dependencia `websockets>=12`); Create `src/cassette_fm/spotify/soloist.py`; Test `tests/spotify/test_soloist.py` (con un servidor `websockets.sync.server` falso que manda eventos y registra comandos).

**Interfaces:**
- Produces: `class ClienteSoloist(url: str, al_evento: Callable[[dict], None], al_desconectar: Callable[[], None] | None = None, reintento_segundos: float = 2.0)`:
  - `conectar(timeout: float) -> None` (abre la conexión y arranca un hilo lector; `ErrorSpotify("Soloist no responde en <url>: …")` si no conecta).
  - `comando(nombre: str, **campos) -> None` (`{"type": "command", "command": nombre, ...}`; `ErrorSpotify` si no hay conexión).
  - `conectado: bool`; `cerrar() -> None`.
  - El hilo lector entrega cada evento JSON a `al_evento`; si la conexión se corta, llama a `al_desconectar` una vez e intenta reconectar cada `reintento_segundos` hasta `cerrar()`. Al reconectar pide `get_state` (para resincronizar).
- [ ] Tests (fallan primero): comandos con el formato exacto (`set_volume` con `volume`); eventos llegan en orden a `al_evento`; servidor que corta → `al_desconectar` una vez y reconexión automática (el falso vuelve a aceptar) con `get_state`; `conectar` contra un puerto cerrado → `ErrorSpotify` con la URL; `cerrar` termina el hilo.
- [ ] `.venv/bin/pip install -e .` (para la dependencia nueva), suite en verde, commit `Soloist: cliente del WebSocket con reconexión`.

### Task 4: Reproductor de Spotify — sintonía, eventos, posición y fallas

**Files:** Create `src/cassette_fm/reproductor_spotify.py`; Test `tests/test_reproductor_spotify.py` (con `ControlSpotify` y `ClienteSoloist` falsos que registran llamadas y permiten inyectar eventos, y un reloj falso).

**Interfaces:**
- Consumes: `ControlSpotify.reproducir`, `ClienteSoloist.comando/conectado`, `agenda.secuencia`, `Pista.clave/uri`.
- Produces: `class ReproductorSpotify(control, soloist, reloj=time.time, uris_por_pedido=100, espera_sonido_segundos=10.0)` con la **misma interfaz** que `Reproductor`: `sintonizar(estacion)`, `detener()`, `posicion() -> float | None`, `volumen(valor) -> int`, `atenuar(factor, segundos=0.0)`, `asegurar()`, `pista_actual`, `al_cambiar_pista`, `al_fallar`; más `al_sonar: Callable[[], None] | None` (la radio apaga la estática) y `manejar_evento(evento: dict)` (lo conecta el servicio como `al_evento` del `ClienteSoloist`).
  - `sintonizar`: arma `uris` = la secuencia de la agenda desde `reloj()` (el actual primero, hasta `uris_por_pedido`), `posicion_ms` = segundo del actual según el reloj virtual × 1000, y llama a `control.reproducir`. Guarda un número de sintonía; los eventos de una sintonía vieja se ignoran. Si `reproducir` lanza `ErrorSpotify` → `al_fallar(estacion, motivo)`.
  - Evento `playback_changed`/`playback_state` con `status: "playing"` del tema esperado tras sintonizar → `al_sonar()`; si en `espera_sonido_segundos` no pasó → `al_fallar(estacion, "Spotify no empezó a sonar en 10 s")`.
  - `track_changed` → `pista_actual` = la pista de la agenda con esa `clave` (o una `Pista` mínima de Spotify si no es de la agenda) y `al_cambiar_pista(pista, estacion)`.
  - `position_sync` → `posicion()` interpola `position_ms + (ahora − timestamp_ms) × speed`.
  - `detener`: `pause` por el WebSocket (si hay conexión), olvida la estación; los eventos posteriores no disparan nada.
  - Desconexión del WebSocket mientras suena → `al_fallar(estacion, "se perdió la conexión con Soloist")` si no vuelve en `espera_sonido_segundos`.
  - `al_fallar` con firma `(estacion, motivo: str | None = None)` (la radio se adapta en la Task 6).
- [ ] Tests (fallan primero, uno por punto de arriba), incluido el de Review Focus 2: sintonía A, luego B; un `playing` tardío de A no dispara `al_sonar` para B; y un `track_changed` tras `detener` no dispara nada.
- [ ] Implementar, suite en verde, commit `Reproductor de Spotify: sintonía con la agenda, eventos de Soloist, posición y fallas`.

### Task 5: Reproductor de Spotify — volumen, rampas, desfase y control de la cuenta

**Files:** Modify `src/cassette_fm/reproductor_spotify.py`; Test `tests/test_reproductor_spotify.py`.

**Interfaces:**
- Produces:
  - `volumen(valor)` y `atenuar(factor, segundos)` con la misma semántica que el `Reproductor` (rampa por pasos de 0,05 s, una rampa nueva reemplaza a la anterior desde el valor actual); lo que se manda es `set_volume` con `round(min(100, valor × factor × ganancia))`, donde `ganancia = 10 ** (ajuste_volumen_db / 60)` (curva cúbica) y `ajuste_volumen_db` viene de la config (Task 6). Si `valor × factor × ganancia > 100` se manda 100 y se sube el stream "Spotify" de PipeWire con `pactl set-sink-input-volume <id> <porcentaje>%` (tope 150 %); el comando de `pactl` se inyecta (`correr=subprocess.run`) para testearlo.
  - Desfase: en cada `track_changed` de un tema de la agenda (no el primero tras sintonizar), si `|agenda.desfase(...)| > tolerancia_resync_segundos` (3 s) → re-sintoniza en ese borde (sin estática, sin `al_sonar`). Un tema que no es de la agenda no dispara nada (Review Focus 3). Si quedan menos de 10 temas de la lista enviada, re-manda la lista en el próximo borde.
  - `device_changed` con `is_active: false` mientras hay una emisora sonando y la radio no pidió detener → `al_fallar(estacion, "Spotify se está escuchando en otro dispositivo")`.
- [ ] Tests (fallan primero): valores de `set_volume` para `volumen(80)`, `atenuar(0.6)` con y sin rampa y con ajuste en dB; rampa reemplazada a mitad de camino termina en el valor nuevo (Review Focus 5); `pactl` solo cuando se pasa de 100 y con el porcentaje correcto; re-sintonía en el borde con desfase > 3 s y no con 2 s; tema ajeno no re-sintoniza; re-envío de la lista cuando se acaba; `device_changed` inactivo → `al_fallar` con el motivo, pero no después de `detener`.
- [ ] Implementar, suite en verde, commit `Reproductor de Spotify: volumen con rampas, corrección de desfase y control de la cuenta`.

### Task 6: La radio con dos reproductores, estática y servicio

**Files:** Modify `src/cassette_fm/radio.py`, `src/cassette_fm/reproductor.py` (estática), `src/cassette_fm/clips.py`, `src/cassette_fm/config.py`, `src/cassette_fm/servicio.py`, `src/cassette_fm/emisoras.py`, `src/cassette_fm/cli.py`; Create `packaging/cassette-soloist.service.in`, `scripts/instalar-spotify.sh`, `scripts/actualizar-soloist.sh`; Test `tests/test_radio.py`, `tests/test_reproductor.py`, `tests/test_clips.py`, `tests/test_config.py`, `tests/test_servicio.py`, `tests/test_cli.py`.

**Interfaces:**
- Produces:
  - `clips.generar_estatica(ruta: Path, segundos: float = 3.0) -> Path` — WAV mono 22050 Hz de ruido filtrado (suena a radio entre emisoras), nivel moderado (RMS ≈ −24 dBFS), con fundido en los bordes para que el bucle no haga click.
  - `Reproductor.estatica(ruta: Path | None) -> None` — con ruta: deja la emisora y reproduce ese archivo en bucle (`loadfile` + `loop-file=inf`); con `None`: baja el volumen en 0,3 s y hace `stop`.
  - `class Reproductores` (en `radio.py` o módulo propio `reproductores.py`): envuelve al de mpv y al de Spotify con la interfaz de un reproductor. `sintonizar(estacion)`: si es `spotify`, detiene mpv, pone la estática, sintoniza Spotify y al `al_sonar` saca la estática; si es local, detiene Spotify (si estaba) y sintoniza mpv. `volumen`, `atenuar`, `posicion`, `pista_actual` van al activo. `al_cambiar_pista` y `al_fallar` se reenvían. Sin reproductor de Spotify (no configurado), sintonizar una emisora `spotify` es `al_fallar(estacion, "Spotify no está configurado")`.
  - `Radio._al_fallar(estacion, motivo=None)`: además de apagar, avisa con `avisar(estacion.nombre, motivo)` si hay motivo. `Radio.estado()` agrega `"fuente": "carpeta" | "spotify" | None`; `cassette status` la muestra.
  - `ConfigSpotify` gana: `soloist_ws: str = "ws://127.0.0.1:9787"`, `nombre_dispositivo: str = "cassette-fm"`, `ajuste_volumen_db: float = 0.0`, `uris_por_pedido: int = 100` (según Task 1), `tolerancia_resync_segundos: float = 3.0`, `activo: bool = True`.
  - `servir`: si `config.spotify.activo`, arma `ClienteSoloist` (conecta en segundo plano, sin frenar el arranque), `ControlSpotify` y `ReproductorSpotify`; el `Catalogo` va con `reproduce_spotify=True`. Locutor y radio reciben el `Reproductores`.
  - `cassette spotify estado` agrega: Soloist (conecta al WebSocket: corriendo/no responde, `logged_in`, `is_active`) y días que le quedan al build (de `soloist --version`, "build … (AAAAMMDD)" + 90 días; avisa si quedan menos de 14).
  - `packaging/cassette-soloist.service.in`: `ExecStart` con un `sh -c` que lee la key del archivo (`-k "$(cat …/soloist.key)"`), `-n cassette-fm`, `-D ~/.local/share/cassette-fm/soloist`, `-C ~/.cache/cassette-fm/soloist`, `-w 127.0.0.1:9787`, `-i 80`; `Restart=on-failure`, `RestartPreventExitStatus=10` (build vencido).
  - `scripts/instalar-spotify.sh`: baja Soloist a `~/.local/share/cassette-fm/soloist/bin`, instala la unidad, verifica que exista la key (si no, dice dónde ponerla y sale), corre el emparejamiento (`--pair`) explicando qué tocar en el celular, habilita el servicio y corre `cassette spotify login` si no hay sesión. `scripts/actualizar-soloist.sh`: baja el build, reemplaza el binario, reinicia el servicio.
- [ ] Tests (fallan primero): estática generada (WAV válido, duración, RMS en rango, bordes en silencio); `Reproductor.estatica` manda `loadfile` + `loop-file` y al sacarla `stop`; `Reproductores` (local → Spotify → local, con falsos): nunca dos activos, estática puesta y sacada al `al_sonar`, el `al_sonar` de una sintonía vieja no saca la estática de la nueva; `_al_fallar` con motivo avisa; `estado()` con fuente; config `[spotify]` nueva con validaciones; `servir` con `spotify.activo = false` no crea nada de Spotify; `cassette spotify estado` con un WebSocket falso y un `soloist --version` simulado.
- [ ] Implementar; README (Spotify: instalación con `scripts/instalar-spotify.sh`, actualización, `ajuste_volumen_db`, qué pasa si otro dispositivo toma Spotify), suite en verde, commit `Radio: emisoras de Spotify con Soloist, estática al sintonizar y avisos de falla`.

### Task 7: Calibración del volumen (con el usuario)

**Files:** Create `scripts/calibrar-spotify.py`.

- [ ] Script que, con la radio corriendo, sintoniza una emisora local y una de Spotify al mismo volumen, graba cada stream ~15 s (`parec --monitor-stream`, como el spike), compara el nivel medio (dB) y propone `ajuste_volumen_db` para `[spotify]` del `config.toml`. Se corre con el usuario y el valor se deja en su config.
- [ ] Commit `Script de calibración del volumen de Spotify contra las emisoras locales`.

## Verificación con el usuario (al final)

`scripts/instalar-spotify.sh` (o el Soloist ya emparejado del spike), reiniciar los servicios, sintonizar "Sing": estática y
música en ~1 s; dejar correr dos cambios de tema (sin cortes); `cassette dj pedir --en 180` en Sing y escuchar el ducking;
cambiar Spotify ↔ local con los atajos varias veces; poner algo en el celular → la radio se apaga y avisa; encolar un tema
desde la app → suena; `cassette spotify estado`; calibrar el volumen.
