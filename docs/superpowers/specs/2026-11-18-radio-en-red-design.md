# Radio en red: escuchar las emisoras desde otros dispositivos — diseño

Fecha: 18/11/2026. Antecedentes: [`2026-11-13-cassette-fm-design.md`](2026-11-13-cassette-fm-design.md) (reloj virtual),
[`2026-11-14-etapa-4-spotify-design.md`](2026-11-14-etapa-4-spotify-design.md) (Spotify y Soloist),
[`2026-11-15-peticiones-spotify-design.md`](2026-11-15-peticiones-spotify-design.md) (pedidos por la cola).

## Intención

Hoy la radio entera vive y suena en esta PC. El usuario quiere **escuchar la misma radio desde otros dispositivos** de la
misma red —mismas emisoras, mismas canciones en el mismo segundo, mismas voces y diálogos del DJ— **sin tener que
instalar en cada uno todo lo pesado** (Soloist, Docker, el LLM y el TTS del DJ). Usos concretos:

- **Cambiar de dispositivo** como en Spotify Connect: la radio suena en esta PC *o* en la notebook (mismo sistema,
  mismo usuario), no hace falta que suenen a la vez.
- **Compartir la radio con amigos**: cada uno la escucha en su dispositivo, con su propia cuenta de Spotify, y puede
  cambiar de emisora por su cuenta (en paralelo con los demás). Se conecta apuntando a la dirección de este equipo.

**Prioridad (dicha por el usuario, 18/11):** primero que la radio **ande exactamente igual en la notebook** que en esta PC
—es un uso que va a tener al 100 %—; compartir con amigos es secundario ("quizás nunca lo comparta"). Por eso la primera
entrega apunta a la paridad con esta PC en los dispositivos propios (incluida la rapidez de sintonía y la música bajada
con el DJ), y lo de los amigos es una segunda entrega sobre la misma base.

La idea de fondo: **esta PC es el servidor** (catálogo, agendas, DJ, clips) y cada dispositivo es un **cliente liviano**
que reproduce. El cliente sabe a qué dirección apuntar: en esta PC es "acá mismo", en el de un amigo es la dirección de
esta PC. Un amigo instala el cliente, inicia sesión en Spotify, pega la dirección y la clave, y le aparecen todas las
emisoras.

## Objetivos

- Un **servidor** que publica por red, en solo lectura para los oyentes: emisoras (con sus temas y metadata), agenda
  por emisora y los clips de voz del DJ.
- Un **modo cliente** del servicio `cassette` (mismo paquete, mismo applet) que no necesita Soloist, Docker, LLM ni TTS:
  arma las emisoras con lo que le publica el servidor, calcula la agenda con la misma función determinista, reproduce la
  música con el cliente de Spotify del dispositivo y las voces con un mpv local, con la música atenuada mientras habla
  el DJ.
- **Dos roles**: *dueño* (esta PC, por loopback, control total) y *oyente* (por red, con clave, sin poder editar nada).
- **Dirección de la radio** configurable desde el applet (con la clave de oyente). El applet de un oyente no muestra ni
  permite lo que edita (Nueva emisora…, borrar, renombrar, DJ, rescan).
- **Pasar la radio de un dispositivo a otro** (misma cuenta): sintonizar desde la notebook apaga la de esta PC y al revés,
  como ya hace el diseño de la etapa 4 cuando otro dispositivo toma la reproducción.
- La API del servidor queda **lo bastante completa como para que se escriban otros clientes** (el siguiente probable es
  un cliente web) sin tocar el servidor.

## No objetivos (en este diseño)

- **App de Android** (B): se posterga hasta que el resto esté; el usuario lo piensa aparte.
- **Cliente web / otras plataformas**: la intención es hacerlo después, sobre la misma API. Acá solo se garantiza que la
  API alcance.
