# Puente a la nube (emisor hacia un relay) — diseño

Estado: borrador para aprobar (2026-11-19). Sigue a la radio por la LAN
([`2026-11-18-radio-lan-design.md`](2026-11-18-radio-lan-design.md)) y se apoya en el bus de audio
([`2026-11-18-bus-de-audio-design.md`](2026-11-18-bus-de-audio-design.md)).

## Para qué

El usuario quiere escuchar y manejar su radio desde cualquier dispositivo y cualquier red (el teléfono con datos
móviles, una tablet, un smart TV, una PC con Windows) **sin instalar nada en cada uno**: ni Tailscale ni una interfaz
propia por dispositivo como el applet. La solución completa tiene tres piezas:

1. **Este módulo** (el puente, en esta PC): conecta la radio con un relay en la nube.
2. **El relay** (después): un servicio chico en una plataforma gratuita que acepte Docker (Railway, Render, Koyeb, una
   VM de Oracle…; se elige al hacerlo). Recibe al puente y atiende a los oyentes.
3. **El consumidor** (después): una web que anda en cualquier navegador.

Sigue siendo **un solo usuario**: cambiar de emisora desde el teléfono cambia la radio de esta PC, como el applet
remoto de la LAN. No hay otros oyentes que coordinar.

## Restricciones

- **Todo sale desde esta PC.** Está detrás de un router sin puertos abiertos y no se expone su IP: el puente abre
  conexiones salientes al relay y nada más. No abre ningún puerto en esta PC.
- **Opcional y apagado por defecto** (`[nube] activo = false`). Apagado no arranca hilos ni conexiones, y ni la radio
  local ni la LAN cambian en nada. Prendido, una falla del puente (relay caído, sin internet, clave mala) nunca
  afecta a la radio local ni a la LAN.
- **Sin gasto con nadie escuchando**: ni subida ni CPU de codificación hasta que el relay avise que hay oyentes en una
  calidad, y se corta solo cuando se va el último.
- **Tolerante a microcortes**: se reconecta solo, sin intervención, y sin que un corte de internet de unos segundos
  deje la radio en un estado raro.
- Necesita el bus de audio (`bus_audio = true`), igual que la LAN.

## Objetivos, no objetivos, anti-objetivos

**Objetivos**

- Reportar al relay el estado de la radio: emisoras, la sintonizada, si está prendida, el tema que suena (con su
  fuente y posición) y los logos, para que la web pueda verse como el dial.
- Recibir órdenes del relay y ejecutarlas: sintonizar una emisora, siguiente, anterior.
- Subir el audio del bus en MP3, en la calidad que pida cada oyente: **64, 96 o 160 kbps**, un codificador por calidad
  en uso.

**No objetivos (ahora)**

- El relay y la web (son las entregas siguientes; este documento fija el protocolo para que encajen).
- Varios usuarios, cuentas o permisos.
- Apagar la radio, tocar el volumen de esta PC o el monitor local desde la nube (el volumen es de cada dispositivo).
- Opus u otros formatos: MP3 es lo único que cualquier navegador (incluido Safari de iOS y los de smart TV) reproduce
  como stream continuo.
- Transcodificar en la nube (los planes gratuitos tienen poca CPU): las calidades se codifican acá.

**Anti-objetivos (fallaría aunque "funcione")**

- Abrir un puerto o exponer la IP de esta PC.
- Que la clave aparezca en logs, en la línea de comandos de un proceso o en una URL (va en un encabezado).
- Que una subida lenta trabe las órdenes: un "cambiá de emisora" tiene que llegar al toque aunque el audio venga con
  atraso.
- Subir audio que nadie escucha.

## Enfoques considerados

- **A. Un solo WebSocket** con JSON de control y el audio como mensajes binarios. Una conexión, una autenticación.
  Descartado: con la subida lenta el audio llena la conexión y las órdenes y el estado esperan detrás de segundos de
  audio.
- **B. Un WebSocket de control permanente y uno de audio por calidad, solo mientras haya oyentes en esa calidad.**
  Elegido por el usuario: el control nunca queda detrás del audio, un corte del audio no tira el control y para el
  relay cada conexión de audio es un caño directo hacia los oyentes de esa calidad.
- **C. Subida HTTP continua (estilo Icecast `SOURCE`/`PUT`)**: descartado, es lo primero que cortan las plataformas
  gratuitas (tiempo máximo por pedido, buffering de proxies).

## Protocolo (versión 1)

La config da una base, `url = "wss://relay.ejemplo.com"`. Las rutas son fijas:

| Conexión | Ruta | Vida |
|---|---|---|
| Control | `wss://…/casa/control` | Siempre, mientras el puente esté activo |
| Audio | `wss://…/casa/audio?calidad=96` | Mientras el relay pida esa calidad |
| Logo | `PUT https://…/casa/icono/<emisora url-encoded>?v=<versión>` | Un pedido corto cuando el relay lo pide |

Todas llevan `Authorization: Bearer <clave>`. El relay contesta 401 si la clave no es la suya. La base tiene que ser
`wss://` (y la del logo, el mismo host con `https://`); `ws://`/`http://` solo se aceptan contra `127.0.0.1`/`localhost`
(tests y relay de prueba), así la clave no viaja en claro.

