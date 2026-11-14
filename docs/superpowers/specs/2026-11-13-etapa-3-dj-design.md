# Etapa 3: DJ con voz por estación — Diseño

> Fecha: 13/11/2026. Resultado del brainstorming de la Etapa 3. Complementa el diseño general
> ([`2026-11-13-cassette-fm-design.md`](2026-11-13-cassette-fm-design.md)) y se apoya en dos relevamientos:
> [`radio-dj.md`](../../relevamiento/radio-dj.md) (pruebas con un LLM local y voces) y
> [`texto-para-voz.md`](../../relevamiento/texto-para-voz.md) (cómo preparar el texto para Kokoro, con pruebas
> escuchadas por el usuario). Leer ambos antes de construir.

## Intención

Que cada estación tenga un **DJ** que habla de vez en cuando, como en una radio de verdad: no en todos los temas,
con una voz propia por estación, mencionando datos variados y verdaderos. El DJ nunca puede estorbar a la música ni
volver pesada la PC donde se escucha.

Lo que el usuario **no** quiere es un bot con un molde fijo ("son las X, estás escuchando Y de W" en cada entrada).
Quiere variedad: a veces la hora, a veces el clima, a veces un dato del tema o del artista, a veces un comentario de
clima emocional ("nos vamos relajando"). Tema y artista son casi indispensables; el nombre de la estación está bien
repetirlo; el clima es lo menos importante. Los datos no tienen que ser sorprendentes, pero **tienen que ser verdaderos**:
prefiere un dato verificado a uno inventado.

## Objetivos

- Intervenciones del DJ con una frecuencia **configurable** (por defecto cada 2 o 3 temas, unos 10 a 15 minutos), con una voz
  que se elige por estación.
- **Nada fijo en el código:** todo valor que pueda querer cambiarse (duración máxima de la voz, frecuencia, margen, nivel
  y rampas del ducking, pesos de los ingredientes, tiempos de espera) vive en la configuración, con un valor por defecto.
- Variedad real en el contenido: la selección de qué decir es al azar y ponderada, y evita repetir lo dicho hace poco.
- **Cero datos inventados.** Todo hecho que se dice sale de los tags, del reloj, del clima o de una fuente consultada
  (MusicBrainz, Wikipedia). El LLM redacta; nunca es la fuente de un hecho.
- La voz suena natural y bien pronunciada: nombres en otro idioma bien dichos, español rioplatense, sin pausas ni
  acentos raros (reglas de `texto-para-voz.md`).
- La parte pesada (datos, LLM, voz) corre en un **servicio aparte**, hoy en esta misma PC y mañana en otra más
  modesta, cambiando solo una dirección en la configuración.
- Cada hueco del DJ vive en la agenda de su estación: se escucha igual si el usuario cambia a esa estación mientras
  la intervención está sonando (entra a mitad de la frase).

## No objetivos

- DJ sobre estaciones de Spotify (Etapa 4) ni pedidos de temas (Etapa 7).
- Voz en tiempo real o en streaming: se genera el clip completo con antelación.
- Autenticación o multiusuario del servicio DJ. Es para una red doméstica de confianza.
- Que el DJ conozca el catálogo de música "de memoria": no se le pide ningún dato al LLM.
- Cambiar la agenda de temas: sigue siendo una función pura y determinista.

## Anti-objetivos (cosas que lo harían fracasar aunque funcione)

- **Que la música se demore, se corte o espere al DJ.** Si una intervención no está lista a tiempo, simplemente no suena.
- Que diga un dato falso con total seguridad.
- Que se sienta repetitivo o calcado (siempre la misma estructura o los mismos ingredientes).
- Que consuma recursos notorios en la PC del oyente mientras no hay nada que preparar, o que el DJ trabaje para
  estaciones que nadie escucha, salvo terminar lo que ya empezó.
- Que una intervención vieja suene a destiempo.

## Restricciones

- Linux Mint 22.1 Cinnamon, Ryzen 5 5600G, 13 GB de RAM (la PC del oyente). **No hay ffmpeg**: no depender de él.
- **Máquina futura del servicio DJ:** unos 8 GB de RAM DDR3 y un procesador de potencia similar o menor, **solo CPU**,
  compartida con otros servicios. El diseño tiene que entrar ahí.
