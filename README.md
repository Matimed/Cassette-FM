# cassette-fm

Convierte las carpetas de `~/Música` en **radios continuas**: cada subcarpeta es una estación que "suena" todo el
tiempo en orden aleatorio, y al sintonizarla se entra con el tema ya empezado. Un servicio local (Python + mpv)
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
| `cassette next` / `prev` | estación siguiente o anterior (alfabético, con vuelta) |
| `cassette tune <nombre>` | sintoniza por nombre o por el comienzo (`cassette tune reg`) |
| `cassette status` | qué suena |
| `cassette list` | estaciones y cantidad de temas |
| `cassette vol 70` / `+5` / `-5` | volumen; en 0 la radio se apaga (como un mute) y subirlo la enciende |
| `cassette rescan` | vuelve a leer `~/Música` |
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

Parámetros de la sección `[dj]` (todos opcionales; también se pueden pisar por estación con
`[dj.estaciones."Nombre"]`):

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

El cambio **no se guarda**: al reiniciar el servicio DJ vuelve a `plantillas`. Para arrancar siempre en LLM, poné
`modo = "llm"` en `~/.config/cassette-dj/config.toml`. En modo `plantillas` no se hace ningún pedido al LLM ni a Wikipedia.
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

[dj.estaciones."Lentos"]
voz = "em_santa"         # una voz por estación (cassette-dj voces lista las disponibles)
idioma = "es"            # es | en | en-us | en-gb
personalidad = "cálido, de madrugada"
frecuencia = { min = 4 }               # solo pisa lo que dice: acá, 4 a 5 temas

[dj.estaciones."Rock"]
frecuencia = { modo = "minutos", min = 8, max = 15 }
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
| `voz` / `idioma` / `personalidad` | `em_santa` / `es` / vacía | cómo habla la estación |
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

La velocidad de la voz de cada estación se pone con `velocidad` (0,5 a 2) en `[dj.estaciones."X"]` de la configuración
de la radio; si falta, vale la del servicio (`velocidad` de `cassette-dj`, 1,05).

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

Otras claves (con su valor por defecto): `latitud`/`longitud` (Buenos Aires), `timeout_hechos_segundos = 5`,
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

## Configuración

`~/.config/cassette-fm/config.toml` (todas las claves son opcionales):

```toml
raiz_musica = "~/Música"   # cada subcarpeta es una estación
puerto = 7710              # la API escucha solo en 127.0.0.1
avisos = true              # notificación de escritorio con estación y tema
normalizar = true          # parejiza el volumen entre temas (filtro dynaudnorm de mpv)
```

El estado (última estación y volumen) se guarda en `~/.local/state/cassette-fm/estado.json`.

## Desarrollo

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```

Logs del servicio: `journalctl --user -u cassette-fm -f`.
