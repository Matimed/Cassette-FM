# Relay en la nube — diseño

> **Cambio posterior:** `APP_PASSWORD` pasó a ser `MASTER_PASSWORD` (la clave maestra) y hay claves de solo escucha o
> completas, administradas desde la PC: [`2026-11-19-claves-relay-design.md`](2026-11-19-claves-relay-design.md).
> Donde este documento dice `APP_PASSWORD`, leer la maestra.

Estado: borrador para aprobar (2026-11-19). Segunda de las tres piezas del
[puente a la nube](2026-11-19-puente-nube-design.md): implementa el lado relay del protocolo versión 1 que el puente
de esta PC ya habla. La tercera pieza (la web) viene después y se monta sobre este relay.

## Para qué

El usuario quiere escuchar y manejar su radio desde cualquier dispositivo y cualquier red (el teléfono con datos
móviles, una tablet, un smart TV, una PC con Windows) sin instalar nada. Su PC está detrás de un router sin puertos
abiertos, así que hace falta un punto de encuentro público: el relay. La PC se conecta hacia afuera al relay
(ya hecho, `puente_nube.py`) y los oyentes se conectan al relay. Sigue siendo **un solo usuario**: lo que se ordena
desde la nube cambia la radio de esta PC.

Esta entrega deja el relay listo para desplegar y probar contra la PC; la web de verdad es la entrega siguiente.

## Decisiones del usuario

- **Plataforma: Render, plan gratuito, desplegando una imagen publicada en Docker Hub** (el repo sigue solo local).
- **Colas de los oyentes más largas** que la propuesta inicial de 4 s, para que con datos móviles flojos no haya saltos
  constantes. (Los valores de abajo son la respuesta a eso.)
- Lo pedido originalmente: token de la PC por `INGEST_TOKEN`, clave de los oyentes por `APP_PASSWORD`, Docker con un
  solo puerto `$PORT` detrás del proxy de la plataforma, la PC sube cada calidad una sola vez para todos los oyentes,
  aviso a la PC al pasar de 0 a 1 oyente y de vuelta a 0, oyentes lentos que no acumulan atraso ni RAM, y la radio
  fuera de línea se informa sin que el relay falle.

## Restricciones

- **Render gratis**: un solo puerto HTTP (`$PORT`, TLS lo pone Render), 512 MB de RAM, CPU compartida, 750 horas por
  mes (alcanza para un servicio prendido todo el mes). Se duerme a los 15 min sin pedidos HTTP ni mensajes de
  WebSocket entrantes, y despierta en ~1 min con el próximo pedido. Los pedidos HTTP duran como mucho 100 min; los
  WebSockets no tienen límite. Todo el estado vive en memoria: un reinicio o redespliegue lo pierde, y la PC lo vuelve
  a mandar al reconectarse.