- Python 3.12. El servicio DJ tiene dependencias propias (`kokoro-onnx`, `soundfile`, `numpy`) que no deben pesar en la
  instalación de la radio: van en un extra opcional (`[dj]`) del mismo paquete, con su propio comando (`cassette-dj`).
- MusicBrainz: ~1 pedido por segundo por IP y un `User-Agent` con un dato de contacto.
- Kokoro: ~326 MB de modelo; ~3 s para sintetizar ~9 s de audio en esta CPU (relevamiento).
- Git solo local, commits en español; desarrollo con TDD.

## Enfoques considerados

| Enfoque | Qué es | Contras |
|---|---|---|
| **A. Servicio DJ que la radio llama** (elegido) | La radio decide cuándo y para qué estación, mantiene la cola de un trabajo a la vez y reserva el hueco en la agenda. Al servicio DJ le manda los datos básicos de los temas, la voz, el idioma y qué se dijo hace poco; el servicio busca los datos, redacta, genera la voz y devuelve el audio. | El planificador vive en la radio (poca lógica, liviana). |
| B. Todo dentro del proceso de la radio | El LLM va por red, pero la voz y los datos corren en la PC del oyente. | Kokoro queda cargado en la PC del oyente; mover el DJ después obliga a reescribir. |
| C. DJ como demonio que consulta y empuja a la API de la radio | Separación total entre radio y DJ. | Para usarlo desde otra máquina hay que **exponer la API de la radio en la red**, justo lo que se quería evitar; y exige endpoints nuevos. |

Se eligió **A**. La PC del oyente solo hace pedidos hacia afuera (no abre puertos); el servicio no guarda estado entre
pedidos, así que puede atender a varios clientes de radio con agendas distintas (hoy no se prueba ni se prepara más
que eso); y dos dispositivos en la misma radio se resuelven "retransmitiendo" el servicio de radio (Etapa 6) sin tocar
el DJ.

## Arquitectura

```
 PC del oyente (radio)                          servicio DJ (hoy: esta misma PC)
 ├─ agenda de temas (pura, sin cambios)  ────►  POST /intervenciones
 ├─ planificador + cola (1 trabajo)             ├─ hechos: tags, hora, clima, MusicBrainz → Wikipedia (con caché)
 ├─ capa de intervenciones (por estación) ◄───  ├─ LLM redacta (solo con esos hechos) + verificación
 └─ 2º mpv para la voz + bajar la música        └─ texto para voz + Kokoro → clip de audio
```

### Capa de intervenciones (en la radio)

Una segunda capa sobre la agenda de cada estación. **No altera** la agenda de temas.

```python
@dataclass(frozen=True)
class Intervencion:
    estacion: str
    inicio: float        # epoch: cuándo empieza a sonar la voz
    duracion: float      # segundos
    audio: Path          # clip WAV en el caché
    texto: str           # lo que dice (para el registro)
```

- Se registra cuando el clip está listo. El hueco (`inicio`) se eligió **antes** de pedir el clip y se reserva para que
  dos intervenciones de una misma estación no se pisen (separación mínima configurable, por defecto igual al mínimo de la frecuencia).
- Persisten en `~/.local/state/cassette-fm/intervenciones.json`; los clips en `~/.cache/cassette-fm/dj/`. Se descartan
  las que ya terminaron y sus archivos.
- Si el usuario está en esa estación y el instante cae dentro de `[inicio, inicio+duracion)`, la voz suena **desde el
  segundo que corresponda** (entra a mitad de frase). Si quedan menos de 1,5 s, no suena.
- Una intervención reservada para la estación A suena aunque el usuario haya estado en B hasta un segundo antes.

### Reproducción de la voz y música bajada

- Un **segundo proceso mpv** (solo voz, idle, `--no-config`, sin video) reproduce el clip, con `start` = el segundo de
  entrada. No se usa ffmpeg ni compresión por sidechain.
- **Ducking:** se baja el volumen de la música con una rampa corta antes de la voz (~0,4 s) y se restaura con otra más
  lenta al terminar (~1 s), hasta `nivel_musica_con_voz` (por defecto 0,6 desde el 14/11; la escala de volumen de mpv es cúbica, así que 0,35 dejaba la música ~28 dB abajo, casi muda) del volumen del usuario; los tiempos de las rampas también son
  configurables (`rampa_bajada_segundos` 0,4 y `rampa_subida_segundos` 1). El volumen que el usuario fija con `cassette vol` o
  las teclas sigue valiendo durante y después del ducking, y el volumen 0 (radio apagada) corta la voz también. Cómo
  se implementa la rampa (propiedad `volume` o `volume-gain` de mpv) queda a criterio de quien construye, con esa
  restricción de comportamiento.