- **Servir audio por red**: queda para después, con prioridad baja (pedido del usuario).
- Escuchar **fuera de la red local** (Internet), TLS, cuentas o permisos por amigo. La dirección es una URL cualquiera,
  así que más adelante se puede usar con una VPN o un túnel, pero no se diseña ni se prueba acá.
- **Pedidos de los oyentes** (que un amigo encole un tema y el DJ lo anuncie): la cola de Spotify es de cada cuenta.
- Editar emisoras desde un cliente remoto.

## Anti-objetivos (sería un fracaso aunque "funcione")

- Que un oyente pueda cambiar algo de esta PC (apagarla, cambiar su emisora o su volumen, editar emisoras o el DJ).
- Que lo que hace un oyente se oiga en esta PC o cambie su estado.
- Que la cuenta o el token de Spotify de un amigo pase por el servidor o quede guardado en él.
- Que la clave de oyente aparezca en logs, en `cassette estado` o en mensajes de error.
- Que al pasar de dispositivo suenen los dos a la vez, o que se queden peleando por el control de Spotify.
- Que una falla del servidor, de la red o de la cuenta del oyente deje al cliente colgado: se apaga y avisa, como hoy.
- Que las emisoras de esta PC suenen distinto (agenda, orden, voces, volumen, latencia de sintonía) por haber agregado esto.
- Que la API quede abierta a la red sin autenticación.

## Restricciones

- **Premium reproduce en un dispositivo por cuenta.** Pasar de esta PC a la notebook (misma cuenta) es una transferencia,
  no una reproducción doble. Dos amigos con cuentas distintas sí suenan en paralelo.
- **La API de Spotify, en modo desarrollo, admite hasta 5 usuarios** (el dueño más 4). Un oyente que controla su Spotify con
  la Web API usa su propia sesión (PKCE) contra la app de desarrollador existente (Client ID del proyecto), por lo que
  entra en ese cupo. **Cada amigo tiene que estar dado de alta a mano por el dueño** (su email, en el panel de
  desarrolladores de Spotify) antes de poder iniciar sesión; el flujo de login del cliente es el mismo en cualquier equipo
  porque el redirect (`http://127.0.0.1:8888/callback`) es de su propio loopback y ya está registrado. Un amigo sin alta
  ve un mensaje que lo explica ("pedile al dueño que te agregue en Spotify"). `cassette clave` lo recuerda. Ya se sabe que los temas de una playlist solo se leen con la cuenta que la creó: por eso el servidor
  publica los temas (URI y metadata), así el oyente no necesita acceso a la playlist, solo reproducir las URIs.
- **La Web API de Spotify es lenta para iniciar la reproducción** (3–10 s en esta PC; la sintonía local sale por Soloist
  en 0,3–0,9 s). Por eso los dispositivos propios usan el backend `soloist`. El backend `webapi` (amigos) tarda más y se
  tapa con el sonido de sintonización; cuánto tarda de verdad se mide en un cliente real.
- **El cliente de Spotify del dispositivo tiene que estar abierto** para aparecer como dispositivo de la cuenta.
- La **agenda es determinista** (nombre de la emisora, época fija, lista de temas, corrimiento y pedidos) y se calcula con
  el reloj de pared: dos clientes con los mismos datos calculan lo mismo. Los relojes de los dispositivos pueden diferir,
  así que el cliente mide el desvío contra el reloj del servidor y lo compensa.
- **Los pedidos de Spotify de esta PC** (cola de la cuenta del dueño) alteran la agenda de la emisora (corrimiento y
  pedidos). Como el oyente reproduce lo mismo, la agenda publicada los incluye y el cliente tiene que enterarse de los
  cambios en tiempo real.
- Hoy el **planificador del DJ solo trabaja la emisora sintonizada** en esta PC, y generar un diálogo (LLM + TTS en CPU)
  es lento. El servidor ya no puede asumir que "la sintonizada" es la de esta PC: tiene que haber emisoras en uso por
  oyentes aunque esta PC esté apagada.
