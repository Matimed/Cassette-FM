# El DJ

Un locutor por emisora que habla de vez en cuando, como en una radio de verdad: no en todos los temas, con una voz
propia, y diciendo cosas **verdaderas** (la hora, el clima, un dato verificado del tema o del artista). Esta página es la
referencia para usarlo y ajustarlo. La instalación está en [`setup.md`, paso 3](setup.md#3-dj-con-voz-opcional); las
decisiones de diseño, en [`arquitectura.md`](arquitectura.md#el-dj).

## Cómo funciona

Son dos partes:

- **La radio** (`cassette-fm`) sabe reproducir un clip de voz en un hueco reservado de la agenda de una emisora, con la
  música bajada (*ducking*), y entrar a mitad de frase si sintonizás con la voz en curso. Decide **cuándo** pedir una
  intervención (el *planificador*), la reserva en el hueco justo y la descarga cuando está lista.
- **El servicio DJ** (`cassette-dj`) escribe la frase, la sintetiza con una voz y devuelve el audio. Es un servicio aparte:
  corre en esta PC o en otra; la radio solo necesita su dirección.

Dos garantías: **la música nunca espera al DJ** (si una intervención no llega a tiempo, simplemente no suena) y **no se
inventan datos** (el LLM, si lo usás, redacta pero nunca es la fuente de un hecho).

La voz cae alrededor del empalme entre dos temas. Se ancla al **corte**, no al arranque del tema nuevo, y puede caer en
`inicio`, `entre`, `final` o `mixto` (al azar); el texto se adapta a cada posición (ver `posicion_voz`, abajo). Todavía
no hay *crossfade*.

## Activarlo

Viene **apagado**. En `~/.config/cassette-fm/config.toml`:

```toml
[dj]
activo = true
url = "http://127.0.0.1:7720"    # sin url no intenta conectarse a nada

[dj.frecuencia]                  # general: vale para todas las emisoras
modo = "temas"                   # "temas" o "minutos"
min = 3
max = 5
```

y `systemctl --user restart cassette-fm`. Con `activo = false` no se crea nada (ni el segundo mpv).

Lo de cada emisora va en su `"dj"` de `estaciones.json` (solo pisa lo que dice):

```json
[
  {"nombre": "Lentos", "fuente": {"carpeta": "~/Música/Lentos"},
   "dj": {"voz": "daniela", "idioma": "es", "personalidad": "cálido, de madrugada", "frecuencia": {"min": 4}}},
  {"nombre": "Rock", "fuente": {"carpeta": "~/Música/Rock"},
   "dj": {"frecuencia": {"modo": "minutos", "min": 8, "max": 15}}}
]
```

La intervención cae entre `min` y `max` temas (o minutos) después de la última de esa emisora; nunca antes del
`margen_minutos` (da tiempo a generar el clip) y siempre en un tema con artista y título en los tags. Habla solo la
emisora sintonizada, pero un pedido ya iniciado termina siempre y su clip queda reservado para su emisora. Si el servicio
no responde, la música sigue igual: un único aviso en el log, reintentos con espera creciente y recuperación sola.

## Comandos de la radio

| Comando | Qué hace |
|---|---|
| `cassette dj estado` | qué tiene programado el DJ, si está hablando, el desfase entre mpv y el reloj y, con planificador, `servicio DJ: ok` o `no responde (…) · reintento en N s` y el pedido en curso |
| `cassette dj pedir [--en 30]` | le pide **ahora** una intervención real al servicio DJ para el primer tema que arranque en ≥ 20 s (o los que digas), sin esperar a la frecuencia |
| `cassette dj probar` | registra un clip de tonos en el próximo hueco de la emisora sintonizada (a ≥ 20 s); para probar el *ducking* sin servicio |
| `cassette dj probar --audio clip.wav --en 45` | usa tu propio clip (≤ la duración máxima) y una antelación de 45 s |
| `cassette dj modo [llm\|plantillas\|apagado]` | muestra o cambia cómo redacta el DJ (ver [Modos](#modos-plantillas-llm-o-apagado)) |

## Parámetros de `[dj]`

Todos son opcionales y también se pueden pisar por emisora en su `"dj"` de `estaciones.json`.

**Planificador**

| Clave | Por defecto | Qué es |
|---|---|---|
| `activo` | `false` | enciende el DJ |
| `url` | `""` | dirección del servicio DJ; vacía = sin planificador |
| `frecuencia.modo` / `min` / `max` | `temas` / 2 / 3 | cada cuánto habla (en `temas`, enteros ≥ 1) |
| `margen_minutos` | 6 | antes de esto no se agenda nada |
| `peticion_margen_segundos` | 30 | lo mínimo que tiene que quedar del tema actual para anunciar una petición antes |
| `voz` / `idioma` / `personalidad` | `af_heart` / `en` / vacía | cómo habla la emisora (`voz`: mejor un [alias](#voces-con-nombre-alias)) |
| `velocidad` | la del servicio | velocidad de la voz de la emisora (0,5 a 2) |
| `recientes_cantidad` | 6 | cuántos ingredientes de frases anteriores se le recuerdan al servicio por emisora |
| `timeout_http_segundos` | 10 | espera máxima por una respuesta del servicio |
| `espera_reintento_segundos` / `espera_reintento_maxima_segundos` | 5 / 300 | espera tras un fallo y su tope (se duplica) |
| `espera_trabajo_maxima_segundos` | 600 | un pedido que tarda más que esto se cancela |

**Dónde cae la voz y cómo suena la música**

| Clave | Por defecto | Qué es |
|---|---|---|
| `duracion_maxima_segundos` | 15 | tope de duración de la voz |
| `posicion_voz` | `mixto` | dónde cae la voz respecto del corte entre dos temas: `inicio` (toda después del corte), `entre` (el corte cae dentro de la voz), `final` (termina justo antes del corte, sobre el final del tema que termina) o `mixto` (una de las tres al azar en cada intervención). En `entre` el DJ cierra el tema anterior y presenta el nuevo; en `final` habla en futuro («a continuación…») |
| `retraso_voz_segundos` | 1 | con `posicion_voz = "inicio"`, cuánto después del comienzo del tema entra la voz |
| `fraccion_entre_min` / `fraccion_entre_max` | 0.3 / 0.7 | en `entre`, qué parte del clip suena antes del corte (entre 0 y 1) |
| `final_antes_min_segundos` / `final_antes_max_segundos` | 0 / 2 | en `final`, cuántos segundos antes del corte termina la voz |
| `nivel_musica_con_voz` | 0.6 | volumen de la música mientras habla, como fracción del tuyo **en la escala de mpv, que es cúbica**: 0.6 ≈ 13 dB más bajo (de fondo), 0.35 ≈ 28 dB (casi mudo), 0.7 ≈ 9 dB |
| `ganancia_voz_db` | 10 | sube y comprime la voz de Kokoro, que sale mucho más baja que la música; 0 = sin filtro |
| `rampa_bajada_segundos` / `rampa_subida_segundos` | 0.4 / 1 | tiempo de bajar y de volver a subir la música |
| `minimo_restante_segundos` | 1.5 | si queda menos de esto de la frase, no se reproduce |

**Tolerancias**

| Clave | Por defecto | Qué es |
|---|---|---|
| `tolerancia_desfase_segundos` | 60 | cuánto puede apartarse el inicio real del tema del previsto |
| `desfase_aviso_segundos` | 5 | desfase a partir del cual se avisa en el log |
| `margen_seguridad_voz_segundos` | 2 | espera extra del temporizador que restaura la música |

## Modos: plantillas, LLM o apagado

El servicio redacta de dos maneras: con **plantillas** (por defecto, siempre disponibles) o con un **LLM** local que usa
los hechos verificados y, además, el resumen de Wikipedia del artista.

| Comando | Qué hace |
|---|---|
| `cassette dj modo` | muestra el modo actual (`plantillas` o `llm`) |
| `cassette dj modo llm` | pasa a LLM; avisa si el servidor de LLM (Ollama) no responde |
| `cassette dj modo plantillas` | vuelve a las plantillas |
| `cassette dj modo apagado` | apaga el locutor: la radio sigue sonando sin voces y no le pide nada al servicio DJ |

- **`llm` y `plantillas` no se guardan**: al reiniciar el servicio DJ vuelve a `plantillas`. Para arrancar siempre en LLM,
  `modo = "llm"` en `~/.config/cassette-dj/config.toml`. (`cassette-dj modo [llm|plantillas]` hace lo mismo hablando
  directo con el servicio.)
- **`apagado` sí se guarda** (vive en la radio): descarta lo que había reservado y deja de pedir clips; el servicio DJ,
  sin trabajo, suelta la voz de la memoria a los `descargar_tras_minutos` y Ollama descarga el modelo a los 5 minutos.
  Para apagarlo para siempre: `[dj] activo = false`.
- En modo `plantillas` no se hace ningún pedido al LLM ni a Wikipedia.
- Si el LLM no responde, tarda de más o su frase no pasa la verificación (año o cifra inventados, nombres que no están
  en los hechos, enlaces…), esa frase sale por plantillas.

### El LLM (Ollama en Docker)

`scripts/instalar-llm.sh` arranca el contenedor `cassette-ollama` (solo en `127.0.0.1:11434`) y baja el modelo;
`cassette-dj llm estado` informa la URL, el modelo, si el servidor responde y si el modelo está descargado. Los modelos
quedan en `~/.local/share/cassette-dj/ollama`. Para borrar todo: `docker rm -f cassette-ollama` y esa carpeta.

Claves en `~/.config/cassette-dj/config.toml` (todas opcionales):

| Clave | Por defecto | Qué es |
|---|---|---|
| `llm_url` | `http://127.0.0.1:11434/v1` | dónde está el servidor |
| `llm_modelo` | `gemma3:4b` | el modelo (si queda corto, probar otro) |
| `llm_timeout_segundos` | 240 | espera máxima por una respuesta |
| `llm_intentos` | 2 | cuántas veces se le pide una frase antes de usar la plantilla |
| `llm_temperatura` | 0.8 | |
| `llm_margen_segundos` | 45 | lo que se reserva antes de la voz para sintetizar; el LLM solo se usa si quedan más de eso y de 5 s antes de que empiece la voz, así que con el LLM conviene `margen_minutos` de 3 o más en la radio |
| `wikipedia_dias` / `wikipedia_palabras_maximas` | 90 / 120 | caché y largo del resumen de Wikipedia |
| `wikipedia_url` / `wikidata_url` | | para apuntar a otra instancia |

**Qué queda registrado:** cada frase que escribe el LLM, aceptada o descartada, queda en
`~/.local/state/cassette-dj/guiones.jsonl` con `fuente: "llm"`, el prompt (`sistema` y `usuario`), el texto `crudo`, el
`modelo`, el `intento` y, si se descartó, `descartado` y el `motivo`; la de plantilla por fallo lleva `fuente: "plantilla"` y
`motivo`. Los hechos usados y la URL de Wikipedia (texto CC BY-SA) van en `hechos`. Los descartados no entran en
`cassette-dj voz-prueba`.

## El servicio DJ

`cassette-dj` es un servicio de usuario (`systemctl --user … cassette-dj`) que escucha en `127.0.0.1:7720`.
**No tiene autenticación** (con un `host` que no sea local, avisa en el log): para usarlo desde otra máquina hay que poner
`host = "0.0.0.0"` y hacerlo en una red de confianza.

### Configuración

`~/.config/cassette-dj/config.toml` (todo opcional):

| Clave | Por defecto | Qué es |
|---|---|---|
| `host` / `puerto` | `127.0.0.1` / `7720` | dónde escucha |
| `trabajadores` | 1 | pedidos que se procesan a la vez |
| `retencion_minutos` | 60 | cuánto se conserva un clip terminado |
| `descargar_tras_minutos` | 5 | Kokoro se descarga de la memoria tras este tiempo sin trabajo |
| `modelos_dir` | `~/.local/share/cassette-dj/modelos` | dónde están los modelos (ruta absoluta o con `~`) |
| `palabras_maximas` | 45 | largo máximo de una frase |
| `velocidad` | 1.05 | velocidad de la voz (0,5 a 2) |
| `pausa_oracion_segundos` / `pausa_coma_segundos` | 0.25 / 0.1 | pausas mínimas tras un punto y una coma |
| `continuo` | `false` | síntesis continua de Kokoro (a probar con frases largas) |
| `zona_horaria` | `America/Argentina/Buenos_Aires` | para la hora que dice el DJ |
| `latitud` / `longitud` | Buenos Aires | de dónde sale el clima |
| `contacto` | vacío | tu mail, para el `User-Agent` de MusicBrainz (sin él no se consulta) |

### Voces con nombre (alias)

Cada emisora dice con qué voz habla su DJ. En lugar de poner el nombre crudo del modelo (`am_puck`,
`piper:es_AR-daniela-high`) conviene darle un **alias** una sola vez y usarlo en las emisoras: se lee mejor, para cambiar
la voz de varias emisoras alcanza con tocar una línea, y el DJ comparte lo que aprendió de esa voz (cuántas palabras dice
por segundo, para no pasarse de `duracion_maxima_segundos`) entre el alias y el nombre crudo.

**1. Definir los alias** en la tabla `[voces]` de `~/.config/cassette-dj/config.toml`:

```toml
[voces]
puck = "am_puck"                         # una voz de Kokoro
daniela = "piper:es_AR-daniela-high"     # una voz de Piper: "piper:" + el nombre del modelo
alex_santa = "em_alex+em_santa"          # una mezcla de voces de Kokoro (promedio), con "+"
```

- El alias solo puede tener letras, números, `_`, `.` y `-`.
- `cassette-dj voces` lista primero los alias (con la voz a la que apunta cada uno, y un aviso si esa voz no existe) y
  después todo lo demás que se puede usar: las voces de Kokoro y los modelos de Piper que haya en
  `~/.local/share/cassette-dj/modelos/piper/`, cada una con su alias al lado si tiene. En Kokoro, la primera letra del
  nombre es el idioma de la voz (`a` inglés de EE. UU., `b` británico, `e` español, `f` francés, `h` hindi, `i` italiano,
  `j` japonés, `p` portugués de Brasil, `z` chino) y la segunda el género (`f` mujer, `m` hombre).
- Para sumar una voz de Piper, bajá su modelo a esa carpeta (las voces están en
  [rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices)):
  `.venv/bin/python -m piper.download_voices --download-dir ~/.local/share/cassette-dj/modelos/piper es_MX-claude-high`.
- Para **escuchar una voz antes de elegirla**:
  - `cassette-dj voz-prueba --voz daniela` vuelve a decir los últimos guiones con esa voz.
  - `mpv $(cassette-dj muestra --voz daniela --idioma es --radio "Sing")` le hace decir «Hola, soy daniela y estás
    escuchando Sing» (la pide al servicio y la guarda; es lo que suena con ▶ en el modal de emisora nueva del applet).
- Después de tocar `[voces]`: `systemctl --user restart cassette-dj` (el servicio lee los alias al arrancar).

**2. Usarlos en las emisoras**, en el `"dj"` de cada una en `estaciones.json`; la `velocidad` es opcional:

```json
{"nombre": "Synthwave F.M.", "fuente": {"spotify": "…"}, "dj": {"idioma": "es", "voz": "daniela", "velocidad": 0.9}}
```

Y, si querés, la voz de las emisoras que no tengan una propia, en `[dj]` del `config.toml` de la radio: `voz = "heart"`.
Después de tocar `estaciones.json` alcanza con `cassette rescan`.

Si una emisora usa un alias que no existe, sus intervenciones fallan (queda en `cassette-dj guiones` y en el log del
servicio) y la música sigue sin voz: revisá que el alias esté escrito igual en los dos archivos.

### Pronunciación de nombres propios

El idioma con que se pronuncia cada nombre propio («Daddy Yankee» en inglés, aunque la frase sea en español) y cómo
escribirlo para que la voz lo diga bien se configuran en `~/.config/cassette-dj/lexico.toml`:

```toml
[idiomas]
"Daddy Yankee" = "en-us"

[pronunciacion]          # cómo escribir un nombre para que la voz lo diga bien (se busca sin mayúsculas ni acentos)
"Regueton 2000" = "Reguetón 2000"
```

### Hechos reales en las frases

El servicio junta datos **verificados** y los mezcla en las frases; si no hay un dato confiable, no lo dice:

- **Clima** (open-meteo, sin clave): temperatura y cielo, dichos en palabras.
- **Datos del tema y del artista** (MusicBrainz): año de lanzamiento (el más antiguo entre las grabaciones que coinciden
  exacto en título y artista), país del artista y, si es una banda, cuándo empezó. No se usa nada si hay dos artistas con
  el mismo nombre o si el dato no es coherente. Todo queda en una caché SQLite
  (`~/.local/state/cassette-dj/hechos.sqlite`), también lo que no se encontró.

Cada frase combina de 1 a 3 ingredientes (el tema siempre; emisora, hora, momento del día o día de la semana, álbum, tema
anterior, clima y dato, de a uno por vez). El peso de cada uno se puede cambiar:

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

Otras claves (con su valor por defecto): `timeout_hechos_segundos = 10`, `cache_clima_minutos = 15`,
`cache_datos_dias = 90`, `cache_sin_dato_dias = 14`, `cache_error_minutos = 10`, `musicbrainz_url` y `open_meteo_url`.

`cassette-dj hechos` muestra el clima de ahora y `cassette-dj hechos --artista "a-ha" --titulo "Take On Me"` los datos
que se usarían.

### Guiones y pruebas de voz

Todo lo que el DJ dice queda en `~/.local/state/cassette-dj/guiones.jsonl`, sin borrarse nunca. Cada frase anota qué
hechos usó y de qué fuente. `cassette-dj guiones` los lista, y `cassette-dj voz-prueba --voz daniela --voz em_alex`
vuelve a sintetizar los últimos guiones **tal cual** con las voces que le pases (también acepta mezclas,
`em_santa+em_alex`), para comparar voces con las mismas frases.

### Comandos de `cassette-dj`

| Comando | Qué hace |
|---|---|
| `cassette-dj serve` | levanta el servicio a mano |
| `cassette-dj modelos` | baja los modelos de Kokoro que falten |
| `cassette-dj voces` | lista los alias y las voces disponibles |
| `cassette-dj guiones` | muestra los últimos guiones |
| `cassette-dj voz-prueba --voz …` | vuelve a sintetizar los últimos guiones con otras voces |
| `cassette-dj muestra --voz … --idioma … --radio …` | la frase de muestra de una voz: imprime la ruta del WAV |
| `cassette-dj modo [llm\|plantillas]` | muestra o cambia el modo de redacción |
| `cassette-dj llm estado` / `modelo` | estado del servidor de LLM / imprime el modelo configurado |
| `cassette-dj hechos [--artista … --titulo …]` | el clima de ahora y los datos de un tema |

### Contrato HTTP

JSON UTF-8. Todo viaja en el pedido: el servicio no guarda estado entre pedidos.

| Método y ruta | Qué hace |
|---|---|
| `POST /intervenciones` | encola un pedido; `202 {"id"}`; `400` si es inválido; repetir el `id` no lo vuelve a encolar |
| `GET /intervenciones/<id>` | `{"estado": "pendiente\|trabajando\|listo\|error\|cancelado", "duracion", "texto", "ingredientes", "error"}` |
| `GET /intervenciones/<id>/audio` | el WAV, cuando está `listo` (`409` si todavía no) |
| `DELETE /intervenciones/<id>` | cancela si todavía no empezó: `{"cancelado": true\|false}` |
| `POST /muestra` | la muestra de una voz (la que suena con ▶ en el applet) |
| `GET /voces`, `GET /salud` | voces disponibles; estado del servicio (modelos que faltan, trabajos por estado) |

```bash
curl -s -X POST localhost:7720/intervenciones -d '{
  "id": "prueba1", "estacion": "Lentos", "idioma": "es", "voz": "daniela",
  "momento": "2026-11-13T21:47:00-03:00",
  "anterior": {"artista": "Whitesnake", "titulo": "Is This Love"},
  "siguiente": {"artista": "Foreigner", "titulo": "Waiting for a Girl Like You"}}'
curl -s localhost:7720/intervenciones/prueba1                       # estado y texto
curl -s localhost:7720/intervenciones/prueba1/audio -o prueba1.wav   # el clip
```

## Ensayar el DJ

`scripts/herramientas/ensayo-dj.py` prueba todas las emisoras sin esperar. Arma transiciones reales de la agenda de cada una (10 por
defecto), le manda al servicio DJ los mismos pedidos que armaría el planificador (voz, idioma y personalidad de cada
emisora) y muestra los guiones en vivo: hora en cian, frases del LLM en verde, descartados en rojo y plantillas en
amarillo. Al final resume por emisora y por motivo de descarte, y guarda todos los registros (prompt, crudo, hechos) en
`~/.local/state/cassette-dj/ensayos/`.

Opciones: `--canciones N`, `--estacion "Nombre"` (repetible), `--modo llm|plantillas`, `--margen SEGUNDOS` (cuánto tiempo
tiene el LLM para escribir, 300 por defecto), `--conservar-audio`, `--sin-color`. Los pedidos van de a uno (como el
planificador, que pasa los `recientes`) y los clips se borran al terminar cada uno.

## Cómo verificar que anda

1. `cassette dj estado` dice `servicio DJ: ok`.
2. Sintonizá una emisora y corré `cassette dj pedir --en 30`; escuchá la frase.
3. **Clip fijo** (sin servicio): `cassette dj probar --en 20` y comprobá que (a) la voz entra ~1 s después de que arranca el
   tema siguiente, con la música bajada; (b) si cambiás de emisora y volvés con la voz todavía sonando, retoma la frase en
   el punto que corresponde; (c) bajar el volumen a 0 la corta; (d) `cassette dj estado` informa el desfase.
4. **Con el LLM:** `cassette-dj llm estado`, `cassette dj modo llm` y `cassette dj pedir --en 180` en varias emisoras (con
   menos antelación el LLM no llega a tiempo y la frase sale por plantillas); mirá `cassette-dj guiones` y el
   `guiones.jsonl`; `cassette dj modo plantillas` para volver.
5. **Con datos reales:** `cassette-dj hechos --artista "a-ha" --titulo "Take On Me"` tiene que dar 1984, Noruega y grupo
   desde 1983. Para ver que aparezcan, subí temporalmente `clima` y `dato` a 1 en `[ingredientes]`, pedí varias
   intervenciones y volvé a los pesos de fábrica.