- La voz empieza **`retraso_voz_segundos` (por defecto 1 s) después del comienzo del tema siguiente** (arriba del
  arranque del tema) y dura como máximo **`duracion_maxima_segundos` (por defecto 15 s)**. El texto que se le pide al
  LLM se limita en proporción (`palabras_maximas`, por defecto ~45); si el clip generado igual excede la duración
  máxima, se descarta y se usa la plantilla.
- **Quién manda, el reloj o mpv:** las duraciones de la agenda salen de mutagen y pueden diferir de las que mide mpv
  (sobre todo en MP3 VBR), y el reproductor no resincroniza, así que con una escucha larga la música real se corre un
  poco respecto del reloj. Por eso, **estando sintonizada la estación, la voz se dispara por el inicio real del tema en
  mpv** (el evento `start-file` del tema que la agenda marcó como destino). El reloj se usa solo para: (1) elegir y
  reservar la transición (por posición en la agenda, no por segundos), y (2) **entrar a mitad de frase** al sintonizar,
  momento en que la música también se realinea con el reloj (se vuelve a cargar desde la agenda). No se resincroniza la
  música durante una escucha continua (evita saltos audibles y no toca la Etapa 1). Si el desfase medido en un cambio
  de tema supera 5 s, se registra en el log. La parte 1 mide el desfase real con la biblioteca del usuario.
- Cambiar de estación, apagar la radio o llegar al final corta la voz y restaura la música.

### Planificador y cola (en la radio)

- **Un solo trabajo a la vez** (cola FIFO de un trabajador). Un trabajo ya iniciado **siempre termina**, aunque el
  usuario cambie de estación. **"Iniciado" significa que la radio ya hizo el `POST`** al servicio. Antes de eso, la
  radio guarda **como máximo un pedido pendiente**, el de la estación sintonizada, que **se reemplaza** al cambiar de
  estación: saltar de A a B, C y D deja un solo trabajo en curso y, a lo sumo, un pendiente para la estación final.
  Los trabajos en curso se guardan (id, estación, hueco) en el estado; si la radio se reinicia, retoma el resultado por
  `id` (los pedidos son idempotentes) y lo descarta si su hueco ya pasó. `DELETE` se usa solo para cancelar un trabajo
  que el servicio todavía no empezó, p. ej. al apagar la radio.
- Solo se planifican intervenciones para la **estación sintonizada** (nada para estaciones que nadie escucha, salvo
  terminar lo ya iniciado). Con la radio apagada no se planifica.
- Para la estación sintonizada, si no hay una intervención pendiente o lista en el futuro y pasó la separación mínima
  desde la última, se elige la próxima transición entre temas que cumpla: (a) empieza al menos `margen` en el futuro
  (por defecto 6 minutos, para dar tiempo a generar; configurable) y (b) cumple la **frecuencia configurada**: o bien
  entre `min` y `max` **temas** después de la última intervención de esa estación (por defecto 2 y 3), o bien entre
  `min` y `max` **minutos** (modo por tiempo); el valor exacto se sortea dentro del rango. Esa transición fija
  `inicio`. Si ni la del tema 2 ni la
  del 3 respetan el `margen`, se toma la **primera transición posterior que sí lo respete**, aunque quede a más de 3
  temas. Si un `rescan` cambia la agenda de una estación, se descartan sus reservas.
- Al cambiar a otra estación B: si B no tiene intervención reservada en el futuro, se encola una para B detrás del
  trabajo en curso.
- Si el clip no está listo para cuando termina su ventana, se descarta. **La música nunca espera.**
- Los datos de MusicBrainz y Wikipedia de los temas por venir los pide el servicio DJ cuando le llega el pedido; la caché
  hace que cada tema se consulte una sola vez.

### Servicio DJ (HTTP)

Asíncrono, porque el LLM puede tardar minutos. El cuerpo es JSON UTF-8.

`POST /intervenciones` →

