# cassette-fm — Diseño

> Fecha: 13/11/2026. Resultado del brainstorming inicial. Base para dar de alta las tareas en Beans.
> Contexto y relevamiento previo: [`docs/project-context.md`](../../project-context.md).

## Intención

Convertir la biblioteca de música local en un conjunto de **radios continuas**, como las radios de GTA (de ahí
salió la idea). Cada subcarpeta de `~/Música` es una estación. Todas "están sonando" siempre en orden aleatorio
y, al sintonizar una, **se entra con el tema ya empezado**. Se cambia de estación como en una radio. Es un
proyecto personal y tiene que ser divertido de usar.

La PC del usuario tiene que quedar **liviana**. La parte pesada que viene después (el DJ con IA: LLM y quizás TTS)
tiene que poder correr en otra máquina.

## Objetivos

- **MVP:** todas las estaciones (una por carpeta) suenan en orden aleatorio, se puede pasar a la siguiente o a la anterior y sintonizar una
  por nombre. Al sintonizar se entra a mitad del tema que "está sonando".
- Que la arquitectura permita, más adelante y sin reescribir:
  - controles de escritorio (un applet de Cinnamon con rueda del mouse, atajos de teclado),
  - un DJ por estación (voz propia, habla cada algunos temas, no en todos),
  - el DJ (LLM y quizás TTS) en otra máquina,
  - playlists de Spotify como estaciones (el usuario tiene Premium),
  - una UI con un selector estilo GTA,
  - eventualmente clientes en otra PC o en el celular.

## No objetivos

- Transmitir audio de radio por la red (Icecast o similar). El audio se reproduce siempre en la máquina del oyente.
- Sincronizar con exactitud entre varios clientes. Si algún día hay dos, que muestren "más o menos lo mismo" alcanza.
- Que haya varios oyentes a la vez.

## Anti-objetivos (cosas que lo harían fracasar aunque funcione)

- Que consuma recursos de forma notoria en la PC del usuario. En particular, que las estaciones que no se escuchan
  consuman algo, o que el LLM sea obligatorio en la PC local.
- Silencios largos: al sintonizar, la música tiene que arrancar al instante. El DJ nunca puede trabar la música.
- Que cambiar de estación sea engorroso.

## Restricciones

- Linux Mint 22.1 **Cinnamon** (no GNOME). Ryzen 5 5600G sin GPU dedicada, 13 GB de RAM.
- Instalado: Python 3.12, mpv, Node 18, Docker. **No hay ffmpeg** (recién haría falta en la etapa del DJ).
- Biblioteca actual: `~/Música/Lentos` y `~/Música/Regueton 2000`, 128 mp3.
- Git solo local, commits en español.

## Enfoques considerados

| Enfoque | Qué es | Contras |
|---|---|---|
| **A. Servicio local + clientes livianos** (elegido) | Un único servicio Python con agenda, reproductor (mpv) y API de control local. La CLI, el applet y la UI son clientes livianos. El DJ es un servicio aparte. | Si algún día hay clientes remotos, hay que exponer la API y servir archivos (está previsto). |
| B. Motor y reproductor como dos procesos desde el día 1 | El motor es un servidor HTTP que calcula la agenda y sirve archivos; el reproductor es otro daemon. | Hoy agrega red, protocolo y dos servicios para algo que vive en una sola PC. |
| C. Sin servicio, solo comandos | `cassette next` calcula la agenda y relanza mpv. | Se queda corto con el applet y el DJ, que necesitan un proceso vivo que sepa qué suena. |

**Se eligió A.** Al principio el usuario pensaba en separar *motor / reproductor* para poder mover cosas a otra
máquina. Como lo que se va a mover es el **DJ** (y no el motor), el corte que importa es **radio ↔ DJ**. A
deja ese corte limpio y no paga hoy el costo de B. La agenda se escribe como un módulo puro y aislado, así que
pasar a B más adelante es exponerla por HTTP.

## Arquitectura

```
cassette-fm (servicio de usuario, Python)            clientes
 ├─ biblioteca: escanea estaciones, lee duraciones    ← CLI `cassette`
 ├─ agenda (pura): estación + instante → pista, seg   ← applet Cinnamon   (etapa 2)
 ├─ reproductor: controla mpv por IPC                 ← UI estilo GTA     (etapa 5)
 ├─ API de control: HTTP+JSON en 127.0.0.1
 └─ cliente DJ ───────────(etapa 3)──────────► servicio DJ (LLM + TTS), local o remoto
```

### Biblioteca

- Raíz configurable (por defecto `~/Música`). Cada **subcarpeta directa** es una estación y su nombre es el
  de la carpeta. Los archivos sueltos en la raíz y las carpetas ocultas se ignoran. Una estación incluye los
  archivos de audio de su carpeta **de forma recursiva**.
