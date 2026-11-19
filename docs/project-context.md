# Contexto del proyecto

> Punto de entrada. Si acabás de llegar al proyecto, o sos una sesión nueva de Claude Code,
> leé este documento entero antes de tocar nada.

## Objetivo

**cassette-fm** es una app para Linux Mint que convierte la biblioteca de música local en un conjunto
de **radios continuas**:

- Cada **emisora** está definida en `~/.config/cassette-fm/estaciones.json`: una carpeta de música (en cualquier
  ruta) o, desde la etapa 4, una playlist de Spotify. (Al principio era cada subcarpeta de `~/Música`.)
- Cada estación está "sonando" todo el tiempo, en orden aleatorio; al sintonizarla **se entra con el tema ya empezado**.
- Se cambia de estación como en una radio (o como en las radios de GTA, que inspiraron la idea).
- Etapa posterior: un **DJ con IA local** que habla entre temas (presentaciones, hora y clima de Buenos Aires).

## Estado

Etapas 1 a 4 hechas y probadas con el usuario (radio local, applet y atajos, DJ con plantillas y con LLM,
Spotify como fuente). La etapa 4 tiene emisoras en `~/.config/cassette-fm/estaciones.json`, catálogo de playlists
por la Web API y reproducción con **Spotify Soloist** (servicio `cassette-soloist`; el build vence cada 90 días y se
renueva con `scripts/actualizar-soloist.sh`). Diseño:
[`superpowers/specs/2026-11-14-etapa-4-spotify-design.md`](superpowers/specs/2026-11-14-etapa-4-spotify-design.md).
Los menores que quedaron pendientes de cada parte están en los mensajes de commit de sus revisiones finales.
Además la radio se anuncia por MPRIS y pide las teclas multimedia a Cinnamon (`GrabMediaPlayerKeys`), así los
botones de un parlante Bluetooth cambian de emisora:
[`superpowers/specs/2026-11-14-teclas-multimedia-design.md`](superpowers/specs/2026-11-14-teclas-multimedia-design.md).
Etapa 7a (adelantada): **peticiones por la cola de Spotify**: lo encolado desde la app suena como petición, el DJ
la anuncia (antes o después) y la agenda de la emisora se corre sin perder temas:
[`superpowers/specs/2026-11-15-peticiones-spotify-design.md`](superpowers/specs/2026-11-15-peticiones-spotify-design.md).
Probada con el usuario el 2026-11-15; el cierre (anuncio combinado de dos pedidos seguidos, anuncios que se
descartan al sacar de la cola o saltear) el 2026-11-16:
[`superpowers/specs/2026-11-15-peticiones-cierre-design.md`](superpowers/specs/2026-11-15-peticiones-cierre-design.md).
(De paso se arregló que la sintonía de Spotify arrancaba 2–8 s atrasada: la posición se calcula justo antes del
play.) El 2026-11-16 el cambio de emisora de Spotify bajó de ~1,8 s a ~0,45 s (shuffle y repeat por el WebSocket de
Soloist: [`superpowers/specs/2026-11-16-sintonia-spotify-rapida-design.md`](superpowers/specs/2026-11-16-sintonia-spotify-rapida-design.md)),
y desde la noche del 16/11 el primer tema sale directo por Soloist (~0,3–0,9 s aunque la Web API tarde 3–10 s:
[`superpowers/specs/2026-11-16-sintonia-local-design.md`](superpowers/specs/2026-11-16-sintonia-local-design.md)),
y la radio acepta los temas que Soloist no logra cargar y saltea, en vez de re-sintonizar en bucle (CASSETTE-FM-49ga,
probado en real: [`superpowers/specs/2026-11-16-soloist-saltea-temas-design.md`](superpowers/specs/2026-11-16-soloist-saltea-temas-design.md)).
La clave de Soloist sigue en la línea de comando (decisión de CASSETTE-FM-q2ry): nunca mostrar los argumentos del
proceso (`systemctl status`, `ps` con argumentos). `cassette nueva NOMBRE LINK` crea una emisora de Spotify con un DJ
de voz propia y la sintoniza ([`superpowers/specs/2026-11-16-emisora-nueva-design.md`](superpowers/specs/2026-11-16-emisora-nueva-design.md));
el applet tiene "Nueva emisora…", un modal que corre `cassette voces --json` y `cassette nueva`
([`superpowers/specs/2026-11-16-modal-emisora-nueva-design.md`](superpowers/specs/2026-11-16-modal-emisora-nueva-design.md)),
con ▶ para escuchar la voz elegida ("Hola, soy dora y estás escuchando…": `POST /muestra` del servicio DJ y
`cassette-dj muestra`; [`superpowers/specs/2026-11-16-muestra-de-voz-design.md`](superpowers/specs/2026-11-16-muestra-de-voz-design.md)).
`cassette borrar "nombre"` la saca, preguntando antes
([`superpowers/specs/2026-11-16-borrar-emisora-design.md`](superpowers/specs/2026-11-16-borrar-emisora-design.md)),
y `cassette renombrar "viejo" "nuevo"` le cambia el nombre (y con él el orden de los temas:
[`superpowers/specs/2026-11-16-renombrar-emisora-design.md`](superpowers/specs/2026-11-16-renombrar-emisora-design.md)).
Etapa 5 (CASSETTE-FM-qyz0): **el dial**, una tira de logos estilo GTA 4 que se abre con Super+Alt+Espacio desde el
applet, y logos por emisora (campo `"icono"` en `estaciones.json`, `cassette icono`; los del usuario viven en
`~/.config/cassette-fm/iconos/`, en el repo solo el genérico):
[`superpowers/specs/2026-11-16-dial-de-emisoras-design.md`](superpowers/specs/2026-11-16-dial-de-emisoras-design.md).
Etapa 6 (diseño aprobado el 2026-11-18, sin implementar): **radio en red**, escuchar las mismas emisoras desde otros
dispositivos con esta PC como servidor y clientes livianos; primero la notebook igual que esta PC (CASSETTE-FM-5as8,
prioridad) y después compartir con amigos (CASSETTE-FM-3m6b, diferible):
[`superpowers/specs/2026-11-18-radio-en-red-design.md`](superpowers/specs/2026-11-18-radio-en-red-design.md).
Bus de audio (CASSETTE-FM-r80e, 18/11): todo el audio sale al sink virtual `radio_virtual` y lo que se oye en esta PC es un
monitor local con volumen propio (el volumen de la radio es el del monitor; las fuentes quedan al 100 % salvo ducking y
calibración), base de la retransmisión por red; `bus_audio` en `config.toml` (por defecto `true`), `POST /monitor`,
interruptor en el applet y `scripts/instalar-bus.sh` para Soloist (cliente PipeWire nativo: `PIPEWIRE_NODE`, no `PULSE_SINK`):
[`superpowers/specs/2026-11-18-bus-de-audio-design.md`](superpowers/specs/2026-11-18-bus-de-audio-design.md).
Radio por la LAN (CASSETTE-FM-u8ea, 18/11): una segunda PC propia escucha la misma transmisión con el mismo applet en modo remoto;
servidor `lan_server.py` (`[lan]`, apagado por defecto, escucha en la IP de Tailscale) con `/status`, `/station`, `/stream`
(MP3 del bus, estática con la radio apagada) e `/icon`, clave Bearer (`cassette lan`) y receptor `lan_receiver.py` dentro de la
carpeta del applet: [`superpowers/specs/2026-11-18-radio-lan-design.md`](superpowers/specs/2026-11-18-radio-lan-design.md),
plan en [`superpowers/plans/2026-11-18-radio-lan.md`](superpowers/plans/2026-11-18-radio-lan.md).
Puente a la nube (19/11): con `[nube]` esta PC se conecta hacia afuera a un relay (WebSocket de control con estado y
órdenes; audio MP3 de 64/96/160 kbps solo mientras el relay pide cada calidad), para escuchar desde cualquier dispositivo sin
Tailscale; el relay y la web son las entregas siguientes, por ahora hay `scripts/relay-de-prueba.py`:
[`superpowers/specs/2026-11-19-puente-nube-design.md`](superpowers/specs/2026-11-19-puente-nube-design.md),
plan en [`superpowers/plans/2026-11-19-puente-nube.md`](superpowers/plans/2026-11-19-puente-nube.md).
Prender desde volumen 0 sube a 50. Ojo al tocar el applet: `ReloadXlet` recarga `applet.js` pero no `logic.js` (queda en caché hasta reiniciar Cinnamon).