- La API hoy escucha solo en `127.0.0.1`, sin autenticación, y se sirve con `http.server` en hilos.
- Desarrollo con TDD; git local en `main`; commits en español. Los tests de applet (`applet/tests`) y de la API
  (`tests/test_api.py`) ya existen y hay que extenderlos.

## Enfoques considerados

1. **El cliente maneja su propio Spotify (elegido).** El servidor publica agenda y clips; cada cliente inicia sesión con su
   cuenta, le ordena a su Spotify "tocá esta lista desde este segundo" y reproduce las voces en el momento justo.
   Es lo mismo para el usuario, un amigo o (después) un cliente web, y el servidor no toca cuentas ajenas. Cuesta repetir
   la lógica del reproductor en cada cliente, pero en Linux es el mismo paquete Python.
2. **El servidor maneja todo por la Web API de Spotify**, con el cliente como parlante y reproductor de voces. Descartado:
   el servidor tendría que guardar tokens de otros y hacer el trabajo por cada oyente (choca con el anti-objetivo de las
   cuentas ajenas).
3. **Retransmitir audio ya mezclado**, es válida siempre y cuando sea solo para el mismo usuario dado que se basa en audio
   ya decodificado por la PC principal (no viola las políticas de spotify), no permitira multiples emisoras en paralelo ni
   multiples cuentas.

El usuario eligió el 1 y este orden de trabajo: primero la base de red y el cliente en Cinnamon (applet), después, con
todo separado por API, los clientes de otras plataformas (probablemente uno web) y por último Android. Dentro de la base,
prioriza que **la notebook ande igual que esta PC** (cliente con Soloist) y deja **compartir con amigos** (backend Web API,
cupo de 5 usuarios, DJ para varias emisoras) como segunda entrega.

## Diseño

### 1. Servidor y roles

- `[red]` en `config.toml`: `escuchar` (por defecto `false`: nada cambia para quien no lo active), `puerto` (el de la API
  actual) y `clave_oyente` (se genera la primera vez que se activa; se regenera con un comando `cassette clave
  regenerar`, que corta a los oyentes actuales). Con `escuchar` activo la API escucha en todas las interfaces, no solo
  en loopback. Guardado de la clave como el de `soloist.key` (modo 600, nunca en la línea de comandos ni en logs).
- **Rol por origen**: una solicitud que llega por loopback es del **dueño** y tiene todos los permisos de hoy. Una que llega
  por red es de un **oyente** y tiene que traer `Authorization: Bearer <clave>`; sin clave o con una mala, 401. El oyente
  solo puede los endpoints de lectura de abajo y los de presencia; todo lo demás, 403. Las solicitudes de dueño por red
  no existen (ni desde la notebook del usuario, salvo que más adelante se pida). "Loopback" es literal: la dirección de
  origen es `127.0.0.1`/`::1`. Una solicitud que llega desde la propia IP de la LAN de esta PC cuenta como de red
  (oyente), así que el servicio local y el applet de esta PC siempre hablan con el servidor por `127.0.0.1`. Supuesto
  declarado: *loopback = dueño* se rompe si alguien pone un proxy o un túnel SSH delante del servicio; se documenta.
- Los endpoints actuales (`/estado`, `/sintonizar`, `/volumen`, `/dj/*`, las acciones) siguen siendo **del dueño**, es
  decir, de la radio local de esta PC.