### Control: mensajes JSON (texto), cada uno con `"tipo"`

**De la PC al relay**

- `hola` — primero al conectar: `{"tipo": "hola", "protocolo": 1, "calidades": [64, 96, 160]}`.
- `estado` — justo después del `hola` y cada vez que la radio cambia (a lo sumo uno cada 0,5 s; si hubo varios cambios
  en ese lapso va el último):
  `{"tipo": "estado", "seq": 12, "encendida": true, "estacion": "Power F.M.", "pista": "Artista - Tema",
  "fuente": "spotify", "segundo": 37.2, "estaciones": ["…"], "iconos": {"Power F.M.": "a1b2c3d4e5f6"}}`.
  Son los mismos campos que el `/status` de la LAN (`estado_publico`), salvo que `iconos` lleva solo la versión de cada
  logo (el relay los pide por `pedir_icono`). `seq` crece con cada `estado` de la conexión, para descartar uno viejo.
- `resultado` — respuesta a cada orden: `{"tipo": "resultado", "id": "…", "ok": true}` o
  `{"tipo": "resultado", "id": "…", "ok": false, "error": "esa emisora no existe"}`. Si la orden cambió algo, el
  `estado` nuevo sale aparte, como cualquier cambio.

**Del relay a la PC**

- `sintonizar` — `{"tipo": "sintonizar", "id": "…", "estacion": "Power F.M."}`. Con la misma regla que la LAN: sintoniza
  sin prender los parlantes de esta PC (`oir_aca=False`) y una emisora que no existe es un error.
- `siguiente` / `anterior` — `{"tipo": "siguiente", "id": "…"}`; misma regla (no prenden el monitor local).
- `demanda` — qué calidades tienen oyentes: `{"tipo": "demanda", "calidades": [96]}`. El relay lo manda al conectarse
  el control y cada vez que cambia. La PC abre las conexiones de audio que falten y cierra las que sobran. Una calidad
  que no está en el `hola` se ignora (con un aviso en el log).
- `pedir_icono` — `{"tipo": "pedir_icono", "estacion": "Power F.M."}`. La PC sube ese logo por `PUT`, con su tipo de
  imagen en `Content-Type` y la versión en `?v=`; el relay lo guarda por versión y no lo vuelve a pedir mientras no
  cambie. Mismas reglas que `/icon` de la LAN: solo los logos del mapa de la propia radio, de los tipos y el tamaño ya
  permitidos.

Los tipos que el puente no conoce se ignoran (con un aviso en el log) y un JSON roto no corta la conexión: así el relay
puede crecer sin romper puentes viejos. Las órdenes corren fuera del hilo que lee la conexión (sintonizar puede tardar
~1 s) y de a una, en orden de llegada.

### Audio

Solo mensajes binarios de la PC al relay: MP3 CBR, 44,1 kHz estéreo, a la calidad de la conexión, en el orden en que
sale del codificador (pedazos de hasta ~4 KB). Un oyente nuevo en el relay puede entrar en cualquier pedazo: los
reproductores de MP3 se sincronizan solos con el siguiente frame. Con la radio apagada se sube la misma estática que en
la LAN; el cambio entre estática y radio lo hace el `Difusor` como hoy.

## Cómo se arma en esta PC

### `Difusor` por calidad

El `Difusor` de [`lan_stream.py`](../../../src/cassette_fm/lan_stream.py) ya hace casi todo: arranca el codificador con
el primer oyente, lo para unos segundos después del último, cambia entre monitor y estática, y descarta a un oyente que
no consume. Gana un parámetro `kbps` (que ya acepta `comando_gst`). Cada calidad en uso es un `Difusor` propio; la LAN
sigue con el suyo de 160 kbps, y la nube a 160 comparte ese mismo (una conexión de audio de la nube cuenta como un
oyente más; si la LAN está apagada, la nube crea el suyo). Así nunca hay dos codificadores de la misma calidad: los
`Difusor` salen de un registro por calidad que crea `servicio.servir` y reciben tanto `iniciar_lan` como
`iniciar_nube` (cada uno se crea la primera vez que se pide su calidad).

Una conexión de audio es un oyente del `Difusor`: se suscribe, manda cada bloque de su cola como mensaje binario y se
desuscribe al cerrarse. Si la subida se traba más de lo que aguanta la cola (~5 s, `cola_max`), el `Difusor` la
descarta como a cualquier oyente lento: la conexión se cierra y se vuelve a abrir si la calidad sigue pedida, que
vuelve al vivo en vez de arrastrar atraso. Con buffers de envío chicos (como el `SO_SNDBUF` de la LAN) para que el
atraso no se esconda en el kernel.

### El puente (`src/cassette_fm/puente_nube.py`)

- Un hilo para el control y uno por cada conexión de audio abierta, con el cliente síncrono de `websockets` (el mismo
  que usa Soloist; ya es dependencia).
