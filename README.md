# cassette-fm

Convierte carpetas de música en **radios continuas**: cada emisora (definida en
`~/.config/cassette-fm/estaciones.json`, ver [Emisoras](#emisoras)) "suena" todo el tiempo en orden aleatorio, y al
sintonizarla se entra con el tema ya empezado. Un servicio local (Python + mpv)
lleva el reloj de cada estación y se controla con el comando `cassette`.

Diseño: [`docs/superpowers/specs/2026-11-13-cassette-fm-design.md`](docs/superpowers/specs/2026-11-13-cassette-fm-design.md).

## Instalación

Requiere Python 3.12 y mpv. Un solo comando instala el servicio, el comando `cassette`, los atajos de
teclado y el applet del panel de Cinnamon:

```bash
scripts/instalar-todo.sh
```

Después recargá Cinnamon con `Ctrl+Alt+Esc` para ver el applet. Se puede correr las veces que haga falta.
El servicio arranca con la sesión **en silencio**: solo suena con `cassette on` (o con el applet).

Si solo querés el servicio y la CLI, sin el escritorio: `scripts/instalar.sh`.

## Uso

| Comando | Qué hace |
|---|---|
| `cassette on` / `off` / `toggle` | enciende, apaga o alterna (al encender suena lo que corresponde *ahora*) |
| `cassette next` / `prev` | estación siguiente o anterior (en el orden de `estaciones.json`, con vuelta) |
| `cassette tune <nombre>` | sintoniza por nombre o por el comienzo (`cassette tune reg`) |
| `cassette status` | qué suena |
| `cassette list` | estaciones y cantidad de temas |
| `cassette vol 70` / `+5` / `-5` | volumen; en 0 la radio se apaga (como un mute) y subirlo la enciende |
| `cassette rescan` | vuelve a leer `estaciones.json` y la música de cada emisora |
| `cassette serve` | levanta el servicio a mano (sin systemd) |

## Applet de Cinnamon

Un ícono en el panel con el nombre de la estación (vacío si está apagada). Rueda del mouse: hacia arriba pasa
a la estación siguiente y hacia abajo a la anterior. Clic izquierdo: enciende o apaga. Clic derecho: lista de
estaciones para elegir una. El tooltip muestra estación, tema y volumen; si el servicio no está, dice que no
responde. En los ajustes del applet se cambia el puerto y si se muestra el nombre.

Si algo falla: `Alt+F2`, escribir `lg`, pestaña *Errors* (Looking Glass), y `journalctl --user -u cassette-fm -e`.

## DJ (en desarrollo)

La Etapa 3 agrega un DJ que habla entre temas. La radio sabe reproducir un clip de voz en un hueco reservado de la
agenda de una estación, con la música bajada, y entrar a mitad de frase si sintonizás con la intervención en curso
(se prueba con `cassette dj probar`). Y, si le das la dirección del [servicio DJ](#servicio-dj), **decide sola cuándo
pedirle una intervención** según una frecuencia configurable, la reserva en el hueco justo y la descarga cuando está lista.

**Viene apagado.** Para activarlo, en `~/.config/cassette-fm/config.toml`:

```toml
[dj]
activo = true
```

y `systemctl --user restart cassette-fm`. Con `activo = false` no se crea nada (ni el segundo mpv).

| Comando | Qué hace |
|---|---|
| `cassette dj probar` | registra un clip de tonos en el próximo hueco de la estación sintonizada (a ≥ 20 s) |
| `cassette dj probar --audio clip.wav --en 45` | usa tu propio clip (≤ la duración máxima) y una antelación de 45 s |
| `cassette dj pedir [--en 30]` | le pide **ahora** una intervención real al servicio DJ para el primer tema que arranque en ≥ 20 s (o los que digas), sin esperar a la frecuencia |
| `cassette dj estado` | qué tiene programado el DJ, si está hablando, el desfase entre mpv y el reloj y, con planificador, `servicio DJ: ok` o `no responde (…) · reintento en N s` y el pedido en curso |

Parámetros de la sección `[dj]` (todos opcionales; también se pueden pisar por emisora en su `"dj"` de
`estaciones.json`, ver [Emisoras](#emisoras)):

| Clave | Por defecto | Qué es |
|---|---|---|
| `duracion_maxima_segundos` | 15 | tope de duración de la voz |
| `retraso_voz_segundos` | 1 | cuánto después del comienzo del tema entra la voz |
| `nivel_musica_con_voz` | 0.6 | volumen de la música mientras habla, como fracción del tuyo **en la escala de mpv, que es cúbica**: 0.6 ≈ 13 dB más bajo (de fondo), 0.35 ≈ 28 dB (casi mudo), 0.7 ≈ 9 dB |
| `rampa_bajada_segundos` / `rampa_subida_segundos` | 0.4 / 1 | tiempo de bajar y de volver a subir la música |
| `minimo_restante_segundos` | 1.5 | si queda menos de esto de la frase, no se reproduce |
| `tolerancia_desfase_segundos` | 60 | cuánto puede apartarse el inicio real del tema del previsto |
| `desfase_aviso_segundos` | 5 | desfase a partir del cual se avisa en el log |
| `margen_seguridad_voz_segundos` | 2 | espera extra del temporizador que restaura la música |

### DJ con LLM (plantillas o LLM)

El servicio DJ redacta de dos maneras: con **plantillas** (por defecto, siempre) o con un **LLM** local que usa los hechos
verificados y, además, el resumen de Wikipedia del artista. El modo se cambia en caliente:

| Comando | Qué hace |
|---|---|
| `cassette dj modo` | muestra el modo actual (`plantillas` o `llm`) |
| `cassette dj modo llm` | pasa a LLM; avisa si el servidor de LLM (Ollama) no responde |
| `cassette dj modo plantillas` | vuelve a las plantillas |
| `cassette dj modo apagado` | apaga el locutor: la radio sigue sonando sin voces y no le pide nada al servicio DJ |

El cambio **no se guarda**: al reiniciar el servicio DJ vuelve a `plantillas`. Para arrancar siempre en LLM, poné
`modo = "llm"` en `~/.config/cassette-dj/config.toml`. El modo `apagado` vive en la radio y **sí se guarda**:
descarta lo que había reservado y deja de pedir clips; el servicio DJ, sin trabajo, suelta la voz de la memoria a los
`descargar_tras_minutos` y Ollama descarga el modelo a los 5 minutos. Para apagarlo para siempre, `[dj] activo = false`
en la config de la radio. En modo `plantillas` no se hace ningún pedido al LLM ni a Wikipedia.
Si el LLM no responde, tarda de más o su frase no pasa la verificación (año o cifra inventados, nombres que no están en
los hechos, enlaces…), esa frase sale por plantillas. `cassette-dj modo [llm|plantillas]` hace lo mismo hablando
directo con el servicio.

#### Instalar el LLM (Ollama en Docker)

```bash
scripts/instalar-llm.sh        # arranca el contenedor cassette-ollama (solo en 127.0.0.1:11434) y baja el modelo
cassette-dj llm estado         # URL, modelo configurado, si el servidor responde y si el modelo está descargado
```

Los modelos quedan en `~/.local/share/cassette-dj/ollama`. Para borrar todo: `docker rm -f cassette-ollama` y esa carpeta.
Configuración en `~/.config/cassette-dj/config.toml` (todo opcional, con su valor por defecto): `llm_url`
(`http://127.0.0.1:11434/v1`), `llm_modelo` (`gemma3:4b`), `llm_timeout_segundos` (240), `llm_intentos` (2: cuántas veces
se le pide una frase antes de usar la plantilla), `llm_temperatura` (0.8), `llm_margen_segundos` (45: lo que se reserva antes de la voz para sintetizar; el LLM solo se usa si
quedan más de eso y de 5 s antes de que empiece la voz, así que con el LLM conviene `margen_minutos` de 3 o más en la radio),
`wikipedia_dias` (90),
`wikipedia_palabras_maximas` (120), `wikipedia_url` y `wikidata_url`.

**Qué queda registrado:** cada frase que escribe el LLM, aceptada o descartada, queda en
`~/.local/state/cassette-dj/guiones.jsonl` con `fuente: "llm"`, el prompt (`sistema` y `usuario`), el texto `crudo`, el
`modelo`, el `intento` y, si se descartó, `descartado` y el `motivo`; la de plantilla por fallo lleva `fuente: "plantilla"`
y `motivo`. Los hechos usados y la URL de Wikipedia (texto CC BY-SA) van en `hechos`. Los descartados no entran en
`cassette-dj voz-prueba`.

**Verificación con el LLM real (la hacemos juntos):** (1) `scripts/instalar-llm.sh` (baja ~3 GB); (2) `cassette-dj llm
estado`; (3) `cassette dj modo llm` y `cassette dj pedir --en 180` en varias estaciones (con menos antelación el LLM no llega a tiempo y la frase sale por plantillas); escuchar; (4) mirar `cassette-dj
guiones` y el `guiones.jsonl` (prompts, crudos, descartados y motivos); (5) medir cuánto tarda cada frase; (6)
`cassette dj modo plantillas` para volver. Si `gemma3:4b` se queda corto, probar otro modelo con `llm_modelo`.

### Ensayo del DJ (probar todas las radios sin esperar)

`scripts/ensayo-dj.py` arma transiciones reales de la agenda de cada radio (10 por defecto), le manda al servicio
DJ los mismos pedidos que armaría el planificador (voz, idioma y personalidad de cada radio) y muestra los
guiones en vivo: hora en cian, frases del LLM en verde, descartados en rojo y plantillas en amarillo. Al final
resume por radio y por motivo de descarte, y guarda todos los registros (prompt, crudo, hechos) en
`~/.local/state/cassette-dj/ensayos/`. Opciones: `--canciones N`, `--estacion "Nombre"` (repetible), `--modo
llm|plantillas`, `--margen SEGUNDOS` (cuánto tiempo tiene el LLM para escribir, 300 por defecto),
`--conservar-audio`, `--sin-color`. Los pedidos van de a uno (como el planificador, que pasa los `recientes`), y
los clips se borran al terminar cada uno.

### Planificador (frases reales)

Para que la radio le pida intervenciones al servicio DJ hay que poner **las dos cosas** (sin `url` no intenta
conectarse a nada):

```toml
[dj]
activo = true
url = "http://127.0.0.1:7720"

[dj.frecuencia]          # general: vale para todas las estaciones
modo = "temas"           # "temas" o "minutos"
min = 3
max = 5

```

Lo de cada emisora va en su `"dj"` de `estaciones.json` (solo pisa lo que dice):

```json
[
  {"nombre": "Lentos", "fuente": {"carpeta": "~/Música/Lentos"},
   "dj": {"voz": "em_santa", "idioma": "es", "personalidad": "cálido, de madrugada", "frecuencia": {"min": 4}}},
  {"nombre": "Rock", "fuente": {"carpeta": "~/Música/Rock"},
   "dj": {"frecuencia": {"modo": "minutos", "min": 8, "max": 15}}}
]
```

La intervención cae entre `min` y `max` temas (o minutos) después de la última de esa estación; nunca antes del
`margen_minutos` (da tiempo a generar el clip) y siempre en un tema con artista y título en los tags. Habla solo la
estación sintonizada, pero un pedido ya iniciado termina siempre y su clip queda reservado para su estación. Si el
servicio no responde, la música sigue igual: un único aviso en el log, reintentos con espera creciente y recuperación sola.

| Clave | Por defecto | Qué es |
|---|---|---|
| `url` | `""` | dirección del servicio DJ; vacía = sin planificador |
| `frecuencia.modo` / `min` / `max` | `temas` / 2 / 3 | cada cuánto habla (en `temas`, enteros ≥ 1) |
| `margen_minutos` | 6 | antes de esto no se agenda nada |
| `peticion_margen_segundos` | 30 | lo mínimo que tiene que quedar del tema actual para anunciar una petición antes |
| `voz` / `idioma` / `personalidad` | `af_heart` / `en` / vacía | cómo habla la estación (`voz`: mejor un [alias](#voces-con-nombre-alias)) |
| `timeout_http_segundos` | 10 | espera máxima por una respuesta del servicio |
| `espera_reintento_segundos` / `espera_reintento_maxima_segundos` | 5 / 300 | espera tras un fallo y su tope (se duplica) |
| `espera_trabajo_maxima_segundos` | 600 | un pedido que tarda más que esto se cancela |
| `recientes_cantidad` | 6 | cuántos ingredientes de frases anteriores se le recuerdan al servicio por estación |

**Verificación con audio real (la hacemos juntos):** (1) `scripts/instalar-dj.sh` y `cassette-dj modelos`;
(2) poner la `url` de arriba en `config.toml` y `systemctl --user restart cassette-fm`; (3) sintonizar una estación y
correr `cassette dj pedir --en 30`, escuchar la frase; (4) dejarlo solo y comprobar que habla cada 2–3 temas;
(5) `cassette dj estado` muestra `servicio DJ: ok`.

**Cómo probar el clip fijo con audio real:** sintonizá una estación, corré `cassette dj probar --en 20` y comprobá que
(a) la voz entra ~1 s después de que arranca el tema siguiente, con la música bajada; (b) si cambiás de estación
y volvés con la voz todavía sonando, retoma la frase en el punto que corresponde; (c) bajar el volumen a 0 la corta;
(d) `cassette dj estado` informa el desfase.

## Servicio DJ

Servicio aparte (`cassette-dj`) que escribe y sintetiza las frases del DJ. Puede correr en esta PC o en otra:
la radio solo necesita su dirección. **No tiene autenticación** (con un `host` que no sea local, avisa en el log): para usarlo desde otra máquina hay que poner
`host = "0.0.0.0"` y hacerlo en una red de confianza.

**Instalación** (la hacés vos; instala el extra `[dj]` y el servicio de usuario `cassette-dj`):

```bash
scripts/instalar-dj.sh
cassette-dj modelos        # baja los modelos de voz de Kokoro (~350 MB), una sola vez
```

**Configuración** en `~/.config/cassette-dj/config.toml` (todo opcional):

| Clave | Por defecto | Qué es |
|---|---|---|
| `host` / `puerto` | `127.0.0.1` / `7720` | dónde escucha |
| `trabajadores` | 1 | pedidos que se procesan a la vez |
| `retencion_minutos` | 60 | cuánto se conserva un clip terminado |
| `descargar_tras_minutos` | 5 | Kokoro se descarga de la memoria tras este tiempo sin trabajo |
| `modelos_dir` | `~/.local/share/cassette-dj/modelos` | dónde están los modelos (ruta absoluta o con `~`) |
| `palabras_maximas` | 45 | largo máximo de una frase |
| `velocidad` | 1.05 | velocidad de la voz |
| `pausa_oracion_segundos` / `pausa_coma_segundos` | 0.25 / 0.1 | pausas mínimas tras un punto y una coma |
| `continuo` | `false` | síntesis continua de Kokoro (a probar con frases largas) |
| `zona_horaria` | `America/Argentina/Buenos_Aires` | |

El idioma con que se pronuncia cada nombre propio ("Daddy Yankee" en inglés, aunque la frase sea en español) se
configura en `~/.config/cassette-dj/lexico.toml`:

```toml
[idiomas]
"Daddy Yankee" = "en-us"

[pronunciacion]          # cómo escribir un nombre para que la voz lo diga bien (se busca sin mayúsculas ni acentos)
"Regueton 2000" = "Reguetón 2000"
```

La velocidad de la voz de cada emisora se pone con `velocidad` (0,5 a 2) en su `"dj"` de `estaciones.json`; si falta, vale la del servicio (`velocidad` de `cassette-dj`, 1,05).

### Voces con nombre (alias)

Cada emisora dice con qué voz habla su DJ. En lugar de poner el nombre crudo del modelo (`am_puck`,
`piper:es_AR-daniela-high`) conviene darle un **alias** una sola vez y usar el alias en las emisoras: se lee mejor,
para cambiar la voz de varias emisoras alcanza con tocar una línea y el DJ comparte lo que aprendió de esa voz (cuántas
palabras dice por segundo, para no pasarse de `duracion_maxima_segundos`) entre el alias y el nombre crudo.

**1. Definir los alias** en la tabla `[voces]` de `~/.config/cassette-dj/config.toml` (el del servicio DJ):

```toml
[voces]
puck = "am_puck"                         # una voz de Kokoro
daniela = "piper:es_AR-daniela-high"     # una voz de Piper: "piper:" + el nombre del modelo
alex_santa = "em_alex+em_santa"          # una mezcla de voces de Kokoro (promedio), con "+"
```

- El alias solo puede tener letras, números, `_`, `.` y `-`.
- `cassette-dj voces` lista primero los alias (con la voz a la que apunta cada uno, y un aviso si esa voz no
  existe) y después todo lo demás que se puede usar: las voces de Kokoro y los modelos de Piper que haya en
  `~/.local/share/cassette-dj/modelos/piper/`, cada una con su alias al lado si tiene. En Kokoro, la primera letra
  del nombre es el idioma de la voz (`a` inglés de EE. UU., `b` británico, `e` español, `f` francés, `h` hindi,
  `i` italiano, `j` japonés, `p` portugués de Brasil, `z` chino) y la segunda el género (`f` mujer, `m` hombre). Para escuchar una antes de elegirla:
  `cassette-dj voz-prueba --voz daniela` vuelve a decir los últimos guiones con esa voz, y
  `mpv $(cassette-dj muestra --voz daniela --idioma es --radio "Sing")` le hace decir "Hola, soy daniela y estás
  escuchando Sing" (la pide al servicio y la guarda; es lo que suena con ▶ en el modal de emisora nueva del applet).
- Para sumar una voz de Piper, bajá su modelo a esa carpeta (las voces están en
  [rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices)):
  `.venv/bin/python -m piper.download_voices --download-dir ~/.local/share/cassette-dj/modelos/piper es_MX-claude-high`.
- Después de tocar `[voces]`: `systemctl --user restart cassette-dj` (el servicio lee los alias al arrancar).

**2. Usarlos en las emisoras**, en el `"dj"` de cada una en `~/.config/cassette-fm/estaciones.json` (ver
[Emisoras](#emisoras)); la `velocidad` es opcional:

```json
{"nombre": "Más Gasolina F.M.", "fuente": {"spotify": "…"}, "dj": {"idioma": "es", "voz": "daniela", "velocidad": 0.9}}
```

Y, si querés, la voz de las emisoras que no tengan una propia, en `[dj]` del `config.toml` de la radio:
`voz = "heart"`. Después de tocar `estaciones.json` alcanza con `cassette rescan` (sin cortar la música).

Si una emisora usa un alias que no existe, sus intervenciones fallan (queda en `cassette-dj guiones` y en el log del
servicio) y la música sigue sin voz: revisá que el alias esté escrito igual en los dos archivos.

### Hechos reales en las frases

El servicio junta datos **verificados** y los mezcla en las frases; si no hay un dato confiable, no lo dice:

- **Clima de Buenos Aires** (open-meteo, sin clave): temperatura y cielo, dichos en palabras.
- **Datos del tema y del artista** (MusicBrainz): año de lanzamiento (el más antiguo entre las grabaciones que coinciden
  exacto en título y artista), país del artista y, si es una banda, cuándo empezó. No se usa nada si hay dos artistas con
  el mismo nombre o si el dato no es coherente. Todo queda en una caché SQLite (`~/.local/state/cassette-dj/hechos.sqlite`),
  también lo que no se encontró.
- **MusicBrainz pide un contacto en el `User-Agent`**: poné el tuyo en `~/.config/cassette-dj/config.toml` con
  `contacto = "tu@mail"` (no se guarda en ningún otro lado). Sin `contacto` no se consulta MusicBrainz.

Cada frase combina de 1 a 3 ingredientes (el tema siempre; estación, hora, momento del día o día de la semana, álbum,
tema anterior, clima y dato, de a uno por vez). El peso de cada uno y las demás claves se pueden cambiar:

```toml
contacto = "tu@mail"
ingredientes_max = 3            # cuántos ingredientes junta una frase
penalizacion_reciente = 0.3     # lo que salió hace poco pesa 0,3 veces por cada aparición

[ingredientes]                  # probabilidad de ofrecer cada ingrediente (0 a 1); el tema siempre va
estacion = 0.5
hora = 0.35
momento = 0.3
album = 0.3
anterior = 0.3
clima = 0.12
dato = 0.25
```

Otras claves (con su valor por defecto): `latitud`/`longitud` (Buenos Aires), `timeout_hechos_segundos = 10`,
`cache_clima_minutos = 15`, `cache_datos_dias = 90`, `cache_sin_dato_dias = 14`, `cache_error_minutos = 10`,
`musicbrainz_url` y `open_meteo_url`. `cassette-dj hechos` muestra el clima de ahora y
`cassette-dj hechos --artista "a-ha" --titulo "Take On Me"` los datos que se usarían; `cassette-dj guiones` y el
registro de guiones anotan, en cada frase, qué hechos se usaron y su fuente.

**Verificación con los servicios reales (la hacemos juntos):** (1) poner `contacto` y reiniciar `cassette-dj`;
(2) `cassette-dj hechos --artista "a-ha" --titulo "Take On Me"` tiene que dar 1984, Noruega y grupo desde 1983, y
`cassette-dj hechos` el clima de ahora; (3) subir temporalmente `clima` y `dato` a 1 en `[ingredientes]`, correr
`cassette dj pedir --en 30` en varias estaciones y escuchar; (4) volver a los pesos de fábrica y dejarlo andar:
tienen que aparecer frases distintas y, de vez en cuando, clima o un dato.

**Contrato HTTP** (JSON UTF-8; todo viaja en el pedido, el servicio no guarda estado entre pedidos):

| Método y ruta | Qué hace |
|---|---|
| `POST /intervenciones` | encola un pedido; `202 {"id"}`; `400` si es inválido; repetir el `id` no lo vuelve a encolar |
| `GET /intervenciones/<id>` | `{"estado": "pendiente\|trabajando\|listo\|error\|cancelado", "duracion", "texto", "ingredientes", "error"}` |
| `GET /intervenciones/<id>/audio` | el WAV, cuando está `listo` (`409` si todavía no) |
| `DELETE /intervenciones/<id>` | cancela si todavía no empezó: `{"cancelado": true\|false}` |
| `GET /voces`, `GET /salud` | voces disponibles; estado del servicio (modelos que faltan, trabajos por estado) |

```bash
curl -s -X POST localhost:7720/intervenciones -d '{
  "id": "prueba1", "estacion": "Lentos", "idioma": "es", "voz": "em_santa",
  "momento": "2026-11-13T21:47:00-03:00",
  "anterior": {"artista": "Whitesnake", "titulo": "Is This Love"},
  "siguiente": {"artista": "Foreigner", "titulo": "Waiting for a Girl Like You"}}'
curl -s localhost:7720/intervenciones/prueba1                       # estado y texto
curl -s localhost:7720/intervenciones/prueba1/audio -o prueba1.wav   # el clip
```

**Guiones y pruebas de voz.** Todo lo que el DJ dice queda en `~/.local/state/cassette-dj/guiones.jsonl`, sin borrarse nunca.
`cassette-dj guiones` los lista, y `cassette-dj voz-prueba --voz em_santa --voz em_alex` vuelve a sintetizar los últimos
guiones **tal cual** con las voces que le pases (también acepta mezclas, `em_santa+em_alex`), para comparar voces con
las mismas frases.

## Atajos de teclado (Cinnamon)

`cassette atajos` (ya lo hace `instalar-todo.sh`) registra estas teclas (no pisa las que ya uses ni las que cambies a mano):

| Tecla | Acción |
|---|---|
| `Super+Alt+→` / `Super+Alt+←` | estación siguiente / anterior |
| `Super+Alt+↑` / `Super+Alt+↓` | volumen +10 / −10 (en 0 se apaga; subir lo enciende) |

### Teclas multimedia y parlantes Bluetooth

Mientras corre el servicio, la radio se queda con las teclas multimedia (las del teclado y los botones de un
parlante o auriculares Bluetooth, que llegan como teclas) y aparece en el applet de sonido de Cinnamon con el tema,
el artista y la emisora:

| Tecla / botón | Acción |
|---|---|
| Siguiente (dos toques en un JBL) | emisora siguiente |
| Anterior (tres toques) | emisora anterior |
| Play/pausa (un toque) | prende o apaga la radio (al volver entra con el tema en curso) |

Mientras la radio corre, otros reproductores (un video en el navegador, por ejemplo) no reciben esas teclas: Cinnamon
se las da al último programa que las pidió.

## Configuración

`~/.config/cassette-fm/config.toml` (todas las claves son opcionales):

```toml
raiz_musica = "~/Música"   # solo para crear estaciones.json la primera vez (ver Emisoras)
puerto = 7710              # la API escucha solo en 127.0.0.1
avisos = true              # notificación de escritorio con estación y tema
normalizar = true          # parejiza el volumen entre temas (filtro dynaudnorm de mpv)
```

El estado (última estación y volumen) se guarda en `~/.local/state/cassette-fm/estado.json`.

### Spotify

Una emisora puede ser una playlist de Spotify. Requisitos: cuenta **Premium** y que la playlist sea **tuya** (creada
por vos o colaborativa): desde febrero de 2026 Spotify no deja leer los temas de las playlists que solo seguís; para
usar una de esas, copiala a una playlist propia.

- `cassette spotify login` abre el navegador para darle permiso a cassette-fm (una sola vez; la sesión se guarda en
  `~/.local/state/cassette-fm/spotify-token.json` y se renueva sola).
- `cassette spotify estado` muestra la cuenta y cuántos temas tiene cada emisora de Spotify.
- `cassette nueva "Synthwave F.M." <link de la playlist>` crea la emisora y la sintoniza: la agrega a
  `estaciones.json` con un DJ de voz propia (un alias de `[voces]` de cassette-dj que no use otra emisora, al azar;
  el idioma sale de la voz). `--voz sarah` la elige, `--idioma es` pide una en español. Si la playlist no es tuya
  o está vacía, no se guarda nada. Dos emisoras pueden usar la misma playlist: cada una va por otro tema.
- `cassette voces` lista los alias que puede usar una emisora nueva, con su idioma y las emisoras que ya los usan
  (`--json`, para el applet).
- Los temas se guardan en `~/.cache/cassette-fm/spotify.json`: el rescan solo los vuelve a bajar si la playlist cambió,
  y si Spotify no responde usa los guardados.
- Suenan con **Spotify Soloist** (cliente oficial de Spotify sin ventana, ~45 MB de RAM), que corre como servicio de
  usuario `cassette-soloist`. Instalación (una vez): guardá la API key de Soloist (se genera en
  <https://developer.spotify.com/dashboard/soloist>) en `~/.config/cassette-fm/soloist.key` con `chmod 600` y corré
  `scripts/instalar-spotify.sh` (baja Soloist, lo empareja desde el celular, instala el servicio y hace el login).
- **Cada build de Soloist vence a los 90 días**: `cassette spotify estado` avisa cuando faltan menos de 14 y
  `scripts/actualizar-soloist.sh` lo renueva.
- Al sintonizar una emisora de Spotify suena un segundo de estática hasta que arranca la música. Los temas siguen la
  misma agenda que una emisora local (orden mezclado, se entra con el tema empezado) y Spotify los encadena sin cortes.
  El DJ habla igual, con la música bajada.
- A veces Soloist no logra cargar un tema (le pasa a algunos, de a ratos, aunque en la app de Spotify suenen) y pasa
  al siguiente en menos de un segundo; a veces toca otra versión del tema (otra edición del disco). La radio lo
  acepta: si cambia de tema a menos de 2 s del anterior, la agenda sigue desde lo que suena (en el log: «Soloist
  salteó …»), y otra versión cuenta como el tema que tocaba. Lo mismo si salteás rápido desde la app; un salto más
  lento vuelve a la agenda.
- Lo que agregás a la cola desde la app de Spotify es una **petición**: ver [Peticiones](#peticiones).
- Si ponés Spotify en otro dispositivo (el celular), la radio se apaga y avisa. Si sintonizás una emisora de Spotify,
  la radio toma el control de tu cuenta.
- `[spotify]` del `config.toml`: `activo` (false = ignorar las emisoras de Spotify), `ajuste_volumen_db` (para que
  suenen tan fuerte como las locales; lo propone `scripts/calibrar-spotify.py`), `nombre_dispositivo`, `soloist_ws`,
  `soloist_bin`, `uris_por_pedido`, `tolerancia_resync_segundos`, `client_id`, `puerto_login` y `timeout_segundos`.

### Peticiones

Mientras suena una emisora de Spotify, agregá un tema a la cola desde la app de Spotify (en la compu o el celular):
cuando termina el tema actual suena el tuyo y el DJ lo anuncia como **petición especial**.

- **Antes o después:** si quedan al menos `peticion_margen_segundos` (30 por defecto) del tema actual, el DJ lo
  presenta al arrancar («y ahora, una petición especial…»); si no llega, lo anuncia al terminar («eso fue una
  petición especial…»). Necesita que el tema tenga artista y título, y que el DJ esté activo.
- **La agenda se corre:** la emisora no pierde temas: mientras suena el pedido su agenda se detiene y después sigue
  con el tema que venía. Se corre lo que sonó de verdad: menos si lo salteás desde la app, y hasta 15 s más si
  Spotify tarda en pasar al siguiente (más que eso es una pausa, y la radio sigue siendo un reloj).
- **Pedidos seguidos:** varios encolados se encadenan. Si el segundo entra con tiempo, el DJ cierra el primero y
  presenta el segundo en un solo anuncio («eso fue una petición especial: …; y llega otra»). Si encolás dos con
  menos del margen, el primero queda sin mención.
- **Anuncios que ya no van:** si sacás un tema de la cola (con o sin encolar otro) o salteás un pedido, su anuncio
  se descarta y no frena las intervenciones normales.
- Cuenta como petición todo lo que viene de la cola, aunque sea un tema de la playlist o justo el siguiente.
- Si cambiás de emisora (o reiniciás la radio) a mitad de un pedido y volvés, sigue el pedido en el segundo que
  corresponde. Los pedidos se guardan en `estado.json` (`agendas`).
- Encolar mientras habla el DJ no lo corta: solo se descarta lo que estaba previsto desde el pedido en adelante.
- Para ver qué manda Soloist al encolar: `.venv/bin/python scripts/capturar-cola-soloist.py SALIDA.jsonl` (solo
  escucha; no cambia lo que suena).

### Emisoras

Las emisoras están en `~/.config/cassette-fm/estaciones.json`, una lista en el orden en que se rotan:

```json
[
  {"nombre": "Lentos", "fuente": {"carpeta": "~/Música/Lentos"}, "dj": {"idioma": "es", "voz": "daniela"}},
  {"nombre": "Otra", "fuente": {"carpeta": "/media/disco/música/otra"}},
  {"nombre": "Sing", "fuente": {"spotify": "https://open.spotify.com/playlist/4iHcTVQbU4QvIJV5Xao0fs"}}
]
```

- `fuente` es una carpeta (ruta absoluta o con `~`, en cualquier lugar del disco) o una playlist de Spotify (link o
  URI; ver [Spotify](#spotify)).
- `dj` (opcional) pisa los ajustes de `[dj]` del `config.toml` para esa emisora.
- **La primera vez** el archivo se crea solo con las subcarpetas de `raiz_musica` y los `[dj.estaciones."X"]` que
  hubiera en el `config.toml`. Desde entonces `[dj.estaciones]` del `config.toml` se ignora (avisa una vez en el log).
- `cassette rescan` lo relee. Si quedó mal escrito, la radio sigue con las emisoras que tenía y el comando muestra el
  error con la línea. Si está mal escrito **al arrancar**, el servicio no levanta: el motivo (con la línea) se ve con
  `journalctl --user -u cassette-fm -n 20`.

## Desarrollo

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```

Logs del servicio: `journalctl --user -u cassette-fm -f`.
