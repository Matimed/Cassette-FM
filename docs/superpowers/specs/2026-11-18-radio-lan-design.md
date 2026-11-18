# Radio por la LAN: escuchar la radio de esta PC desde otra PC propia — diseño

Fecha: 18/11/2026. Antecedentes: [`2026-11-18-bus-de-audio-design.md`](2026-11-18-bus-de-audio-design.md) (el bus
`radio_virtual` y su monitor, que son la fuente de todo esto) y [`2026-11-18-radio-en-red-design.md`](2026-11-18-radio-en-red-design.md)
(clientes livianos con su propia cuenta de Spotify; el enfoque 3 de ese documento, "retransmitir audio ya mezclado", es
este). Esto implementa ese enfoque **solo para dispositivos propios del usuario**, hoy; no lo reemplaza.

## Intención

El usuario tiene una segunda computadora en su red doméstica (misma LAN, mismo Linux Mint con Cinnamon) y quiere
**escuchar en ella la misma radio que suena en esta PC, con el mismo applet**, sin correr allí nada del backend (ni
Soloist, ni Docker, ni el DJ, ni el servicio `cassette`). Es **una sola transmisión**: lo que suena en la PC 2 es lo que
suena en el bus de esta PC (música y voces del DJ ya mezcladas); cambiar de emisora desde cualquiera de las dos cambia la
emisora para las dos. Cada PC mantiene su **propio volumen y su propio encendido** de escucha.

## Objetivos

- Esta PC publica por HTTP, en `0.0.0.0:8765`, tres cosas y nada más: el **audio** del bus (`GET /stream`), el **estado**
  (`GET /status`: emisora activa, lista de emisoras, tema actual) y el **cambio de emisora** (`POST /station/{id}`).
- Un script `lan_receiver.py` **independiente** (solo biblioteca estándar de Python + `mpv`) que en la PC 2 reproduce el stream,
  se prende y apaga y maneja su volumen local, sin importar nada del paquete `cassette_fm`.
- Un **modo remoto del applet** (`is_remote`, `server_url`, más la clave): la lista de emisoras, la emisora y el tema salen
  de la API de la PC principal; el encendido, el silencio y el volumen actúan sobre `lan_receiver.py` en la PC 2.
- Con todo apagado por defecto: sin activarlo, la radio de hoy no cambia en nada y no se abre ningún puerto nuevo.

## No objetivos

- Sincronía exacta entre las dos PCs: el stream llega con 1–3 s de retraso respecto de la principal (aceptado).
- Escuchar fuera de la red local (Internet, VPN, TLS), varias cuentas de Spotify, varios oyentes con emisoras distintas
  (hay una sola transmisión).
- Editar emisoras, el DJ o la configuración desde la PC 2; controlar el volumen o el encendido **de la PC principal**.
- Clientes que no sean el applet (Android, web): la API y el stream están pensados para que se puedan escribir después,
  pero no se hacen ahora.
- Los logos de las emisoras en la PC 2: viven en archivos de esta PC. En modo remoto el dial usa el logo genérico.
- Descubrimiento automático del servidor (mDNS): la dirección se escribe a mano.

## Anti-objetivos (un fracaso aunque "funcione")

- Exponer a la red algo más que esas tres rutas: ni la API de dueño (`/volumen`, `/dj/*`, `/apagar`…), ni el servidor de
  audio completo (el micrófono, otros streams), ni archivos.
- Que sin la clave se pueda oír el stream o cambiar la emisora; que la clave aparezca en logs, en `cassette lan`
  sin pedirlo, en mensajes de error o en la línea de comandos de algún proceso (`ps`).
- Que cambiar de emisora desde la PC 2 **prenda o desmutee** los parlantes de la PC principal (el monitor local de esta PC
  es de esta PC), o que oír la radio en la PC 2 dependa de que esta PC la tenga en el monitor prendido.
- Que un oyente lento o colgado frene el stream de los demás, o que el stream codifique (gaste CPU) sin nadie escuchando.
- Que el applet en la PC 2 quede colgado o mienta si la PC principal no responde: tiene que decir que no la alcanza.