```json
{
  "id": "<uuid generado por el cliente>",
  "estacion": "Lentos",
  "idioma": "es",
  "voz": "em_santa",
  "personalidad": "texto libre opcional con el tono de la estación",
  "momento": "2026-11-13T21:47:00-03:00",
  "anterior": {"artista": "...", "titulo": "...", "album": "...", "isrc": "..."},
  "siguiente": {"artista": "...", "titulo": "...", "album": "...", "isrc": "..."},
  "recientes": ["hora", "dato_cancion", "clima"]
}
```

`recientes` son los ingredientes usados en las últimas intervenciones de esa estación (el servicio no guarda
estado entre pedidos; el cliente lo lleva). Responde `202 {"id": ...}`.

`GET /intervenciones/<id>` → `{"estado": "pendiente|trabajando|listo|error", "duracion": 11.4, "texto": "...",
"ingredientes": ["cancion", "hora"], "error": null}`. `GET /intervenciones/<id>/audio` → el WAV.
`DELETE /intervenciones/<id>` cancela si todavía no empezó. Un pedido repetido con el mismo `id` es idempotente.

- Un trabajador por defecto (configurable); los pedidos esperan en orden de llegada.
- **Cómo corre:** como servicio de usuario de systemd (`cassette-dj`), instalado **aparte** de la radio con
  `scripts/instalar-dj.sh` (`instalar-todo.sh` no lo instala: el DJ viene apagado). Con `activo = false` en la radio
  no se hace ningún pedido.
- **Memoria en reposo:** Kokoro se carga **al llegar un pedido** y se descarga tras un rato sin trabajo
  (`descargar_tras_minutos`, por defecto 5). El servidor de LLM (Ollama) se configura con su propio `keep_alive`.
  Nada de esto ocupa memoria mientras no haya nada que preparar.
- Si el servicio no responde, la radio sigue funcionando en silencio, reintenta con espera creciente y registra el
  problema una sola vez por episodio.

## Contenido de una intervención

### Ingredientes y frecuencia

El **programa** elige los ingredientes (al azar, ponderado, sin repetir los de `recientes`) y le pasa al LLM solo hechos
verificados. Cada intervención combina 1 a 3 ingredientes.

| Ingrediente | Fuente | Frecuencia |
|---|---|---|
| Tema y artista | tags | casi siempre |
| Nombre de la estación | carpeta | seguido |
| Hora ("pasadas las nueve", "diez menos diez") | reloj, `America/Argentina/Buenos_Aires` | a veces |
| Momento del día o de la semana | reloj | a veces |
| Álbum | tags (~60 % de los temas) | a veces |
| Del tema anterior al siguiente | agenda | a veces |
| Clima de Buenos Aires (−34,6037; −58,3816) | open-meteo, sin clave | rara vez |
| Comentario de clima emocional ("nos vamos relajando") | LLM, sin hechos nuevos | de vez en cuando |
| Dato del tema, álbum o artista | MusicBrainz → Wikipedia | de vez en cuando, si hay |

Los pesos y las separaciones mínimas son configurables; los iniciales son los de la tabla. La biblioteca actual no
trae año ni género en los tags.

### Datos verificados (MusicBrainz → Wikipedia)

> Parte 3: pasos 1, 2 y 5 (MusicBrainz y caché). Pasos 3, 4 y 6 (Wikipedia/Wikidata y la frase extraída) → parte 4.
> Hallazgos del 14/11 con la API real: la biblioteca no trae ISRC (0 de 395 temas), así que se identifica por
> artista + título; la búsqueda devuelve muchas grabaciones del mismo tema (vivos, recopilaciones) con
> `first-release-date` distintas, por eso el **año del tema es el mínimo** entre las que coinciden exactamente en título
> y artista ("Take On Me" de a-ha: 1984); el comienzo del artista solo se usa si es un grupo (en una persona
> `life-span.begin` es el nacimiento); los guiones de MusicBrainz (a‐ha usa U+2010) se normalizan al comparar.

1. **Identificar el tema:** por ISRC si lo hay; si no, por artista + título (+ álbum) en MusicBrainz, **exigiendo que
   el artista coincida**. Si hay más de un candidato y no se puede desempatar, **no se usa ningún dato** (ejemplo
   real: el "True" de Spandau Ballet no es el EP "True" de Solange).
2. **Datos de MusicBrainz:** año de lanzamiento, álbum, país y fecha de inicio del artista, tipo y orden de sus
   discos ("es su primer disco").
