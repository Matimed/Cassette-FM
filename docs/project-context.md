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
- Voz del DJ: **Kokoro** como opción preferida (em_santa en español; am_michael y af_heart en inglés).
  Alternativa: edge-tts (es-MX-Jorge, es-US-Alonso, en-US-BrianMultilingual, en-US-Christopher). Piper descartado.
- Hora y clima: Buenos Aires, Argentina.
- Primero la radio sin DJ; el DJ después.

## Equipo objetivo

Linux Mint, Ryzen 5 5600G (sin GPU dedicada, gráficos Vega integrados), 13 GB de RAM. Ya instalados: mpv, Docker,
Python 3, Node. No hay Ollama ni Go instalados en el sistema (en las pruebas corrieron en Docker).

## Gestión del trabajo

- Tareas en **Beans**, integrado en este repo (`.beans/`, prefijo `CASSETTE-FM-`).
  `beans list`, `beans show <id>`; para crear: `/beans:create <descripción>`.
- Git **solo local** (sin remote por ahora). Rama `main`.