## Restricciones

- Fuente del audio: `radio_virtual.monitor` (hace falta `bus_audio = true`; sin bus, el stream responde 503 con el motivo).
- PipeWire 1.0.5 con pipewire-pulse; GStreamer ya instalado con `pulsesrc`, `lamemp3enc` y `opusenc` (verificado). Sin
  `ffmpeg`. La PC 2 necesita `python3` y `mpv`, y que el applet esté instalado allí.
- La red de esta casa es `192.168.0.x`. HTTP sin cifrar: la clave sirve para una red de confianza (se documenta, como en el
  spec de radio en red).
- El proyecto usa `http.server` de la biblioteca estándar; el applet recibe todo por `Gio` y ya tiene `_correr` para
  lanzar comandos sin bloquear.
- `logic.js` no se recarga con `ReloadXlet` (hay que reiniciar Cinnamon al tocarlo).
- TDD, git local en `main`, commits en español, comentarios y mensajes en español rioplatense.

## Enfoques considerados

1. **Protocolo nativo de PulseAudio por TCP + `module-tunnel-source`** (lo que el usuario sugirió primero). Sin dependencias y
   sin pérdida, pero `module-native-protocol-tcp` da acceso a *todo* el servidor de audio a quien entre por el ACL (grabar
   el micrófono, controlar streams), y `auth-anonymous` no se puede acotar a una sola fuente. Y ata el receptor a
   PulseAudio. Descartado por seguridad.
2. **Stream HTTP comprimido (elegido por el usuario).** Un servidor liviano que codifica `radio_virtual.monitor` y lo sirve
   por HTTP; el receptor es un `mpv` apuntado a la URL. Solo expone el audio, tiene clave, anda en cualquier equipo con un
   reproductor de HTTP y es lo mismo que necesitaría un cliente Android o web. Costo: 1–3 s de retraso y un codificador.
3. **RTP multicast** (`module-rtp-send`/`module-rtp-recv`). Muy liviano y poco retraso, pero el multicast por Wi-Fi es
   poco confiable y no tiene autenticación. Descartado.

El usuario eligió el 2 el 18/11. Consecuencia: **no se agrega `enable_lan_sharing` al `AudioRouter`** (era para el enfoque
1): `audio_router.py` no cambia; el stream lee el monitor del bus que ya existe.

## Diseño

### 1. Servidor LAN (esta PC) — `lan_server.py`

Un `ThreadingHTTPServer` aparte, **separado de la API de dueño** (que sigue en `127.0.0.1:7710`). Rutas, todas con
`Authorization: Bearer <clave>` (comparación con `hmac.compare_digest`; sin clave o mala, 401 sin más detalle; cualquier otra
ruta, 404):

- `GET /status` → JSON con lo que hoy da `/estado` limitado a: `encendida`, `estacion`, `pista`, `estaciones`, `fuente`,
  `segundo`, `iconos: {}`. Nada de `volumen` ni `monitor_local` (son de esta PC).
- `POST /station/{id}` → sintoniza. El `id` es el nombre de la emisora codificado como URL (no hay otros ids). 404 si no
  existe. **Sintonizar desde la red no toca el monitor local de esta PC** (hace falta que `Radio.sintonizar` acepte
  "sin oír acá"; hoy sintonizar prende el monitor). Si la radio estaba apagada, la enciende.
- `GET /stream` → `audio/mpeg`, sin `Content-Length`, `Cache-Control: no-store`.

**Stream.** Un único proceso de codificación para todos los oyentes (`gst-launch-1.0 -q pulsesrc
device=radio_virtual.monitor ! audioconvert ! audioresample ! lamemp3enc … ! fdsink fd=1`, MP3 CBR ~160 kbps; *mi
decisión*: MP3 por compatibilidad con cualquier reproductor; Opus en Ogg es la alternativa si importa más la calidad), con
un reparto a los oyentes por colas acotadas. Arranca con el primer oyente y se detiene unos segundos después del último
(sin oyentes no hay CPU). Un oyente que no consume se descarta sin frenar a los demás. Máximo de oyentes simultáneos
configurable (por defecto 4; el siguiente recibe 503). Sin `gst-launch-1.0`, sin bus o con falla del proceso, 503 con el
motivo.