3. **Dato de Wikipedia:** MusicBrainz enlaza a Wikidata y Wikidata da el título del artículo en cada idioma; el
   resumen se pide a la API de Wikipedia (se prefiere el idioma de la estación y, si no existe, el inglés). Se
   comprobó con un caso real (MusicBrainz → Wikidata → Wikipedia en inglés y español).
4. **El LLM extrae del texto una frase corta** (hasta ~25 palabras) y se le ordena no agregar nada que no esté en él.
5. **Todo se guarda en caché persistente (SQLite), incluido "no se encontró"**. Los datos de MusicBrainz y Wikipedia no
   se piden en el momento de hablar si ya están.
6. El texto de Wikipedia es CC BY-SA: se conserva la URL de origen en el registro de cada intervención.
7. "Cuánto vendió" **no** está en MusicBrainz; no se promete como ingrediente. Si aparece en un resumen de Wikipedia,
   puede usarse como cualquier otro dato del texto.

### Verificación del texto generado

Antes de aceptar la frase del LLM: todo número, año o nombre propio que contenga debe estar entre los hechos que se le
pasaron (o en el conjunto permitido: tema, artista, estación, hora, clima). Si no, se descarta y se usa la frase de
plantilla. Es una comprobación liviana, no una garantía total.

### Si el LLM falla o tarda demasiado

Hay un respaldo por **plantillas** (variadas, con tema/artista/estación y a veces hora), que se usa si el LLM da error,
se pasa del tiempo (`timeout` configurable, por defecto 4 minutos) o su frase no pasa la verificación. Así siempre hay
intervención.

### LLM

El servicio habla con cualquier servidor **compatible con la API de OpenAI** (Ollama sirve): la dirección y el modelo
son configuración. El plan de pruebas es un modelo de **7 a 8 mil millones de parámetros cuantizado (Q4)**, que debería
entrar en 8 GB junto a Kokoro (unos 4,5 a 5 GB + ~0,4 GB) y tardar de 30 a 60 s por frase en esa máquina; hay que
medirlo ahí. Con 10 a 15 minutos entre apariciones la latencia no importa. **Cómo se instala y se corre el servidor de LLM** (Ollama
nativo o en Docker, y en qué máquina) **lo decide el usuario al llegar a la parte 4**; las partes 1 a 3 no necesitan LLM.
La parte 4 se cierra con mediciones en esta PC; validar los tiempos en la máquina de 8 GB es un paso posterior que no
bloquea.

## Texto para voz

Capa propia entre el texto del LLM y Kokoro, con las reglas de [`texto-para-voz.md`](../../relevamiento/texto-para-voz.md):

1. Se fonemiza **por tramos y por idioma** (los nombres propios con su idioma; el resto con el de la voz) y se le pasa a
   Kokoro con `is_phonemes=True`.
2. Español: `θ` → `s` en los fonemas (seseo rioplatense).
3. Sin `¡ ! ¿`; pocas comas.
4. **Ninguna oración corta suelta**: las de pocas palabras se unen a la anterior con un conector, y el prompt del LLM
   pide frases largas.
5. Las mayúsculas no importan.
6. **Idioma de cada nombre:** un **léxico editable** (`lexico.toml`: nombre → idioma) con "Daddy Yankee" en inglés,
   etc. Lo que no esté en el léxico se asume del idioma de la estación. Cómo reconocer los nombres dentro de la frase
   queda a criterio de quien construye (por ejemplo, buscar los nombres conocidos del tema, artista y álbum del propio
   pedido).

Voces: el usuario eligió **algunas para empezar** (Kokoro: español `em_santa`; inglés `am_michael` y `af_heart`), pero
**no son una lista cerrada**: la voz es un dato de cada estación y se elige al crearla o configurarla. El servicio debe
aceptar cualquier voz que ofrezca el modelo y poder listar las disponibles.

## Configuración

En `config.toml` de la radio (todo opcional; **el DJ viene apagado**). Los valores de abajo son los **por defecto**; todos
se pueden cambiar, y los de la estación pisan a los generales:

```toml
[dj]
activo = false
url = ""                              # el servicio DJ (p. ej. "http://127.0.0.1:7720"); vacío = sin planificador
margen_minutos = 6                      # antelación mínima para planificar
duracion_maxima_segundos = 15           # tope de la voz
palabras_maximas = 45
retraso_voz_segundos = 1                # después del comienzo del tema
nivel_musica_con_voz = 0.6              # ducking (escala cúbica de mpv: 0.6 ≈ -13 dB)
rampa_bajada_segundos = 0.4
rampa_subida_segundos = 1.0

[dj.frecuencia]                         # modo = "temas" | "minutos"
modo = "temas"
min = 2
max = 3

[dj.estaciones."Lentos"]                # una tabla por estación; lo que falte usa los valores generales
voz = "am_michael"
idioma = "en"
personalidad = "baladas de los 80, tono cálido y tranquilo"
frecuencia = { modo = "minutos", min = 8, max = 15 }   # opcional
```

El servicio DJ tiene su propia configuración (`~/.config/cassette-dj/config.toml`): dirección del LLM y modelo,
trabajadores, ruta de modelos de Kokoro, contacto para el `User-Agent` de MusicBrainz, pesos de ingredientes.

## Cómo se construye (en partes audibles; cada una se prueba sola)

1. **Radio: capa de intervenciones + segundo mpv + música bajada**, con clips de prueba fijos. Incluye entrar a mitad de
   frase y un comando de desarrollo (`cassette dj probar`) que registra un clip de prueba en el próximo hueco.
2. **Servicio DJ: cola, contrato HTTP, texto para voz y Kokoro**, con frases armadas por plantillas; y en la radio el
   planificador, la cola de un trabajo y el cliente HTTP. Queda funcionando de punta a punta (con plantillas).
3. **Hechos reales:** hora, clima, MusicBrainz (año del tema, país y comienzo del artista), caché y el selector de ingredientes, con plantillas que usan esos datos. *(Acordado el 14/11: Wikipedia, Wikidata y la frase extraída pasan a la parte 4, donde el LLM las usa.)*
4. **LLM redactor**, con verificación del texto, respaldo por plantillas y pruebas en la máquina de 8 GB.

Cada parte tendrá su plan de implementación. Los beans actuales de la Etapa 3 se reparten entre estas partes.

## Decisiones del usuario

- Arquitectura A (servicio DJ que la radio llama); el servicio no guarda estado entre pedidos.
- Cada intervención reserva su hueco en la agenda al generarse; entrar a mitad de frase está bien.
- Un solo trabajo a la vez; el ya iniciado termina; se prepara para la estación sintonizada.
- Datos verificados (MusicBrainz, Wikipedia) en vez de inventados; sin dato, el DJ dice lo básico.
- Variedad de ingredientes y frecuencias como en la tabla; una intervención cada 2 o 3 temas.
- Voces de ejemplo del relevamiento para empezar (la voz se elige por estación, sin lista cerrada); reglas de texto para
  voz de `texto-para-voz.md` (seseo, sin signos de pausa, nada de oraciones cortas, fonemas por idioma).
- Duración máxima de la voz, frecuencia y demás parámetros: **configurables en archivo, nunca fijos en el código**; la
  frecuencia se puede dar por cantidad de temas o por tiempo.
- El LLM puede correr en esta PC y después en otra de 8 GB solo CPU; la latencia no importa.

## Decisiones tomadas en el diseño (a revisar por el usuario)

- **La voz va arriba del comienzo del tema siguiente**, ~1 s después de que arranca, no antes ni en un hueco aparte.
- Ducking a 35 % con rampas de 0,4 s y 1 s (valores por defecto, configurables), sin ffmpeg, con un segundo mpv para la voz.
- `margen` de 6 minutos de antelación mínima y duración máxima de 15 s (~45 palabras) como **valores por defecto
  configurables**.
- Contrato HTTP asíncrono con `recientes` llevado por el cliente.
- El DJ viene **apagado** por defecto y se configura por estación.
- Plantillas como respaldo cuando el LLM falla, tarda o no pasa la verificación.
- Extra opcional `[dj]` y comando `cassette-dj` en el mismo paquete.
- Léxico editable para el idioma de los nombres propios.
- WAV como formato del clip (~0,5 MB por 10 s).
- **La voz se ancla al inicio real del tema en mpv**, no al reloj (ver arriba); el reloj solo reserva el hueco y sirve
  para entrar a mitad de frase.
