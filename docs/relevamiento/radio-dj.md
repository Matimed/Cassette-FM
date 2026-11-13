# Relevamiento: radio-dj y pruebas de voz

> Este documento es el resultado del relevamiento previo a cassette-fm (13/11/2026).
> Se evaluó un proyecto existente, se probaron voces y modelos, y se decidió arrancar
> **desde cero**. Nada de este código se reutiliza tal cual; sirve como referencia.

## La idea original

Partió de querer poner música propia en las radios de GTA IV (una estación por estilo).
Se generalizó a una app para Linux Mint que funcione como **"radio continua"**:

- Cada **subcarpeta** de la biblioteca de música es una **estación**.
- Cada estación está "sonando" todo el tiempo, en orden aleatorio.
- Al cambiar de estación **se entra con el tema ya empezado**, como en una radio real, no desde el inicio.
- Opcional (y "divertido"): un **DJ con IA** que habla entre temas: presenta canciones, dice la hora y el clima.

Biblioteca actual del usuario: `~/Música/Lentos` (12 temas, baladas de los 80 en inglés) y
`~/Música/Regueton 2000` (~90 temas).

## Proyecto evaluado: radio-dj

- Repo: https://github.com/johncrash64/radio-dj (MIT), commit probado `cb32022`.
- Go, ~14k líneas. Un solo binario + Icecast + ffmpeg.
- Copia local de la prueba: `~/Descargas/radio-dj/src` (puede borrarse).

### Qué resuelve

1. **Transmisión por red**: Icecast + un ffmpeg "master" persistente generan un stream HTTP
   continuo (MP3/AAC) que se escucha desde VLC, mpv, el celular, etc. Por eso "se entra en vivo".
2. **Mezcla de voz**: baja la música mientras habla el DJ (`sidechaincompress` de ffmpeg),
   antes de un tema o a mitad de uno ("midroll").
3. **"Director" con LLM**: en una llamada JSON (`response_format: json_object`, hasta 1200 tokens)
   recibe una lista corta de candidatos, arma el orden de la tanda y decide dónde hablar y qué tipo de
   intervención hacer (intro, dato curioso, wiki, hora, ID de estación).
   Frases cortas: hasta 160 tokens. API compatible con OpenAI (sirve con Ollama).
4. **Datos reales**: clima de open-meteo (sin API key), hora local, Wikipedia. La "búsqueda web"
   solo existe con el proveedor GLM (nube).
5. **TTS por comando**: `voice_cmd` con `{text}` y `{out}`, así que se le puede enchufar cualquier motor.
6. **Extras**: UI web (cassette animado, ahora suena/siguiente, historial, log del DJ), pedidos de
   oyentes, API, PWA, instalación como servicio systemd, asistente de configuración.
7. **"Skills" editables**: los segmentos del DJ son archivos de texto (`internal/i18n/skills/{es,en}/*.md`)
   y los prompts están en `internal/i18n/prompts/{es,en}.json`. **Es lo más reutilizable como idea.**

### Qué NO resuelve (y es lo central para nosotros)

- **Una sola estación por proceso.** No hay "una estación por carpeta".
- **No hay selector de estaciones.** Para cambiar hay que cambiar de URL.
- Varias instancias en el mismo sistema chocan: el puerto 7702 está fijo en el proxy de la UI
  (`internal/status/status.go`) y comparten `~/.radio-dj` salvo que se use `RDJ_STATE_DIR`.
- Cada estación genera diálogos de IA **aunque nadie la escuche**: desperdicio de CPU con un LLM local.

### Bugs encontrados en Linux

1. **Rutas de Homebrew (macOS) en el `icecast.xml` generado**: `webroot` apunta a
   `/opt/homebrew/opt/icecast/share/icecast/web`. En Linux, `status-json.xsl` da 404.
   Workaround: symlink a `/usr/share/icecast2`. (En Debian, además, el binario se llama `icecast2`.)
2. **El vigilante deja la estación muda para siempre** (`internal/radio/serve.go` + `internal/icecast/source.go`):
   - El mount de Icecast recién aparece cuando entra el primer audio.
   - Con LLM local, la primera tanda tarda 1 a 3 minutos, así que el vigilante (cada 30 s, 2 fallos) mata al master.
   - `Alive()` usa `ProcessState == nil`, que solo se completa con `Wait()`, y nadie lo llama, así que el master muerto parece vivo y nunca se reabre.
   - Además, el padre no cerraba los extremos de lectura de los pipes, así que el decoder queda bloqueado escribiendo en vez de recibir EPIPE.
   - Parche en `anexos/radio-dj-fix-watchdog.patch`: compila y pasa los tests, **pero no se llegó a verificar en una estación real**.
3. El log de arranque siempre muestra `/stream.aac` aunque el encoder sea MP3 (cosmético).

### Resultados medidos

Equipo: Ryzen 5 5600G (6 núcleos y 12 hilos, gráficos Vega integrados, sin GPU dedicada), 13 GB de RAM.

