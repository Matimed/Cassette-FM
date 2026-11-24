# Arquitectura y decisiones técnicas

Cómo está armado cassette-fm y **por qué** se tomaron las decisiones que se tomaron. Para instalarlo, [`setup.md`](setup.md);
para usarlo, [`uso.md`](uso.md). Cada decisión importante tiene un documento de diseño con todo el detalle (alternativas,
mediciones, restricciones) en [`superpowers/specs/`](superpowers/specs/); acá está el resumen y el enlace.

## La intención

Convertir una biblioteca de música en un conjunto de **radios continuas**, como las de GTA: cada emisora «suena» todo el
tiempo, en orden aleatorio, y al sintonizarla **se entra con el tema ya empezado**. Se cambia de emisora como en una radio.
Es un proyecto personal y tiene que ser divertido de usar.

Lo que condiciona todo el diseño (son los *anti-objetivos*: cosas que lo harían fracasar aunque funcione):

- **Liviano.** Las emisoras que no se escuchan no consumen nada; la radio entera se duerme sola si nadie escucha; lo pesado
  (voz, LLM) es opcional y puede vivir en otra máquina.
- **Sin silencios.** Al sintonizar, la música arranca al instante. **El DJ nunca puede trabar la música**: si no está
  listo a tiempo, simplemente no habla.
- **Cambiar de emisora no puede ser engorroso**: de ahí el applet, el dial, los atajos y las teclas multimedia.
- **Cero datos inventados** en lo que dice el DJ.

## Vista general

```
                         ┌───────────────────────── esta PC ─────────────────────────┐
  applet / dial          │                                                           │
  atajos / teclas  ──────┼──►  cassette-fm  (servicio de usuario, Python)            │
  CLI `cassette`         │      ├─ agenda (reloj virtual): emisora + instante → tema │
                         │      ├─ reproductor local: mpv ──────────┐                │
                         │      ├─ reproductor Spotify ──► Soloist ─┤  (servicio)    │
                         │      ├─ locutor / planificador ◄─► cassette-dj (servicio)─┼─► LLM (Ollama, opcional)
                         │      ├─ API de control (127.0.0.1:7710)  ▼                │
                         │      ├─ vigilante de oyentes      bus de audio            │
                         │      └─ servidor LAN / puente nube   `radio_virtual`      │
                         │                                    │          │           │
                         └────────────────────────────────────┼──────────┼───────────┘
                                                              ▼          ▼
                                                   monitor local     MP3 (GStreamer)
                                                   (parlantes)       │           │
                                                                     ▼           ▼
                                                        otra PC (applet     relay en la nube ◄── teléfono,
                                                        remoto, LAN)        (Docker) ◄──────────── navegador
```

### Procesos y puertos

| Pieza | Qué es | Escucha en | Opcional |
|---|---|---|---|
| `cassette-fm` | la radio: agenda, reproductores, API de control, vigilante | `127.0.0.1:7710` | no |
| `mpv` | reproduce las emisoras locales (hijo de la radio, por socket IPC) | — | no |
| `cassette-soloist` | Spotify Soloist, el reproductor de Spotify | `127.0.0.1:9787` (WebSocket) | sí |
| `cassette-dj` | escribe y sintetiza las frases del DJ | `127.0.0.1:7720` | sí |
| `cassette-ollama` | el LLM local (contenedor Docker) | `127.0.0.1:11434` | sí |
| servidor LAN | audio y estado para otra PC propia | `8765` (solo con `[lan] activo`) | sí |
| puente a la nube | conexión **saliente** al relay; no abre puertos | — | sí |
| relay | punto de encuentro en la nube (aiohttp en Docker) | `8080` (o el que ponga el hosting) | sí |

Fuera del servidor LAN y del relay, todo escucha solo en la propia máquina.

---

## Decisiones

### Un servicio local y clientes livianos