- "Iniciado" = ya se hizo el `POST`; un pendiente por vez para la estación sintonizada, que se reemplaza al cambiar.
- Kokoro se carga a demanda y se descarga tras 5 minutos ociosos; el DJ se instala aparte con `scripts/instalar-dj.sh`.
- Las reservas se descartan si un `rescan` cambia la agenda; si ninguna transición candidata respeta el margen, se toma la
  primera posterior que lo respete.
- Un plan por parte: ahora se planifica **solo la parte 1**; las demás se planifican cuando se llegue a ellas, con lo
  aprendido (por ejemplo el desfase medido).

## Evolución prevista: estaciones como objetos (fuera de esta fase)

Hoy una estación es una subcarpeta de `~/Música`. **A futuro** el usuario quiere que las estaciones sean **objetos en un
JSON** (nombre, fuente, voz, idioma, personalidad, frecuencia del DJ, etc.), de modo que puedan apuntar a una carpeta
en cualquier lugar o a una playlist de Spotify, y que la voz se elija al crearlas (ver
[`CASSETTE-FM-40h0`](../../../.beans) y la sección homónima del [diseño general](2026-11-13-cassette-fm-design.md)).
**No entra en la Etapa 3**, pero el DJ no debe cerrarle la puerta:

- La configuración del DJ de una estación se lee a través de una sola función (`configuracion_dj(nombre_estacion)`), de
  modo que mañana su fuente sea el objeto de la estación y no la tabla `[dj.estaciones."..."]` de `config.toml`.
- Nada del DJ depende de que la estación sea una carpeta: solo necesita su nombre, sus temas (artista, título, álbum,
  `isrc`) y su agenda.

## Queda a criterio del que construye

- Estructura de módulos, framework HTTP del servicio DJ (se prefiere la biblioteca estándar o algo liviano).
- Cómo reconocer los nombres propios dentro de la frase para el idioma por tramo.
- Cómo se hace la rampa del ducking en mpv.
- Formato del caché SQLite y política de limpieza.
- El texto de los prompts del LLM y de las plantillas (con las reglas de arriba: frases largas, sin molde fijo).
- Cómo se descubre el `ISRC` y qué hacer con los temas locales que no lo tienen (solo artista + título).
- Tests: TDD, con el LLM, MusicBrainz, Wikipedia y open-meteo simulados; las pruebas con servicios reales, a mano.

## Pendiente de probar fuera del código

- Elegir el modelo de LLM definitivo midiendo en la máquina de 8 GB.
- Probar más nombres reales de la biblioteca con el léxico de idiomas.
- Rehilamiento rioplatense de `y` y `ll` en la voz (no se probó).
- Dato de contacto para el `User-Agent` de MusicBrainz (lo pone el usuario en la configuración del servicio).


## Parte 4: decisiones del 14/11

- **Servidor de LLM:** Ollama dentro de **Docker** (`ollama/ollama`), con los modelos en `~/.local/share/cassette-dj/ollama`,
  escuchando solo en `127.0.0.1:11434`; la radio y el servicio DJ lo ven por la API compatible con OpenAI
  (`http://127.0.0.1:11434/v1`). Modelo inicial de **4 mil millones de parámetros** (`gemma3:4b`, configurable; se prueba
  con frases reales y, si se queda corto, se pasa a uno de 8 mil millones). La máquina tiene 13 GB de RAM y no tiene GPU.
- **Modo del DJ:** el servicio tiene un **modo** `plantillas` | `llm`. **Por defecto siempre `plantillas`**: arranca así
  salvo que la configuración diga otra cosa (`modo = "llm"`), y el cambio en caliente **no se guarda** (al reiniciar el
  servicio vuelve al de la configuración). Se cambia con `cassette dj modo llm|plantillas` (en la radio, que se lo pide
  al servicio) o `cassette-dj modo llm|plantillas`; sin argumento muestran el modo actual. Con el modo `llm` el servicio
  además pide **Wikipedia** (MusicBrainz → Wikidata → Wikipedia, solo el artista) y se la da al LLM junto con los hechos
  que ya junta; con `plantillas` no hace pedidos a Wikipedia ni al LLM.
- Si el LLM falla, tarda más que `llm_timeout_segundos` o su frase no pasa la verificación, esa frase sale por plantillas
  y el guion lo anota (`fuente: "plantilla"`, `motivo`). **Todo guion generado por el LLM se registra con el texto crudo
  y el prompt**, para reusarlo en las pruebas de voz.