## Relevamiento previo (leer antes de diseñar)

- [`relevamiento/radio-dj.md`](relevamiento/radio-dj.md) — evaluación de https://github.com/johncrash64/radio-dj,
  bugs encontrados, mediciones con un LLM local (Ollama), pruebas de voces TTS y voces elegidas por el usuario,
  y el enfoque propuesto ("reloj virtual" por estación, sin Icecast).
- Conversación original completa (transcript de Claude Code, JSONL):
  `~/.claude/projects/-home-matimed-Descargas-radio-dj/79cf7bf7-b9b8-4c9c-beaf-e557bfd2507c.jsonl`
- Material de la prueba fuera del repo (descartable): `~/Descargas/radio-dj/` (código de radio-dj, clips de voz).
  Imágenes y volúmenes de Docker: `radio-dj-test`, `radio-dj-kokoro`, `rdj-ollama` (modelo `qwen2.5:3b`), red `rdj-net`.

## Decisiones tomadas

- Proyecto nuevo desde cero; radio-dj solo como referencia de ideas.
- Voz del DJ: **Kokoro** en inglés (una voz por estación, elegidas el 14/11) y **Piper `es_AR-daniela-high`**
  ("daniela") en español: es la locutora. Banco de voces del 16/11 con guiones reales: en español Daniela ganó a
  todas; después `ef_dora` (Kokoro), `es_MX-claude-high`, `es_MX-ald-medium` (Piper) y `alex_santa` (mezcla de
  Kokoro), que quedan como alias listos en `~/.config/cassette-dj/config.toml`.
- TTS pesados descartados (banco del 16/11, en este equipo): XTTS-v2 tarda ~2× la duración del audio y usa 4 GB;
  Qwen3-TTS 0.6B y Chatterbox multilingüe, 5–7× y 5,5–6 GB. Sin una mejora audible clara frente a Kokoro y Piper,
  no compensa.
- Hora y clima: Buenos Aires, Argentina.
- Primero la radio sin DJ; el DJ después.

## Equipo objetivo

Linux Mint, Ryzen 5 5600G (sin GPU dedicada, gráficos Vega integrados), 13 GB de RAM. Ya instalados: mpv, Docker,
Python 3, Node. No hay Ollama ni Go instalados en el sistema (en las pruebas corrieron en Docker).

## Gestión del trabajo

- Tareas en **Beans**, integrado en este repo (`.beans/`, prefijo `CASSETTE-FM-`).
  `beans list`, `beans show <id>`; para crear: `/beans:create <descripción>`.
- Git **solo local** (sin remote por ahora). Rama `main`.