**Configuración.** `[lan]` en `config.toml`: `activo` (por defecto `false`), `puerto` (8765). La clave se genera la primera
vez que se activa y se guarda con modo 600 (`lan.token`, junto a `soloist.key`); `cassette lan` muestra la dirección y la
clave para configurarlas en la PC 2, y `cassette lan regenerar` la cambia (corta a los oyentes). Con `activo` y sin bus de
audio, el servicio arranca igual, no abre el puerto y deja el error en el log.

### 2. Receptor (PC 2) — `lan_receiver.py`

Un solo archivo que se instala **dentro de la carpeta del applet** (así, instalar el applet instala el receptor), con solo
biblioteca estándar. **Sin demonio propio**: el proceso que suena es el `mpv`, que arranca con un socket IPC en
`$XDG_RUNTIME_DIR`. Subcomandos, todos con salida corta y código de salida claro: `on`, `off`, `volume N`, `status --json`
(escuchando o no, volumen, y si el servidor responde).

- `on` lanza `mpv` sin ventana (`--idle`, con IPC) y le manda `loadfile` del stream **por el socket**, con la cabecera de
  autorización como opción de ese archivo: así la clave no queda en la línea de comandos de `mpv`. Reconecta solo si el
  stream se corta (opciones de reconexión de mpv) y usa buffers chicos.
- `off` cierra ese `mpv`. `volume N` (0–100) lo aplica al `mpv` y lo recuerda en un archivo de estado del runtime para la
  próxima vez que se prenda.
- La dirección y la clave las recibe por variables de entorno (`CASSETTE_LAN_URL`, `CASSETTE_LAN_TOKEN`) o por
  `--server-url`; *mi decisión*: el applet las pasa por entorno, no por argumentos.

### 3. Modo remoto del applet

Ajustes nuevos: `is_remote` (interruptor, apagado), `server_url` (por ejemplo `http://192.168.0.157:8765`) y
`server_token` (campo de texto; la guarda Cinnamon sin cifrar, aceptable en una red de confianza). Con `is_remote`:

- el estado (emisoras, emisora actual, tema) sale de `GET /status` del servidor; "encendida" y el volumen salen de
  `lan_receiver.py status`;
- cambiar de emisora (menú, dial, rueda, `siguiente`/`anterior` calculados con la lista) → `POST /station/{id}`;
- el clic izquierdo, el volumen y el "Apagar" del menú → `lan_receiver.py on` / `off` / `volume`. El "Apagar" apaga **la
  escucha en esta PC**, no la radio de la principal;
- se ocultan "Nueva emisora…" y todo lo que edita. Si el servidor no responde o rechaza la clave, el tooltip y el menú lo
  dicen ("no alcanzo a la radio en 192.168.0.157", "clave rechazada") y la escucha local sigue sonando lo que haya.
- La traducción de rutas locales a remotas va en funciones puras de `logic.js` (con tests de node); `_pedir` decide el
  destino. `puerto` (el del servicio local) no se usa en modo remoto.

### 4. Qué pasa según el estado de la PC principal (calls del diseñador tras la revisión)

- **Radio principal apagada** (`Apagar` del clic derecho, `cassette off`): `/stream` **sigue abierto** y sirve silencio; no
  corta a la PC 2. `/status.encendida` es `false`; en modo remoto el applet muestra su propio estado de escucha pero el
  tooltip agrega "la radio principal está apagada". Prender la principal es cosa de la principal (o de un
  `POST /station/{id}`, ver abajo).