- Formatos: los que lean mpv y `mutagen` (mp3, flac, ogg, m4a). Hoy hay solo mp3.
- Las duraciones se leen con `mutagen` y se guardan en un caché (`~/.cache/cassette-fm/`) con ruta, mtime y
  tamaño como clave. Se ignoran los archivos ilegibles o con duración 0, y las carpetas sin audio no son estación.
- Se re-escanea al arrancar y con un comando explícito (`cassette rescan`). No hace falta vigilar el disco en el MVP.
- **Fuente:** cada pista tiene un campo `fuente` (en el MVP siempre es `local`) y un identificador (la ruta).
  Lo que hace falta para Spotify se agrega en la etapa 4, no antes.

### Agenda (el "reloj virtual")

Es la pieza central. Es una **función pura y determinística**:
`agenda(estación, pistas, instante) → (pista actual, segundo dentro de la pista, pistas siguientes)`.

- Época fija común: `2026-01-01T00:00:00Z`.
- Las pistas de la estación se ordenan por ruta (orden canónico). La duración de un **ciclo** es la suma de las duraciones.
- Ciclo `k = floor((instante − época) / duración_ciclo)`. El orden del ciclo `k` es una mezcla aleatoria con semilla
  `hash(nombre_estación, k)`, estable entre ejecuciones: no usar `hash()` de Python, que cambia según el proceso.
  Usar, por ejemplo, sha256.
- El desplazamiento dentro del ciclo se recorre hasta encontrar la pista y el segundo.
- Si la última pista de un ciclo coincide con la primera del siguiente, se intercambia la primera del ciclo nuevo
  con otra para no repetir un tema dos veces seguidas.
- Si cambia el contenido de la carpeta, cambia la agenda (la estación "salta"). Se acepta.
- Las estaciones que no se escuchan **no consumen nada**: solo se calcula la agenda al sintonizar.

### Reproductor

- mpv como proceso hijo, en modo idle, sin video, controlado por **socket JSON IPC** (`--input-ipc-server`).
  No depende de libmpv.
- **Sintonizar:** consulta la agenda, carga la pista actual empezando en el segundo calculado y encola las
  siguientes (2 o 3) en la playlist de mpv, para que las transiciones sean sin cortes. Cuando mpv avanza de pista,
  vuelve a llenar la cola con la agenda.
- Mientras suena, mpv avanza en tiempo real, así que el desfase con la agenda es despreciable. Si igual hiciera
  falta, se resincroniza en cada cambio de pista (a criterio del que construye).
- **Sin pausa real, como en una radio:** `apagar` corta el audio. Al `encender`, se resintoniza la última estación
  y suena lo que corresponde *ahora*.
- Volumen: el de mpv, con comandos para subir y bajar.

### API de control

HTTP+JSON escuchando solo en `127.0.0.1` (el puerto se configura; por defecto, por ejemplo, 7710). Se eligió HTTP y
no D-Bus porque es lo que se puede llevar después a otros clientes o a otra máquina. El framework queda a
criterio del que construye (se prefiere algo liviano).

| Método | Ruta | Qué hace |
|---|---|---|
| GET | `/estado` | encendido/apagado, estación actual, pista actual, segundo, volumen |
| GET | `/estaciones` | lista ordenada de estaciones (nombre, cantidad de pistas) |
| POST | `/sintonizar` `{estacion}` | sintoniza por nombre |
| POST | `/siguiente`, `/anterior` | rota por la lista alfabética, con vuelta al principio |
| POST | `/encender`, `/apagar` | |
| POST | `/volumen` `{delta}` o `{valor}` | |
| POST | `/rescan` | re-escanea la biblioteca |

### CLI

Comando `cassette` (cliente liviano de la API): `next`, `prev`, `tune <nombre>`, `on`, `off`, `toggle`, `status`,
`list`, `vol +5|-5`, `rescan`. Además, `cassette serve` levanta el servicio. Si el servicio no está corriendo,
la CLI lo dice claramente.

### Avisos

Al cambiar de estación y al empezar cada tema, una notificación del escritorio (`notify-send` o libnotify) con
la estación y el tema (de los tags ID3; si no hay, el nombre del archivo). Mientras no haya applet, es la
única "UI". Se puede desactivar por configuración.

### Configuración y estado

- `~/.config/cassette-fm/config.toml`: raíz de música, puerto, avisos activados o no.
- `~/.local/state/cassette-fm/estado.json`: última estación, si estaba encendido, volumen.
- Arranque: unidad de **systemd de usuario**. El servicio arranca con la sesión y **en silencio**; solo suena con
  `cassette on` (o con `toggle` desde un atajo).

## Etapas (hoja de ruta, base de las épicas en Beans)

1. **Radio local (MVP):** biblioteca, agenda, reproductor, API, CLI, avisos, config/estado, unidad systemd.
2. **Controles de escritorio:** applet de Cinnamon (JS) que muestra estación y tema; con la rueda cambia de
   estación y con un clic enciende o apaga. Atajos de teclado (atajos personalizados de Cinnamon que llaman a la CLI).