**Decisión:** un único servicio Python (la radio) con la agenda, el reproductor y una API de control; la CLI, el applet y
la web son clientes livianos. El DJ es un servicio aparte.

**Por qué:** se consideró separar *motor* y *reproductor* en dos procesos desde el principio (para poder mover cosas a otra
máquina) y se descartó: lo que se va a mover a otra máquina es el **DJ**, no el motor, así que el corte que importa es
**radio ↔ DJ**. Tampoco alcanzaba con una CLI sin servicio: el applet y el DJ necesitan un proceso vivo que sepa qué suena.
La agenda es un módulo puro y aislado, así que pasar a dos procesos más adelante sería exponerla por HTTP.

**La API de control es HTTP+JSON en `127.0.0.1`**, no D-Bus, porque es lo que se puede llevar a otros clientes o a otra
máquina. Diseño: [`2026-11-13-cassette-fm-design.md`](superpowers/specs/2026-11-13-cassette-fm-design.md).

### La agenda: un reloj virtual determinista

Es la pieza central. Es una **función pura**: `agenda(emisora, temas, instante) → (tema actual, segundo, siguientes)`.

- Hay una época fija común. La duración de un *ciclo* es la suma de las duraciones de los temas de la emisora, y el orden
  de cada ciclo es una mezcla aleatoria con semilla `hash(nombre, ciclo)` (con SHA-256, estable entre ejecuciones; el
  `hash()` de Python cambia por proceso).
- Por eso **todas las emisoras «están sonando» siempre sin gastar nada**: no hay nada corriendo, solo se calcula la agenda
  al sintonizar. Al sintonizar se entra en el segundo que corresponde, y dos oyentes de la misma emisora oyen lo mismo.
- Al empalmar dos ciclos se evita repetir un tema dos veces seguidas.
- El costo asumido: si cambia el contenido de la carpeta (o la playlist), o el nombre de la emisora, la agenda cambia y la
  emisora «salta».
- Las peticiones de Spotify y el DJ **no rompen la agenda**: la corren, pero la agenda sigue siendo una función del reloj.

### mpv como reproductor local

mpv como proceso hijo, en modo *idle* y sin video, controlado por **socket JSON IPC**. No depende de `libmpv`. Al sintonizar,
se carga el tema actual desde el segundo calculado y se encolan los siguientes, para que las transiciones sean sin cortes.

### Emisoras definidas en un JSON

Al principio cada subcarpeta de `~/Música` era una emisora. Con Spotify eso se quedaba corto: las emisoras pasaron a
definirse en `estaciones.json` con una **fuente** (carpeta en cualquier ruta, o playlist de Spotify) y los ajustes del DJ
de cada una. La primera vez el archivo se genera con lo que había, así que no se pierde nada. Todo lo construido (agenda,
DJ, planificador, rescan, CLI, applet) funciona igual con las dos fuentes.
Diseño: [`2026-11-14-etapa-4-spotify-design.md`](superpowers/specs/2026-11-14-etapa-4-spotify-design.md).

### Spotify con Soloist (y no con Chrome)

**Decisión:** las emisoras de Spotify suenan con **Spotify Soloist**, el cliente oficial sin interfaz.

**Por qué:** la alternativa (el Web Playback SDK dentro de un Chrome oculto) se midió y cuesta ~520–580 MB de RAM en
13–14 procesos y ~4 % de CPU; Soloist, ~41–51 MB en un proceso y ~1 % de CPU. En una PC de 13 GB que además puede correr un
LLM, la diferencia decide.

**Restricciones que condicionan el uso** (todas de Spotify, no nuestras):

- Cada build de Soloist **vence a los 90 días** (de ahí `scripts/actualizar-soloist.sh`) y pide una API key de
  desarrollador y emparejarse una vez.
- La Web API en modo desarrollo solo devuelve los temas de playlists **que el usuario creó o colabora**, y admite pocos
  usuarios por app (de ahí que cada uno cree la suya).