- **Reconexión** con espera creciente con algo de azar: 1, 2, 4… hasta 30 s, y vuelve a 1 s después de una conexión
  que duró más de un minuto. Ping del WebSocket cada 20 s, y se da por caída si no hay respuesta en 20 s (así un corte
  de internet se detecta aunque el TCP no se entere). Un 401 no se reintenta a ritmo normal: se loguea como error
  ("la clave no coincide con la del relay") y se reintenta cada 5 minutos, por si se arregló del otro lado.
- **Logs sin ruido**: la primera caída es un aviso y los reintentos siguientes van a debug hasta que vuelve ("conectado
  al relay después de 3 min"). Nunca la clave.
- **Si se cae el control** las conexiones de audio siguen (los oyentes no notan un corte corto del control). Al volver,
  el `demanda` que manda el relay corrige lo que haga falta. Si el control no vuelve en 60 s, se cierran las de audio:
  sin control no hay forma de saber si siguen pedidas.
- **Cambios de estado**: `Radio.al_cambiar` hoy admite un solo interesado (MPRIS). Pasa a admitir varios (el detalle
  queda al builder), y el puente marca "hay estado nuevo" y lo manda con el límite de 0,5 s de arriba.
- **Clave**: `~/.config/cassette-fm/nube.token`, con las mismas funciones que la de la LAN (`lan_acceso`): se crea sola
  (0600) y se relee en cada conexión, así `cassette nube regenerar` rige sin reiniciar (corta las conexiones abiertas
  y reconecta con la nueva). La misma clave se carga como secreto en el relay.
- `servicio.servir` lo arranca como a la LAN (`iniciar_nube(...)`, que devuelve la función que lo cierra), envuelto
  para que una excepción no tire el servicio.

### Config

```toml
[nube]
activo = false                      # true: conectar con el relay
url = "wss://relay.ejemplo.com"     # base del relay; obligatoria si activo = true
```

`url` se valida al cargar (esquema `wss://`, o `ws://` contra localhost; sin ruta, query ni credenciales). Con
`activo = true` y sin `url` es un error de config, como los demás.

### CLI y estado

- `cassette nube` muestra si está activo, la `url`, si el control está conectado (y desde cuándo, o el último error), las
  calidades que se están subiendo y la clave para cargar en el relay.
- `cassette nube regenerar` genera una clave nueva.
- `/estado` de la API local gana `nube: {"conectado": bool, "subiendo": [96]}` solo si el puente está activo (para el
  CLI; el applet no lo muestra por ahora).

### Relay de prueba (`scripts/relay-de-prueba.py`)

Como el relay real todavía no existe, un relay mínimo de desarrollo (Python, `websockets`, escucha en localhost o en
la LAN) que implementa el lado relay de este protocolo: acepta al puente, guarda el último `estado` y los logos, y les
sirve a los oyentes `GET /escuchar?calidad=96` (MP3 por HTTP, con lo que manda `demanda` al primero y al último),
`GET /estado` y `POST /sintonizar/<emisora>`. Sirve para probar de punta a punta con mpv o el navegador del teléfono en
la misma red, y queda como referencia ejecutable del protocolo para el relay real. No es el relay: sin TLS ni
endurecimiento.

## Pruebas

- Unitarias con un relay falso en el propio test (`websockets.sync.server` en `127.0.0.1`) y un `Difusor` con
  codificador falso (como ya hacen los tests de la LAN): `hola` y `estado` al conectar, `estado` limitado a uno cada
  0,5 s con el último valor, órdenes con su `resultado` (incluida emisora inexistente), `demanda` que abre y cierra
  audio por calidad, la reconexión tras una caída, el 401 que no reintenta en bucle, el control caído que corta el
  audio a los 60 s, la clave regenerada, `url` inválidas en la config, y que apagado no arranca nada.
- En real, con el relay de prueba: el teléfono en el wifi de casa escuchando a 64 kbps, cambiar de emisora desde ahí,
  cortar el wifi de la PC unos segundos y ver que vuelve solo, y que al cerrar el último oyente el codificador se apaga.

## Lo que queda al builder

- Cómo `Radio.al_cambiar` admite varios interesados.
- Qué hace siguiente/anterior por dentro para no prender el monitor local (hoy los botones de la radio sí lo prenden).
- La forma exacta del relay de prueba (puede ser simple; no se despliega).
- El tamaño de los pedazos de audio y de la cola por conexión, si las mediciones piden algo distinto de lo de la LAN.

## Decisiones que tomé yo (para revisar)

- Nombre del módulo y de la sección: `puente_nube.py` y `[nube]`, en español como el resto (`lan_server`, `[lan]`).
- Calidades fijas 64/96/160 en el código, sin config: alcanza para elegir entre ahorro y calidad.
- Desde la nube no se apaga la radio ni se toca el volumen de esta PC: con la radio apagada se oye estática y sintonizar
  la prende, igual que el applet remoto.
- Los logos se suben por un `PUT` corto en vez de por el control, para no trabar órdenes con unos cientos de KB.
- La clave la genera esta PC (como la de la LAN) y se copia al relay, en vez de al revés.
- Un relay de prueba en `scripts/` para poder probar todo antes de que exista el relay real.