- **Silencio o volumen 0 en la principal**: no afectan al stream. Las fuentes siguen al 100 % y el monitor local es de esa PC.
- **`POST /station/{id}`**: `Radio.sintonizar` gana un parámetro para **no tocar el monitor local** y el monitor queda
  como estaba (persiste en `Estado.monitor_local`, también tras un reinicio). Si la radio estaba apagada la enciende; si el
  monitor estaba prendido, la principal vuelve a sonar en sus parlantes, que es lo que ese estado ya significaba.
  Se prueba con la combinación radio apagada/prendida × monitor prendido/silenciado.
- **El id es el nombre**, tal cual lo da `/status`. Si la PC 2 tiene una lista vieja y recibe 404, el applet vuelve a pedir
  `/status`, refresca el menú y avisa; no reintenta solo.
- **El applet sondea, no recibe pushes** (el local ya sondea cada `INTERVALO_SEGUNDOS`): en modo remoto sondea `/status` con
  el mismo intervalo. Sin rutas nuevas en el servidor. El estado de escucha local lo lleva el propio applet (él emite
  `on`/`off`/`volume`) y solo consulta `lan_receiver.py status` al arrancar y cada ~10 s, para enterarse de que el `mpv`
  murió; así no lanza un proceso por tick.
- **Contrato de `lan_receiver.py status --json`**: `{"escuchando": bool, "volumen": int, "error": null | "clave
  rechazada" | "sin conexión"}`; solo habla de la reproducción local y del último error del stream (lo que vio `mpv`, incluido un
  401 en `/stream`). Que el servidor no responda o rechace la clave en `/status` lo detecta el applet con su propio
  `GET /status`.
- **Si el bus se recrea** (reinicio del servicio, `bus_audio` apagado y prendido) el servidor **corta a los oyentes**; `mpv`
  reconecta y el codificador arranca de nuevo con la primera conexión.
- **`cassette lan`** muestra la IP de la interfaz de la ruta por defecto (no las de los puentes de Docker); `[lan] direccion`
  la pisa si hace falta.
- **Empaquetado**: el repo no tiene paquete (solo plantillas de unidades): el receptor viaja dentro de la carpeta del applet y
  no hay nada que actualizar en `packaging/`.

## Lo que queda al constructor

- La tubería exacta de GStreamer (tamaños de buffer para bajar el retraso, bitrate), el reparto a oyentes (colas,
  tiempos de apagado) y cómo se mata el proceso al cerrar el servicio.
- Las opciones de mpv para poca latencia y reconexión, el formato del archivo de estado del receptor, y cómo se asegura
  que dos `on` seguidos no lancen dos mpv.
- Cómo se instala la PC 2 (copiar o enlazar la carpeta del applet y habilitarlo; sin `cassette`): un script o
  instrucciones en el README.
- La forma exacta del cambio en `Radio.sintonizar` ("sin oír acá") y su test.
- Cómo se prueba sin una segunda PC: servidor en loopback con clave, receptor con `--ao=null`, y la verificación real,
  juntos, al final.

## Decisiones que tomó el diseñador (no las pidió el usuario)

- No se toca `audio_router.py` (el enfoque 1 se descartó); el servidor es un módulo aparte.
- MP3 160 kbps, un solo codificador compartido y apagado sin oyentes.
- Servidor separado en `:8765` con solo tres rutas y clave Bearer, con `http.server` y no FastAPI/aiohttp: coincide con el resto
  del proyecto y evita dependencias para tres rutas.
- Apagado por defecto (`[lan] activo = false`) y clave generada y guardada con modo 600.
- El receptor vive dentro de la carpeta del applet, sin demonio, y recibe la clave por entorno.
- Sintonizar desde la red no cambia el monitor local de la principal.
- En el modo remoto "Apagar" apaga la escucha local, no la radio principal.

## Verificación con el usuario (al final, juntos)

En la PC 2: el applet en modo remoto muestra las mismas emisoras y el mismo tema; cambiar de emisora allí la cambia en la
principal y sin que la principal deje de estar silenciada si lo estaba; el encendido y el volumen de la PC 2 no afectan a la
principal; sin la clave el stream y la API responden 401; con `[lan] activo` apagado el puerto no existe.