- Premium reproduce en **un dispositivo a la vez**: la radio toma el control de la cuenta y, si Spotify pasa a otro
  dispositivo, se apaga y avisa.

**Cómo suena rápido.** El primer tema sale directo por Soloist (WebSocket local) en ~0,3–0,9 s mientras la lista de los que
siguen viaja en paralelo por la Web API (que a veces tarda 3–10 s); el cambio de emisora bajó de ~1,8 s a ~0,45 s. La
posición se calcula justo antes del `play`, porque antes la sintonía arrancaba 2–8 s atrasada.
Diseños: [sintonía rápida](superpowers/specs/2026-11-16-sintonia-spotify-rapida-design.md) y
[sintonía local](superpowers/specs/2026-11-16-sintonia-local-design.md).

**La clave de Soloist viaja en su línea de comandos** (decisión de la tarea CASSETTE-FM-q2ry), por eso nunca hay que mostrar
los argumentos de ese proceso (`systemctl status`, `ps` con argumentos).

#### Recuperación: cuando Spotify no arranca

Spotify o la red a veces tardan 10 s o más. La radio no se apaga de entrada, escala:

1. a los 10 s vuelve a pedir el `play`;
2. si sigue sin sonar, pasa a otra emisora (de otra fuente, si hay: otra de Spotify casi seguro falla igual) y avisa;
3. si esa también falla, o no hay otra, **reinicia el servicio** (con Soloist, que es lo que suele trabarse) y al volver retoma;
4. el reinicio tiene un freno: no se repite en 10 minutos, y ahí sí se apaga. No se reinicia si el motivo es Spotify abierto
   en otro dispositivo.

El marcador queda en `~/.local/state/cassette-fm/reinicio.json`; el código está en `recuperacion.py`.

**Temas que Soloist no logra cargar.** A algunos temas Soloist los saltea en menos de un segundo, o toca otra edición del
disco. La radio lo acepta en vez de re-sintonizar en bucle: si cambia de tema a menos de 2 s del anterior, la agenda sigue
desde lo que suena. Diseño: [`2026-11-16-soloist-saltea-temas-design.md`](superpowers/specs/2026-11-16-soloist-saltea-temas-design.md).

### El DJ

**Un servicio aparte.** El DJ (datos, LLM y voz) corre en `cassette-dj`, en esta PC o en otra más modesta, cambiando solo
una dirección. Lo pesado va en un extra opcional del paquete (`[dj]`, `[piper]`) con su propio comando `cassette-dj`, para
no cargar la instalación básica. **No tiene autenticación**: es para una red de confianza.

**La música nunca espera.** Cada hueco del DJ vive **en la agenda de su emisora**: el planificador pide la frase con
antelación, la radio reserva el hueco y descarga el clip cuando está listo. Si no llega a tiempo, no suena. Como el hueco
está en la agenda, si cambiás de emisora mientras habla y volvés, entra a mitad de frase. La voz se ancla al **corte** entre
dos temas (`inicio`, `entre`, `final` o `mixto`).

**Qué dice y cómo se evita lo falso.**

- Cada frase combina de 1 a 3 *ingredientes* (el tema siempre; emisora, hora, momento del día, álbum, tema anterior, clima,
  dato), elegidos al azar con peso y penalizando lo dicho hace poco, para que no suene calcado.
- Los hechos salen de los tags, del reloj, del clima (open-meteo) o de MusicBrainz, y solo se usan si son coherentes (por
  ejemplo, ninguno si hay dos artistas con el mismo nombre).
- **El LLM redacta, nunca es la fuente de un hecho.** Su frase pasa por una verificación (año o cifra inventados, nombres que
  no están en los hechos, enlaces…) y, si no la pasa, sale la plantilla. Por defecto se usan solo plantillas.
- Todo lo dicho queda registrado (`guiones.jsonl`) con sus hechos y su fuente.