- **El protocolo con la PC es el de la versión 1** ([spec del puente](2026-11-19-puente-nube-design.md#protocolo-versión-1)):
  rutas, mensajes y reglas no cambian, salvo el agregado de `latido` (abajo), que es compatible.
- **Las claves nunca en logs ni en URLs.** La de la PC va en `Authorization: Bearer`; la de los oyentes, en el cuerpo
  del pedido de entrada o en `Authorization`.
- Poca CPU: el relay no decodifica ni transcodifica audio, solo reparte bytes.

## Objetivos, no objetivos, anti-objetivos

**Objetivos**

- Aceptar la conexión de la PC (control, audio por calidad, logos) con `INGEST_TOKEN`.
- Guardar el último estado de la radio y los logos, y servirlos a los oyentes.
- Pasar las órdenes de los oyentes (sintonizar, siguiente, anterior) a la PC y devolver su resultado.
- Repartir el audio de cada calidad a todos sus oyentes, y pedirle a la PC solo las calidades que alguien escucha.
- API privada para los oyentes con `APP_PASSWORD`, usable desde un navegador (incluido Safari de iOS y los de smart TV)
  y desde reproductores como VLC o mpv.
- Una página mínima de prueba (entrar, ver el estado, cambiar de emisora, escuchar) para probar antes de la web.
- Imagen Docker chica, lista para publicar en Docker Hub y desplegar en Render, con la guía de despliegue.

**No objetivos (ahora)**

- La web de verdad (entrega siguiente; la página de prueba se reemplaza).
- Varios usuarios, cuentas o claves por dispositivo.
- Guardar nada en disco ni en una base: todo en memoria.
- Apagar la radio o tocar el volumen de la PC desde la nube (igual que el puente).

**Anti-objetivos**

- Que un oyente lento haga crecer la RAM sin límite o arrastre un atraso cada vez mayor.
- Que un oyente lento frene a los demás o a la recepción del audio de la PC.
- Que la PC caída, una orden sin respuesta o un mensaje roto tiren el relay.
- Que una clave aparezca en un log, una URL o la imagen Docker.

## Enfoques considerados

- **Python con aiohttp, un proceso asyncio.** Elegido. Atiende en el mismo puerto los WebSockets de la PC, el audio
  por HTTP de los oyentes y la API; ~40 MB de RAM; mismo lenguaje que el resto, y los tests pueden conectar el puente
  real de la PC contra el relay.
- Hacer crecer el relay de prueba (`websockets` síncrono + `ThreadingHTTPServer`): un hilo por oyente y un manejo de
  conexiones frágil detrás de un proxy. Descartado.
- Go o Node: algo más livianos, pero otro lenguaje y otros tests para uno o dos oyentes. Descartado.

## Diseño

### Dónde vive

Carpeta `relay/` en este repo, autocontenida: su propio `Dockerfile`, `requirements.txt` (aiohttp con versión fija),
paquete `cassette_relay/`, página de prueba en `relay/web/` y un `README.md` con el despliegue. No importa nada de
`cassette_fm` (las constantes del protocolo se duplican, son tres). Los tests del relay corren con el pytest del repo;
`aiohttp` se suma a las dependencias `dev` de `pyproject.toml`.

`scripts/relay-de-prueba.py` y su test se borran: el relay real corre igual en esta PC (`python -m cassette_relay` o
`docker run`) y es la referencia del protocolo desde ahora. El README principal y el del puente pasan a apuntar al
relay real.

### Configuración (variables de entorno)

| Variable | Qué es |
|---|---|
| `INGEST_TOKEN` | Obligatoria. La clave de la PC: el contenido de `~/.config/cassette-fm/nube.token` (la muestra `cassette nube`). |
| `APP_PASSWORD` | Obligatoria, al menos 8 caracteres. La clave de los oyentes. |
| `PORT` | Puerto en el que escucha (Render la pone); por defecto 8080. |

Si falta una obligatoria (o `APP_PASSWORD` es más corta), el relay no arranca y lo dice en el log, sin mostrar valores.
Cambiar `APP_PASSWORD` invalida las sesiones abiertas (ver Acceso).

### Lado de la PC (`/casa/…`)

Todo con `Authorization: Bearer <INGEST_TOKEN>` (comparación en tiempo constante); sin ella, 401 antes de aceptar el
WebSocket.

- **Control** `GET /casa/control` (WebSocket). Una sola conexión vigente: una nueva reemplaza y cierra a la anterior.
  Ping cada 20 s. Al recibir `hola` con `protocolo: 1` contesta con `demanda` (las calidades que hoy tienen oyentes,
  incluidas las que están en su gracia). Con otro `protocolo`, cierra la conexión con un error en el log.
  - `estado`: lo guarda si su `seq` es mayor que el último de esta conexión (el `seq` vuelve a empezar en cada
    conexión). Por cada emisora de `iconos` cuya versión no coincide con el logo guardado, manda `pedir_icono`, y no lo
    repite mientras ese pedido esté pendiente. Un pedido pendiente vence a los **60 s** sin que llegue el logo y al
    reconectarse el control: el próximo `estado` lo vuelve a pedir (así una subida que falló no deja la emisora sin
    logo hasta que cambie de versión). Los logos de emisoras que ya no están en el estado se descartan.
  - `resultado`: resuelve la orden pendiente con ese `id`; un `id` desconocido se ignora.
  - `latido`: no hace nada (ver Cambio en el puente). Cualquier otro tipo, o un JSON roto, se ignora con un aviso en el
    log y no corta la conexión.
  - Al cerrarse el control, la radio queda **fuera de línea**: las órdenes pendientes fallan con "la radio se
    desconectó". El último estado y los logos se conservan para mostrarlos como "lo último que sonó".
- **Audio** `GET /casa/audio?calidad=K` (WebSocket), `K` en 32, 64, 96 o 160 (otra cosa: cierre con código 1008). Una por
  calidad; una nueva de la misma calidad reemplaza a la anterior. Cada mensaje binario se reparte a los oyentes de esa
  calidad. Los mensajes de texto se ignoran. Las conexiones de audio pueden seguir abiertas un rato con el control caído
  (el puente las corta a los 60 s); su audio se sigue repartiendo.
- **Logo** `PUT /casa/icono/<emisora url-encoded>?v=<versión>`: guarda el logo con su `Content-Type` si la emisora
  está en el último estado, el tipo es uno de `image/png`, `image/jpeg`, `image/webp` o `image/gif` (los de la LAN) y pesa hasta 4 MB. Contesta 204; 400 si la emisora no está en el estado; 413/415 si no cumple.

### Demanda (aviso de oyentes a la PC)

Cada calidad está pedida si tiene al menos un oyente o si su último oyente se fue hace menos de **10 s** (gracia: así
recargar el reproductor o cambiar de emisora, que reabre el audio, no apaga y prende el codificador de la PC). Cada vez
que cambia el conjunto de calidades pedidas se manda `demanda` con la lista completa: de 0 a 1 oyente en una calidad,
al instante; de vuelta a 0, al vencer la gracia. Si el control no está conectado no se manda nada; al reconectarse,
la respuesta al `hola` ya lleva la demanda vigente.

### Reparto a los oyentes

Cada oyente es una conexión HTTP de audio con su propia cola de bytes:

- **Tope de la cola: 15 s de audio** de su calidad (`15 × kbps × 1000 / 8` bytes: ~59 KB a 32, ~117 KB a 64, ~293 KB a 160).
  Absorbe bajones de la conexión móvil sin perder nada.
- **Si se llena, un solo salto al vivo**: se vacía la cola entera y se sigue con lo que llega. Nunca se descartan
  pedazos sueltos (saltos constantes).
- **Oyente trabado**: si una escritura hacia él no avanza en **30 s**, se lo corta (el reproductor reconecta solo).
- Lo que tarde un oyente nunca frena la lectura del WebSocket de audio de la PC ni a los demás oyentes: la llegada de un
  pedazo solo lo agrega a cada cola, sin esperar a nadie.
- **Sin audio**: si a un oyente no le llega nada en **20 s** (la PC se cayó o no arrancó a subir), se corta su conexión.
- Un oyente que se va (cierra la pestaña, pierde la señal) se detecta en cuanto falla la escritura o se cierra la
  conexión, se lo saca de su calidad y cuenta para la demanda.

### API de los oyentes

Todas las rutas `/api/…` exigen sesión (cookie) o `Authorization: Bearer <APP_PASSWORD>`, salvo `entrar`. Sin acceso:
401 con JSON. Errores siempre como `{"error": "texto en español"}`.

| Ruta | Respuesta |
|---|---|
| `POST /api/entrar` `{"clave": "…"}` | 204 y la cookie de sesión; 401 si no coincide; 429 si hay demasiados intentos. |
| `POST /api/salir` | 204 y borra la cookie. |
| `GET /api/estado` | `{"en_linea": bool, "visto_hace": segundos o null, "calidades": [32, 64, 96, 160], "radio": {…} o null}` |
| `POST /api/sintonizar` `{"estacion": "…"}` | Orden a la PC (abajo). |
| `POST /api/siguiente`, `POST /api/anterior` | Orden a la PC. |
| `GET /api/escuchar?calidad=96` | MP3 en vivo (`audio/mpeg`, `Cache-Control: no-store`), por defecto 96. |
| `GET /api/icono/<emisora>?v=<versión>` | El logo guardado con su tipo; 404 si no está. Con `?v=` igual a la versión guardada, `Cache-Control` de un año (`immutable`). |
| `GET /salud` (sin clave) | 200 `ok`, para el chequeo de Render. |

- `radio` son los campos del último `estado` sin `tipo` ni `seq` (`encendida`, `estacion`, `pista`, `fuente`,
  `segundo`, `estaciones`, `iconos`); `visto_hace` son los segundos desde que se fue la PC (null si está en línea o
  nunca vino). Con la radio fuera de línea igual se devuelve el último `radio` conocido.
- **Órdenes**: se mandan a la PC con un `id` nuevo y se espera su `resultado` hasta **10 s**. Respuestas: 200
  `{"ok": true}`; 409 `{"error": …}` si la PC dijo que no (por ejemplo "esa emisora no existe"); 503 si la radio está
  fuera de línea o se desconectó esperando; 504 si no contestó a tiempo. `estacion` que no es un texto no vacío: 400.
- **Escuchar**: calidad que no es 32, 64, 96 o 160: 400. Con la radio fuera de línea: 503 sin abrir el stream. Si no, se
  abren los encabezados al toque y empieza a fluir cuando la PC arranca su codificador (1–2 s la primera vez).
- Las órdenes y `entrar` exigen `Content-Type: application/json` (junto con la cookie `SameSite`, corta los pedidos
  cruzados desde otros sitios).

### Acceso (clave de los oyentes)

- **Sesión por cookie**, porque el reproductor de audio del navegador no puede mandar encabezados propios: `entrar`
  pone `sesion=<vence>.<firma>` con `HttpOnly`, `SameSite=Lax`, `Path=/`, `Max-Age` de **180 días**, y `Secure`
  cuando el pedido llegó por HTTPS (en Render, `X-Forwarded-Proto: https`; probando en localhost por HTTP, sin
  `Secure`). La firma es HMAC-SHA256 de `vence` con una llave derivada de `APP_PASSWORD`: no hay sesiones guardadas,
  un reinicio no desconecta a nadie y cambiar la clave invalida todas.
- **Bearer** con la clave en `Authorization` también vale en todas las rutas, para VLC, mpv o curl.
- **Intentos fallidos**: a partir del 5.º fallo en un minuto (en total, no por IP: es un solo usuario, y detrás del
  proxy la IP es dudosa), todo intento de clave contesta 429 durante 1 min, incluida la correcta. Cuentan los fallos de
  `entrar` y los de Bearer. **Una cookie de sesión válida no es un intento de clave**: sigue andando durante el
  bloqueo, así un extraño que conoce la URL no le corta el audio ni el control a quien ya entró. Las rutas `/casa/…` no
  cuentan ni se bloquean (su clave es larga y al azar; un 401 ahí no suma).
- **Corte a los 100 min de Render**: el stream de audio es un pedido HTTP y Render lo corta a los 100 min. La página
  de prueba (y la web después) reabre el audio sola cuando se corta o da error mientras se está escuchando (un hueco
  de 1–2 s). Para reproductores externos el README indica cómo hacer que reconecten.

### Página de prueba (`relay/web/`)

Archivos estáticos públicos (no tienen nada privado; los datos salen de la API). El relay sirve `relay/web/` en `/`.
Hoy, una sola página mínima: formulario de clave, estado (en línea, emisora, tema), botones de emisoras con sus logos,
selector de calidad y un `<audio>` que apunta a `/api/escuchar`. Es para probar; la web de la entrega siguiente
reemplaza la carpeta.

### Cambio en el puente (esta PC)

Render duerme el servicio tras 15 min sin mensajes entrantes. Con la radio quieta (sin cambios de estado) el control
podría pasar más que eso sin mandar nada. El puente manda `{"tipo": "latido"}` por el control cuando lleva **2 min** sin
mandar otro mensaje. Así el relay no se duerme mientras la PC esté conectada. Con la PC apagada se duerme a los 15 min;
el primer oyente que entra lo despierta (~1 min) y ve "fuera de línea". El spec del puente gana `latido` en la lista de
mensajes de la PC al relay.

### Imagen y despliegue

- `Dockerfile` sobre `python:3.12-slim`, usuario sin privilegios, solo `requirements.txt`, el paquete y `web/`;
  arranca `python -m cassette_relay`. Sin claves adentro (`.dockerignore` deja afuera todo lo demás).
- `relay/README.md` con: correrlo local (venv o `docker run -e …`), apuntar el puente (`[nube] url =
  "ws://127.0.0.1:8080"`), publicar en Docker Hub (`docker build`/`docker push`, imagen pública: no lleva nada privado)
  y crear el servicio en Render (imagen existente, plan gratis, variables `INGEST_TOKEN` y `APP_PASSWORD`, chequeo en
  `/salud`, redesplegar tras cada `push`). Después, `[nube] url = "wss://<servicio>.onrender.com"` en la PC.
- Crear las cuentas, publicar la imagen y crear el servicio lo hace el usuario con la guía (son sus cuentas); la
  entrega termina con el relay andando en local contra la PC y la imagen construida.

### Logs

Una línea por evento que importa: la PC se conectó/desconectó, calidades pedidas, oyentes que entran y salen (con la
calidad y cuántos quedan), saltos al vivo por cola llena, oyentes cortados, intentos de clave fallidos. Sin claves, sin
cookies, sin el encabezado `Authorization`. El log de accesos de aiohttp queda apagado (no hace falta y llenaría el
log con el audio).

## Pruebas

- Unitarias con el servidor de prueba de aiohttp: auth de la PC (401 sin clave o con otra), `hola` → `demanda`, estado
  guardado y `seq` viejo descartado, `pedir_icono` una vez por versión, `PUT` de logos con sus límites, órdenes con
  sus respuestas (ok, 409, 503 fuera de línea, 504 sin respuesta), reemplazo del control y del audio, demanda al
  primer oyente y al vencer la gracia, reparto a varios oyentes, cola llena que salta al vivo una sola vez, oyente
  trabado cortado, oyente sin audio cortado, acceso (cookie, Bearer, firma vencida o adulterada, cambio de clave,
  límite de intentos), variables faltantes, `/salud`.
- De punta a punta en el test: el `PuenteNube` real con un `Difusor` de codificador falso conectado al relay, un oyente
  que escucha y recibe los bytes, una orden que llega a la radio falsa, y la demanda que se apaga al irse.
- En real: el relay en esta PC (`docker run`) con el puente apuntando a él, el teléfono en el wifi de casa escuchando
  por la página de prueba, cambio de emisora, y cortar el oyente para ver que el codificador de la PC se apaga.

## Lo que queda al builder

- La organización interna de `cassette_relay/` (módulos para la casa, los oyentes, el acceso y la app son lo esperable).
- Cómo se detecta en aiohttp que un oyente se fue mientras no hay audio para escribirle.
- El diseño visual de la página de prueba (mínimo, se reemplaza).
- Versión exacta de aiohttp (fijarla en `requirements.txt`).

## Decisiones que tomé yo (para revisar)

- Un solo proceso, todo en memoria, sin base: un reinicio pierde el estado y la PC lo repone en segundos.
- Gracia de 10 s antes de avisar a la PC que una calidad quedó sin oyentes.
- Cola de 15 s, salto al vivo de una vez, corte a los 30 s trabado y a los 20 s sin audio.
- Cookie firmada de 180 días derivada de la clave, más Bearer; límite global de 5 fallos por minuto.
- Página de prueba servida por el mismo relay y la web futura en la misma carpeta (mismo origen: sin CORS).
- `latido` del puente cada 2 min sin otros mensajes.
- Imagen pública en Docker Hub (no lleva nada privado).
- Durante el bloqueo por intentos fallidos, la cookie válida sigue andando; Bearer y `entrar` se bloquean; `/casa/…`
  no participa.
- Un `pedir_icono` pendiente vence a los 60 s o al reconectarse la PC, y se vuelve a pedir.
- Ante el corte de 100 min, la página reabre el audio sola (hueco de 1–2 s) en vez de que el relay intente evitarlo.
- Supuesto a verificar al desplegar: que el `latido` (un mensaje entrante por WebSocket) mantiene despierto el
  servicio gratis de Render, como dice su changelog.
- Borrar el relay de prueba: el real lo reemplaza también para probar en casa.