- **Endpoints nuevos para oyentes (solo lectura)** — la forma exacta es del constructor, pero tienen que cubrir:
  - versión de la API y hora del servidor (para medir el desvío de reloj);
  - catálogo: emisoras con nombre, fuente, ícono, ajustes de DJ que el cliente necesita, y sus temas (clave, URI de
    Spotify, duración y metadata). Sin rutas de archivos del servidor. Lleva una **versión del catálogo** (un hash de las
    emisoras y sus temas) que también aparece en la respuesta de agenda: si cambia (rescan, edición), el cliente vuelve a
    bajar el catálogo y recalcula antes de seguir, para que dos dispositivos no se desvíen en silencio;
  - agenda de una emisora: el corrimiento y los pedidos vigentes (lo que hoy se guarda en `Estado.agendas`), con una
    firma que cambia cuando cambian, y una forma de enterarse de cambios sin consultar cada segundo (consulta larga,
    eventos del servidor o consulta periódica barata: lo decide el constructor);
  - intervenciones del DJ vigentes y futuras de una emisora (instante de inicio, duración, tema ancla) y el **clip de audio**
    de cada una;
  - quién soy (`rol`), para que el cliente sepa qué mostrar.
- **Presencia**: un oyente avisa qué emisora tiene sintonizada (y que sigue ahí, con un latido) para que el servidor sepa
  qué emisoras están **en uso**. Sin latido en unos segundos, deja de contar. El servidor no guarda nada de la cuenta de
  Spotify del oyente ni su volumen.

### 2. Emisoras en uso y el DJ

- El servidor define **emisoras en uso** = la sintonizada en esta PC (si está encendida) más las que tienen oyentes con
  latido. El planificador del DJ pasa de "la sintonizada" a "las que están en uso".
- **Primera entrega**: el DJ genera voces para **una** emisora a la vez (límite configurable `dj.emisoras_en_uso_max`,
  por defecto 1, que la entrega no sube). Si hay más emisoras en uso que el límite, el planificador atiende **la de esta
  PC si está encendida** (aunque sea más vieja: así lo que suena acá no cambia por lo que hagan los oyentes) y, si no, la
  que se sintonizó **más recientemente** *(mi decisión, ver abajo)*; los oyentes de las demás escuchan música sin voces y
  sin que eso sea un error. Los clips ya generados de una emisora que deja de atenderse se **siguen sirviendo** mientras
  existan en el registro (se limpian por su propio vencimiento, como hoy). Subir el límite (DJ para varias emisoras a la vez, con el costo de CPU que tiene) es la **segunda
  parte** de este proyecto y se diseña aparte, midiendo cuánto tarda un diálogo en este equipo.
- Los **pedidos** del dueño siguen alterando la agenda y se publican como parte de ella (ver Restricciones).

### 3. Modo cliente

- `[radio]` en `config.toml` del dispositivo: `servidor` (`"local"` por defecto, o una URL como
  `http://192.168.1.10:7710`) y `clave` (solo para un servidor remoto; mismo cuidado que la del servidor). Con `"local"`
  nada cambia: es el servicio de hoy, con servidor y reproducción en la misma máquina.
- En modo cliente el servicio **reutiliza la `Radio`, el locutor, el MPRIS, los atajos, el dial y la API local de hoy**, y
  cambia de dónde salen los datos y cómo se reproduce:
  - el catálogo y las agendas vienen del servidor, no de `estaciones.json` ni de carpetas o de la Web API de Spotify;
  - las intervenciones y los clips vienen del servidor (se descargan antes de su hora a una caché local), no de un
    planificador local; no hay planificador, Docker ni servicio DJ;
  - la música sale por un **backend de Spotify** (ver "Backends de Spotify" más abajo). El de la Web API usa el cliente de
    Spotify del dispositivo con la sesión del propio usuario (login
    PKCE, mismo flujo y mismo Client ID del proyecto, token en el estado local, nunca enviado al servidor). El
    reproductor nuevo tiene la misma interfaz que los actuales (`sintonizar`, `detener`, `posicion`, `volumen`,
    `atenuar`, …). Sin Soloist, la posición se interpola con el reloj y el desvío contra el servidor. Como en la etapa 4,
    no se usa el contexto de la playlist (el oyente no la tiene): se manda a `play` una **lista `uris`** en el orden de la
    agenda, una ventana de unos ~100 temas desde el actual (el máximo real se verifica), con `position_ms` para el tema de
    arranque, y se rearma en un borde de tema cuando se acerca al final o hay desvío; apaga shuffle y repeat antes;
  - **qué se detecta como "me sacaron la reproducción"**: el cliente sondea el dispositivo activo de la cuenta cada pocos
    segundos mientras suena (la frecuencia exacta es del constructor; se apunta a ≲5 s) y, si deja de ser el suyo, se
    apaga y avisa; no hay otra forma de enterarse sin Soloist;
  - las voces suenan en un mpv local; el ducking de la música lo hace el cliente moviendo el volumen del stream de
    Spotify por PipeWire/PulseAudio (como la calibración de la etapa 4). **Es requisito** del cliente: sin `pactl`/stream
    controlable el cliente avisa al arrancar y no sintoniza Spotify (en Linux Mint está de serie). No hay respaldo por la
    Web API: mueve el volumen de todo el dispositivo y es lento *(mi decisión)*;
  - el reloj se corrige con el desvío medido contra la hora del servidor, para que dos dispositivos suenen en el mismo
    segundo aunque sus relojes difieran.