**Voces: Kokoro y Piper, no TTS pesados.** El banco de voces del 16/11 con guiones reales dejó a **Kokoro** (inglés y
mezclas) y **Piper** (`es_AR-daniela-high` ganó en español) como las elegidas. Se descartaron XTTS-v2 (~2× la duración del
audio para sintetizar y 4 GB de RAM), Qwen3-TTS 0.6B y Chatterbox multilingüe (5–7× y 5,5–6 GB): sin una mejora audible clara
frente a Kokoro y Piper, no compensan. Todo corre en CPU.
Relevamiento: [`relevamiento/radio-dj.md`](relevamiento/radio-dj.md) y
[`relevamiento/texto-para-voz.md`](relevamiento/texto-para-voz.md) (cómo preparar el texto para que la voz lo diga bien).

Diseño: [`2026-11-13-etapa-3-dj-design.md`](superpowers/specs/2026-11-13-etapa-3-dj-design.md) y
[la voz entre temas](superpowers/specs/2026-11-20-voz-entre-temas-design.md).

### El bus de audio

**Decisión:** todo el audio (mpv, la voz del DJ, Soloist) sale a un sink virtual, `radio_virtual`, que *es* la señal de la
radio. Lo que se oye en esta PC es un **monitor local**: un `module-loopback` de `radio_virtual.monitor` a la salida
predeterminada, con volumen propio.

**Por qué:** es la base de retransmitir por la red. Cualquier retransmisión lee el mismo monitor y recibe la señal completa
(música y voz ya mezcladas), y **cada monitor tiene su propio volumen**. Como consecuencia, «el volumen de la radio» es el
del monitor; las fuentes quedan al 100 % salvo el *ducking* del DJ y la calibración de Spotify.

**Cómo llega el audio:** mpv va con `--ao=pulse` y `PULSE_SINK=radio_virtual` (en PipeWire la salida por defecto ignora
`PULSE_SINK`); Soloist es un cliente PipeWire nativo y se dirige con `PIPEWIRE_NODE=radio_virtual` desde un *drop-in* de su
unidad (lo instala `scripts/instalar-spotify.sh`; `scripts/bus-audio.sh` lo activa o lo quita). Todo se maneja con `pactl`, así que sirve en PulseAudio y en PipeWire.

**El loopback se carga una sola vez y queda cargado**: cada carga metía un chasquido a escala completa (~1 de cada 5), así que
silenciar es mutear el stream del loopback ya cargado, no descargarlo.

**Costos conocidos:** reiniciar `cassette-fm` reinicia Soloist (van atados con `PartOf`); un salto más en el camino (loopback
de 20 ms) y un punto más de falla; sin `pactl` el servicio arranca sin bus (con `bus_audio = false`).
Diseño: [`2026-11-18-bus-de-audio-design.md`](superpowers/specs/2026-11-18-bus-de-audio-design.md).

### La radio suena si alguien la escucha

**Decisión:** «encendida/apagada» deja de ser un interruptor; la radio es un servicio que **cualquier oyente despierta y que
se duerme sola sin oyentes**.

**Por qué:** antes esta PC era un oyente con más privilegios que los demás (la notebook, el teléfono) y la radio podía quedar
sonando para nadie, con Spotify gastando recursos. Ahora todas las interfaces siguen las mismas reglas.

- **Oyentes** = el monitor local (0 o 1) + las conexiones de audio abiertas (stream LAN y nube, todas las calidades).
- Sin oyentes durante `segundos_hasta_dormir` (60 s), el *vigilante* la duerme. Abrir un stream o elegir emisora con cero
  oyentes la despierta y te vuelve el primer oyente.
- Con otros oyentes, cambiar de emisora no toca el monitor ni el volumen de esta PC (la rueda del applet no prende el sonido de
  tu PC si la escuchan en el teléfono). Un simple `/status` no despierta la radio.
- Ya no hay `apagar`: dejar de escuchar en todos lados es apagarla; `cassette stop`/`start` bajan y levantan todos los
  servicios.
