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

- Esta PC publica por HTTP, en el puerto 8765 (en qué dirección, ver §1), cuatro cosas y nada más: el **audio** del bus
  (`GET /stream`), el **estado** (`GET /status`: emisora activa, lista de emisoras, tema actual), el **cambio de emisora**
  (`POST /station/{id}`) y los **logos** de las emisoras (`GET /icon/{id}`).
- Un script `lan_receiver.py` **independiente** (solo biblioteca estándar de Python + `mpv`) que en la PC 2 reproduce el stream,
  se prende y apaga y maneja su volumen local, sin importar nada del paquete `cassette_fm`.
- Un **modo remoto del applet** (`is_remote`, `server_url`, más la clave), **visualmente equivalente al local** (mismo menú,
  mismo dial, con los logos de las emisoras): la lista de emisoras, la emisora y el tema salen de la API de la PC principal; el encendido, el silencio y el volumen actúan sobre `lan_receiver.py` en la PC 2.
- Con todo apagado por defecto: sin activarlo, la radio de hoy no cambia en nada y no se abre ningún puerto nuevo.

## No objetivos

- Sincronía exacta entre las dos PCs: el stream llega con 1–3 s de retraso respecto de la principal (aceptado).
- Exponer el servidor a Internet abierta ni TLS propio (con Tailscale el túnel ya va cifrado; ver Restricciones), varias
  cuentas de Spotify, varios oyentes con emisoras distintas (hay una sola transmisión).
- Editar emisoras, el DJ o la configuración desde la PC 2; controlar el volumen o el encendido **de la PC principal**.
- Clientes que no sean el applet (Android, web): la API y el stream están pensados para que se puedan escribir después,
  pero no se hacen ahora.
- Descubrimiento automático del servidor (mDNS): la dirección se escribe a mano.

## Anti-objetivos (un fracaso aunque "funcione")

- Exponer a la red algo más que esas cuatro rutas: ni la API de dueño (`/volumen`, `/dj/*`, `/apagar`…), ni el servidor de
  audio completo (el micrófono, otros streams), ni archivos: `/icon/{id}` sirve solo los logos que la propia radio tiene
  registrados para esa emisora, nunca una ruta que venga del cliente.
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
- **Tailscale**: el usuario lo usa y quiere conectarse **por la IP de Tailscale de esta PC** (hoy `100.104.222.41`), que es
  fija, y no por la de la LAN (`192.168.0.x`, que el router puede cambiar). El tráfico entre equipos de la tailnet va
  cifrado por WireGuard, así que el HTTP sin cifrar deja de ser un problema por ese camino (por la LAN sigue siéndolo:
  la clave sirve para una red de confianza, como en el spec de radio en red). Consecuencia: conviene que el servidor escuche
  **solo en la interfaz de Tailscale** (ver §1) y la radio queda alcanzable desde cualquier equipo de la tailnet, también fuera
  de casa.
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

**Dirección.** `[lan] escuchar` (por defecto `"auto"`): la IP de Tailscale de esta PC si existe (interfaz `tailscale0`,
rango 100.64.0.0/10) y, si no hay Tailscale, todas las interfaces (`0.0.0.0`); acepta una IP concreta. Si la IP de
Tailscale todavía no está al arrancar el servicio, el servidor reintenta en segundo plano en vez de caerse.

- `GET /status` → JSON con lo que hoy da `/estado` limitado a: `encendida`, `estacion`, `pista`, `estaciones`, `fuente`,
  `segundo`, `iconos` (`{emisora: "/icon/<id>?v=<versión>"}`, solo las que tienen logo propio; el resto usa el genérico). Nada de
  `volumen` ni `monitor_local` (son de esta PC).
- `POST /station/{id}` → sintoniza. El `id` es el nombre de la emisora codificado como URL (no hay otros ids). 404 si no
  existe. **Sintonizar desde la red no toca el monitor local de esta PC** (hace falta que `Radio.sintonizar` acepte
  "sin oír acá"; hoy sintonizar prende el monitor). Si la radio estaba apagada, la enciende.
- `GET /icon/{id}` → la imagen del logo de esa emisora (`image/png` o `image/jpeg`), con `ETag`; 404 si no tiene.
- `GET /stream` → `audio/mpeg`, sin `Content-Length`, `Cache-Control: no-store`.