- **Backends de Spotify** (misma interfaz de reproductor; el constructor decide cómo se comparten el código y las pruebas):
  - **`soloist`** — para los **dispositivos propios del usuario** (la notebook). Es el mismo reproductor de esta PC
    (`reproductor_spotify`): servicio `cassette-soloist` en el dispositivo, sintonía directa en ~0,3–0,9 s, eventos por
    WebSocket (`device_changed` para el pasaje de dispositivo, `position_sync`), volumen propio para el ducking y la
    calibración de la etapa 4, sin depender de que la app de Spotify esté abierta ni de PipeWire. Se instala con el modo
    cliente del instalador (reutilizando `scripts/instalar-spotify.sh`: binario, API key del propio usuario, emparejado
    y renovación cada 90 días con `actualizar-soloist.sh`). El dispositivo de Spotify lleva un nombre distinto en cada
    equipo (p. ej. `cassette-fm notebook`) para no confundirse con el de esta PC. Sigue sin instalar Docker, LLM ni TTS.
    **Es el backend de la primera entrega** y debe dar paridad con esta PC.
  - **`webapi`** — para **otras cuentas** (amigos): lo descrito arriba (Web API y cliente de escritorio de Spotify,
    ~3–10 s para sintonizar, sondeo del dispositivo activo, ducking por PipeWire/PulseAudio). No se reparte la API key de
    Soloist del dueño. Es de la segunda entrega.
  - El cliente elige el backend por configuración (`[radio] backend = "soloist" | "webapi"`).
- El **estado de escucha** (emisora, volumen, encendida) es del cliente; no se sincroniza con el servidor ni con otros
  clientes, salvo la presencia.
- **Las ediciones no existen en modo cliente**: el servicio local de un cliente rechaza las rutas de dueño (409 con un
  mensaje claro) porque la API del servidor ya las rechaza con 403.
- **Fallas**: servidor inalcanzable, clave rechazada, Spotify cerrado o con otra cuenta activa, clip que no se bajó a
  tiempo (se escucha música sin voz). El cliente se apaga y avisa con el motivo cuando lo que falla es la música; lo que falla
  de la voz se registra y sigue.

### 4. Pasar de un dispositivo a otro (misma cuenta)

Se apoya en lo que la etapa 4 ya decidió: si otro dispositivo toma la reproducción de la cuenta, la radio de esta PC se
apaga y avisa ("Spotify se está escuchando en otro dispositivo"); y sintonizar en esta PC recupera el control. Entonces:

- Sintonizar desde la notebook (cliente, misma cuenta) transfiere Spotify a la notebook; la radio de esta PC se apaga sola.
- Sintonizar en esta PC vuelve a transferir; el cliente de la notebook se apaga con el mismo aviso.
- No se agrega ninguna señal entre cliente y servidor para esto salvo lo que ya haga falta (presencia). El constructor
  verifica que no queden las voces de uno sonando mientras la música ya es del otro.