- Sin bus no se pueden contar oyentes: no hay sueño automático.

Diseño: [`2026-11-20-radio-por-oyentes-design.md`](superpowers/specs/2026-11-20-radio-por-oyentes-design.md).

### Escuchar por la red

El diseño original descartaba retransmitir audio por la red. Cambió con el bus: ahora hay **una sola transmisión** (la del
bus) y los demás dispositivos son oyentes de esa transmisión, no clientes con su propia cuenta de Spotify ni su propio backend
([`2026-11-18-radio-en-red-design.md`](superpowers/specs/2026-11-18-radio-en-red-design.md) compara los enfoques).

**LAN / Tailscale (otra PC propia)** ([diseño](superpowers/specs/2026-11-18-radio-lan-design.md)).

- `lan_server.py` publica **cuatro rutas y nada más**, todas con clave (`Authorization: Bearer …`): `GET /status`,
  `POST /station/{emisora}`, `GET /stream` (MP3 de 160 kbps; estática con la radio apagada) y `GET /icon/{emisora}`. La API
  de control completa sigue solo en `127.0.0.1`.
- El audio lo codifica **un solo** GStreamer (`lamemp3enc`) repartido a todos los oyentes, y solo mientras alguien escucha.
- `lan_receiver.py` (dentro de la carpeta del applet) es independiente: solo biblioteca estándar de Python y mpv, y no importa
  nada de `cassette_fm`. El applet tiene un modo remoto visualmente igual al local.
- Va por HTTP sin cifrar: por Tailscale ya viaja cifrado; por la LAN, para una red de confianza. Escucha en la IP de
  Tailscale si existe. Sin `[lan] activo`, no se abre ningún puerto.

**Nube: puente + relay** ([puente](superpowers/specs/2026-11-19-puente-nube-design.md),
[relay](superpowers/specs/2026-11-19-relay-nube-design.md), [claves](superpowers/specs/2026-11-19-claves-relay-design.md),
[web](superpowers/specs/2026-11-19-web-del-relay-design.md)).

- **Todo sale desde esta PC.** Detrás de un router sin puertos abiertos, el *puente* abre conexiones **salientes** al relay y
  nada más; no se expone la IP ni se abre ningún puerto. Apagado por defecto (`[nube] activo = false`), y una falla del
  puente nunca afecta a la radio local ni a la LAN.
- Un WebSocket de control permanente (`/casa/control`): la PC manda el estado (emisoras, la sintonizada, el tema, los logos) y
  recibe órdenes (sintonizar, siguiente, anterior; nunca apagar ni cambiar el volumen de esta PC). Se reconecta sola, y manda
  un `latido` cada 2 minutos para que el plan gratuito de Render no duerma el relay.
- **Sin gasto con nadie escuchando:** el audio sale solo mientras el relay avisa que hay oyentes, con un WebSocket por calidad
  pedida (MP3 de 32, 64, 96 o 160 kbps; ~14, 29, 43 o 72 MB por hora; la de 32 es «ahorro de datos»: mono a 22,05 kHz). Cada
  calidad se sube **una sola vez** aunque la escuchen varios.
- **Claves.** El relay tiene solo la maestra (`MASTER_PASSWORD`, siempre con todos los permisos). Las demás se crean desde la
  PC (`cassette claves`), que **guarda solo su huella** y le pasa la lista al relay por el puente; así no hay que tocar el
  relay para dar o quitar acceso, y borrar una clave corta su audio en segundos. Después de 5 claves equivocadas en un
  minuto, probar claves queda bloqueado un minuto.
- El relay es un proyecto aparte en el mismo repositorio ([`relay/`](../relay/README.md)): aiohttp en Docker, todo en
  memoria; si se reinicia, la PC se reconecta y vuelve a mandar el estado.

### Peticiones por la cola de Spotify