3. **DJ:**
   - Servicio DJ **separado** (HTTP). Recibe un pedido (estación, tema saliente y entrante, tipo de
     intervención, voz) y devuelve un clip de audio. Puede correr en esta PC o en otra; la radio solo conoce su URL.
   - Cada estación tiene su voz (Kokoro: em_santa, am_michael, af_heart; alternativa: edge-tts) y una frecuencia
     ("cada N temas, con algo de azar").
   - Solo trabaja para la estación sintonizada: prepara la próxima intervención mientras suena el tema. Si no llega
     a tiempo, se saltea y la música sigue.
   - La voz se mezcla sobre el comienzo del tema siguiente bajando la música (ducking). Como va por encima, **no
     altera el reloj de la agenda**.
   - Datos: hora y clima de Buenos Aires (open-meteo). Las ideas de prompts y "skills" se toman de radio-dj (ver
     el relevamiento).
4. **Spotify como fuente:** una estación puede ser una playlist. Agenda igual (duraciones de la API), reproducción
   vía Web API (`play` con `position_ms`) sobre un dispositivo Spotify activo (cliente oficial o librespot/spotifyd).
   Limitación conocida: no hay acceso al audio, así que el DJ sobre Spotify solo puede bajar el volumen de Spotify
   y hablar encima.
5. **UI selector estilo GTA:** rueda radial de estaciones, con sonido de estática al cambiar.
6. **Clientes en otras máquinas:** exponer la API en la red y servir los archivos por HTTP (la agenda ya da
   "qué y desde qué segundo"). No hace falta sincronización exacta.
7. **Pedidos al DJ (prioridad mínima, lo último):** pedirle a una estación que pase un tema aunque no esté en su
   lista: un archivo de la biblioteca o, con Spotify, una búsqueda por nombre. El DJ lo anuncia y suena a
   continuación. Ojo de diseño: rompe el determinismo del reloj virtual. Se modela como una "inserción" en la
   agenda de esa estación (un desvío que corre el reloj a partir de ese punto), guardada en el estado.

Ideas sueltas para más adelante: crear y borrar emisoras por la API (nombre + fuente: un directorio o el
link de una playlist de Spotify), estática entre estaciones también en la CLI, evitar repetir artistas
seguidos. El volumen entre temas ya se parejiza con el filtro `dynaudnorm` de mpv (opción `normalizar`).

## Evolución prevista: estaciones como objetos

Hoy una estación es una subcarpeta de la raíz de música. **El usuario quiere que más adelante sean objetos en un JSON**
(no necesariamente derivados de carpetas), con al menos: nombre, **fuente** (un directorio en cualquier ruta o el link de una
playlist de Spotify), y los ajustes del DJ de esa estación (voz, idioma, personalidad, frecuencia). La voz se elige al
crear la estación. Se crean y se borran por la API (`CASSETTE-FM-40h0`). Es una evolución de la Etapa 4 en adelante: hasta
entonces rige "una estación = una subcarpeta". Las etapas intermedias no deben acoplarse a que la estación sea una carpeta
(en particular el DJ, ver [`2026-11-13-etapa-3-dj-design.md`](2026-11-13-etapa-3-dj-design.md)).

## Decisiones del usuario

- Estación = carpeta. MVP: todas suenan en aleatorio, se rota entre ellas y se entra con el tema empezado.
- Lo remoto es **solo para la IA** (LLM, quizás TTS), para que la PC quede liviana. No se transmite audio por red.
- Puede haber clientes en otra PC o en el celular algún día, sin sincronización exacta.
- Arquitectura A.
- Primero la radio sin DJ (ya decidido en el relevamiento). Voces Kokoro preferidas.
- Desarrollo con **TDD** (skills de superpowers).
- Pedidos al DJ como feature futura, la de menor prioridad.

## Decisiones tomadas en el diseño (a revisar por el usuario)

- **Python** como lenguaje: mpv hace el trabajo pesado y Kokoro y los clientes de LLM están en Python. Rust no aporta acá.
- mpv por **IPC JSON** (sin libmpv).
- API **HTTP local** en vez de D-Bus.
- **Sin pausa:** apagar o encender resintoniza "en vivo".
- El servicio arranca con la sesión pero **en silencio**.
- Orden de estaciones **alfabético**. Las subcarpetas cuentan **recursivamente** dentro de cada estación.
- Notificaciones del escritorio como única UI del MVP.

## Queda a criterio del que construye

- Gestión del entorno y del empaquetado (venv/uv, `pyproject.toml`), el framework HTTP liviano y la estructura de módulos.
- Cuántas pistas se encolan en mpv y la estrategia exacta de resincronización.
- El formato del caché de duraciones.
- Tests: la agenda es pura y se presta para TDD (determinismo, bordes de ciclo, no repetir entre ciclos). El
  reproductor y la API, con pruebas de integración livianas.