- Las cuentas distintas (amigos) no se transfieren nada: suenan en paralelo.

### 5. Applet y configuración

- El applet de Cinnamon sigue hablando con el servicio **local** del dispositivo (loopback, como hoy). Se agregan en sus
  ajustes **"Dirección de la radio"** (por defecto `local`) y **"Clave de oyente"**, que el servicio aplica sin reinstalar
  nada (la forma de pasarlos del applet al servicio es del constructor).
- Con `rol: oyente` el applet oculta o deshabilita *Nueva emisora…* y cualquier otra edición; el dial y el menú de
  emisoras funcionan igual.
- El servidor muestra su clave de oyente y su dirección con un comando (`cassette clave`), para pasársela a un amigo
  junto con el link de instalación del cliente.
- El instalador (`scripts/instalar-todo.sh`) gana un modo cliente que no instala Soloist, Docker ni el servicio DJ.

### 6. Compatibilidad y seguridad

- Con `[red] escuchar = false` (por defecto) y `[radio] servidor = "local"` el comportamiento y la API son exactamente los de
  hoy.
- La clave de oyente es un secreto de red local en HTTP sin cifrar: se documenta que sirve para una red de confianza.
- La API de oyentes no expone rutas de archivos, la clave de Soloist, la configuración del DJ ni el token de Spotify del dueño.

## Lo que queda al constructor

- Forma exacta de los endpoints, formato de eventos o consulta larga para los cambios de agenda, y cómo se versiona la
  API para que clientes futuros (web) no se rompan.
- Cómo se parte en planes (sugerencia, **primera entrega** = notebook igual que esta PC: 1. servidor con roles y clave +
  endpoints de lectura; 2. modo cliente con catálogo y agenda remotos y backend `soloist`, sin voces; 3. voces: clips e
  intervenciones remotas; 4. applet, instalador de cliente y verificación de pasar de dispositivo. **Segunda entrega** =
  compartir: backend `webapi`, alta de amigos y DJ para varias emisoras, aparte).
- La tolerancia de desvío para re-sintonizar y el reparto del código entre los backends, medidos en la notebook real. Para
  el backend `webapi`, si hace falta ayuda del DBus/MPRIS del cliente de escritorio para reducir la latencia.
- Cómo se pasan los ajustes del applet al servicio local, y el diseño de `cassette clave`.
- El sonido de sintonización en el cliente (se puede reusar el actual) y la caché de clips.

## Decisiones que tomó el diseñador (no las pidió el usuario; se pueden cambiar)

- Una única **clave de oyente** compartida y regenerable, en lugar de una cuenta por amigo.
- **Dueño = loopback**; ni la notebook del usuario puede ser dueño por red.
- Primera entrega con **DJ para una sola emisora en uso**, la de sintonía más reciente.
- **Dispositivos propios con Soloist, amigos con la Web API.** El primero es la prioridad del usuario (paridad con esta
  PC); el segundo usa la sesión de cada amigo (que entra en el cupo de 5 usuarios de la app de desarrollador, con alta a
  mano) y es secundario.
- Los cambios de la API actual del dueño no se tocan: lo nuevo se agrega al lado.
- Fuera de la red local no se diseña nada.

## Verificación con el usuario (al final, juntos)

**Primera entrega:** notebook y esta PC con la misma cuenta: sintonizar en la notebook apaga esta PC y suena la misma
canción en el mismo segundo, con la misma voz del DJ, la misma rapidez de sintonía y la misma música bajada cuando habla
el DJ; volver a sintonizar acá vuelve a pasar. **Segunda entrega:** un segundo cliente con otra cuenta (un amigo o una
cuenta de prueba) suena en paralelo, en otra emisora si quiere, sin tocar lo de esta PC. El applet del cliente no deja
editar emisoras. La clave mala o regenerada corta al cliente con un mensaje claro. Todo con `[red] escuchar` apagado vuelve a
ser la radio de hoy.