**Stream.** Un único proceso de codificación para todos los oyentes (`gst-launch-1.0 -q pulsesrc
device=radio_virtual.monitor ! audioconvert ! audioresample ! lamemp3enc … ! fdsink fd=1`, MP3 CBR ~160 kbps; *mi
decisión*: MP3 por compatibilidad con cualquier reproductor; Opus en Ogg es la alternativa si importa más la calidad), con
un reparto a los oyentes por colas acotadas. **Si la radio principal está apagada, el codificador toma estática** (ruido blanco filtrado a bajo nivel, de carácter parecido al
sonido de sintonía) **en vez del monitor**, y vuelve al monitor cuando se prende; cambiar de fuente reinicia el
codificador (un corte de ~medio segundo con los oyentes conectados; los reproductores toleran MP3 concatenados). Arranca con el
primer oyente y se detiene unos segundos después del último (sin oyentes no hay CPU). Un oyente que no consume se descarta sin frenar a los demás. **El retraso del oyente se recupera al cambiar de emisora** (medido el 18/11 con un bip inyectado en el bus: 0,74 s de punta
a punta sin cortes). El reproductor consume a tiempo real, así que el audio que se acumula durante un corte (Wi-Fi, pico de CPU)
queda como retraso permanente (un corte de 8 s dejaba 8,6 s). Descartar al oyente atrasado para reconectarlo sería un salto cada
vez que se atrasa, así que no se hace salvo que esté trabado más de ~5 s (cola de 25 bloques); en cambio, **cada cambio de emisora
desde el applet remoto vuelve a "en vivo"** (`lan_receiver.py resync`: conexión nueva, buffers vacíos, ~0,4 s después del último
cambio), que es cuando un salto no se nota (durante el hueco, de ~0,7 s, el receptor toca la misma estática que la radio al
sintonizar —`estatica.wav`, generada con `generar_estatica`—, y el cierre de 3 s del dial, local o remoto, cuenta desde que suena la
música o termina el resync, no desde que se pide la emisora). El hueco medido es de ~0,7 s y el servidor y `mpv` llevan buffers de red chicos
—8 KB— para que el atraso no se esconda en el kernel). Sin `resync` el retraso tras un corte queda acotado en ~2 s.
Máximo de oyentes simultáneos
configurable (por defecto 4; el siguiente recibe 503). Sin `gst-launch-1.0`, sin bus o con falla del proceso, 503 con el
motivo.

**Configuración.** `[lan]` en `config.toml`: `activo` (por defecto `false`), `puerto` (8765). La clave se genera la primera
vez que se activa y se guarda con modo 600 (`lan.token`, junto a `soloist.key`); `cassette lan` muestra la dirección y la
clave para configurarlas en la PC 2 (la de Tailscale si existe), y `cassette lan regenerar` la cambia (corta a los oyentes). Con `activo` y sin bus de
audio, el servicio arranca igual, no abre el puerto y deja el error en el log.

### 2. Receptor (PC 2) — `lan_receiver.py`

Un solo archivo que se instala **dentro de la carpeta del applet** (así, instalar el applet instala el receptor), con solo
biblioteca estándar. **Sin demonio propio**: el proceso que suena es el `mpv`, que arranca con un socket IPC en
`$XDG_RUNTIME_DIR`. Subcomandos, todos con salida corta y código de salida claro: `on`, `off`, `volume N`, `status --json`
(escuchando o no, volumen y último error del stream) e `icons` (baja los logos del servidor a una caché local y devuelve
`{emisora: ruta local}`; solo vuelve a bajar los que cambiaron).

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
- los **logos**: al arrancar y cuando cambia la lista, el applet corre `lan_receiver.py icons` y completa `estado.iconos` con las
  rutas locales; el dial y el menú usan `iconoDe` igual que hoy;
- se ocultan "Nueva emisora…" y todo lo que edita. Si el servidor no responde o rechaza la clave, el tooltip y el menú lo
  dicen ("no alcanzo a la radio en 192.168.0.157", "clave rechazada") y la escucha local sigue sonando lo que haya.
- La traducción de rutas locales a remotas va en funciones puras de `logic.js` (con tests de node); `_pedir` decide el
  destino. `puerto` (el del servicio local) no se usa en modo remoto.

### 4. Qué pasa según el estado de la PC principal (calls del diseñador tras la revisión)

- **Radio principal apagada** (`Apagar` del clic derecho, `cassette off`): `/stream` **sigue abierto** y sirve estática (ver
  §1); no corta a la PC 2. `/status.encendida` es `false`; en modo remoto el applet muestra su propio estado de escucha pero el
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
- Servidor separado en el puerto 8765 con solo cuatro rutas y clave Bearer, con `http.server` y no FastAPI/aiohttp: coincide con el resto
  del proyecto y evita dependencias para tres rutas.
- Escucha por defecto en la IP de Tailscale si existe (`[lan] escuchar = "auto"`), no en todas las interfaces.
- Apagado por defecto (`[lan] activo = false`) y clave generada y guardada con modo 600.
- El receptor vive dentro de la carpeta del applet, sin demonio, y recibe la clave por entorno.
- Sintonizar desde la red no cambia el monitor local de la principal.
- En el modo remoto "Apagar" apaga la escucha local, no la radio principal.

## Orden de trabajo (sugerencia)

1. Servidor (clave, `/status`, `/station`, `/stream` con la estática) y el cambio de `Radio.sintonizar`. 2. `lan_receiver.py`.
3. Modo remoto del applet. 4. **Logos** (`/icon` + `icons` + applet): separados a propósito, al final, para poder evaluarlos o
dejarlos si resultan caros sin afectar al resto.

## Verificación con el usuario (al final, juntos)

Todo **por la IP de Tailscale** de esta PC. En la PC 2: el applet en modo remoto muestra las mismas emisoras y el mismo tema; cambiar de emisora allí la cambia en la
principal y sin que la principal deje de estar silenciada si lo estaba; el encendido y el volumen de la PC 2 no afectan a la
principal; sin la clave el stream y la API responden 401; con `[lan] activo` apagado el puerto no existe.