Lo que agregás a la cola desde la app de Spotify suena como **petición**: el DJ la anuncia (antes o después, según el tiempo
que quede) y la agenda de la emisora se corre sin perder temas. Se cuenta como petición todo lo que viene de la cola. Se
corre lo que sonó de verdad, así que la agenda sigue siendo un reloj. Diseños:
[peticiones](superpowers/specs/2026-11-15-peticiones-spotify-design.md) y
[cierre](superpowers/specs/2026-11-15-peticiones-cierre-design.md).

### Escritorio: applet, dial, atajos y teclas multimedia

El applet de Cinnamon y el dial son clientes de la API local. La radio se anuncia por **MPRIS** y pide a Cinnamon las
teclas multimedia (`GrabMediaPlayerKeys`), así los botones de un parlante Bluetooth, que llegan como teclas, cambian de
emisora. Cinnamon le da esas teclas al último programa que las pidió. Diseños:
[teclas multimedia](superpowers/specs/2026-11-14-teclas-multimedia-design.md) y
[el dial](superpowers/specs/2026-11-16-dial-de-emisoras-design.md).

---

## El código

```
src/cassette_fm/        la radio (paquete `cassette-fm`, comando `cassette`)
├─ agenda.py, biblioteca.py, emisoras.py     el reloj virtual, el escaneo de carpetas y estaciones.json
├─ radio.py, servicio.py, api.py             el núcleo, el arranque y la API de control
├─ reproductor.py, mpv.py                    emisoras locales (mpv por IPC)
├─ reproductor_spotify.py, spotify/          emisoras de Spotify (Soloist y Web API)
├─ reproductores.py                          los dos reproductores detrás de una sola interfaz
├─ recuperacion.py                           qué hacer si una emisora de Spotify no suena
├─ locutor.py, planificador.py, cliente_dj.py  el DJ del lado de la radio (reservar huecos, pedir y reproducir clips)
├─ audio_router.py, vigilante.py             el bus de audio y el sueño por falta de oyentes
├─ lan_*.py, puente_nube.py, claves.py       escuchar por la red: LAN, nube y claves
├─ mpris.py, atajos.py, applet.py, avisos.py integración con Cinnamon
├─ cli.py, emisora_nueva.py                  el comando `cassette`
└─ dj/                                       el servicio DJ (paquete aparte, comando `cassette-dj`)
   ├─ servidor.py, produccion.py, cola.py       HTTP, producción de clips y cola de trabajos
   ├─ sintetizador.py, texto_voz.py             voz (Kokoro, Piper) y preparación del texto
   ├─ plantillas.py, selector.py, redactor_llm.py, llm.py   qué decir y cómo verificarlo
   └─ hechos/                                   clima, MusicBrainz, Wikipedia y su caché
applet/                 applet de Cinnamon (JavaScript) y lan_receiver.py
relay/                  relay en la nube (aiohttp, Docker) y su web
packaging/              plantillas de las unidades systemd
scripts/                un instalador por componente, mantenimiento y herramientas (ver setup.md)
tests/, relay/tests/    pruebas (pytest; applet/tests con Node)
```

Las pruebas se corren con `.venv/bin/pytest`; el proyecto se desarrolló con TDD.

## Historia, planes y relevamiento

- [`superpowers/specs/`](superpowers/specs/): un documento de diseño por cada pieza (intención, objetivos, no objetivos,
  restricciones, alternativas, decisiones). El de arranque es
  [`2026-11-13-cassette-fm-design.md`](superpowers/specs/2026-11-13-cassette-fm-design.md).
- [`superpowers/plans/`](superpowers/plans/): el plan de implementación de cada uno.
- [`relevamiento/`](relevamiento/): la evaluación previa de otro proyecto de radio con DJ
  ([johncrash64/radio-dj](https://github.com/johncrash64/radio-dj)), las mediciones con un LLM local y las pruebas de voces.
- [`project-context.md`](project-context.md): estado del proyecto y bitácora de decisiones, pensada para quien (o qué
  sesión de Claude Code) retoma el trabajo.