| Qué | Resultado |
|---|---|
| radio-dj sin IA (solo música) | Funciona. ~30 MB de RAM y ~2 % de CPU por estación |
| 2 estaciones en paralelo (1 contenedor c/u) | Funciona; cada una con su carpeta |
| Ollama `qwen2.5:3b` (CPU) | ~2,4 GB de RAM. Frase corta: 11–25 s. Plan del director: ~1m12s (con 2 estaciones compitiendo) |
| Primera tanda con LLM local | 1–3 min de silencio antes del primer tema |
| Calidad de textos (qwen2.5:3b) | Español e inglés correctos pero genéricos. **Inventa datos** (p. ej., "Tito El Bambino, de Zion & Lennox"), confunde el género (le dice "jazz" a la estación de lentos) |
| edge-tts | Fallos intermitentes (`NoAudioReceived`); con reintentos se resuelve. Requiere internet (servicio de Microsoft) |
| Kokoro (kokoro-onnx) | 8 clips en <1 min en CPU. Modelo ~310 MB + voces. 100 % local |

### Conclusión

Lo más complejo de radio-dj (streaming por red para varios oyentes, UI web, pedidos) **no hace falta**:
el único oyente es el usuario, en su compu. Lo que sí hace falta (varias estaciones, cambiar de
estación) **no lo tiene**. Por eso se decidió **hacer cassette-fm desde cero**, reutilizando ideas.

## Enfoque propuesto para cassette-fm (a validar)

- **"Reloj virtual" por estación**: lista mezclada fija (semilla) y hora de inicio por carpeta. Al
  sintonizar se calcula qué tema suena "ahora" y en qué segundo, y se reproduce desde ahí (p. ej., mpv `--start`).
  Las estaciones que no se escuchan no consumen nada.
- **Sin Icecast**: reproducción local directa.
- **El DJ trabaja solo en la estación sintonizada**: mientras suena un tema, prepara la próxima
  intervención (LLM y luego TTS) y la mezcla bajando la música.
- **Cambio de estación** con atajos de teclado o un ícono en la bandeja de Mint.
- Por etapas: 1) radio sin DJ, 2) voz y DJ.
- Ideas para tomar de radio-dj: prompts/skills del DJ, ducking con `sidechaincompress`, clima vía open-meteo,
  "talkiness" configurable, evitar repetir temas.

## Pruebas de voz (TTS)

Texto de prueba en una transición real: fin de un tema, crossfade, voz sobre el tema siguiente con la música bajada.
Scripts en `anexos/edge-tts-clips.sh` y `anexos/kokoro-clips.sh`. Clips en `~/Descargas/radio-dj/muestras-voz/`
(fuera del repo; contienen audio con copyright).

| Motor | Voz | Veredicto del usuario |
|---|---|---|
| Piper | es_AR-daniela, en_US-ryan | ❌ Robóticas |
| edge-tts | es-AR-TomasNeural, en-US-AndrewNeural | ❌ No convencieron |
| edge-tts | **es-MX-JorgeNeural, es-US-AlonsoNeural** | ✅ Las mejores en español de edge |
| edge-tts | **en-US-BrianMultilingualNeural, en-US-ChristopherNeural** | ✅ Las mejores en inglés de edge |
| edge-tts | es-AR-Elena, es-CO-Gonzalo, es-ES-Ximena, en-US-Ava/Emma Multilingual, en-AU-William, en-GB-Ryan | Descartadas |
| Kokoro | **em_santa** (es) | ✅ **Favorita** |
| Kokoro | **am_michael**, **af_heart** (en) | ✅ **Favoritas** |
| Kokoro | em_alex, ef_dora, am_fenrir, am_puck, bm_george | Descartadas |

Preferencias del usuario:
- Prefiere una voz **natural en inglés** antes que una **robótica en español**.
- Hora y clima de **Argentina** (Buenos Aires: lat −34.6037, lon −58.3816, TZ `America/Argentina/Buenos_Aires`).
- Edge-tts suena mejor a 1,05–1,08× de velocidad (`--rate=+5%`/`+8%`), más "de radio". Kokoro se probó a 1,05–1,08.

**Candidato por defecto: Kokoro** (local, gratis, sin internet) con em_santa / am_michael / af_heart.
Uso: `Kokoro(model, voices).create(text, voice=..., speed=..., lang="es"|"en-us"|"en-gb")`, ver `anexos/kokoro-tts.py`.
Modelos: `https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/{kokoro-v1.0.onnx,voices-v1.0.bin}`.

## Anexos

| Archivo | Qué es |
|---|---|
| `anexos/Dockerfile.radio-dj` | Imagen aislada usada para probar radio-dj (Debian + icecast2 + ffmpeg + edge-tts + Piper) |
| `anexos/Dockerfile.kokoro` | Capa extra con kokoro-onnx y sus modelos |
| `anexos/estacion.sh` | Levanta una estación de radio-dj por carpeta (contenedor + Ollama) |
| `anexos/tts-retry.sh` | Wrapper de edge-tts con reintentos |
| `anexos/kokoro-tts.py` | TTS mínimo con Kokoro |
| `anexos/edge-tts-clips.sh`, `anexos/kokoro-clips.sh` | Generan los clips de comparación (mezcla con ducking en ffmpeg) |
| `anexos/radio-dj-fix-watchdog.patch` | Parche al bug del vigilante (no verificado end-to-end) |

Los scripts tienen rutas de la prueba original (`/m` = `~/Música`, `/o` = salida, `/s` = scripts) montadas en Docker.
Son referencia, no código del proyecto.
