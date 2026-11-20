# La voz del DJ entre dos temas — Diseño

> Fecha: 20/11/2026. Resultado del brainstorming con el usuario. Parte del diseño del DJ
> ([`2026-11-13-etapa-3-dj-design.md`](2026-11-13-etapa-3-dj-design.md)) y toca lo que dejaron las peticiones
> ([`2026-11-15-peticiones-spotify-design.md`](2026-11-15-peticiones-spotify-design.md)).

## Intención

Hoy el DJ habla siempre **después** de que arranca el tema nuevo (1 s después), y dice "ahora suena…". En una radio
de verdad el locutor empieza a hablar sobre la cola del tema que termina y sigue hablando cuando entra el siguiente:
la voz **tapa el empalme** y la transición entre canciones se siente natural. Eso es lo que se quiere: que pasar de un
tema a otro suene a radio, no a "se cortó la música y habló un robot".

La voz se ancla al **corte** entre dos temas, no al arranque del tema nuevo. Cada intervención cae en una de tres
posiciones respecto del corte, y lo que dice el DJ se adapta a esa posición (si la voz termina antes de que empiece el
tema nuevo no puede decir "ahora suena").

## Objetivos

- Tres posiciones de la voz respecto del corte: **`inicio`** (toda después del corte, como hoy), **`entre`** (el
  corte cae dentro de la voz) y **`final`** (la voz termina justo antes del corte, sobre el final del tema que termina).
- Una configuración `posicion_voz` con esos tres valores más **`mixto`**: en cada intervención se sortea una de las tres
  (con la misma probabilidad), para que a veces caiga más hacia el final de un tema, a veces más al principio del
  siguiente y a veces bien en el medio. Por defecto: `mixto`. Se puede pisar por emisora.
- Textos adaptados a la posición, en plantillas y en el LLM, en español y en inglés. Las frases de plantilla se
  **clasifican** por lo que pueden decir en cada posición, y se agregan las que falten.
- Que funcione igual en las emisoras locales (mpv) y en las de Spotify (Soloist), y con las peticiones (anuncios
  "antes", "después" y "seguidas").

## No objetivos

- **Crossfade entre temas.** Es un ajuste de Spotify (probablemente de la cuenta) y para lo local habría que
  construirlo; queda para después. Mientras tanto el empalme entre temas sigue siendo el de hoy, ahora tapado por la voz.
  Cuando se active el fundido cruzado de Spotify habrá que revisar dónde cae el corte real (ver Riesgos).
- Que una palabra concreta caiga en un instante concreto (p. ej. que el título del tema nuevo caiga justo en el
  corte). No hace falta; ver "Posibles mejoras".
- Controlar la posición desde la línea de comando o el applet: alcanza con `config.toml` y `estaciones.json`.
- Pesos configurables para `mixto`: las tres posiciones valen lo mismo.

## Anti-objetivos (lo harían fracasar aunque funcione)

- Que el DJ diga "ahora suena X" mientras todavía suena el tema anterior (o "recién sonó Y" cuando Y sigue sonando).
- Que una voz anclada al final de un tema suene en un momento equivocado porque el tema se saltó, se cambió de emisora
  o se sintonizó a mitad de tema.
- Que la música se demore o se corte por esperar a la voz (anti-objetivo del diseño original, sigue vigente).
- Que los textos se vuelvan repetitivos porque algún caso tiene una sola frase.

## Restricciones

- No hay ffmpeg. Un solo reloj de verdad: el de la agenda; la radio corrige con el desfase medido en cada arranque de
  tema (`agenda.desfase`), que ya existe.
- Todo valor que se pueda querer cambiar va en la configuración con un valor por defecto (regla del DJ).
- El servicio DJ puede correr en otra máquina y ser más viejo o más nuevo que la radio: el campo nuevo del pedido es
  opcional y vale `inicio` si falta.
- TDD, commits en español, git local.

## Enfoques considerados (cómo disparar la voz antes del corte)

| | Qué es | Veredicto |
|---|---|---|
| **A. Temporizador desde el arranque del tema de origen** | Cuando empieza el tema A (el que termina), el locutor arma un temporizador que dispara la voz cuando falte lo que corresponda para el corte. Mismo patrón que el anclaje actual, solo que apunta al tema anterior. | **Elegido por el usuario.** Spotify tiene la duración exacta; en lo local la de `mutagen` puede errar unos segundos con MP3 VBR, y como la posición ya es aproximada no se nota. |
| B. Observar el tiempo restante en el reproductor | Disparar cuando mpv o Soloist informen que faltan X segundos. | Más exacto, pero hay que sumarle esa información a los dos reproductores y a sus pruebas. Descartado por ahora. |

## Diseño

### Vocabulario

- **Corte**: el instante (epoch) en que termina el tema de origen y empieza el de destino. Se conoce por la agenda.
- **Origen** / **destino**: el tema que termina y el que arranca en el corte. Hoy la intervención solo conoce el
  destino (`pista_destino`).
- **Adelanto**: cuántos segundos antes del corte empieza la voz (negativo o cero en `inicio`: la voz empieza después).

### Qué decide cada pieza

**El planificador** ([planificador.py](../../../src/cassette_fm/planificador.py), [planificacion.py](../../../src/cassette_fm/planificacion.py))

1. Al elegir el hueco (`elegir_hueco`) guarda el **corte** (hoy `inicio_tema`) y el tema de **origen** (hoy
   `Hueco.anterior`, que ya se calcula, pero la clave hay que conservarla aunque el tema no tenga nombre: solo la frase
   de cierre depende del nombre).
2. Sortea la **posición** (`inicio`/`entre`/`final`) según `posicion_voz`, y se la manda al servicio DJ en el pedido
   (campo nuevo `posicion`). Si `posicion_voz` es `mixto`, es un sorteo uniforme de las tres.
3. El hueco ya no es "`inicio_tema + retraso`": para reservar lugar y para saber si el pedido "llegó tarde" se usa la
   ventana conservadora `[corte − duracion_maxima, corte + retraso + duracion_maxima]` (todavía no se sabe cuánto dura
   el clip). El `momento` del pedido (la hora que dice el DJ) es el corte; el error de unos segundos no importa porque
   la hora se redondea a 5 minutos.
4. Cuando el clip está listo (`_recibir`) y se conoce su duración `D`, calcula el **inicio** real de la voz:
   - `inicio`: `corte + retraso_voz_segundos` (como hoy).
   - `entre`: `corte − f·D`, con `f` sorteada entre `fraccion_entre` (por defecto 0,3 y 0,7).
   - `final`: la voz termina `m` segundos antes del corte (`m` sorteado en `final_antes_segundos`, por defecto 0 a 2):
     `corte − m − D`.
   - Antes de registrar se acota: el adelanto no puede pasar de la mitad de la duración del tema de origen, y en
     `entre` y `final`, si el inicio resultante ya pasó (o falta menos de 1 s), la intervención se descarta con un log
     (un texto pensado para sonar antes del corte no sirve después). `inicio` sigue como hoy.
5. Para las **peticiones** "antes", solo se sortea entre las posiciones que dejan tiempo de generar el clip: las que
   adelantan la voz (`entre` y `final`) requieren `corte − ahora ≥ peticion_margen_segundos + duracion_maxima_segundos`;
   si no, la posición es `inicio`. Los "después" y "seguidas" no tienen ese problema (su corte es el del tema que
   empieza justo cuando se planifica o más adelante).
6. Todo lo que hoy recupera el inicio del tema con `i.inicio − retraso_voz_segundos` (`_antes_reservado`,
   `_olvidar_anuncios`, `al_cambiar_agenda`) pasa a usar el **corte** guardado en la intervención.

**La intervención** ([intervenciones.py](../../../src/cassette_fm/intervenciones.py)): campos nuevos `corte` (epoch),
`pista_origen` (clave) y `posicion`. `inicio`, `fin` y `activa()` no cambian de significado (siguen siendo epoch de
la voz), así que el solape entre intervenciones, la entrada a mitad de frase al sintonizar y la limpieza de vencidas
funcionan sin tocarse. Las entradas persistidas sin estos campos se cargan como `inicio` (sin `corte`: se estima como
`inicio − retraso_voz_segundos`, que es lo que valía hasta ahora).

**El locutor** ([locutor.py](../../../src/cassette_fm/locutor.py)): `pista_iniciada(pista, estacion, desfase)` pasa a
recibir también el **desfase** medido en ese arranque (lo que ya calcula `Radio._medir_desfase`; 0 si no se conoce, p. ej.
en el primer tema tras sintonizar, que sale alineado con el reloj). Con eso, para cada intervención candidata:

- Si la voz empieza **después o en** el corte (`inicio ≥ corte`) y `pista` es el destino: igual que hoy, temporizador
  de `inicio − corte` desde este arranque.
- Si la voz empieza **antes** del corte (`inicio < corte`) y `pista` es el origen: temporizador de
  `inicio − (ahora − desfase)` segundos, es decir, el inicio planificado menos el instante planificado de este arranque.
  Si el tema de origen se sintonizó a mitad (arranque alineado, desfase 0) da lo que falta hasta `inicio` por el reloj.
- Sanidad contra la agenda: el temporizador de origen solo se arma si su espera cae entre 0 y la duración del tema
  de origen más `tolerancia_desfase_segundos`; si no, el tema que arrancó no es el que se esperaba (p. ej. se
  salteó o la agenda cambió) y la intervención no se dispara. Para los temporizadores de destino sigue valiendo la
  comprobación actual (`|ahora − corte| ≤ tolerancia`).
- Pueden convivir dos temporizadores armados en el mismo arranque (el de destino de una intervención y el de origen de
  la siguiente), así que el locutor lleva una lista de anclajes y no uno solo.
- **Se cancelan los temporizadores pendientes cuando empieza cualquier otro tema** (saltear, cambio de pedidos, resincronización):
  un temporizador largo no puede sobrevivir al tema para el que se armó. La cancelación de sintonía, apagado y
  `descartar_estacion` también lo cubre.
- Si la intervención se registra **cuando el origen ya está sonando** (los anuncios "antes" de una petición se piden
  con el tema actual en curso) y su inicio todavía no llegó, el locutor arma el temporizador por reloj (`inicio − ahora`)
  en `registrar`, de la misma forma que hoy entra a mitad de frase. Para eso recuerda el tema actual y su desfase.
- Lo demás (bajar la música con `nivel_musica_con_voz`, rampas, `minimo_restante_segundos`, volumen 0, seguridad) no
  cambia: el ducking baja el volumen general de la música y vale a ambos lados del corte.

**El servicio DJ** (`dj/`): `Pedido.posicion` (`inicio` por defecto; `entre` o `final`; otra cosa es un error de
validación) llega hasta el redactor de plantillas y el del LLM.

### Textos

Hoy las frases de plantilla están escritas para una voz que empieza con el tema nuevo y mezclan tiempos ("Ahora suena",
"Llega", "Coming up next"). Se **clasifican** en tres clases según dónde pueden caer:

| Clase | Qué dice | Vale en |
|---|---|---|
| **ahora** | el tema ya está sonando ("Ahora suena X", "De Y escuchamos ahora X", "Now playing…") | `inicio` |
| **neutra** | sirve a ambos lados del corte ("Llega X", "Sigue X", "Con ustedes…", "Here comes…") | `inicio`, `entre`, `final` |
| **adelante** | el tema todavía no empezó ("A continuación X", "Enseguida X", "Up next…") | `final` |

Clasificación de los marcos que existen hoy (`_MARCOS` de [plantillas.py](../../../src/cassette_fm/dj/plantillas.py)):

- **es**: *ahora* — "Ahora suena…", "De {artista} escuchamos ahora…"; *neutra* — los otros seis; *adelante* — ninguno
  (hay que escribirlos).
- **en**: *ahora* — "Now playing…"; *adelante* — los dos "Coming up next…" y "Up next is…"; *neutra* — "Here comes…" (×2)
  y "Stay with us for…".

Se agregan frases hasta que **cada clase tenga al menos tres marcos por idioma** (hoy faltan: es-adelante, es-ahora
(2 → 3), en-ahora (1 → 3)). Lo mismo para los marcos de petición (`_MARCOS_PETICION`, "antes" y "seguidas"): hoy
solo hay uno o dos "ahora" ("Por pedido… suena…") y ningún "adelante".

Reglas por posición:

- **`inicio`**: marcos *ahora* + *neutros*. Como hoy.
- **`entre`**: marcos *neutros*, y **abre una oración de cierre del tema de origen**, que va **primera** (antes de la hora,
  la estación, etc.) y no es opcional si el origen tiene nombre: "Eso fue {título} de {artista}", "Recién sonó…",
  "Veníamos de…", "That was…". El corte cae más o menos a la altura de esa oración y la presentación del tema nuevo; no
  hace falta que coincida. Si el origen no tiene nombre, la oración se omite y queda solo el marco neutro.
- **`final`**: marcos *adelante* + *neutros*. Si se menciona el origen, es en presente ("Está terminando {título} de
  {artista}", "Estás escuchando {título}…", "That is {título}…"), nunca "eso fue": todavía suena. Es un ingrediente más
  de los opcionales, como hoy ("anterior").
- **Peticiones**: el prefijo de "después" y "seguidas" ("Eso fue X, a petición…") sirve en `inicio` y `entre`; en `final`
  hace falta una variante en presente ("Termina X, un pedido especial del público"). Los marcos de "antes" y "seguidas"
  siguen la misma regla de clases que los normales.
- Las demás oraciones sueltas (hora, estación, momento) no dependen de la posición.

Si el pedido llega sin `posicion` o con `inicio`, el texto sale como hoy, así que el servicio sigue funcionando para
clientes viejos y para `cassette-dj muestra` y `scripts/ensayo-dj.py` sin tocarlos.

**LLM** ([redactor_llm.py](../../../src/cassette_fm/dj/redactor_llm.py)): el prompt suma una línea según la posición:
`inicio`, nada (como hoy); `entre`, "empezás a hablar mientras termina {anterior} y terminás ya con el tema nuevo en el
aire: cerrá el anterior y presentá el siguiente"; `final`, "hablás antes de que empiece el tema nuevo: usá futuro
(a continuación, enseguida) y no digas que ya suena". En `entre` el tema de origen va siempre en el prompt (aunque el
ingrediente "anterior" no esté elegido) y la verificación pide que el texto lo nombre; si no lo hace, se cae a las
plantillas como cualquier otra verificación fallida. Para `final` no se agrega verificación (el tiempo verbal no se
puede chequear con seguridad): confía en el prompt.

### Configuración

En `[dj]` y, por emisora, en el `"dj"` de `estaciones.json` (mismo tratamiento que `velocidad` o `personalidad`):

| Clave | Por defecto | Significado |
|---|---|---|
| `posicion_voz` | `"mixto"` | `inicio`, `entre`, `final` o `mixto`. Otro valor → error de configuración con mensaje claro. |
| `fraccion_entre_min` / `fraccion_entre_max` | 0,3 / 0,7 | qué parte del clip suena antes del corte en `entre` (entre 0 y 1; min ≤ max). |
| `final_antes_min_segundos` / `final_antes_max_segundos` | 0 / 2 | cuántos segundos antes del corte termina la voz en `final`. |

`retraso_voz_segundos` sigue valiendo para `inicio`. Los valores numéricos se validan como el resto de `ConfigDJ`.

### Casos borde (todos con prueba)

- Sintonizar con la ventana de la voz ya abierta: entra a mitad de frase, igual que hoy.
- Sintonizar en el tema de origen un rato antes de la voz: la voz sale en su momento (cuenta con el arranque alineado).
- Saltear el tema de origen con la voz pendiente: no sale a destiempo; la intervención vence sola.
- Cambiar de emisora o apagar con la voz pendiente o sonando: se corta y se limpia, como hoy.
- Un tema de origen muy corto: el adelanto se acota a la mitad de su duración.
- Volumen 0: no habla, como hoy.
- Dos intervenciones de la misma emisora: no se pisan (el registro ya lo valida por `[inicio, fin)`); la separación mínima
  de la frecuencia sigue valiendo.
- Servicio DJ viejo que ignora `posicion`: el texto sale como `inicio` aunque la voz caiga antes del corte. No se agrega
  compatibilidad para eso: la radio y el servicio DJ son del mismo repo y se actualizan juntos (hoy corren en la
  misma PC).

## Lo que queda a criterio de quien construye

- Dónde y cómo se sortean las posiciones (función pura con `random.Random` inyectado, como el resto del planificador).
- Los textos exactos de las frases nuevas, siempre en español rioplatense (voseo) y en inglés natural, cuidando que
  cada oración tenga al menos cuatro palabras (regla de `plantillas.py`).
- Cómo se guarda el corte en `_Trabajo` (el trabajo en curso se persiste y se retoma al reiniciar).
- Si `dj_estado` y el applet muestran la posición (no es necesario).
- Los nombres exactos de los campos nuevos de config, si hay una convención mejor en `config.py`.

## Posibles mejoras (fuera de esta entrega)

- Hacer coincidir el corte con el final de una oración (pedirle al sintetizador el instante de cada oración y elegir
  el adelanto para que el corte caiga justo ahí). El usuario no lo pidió; se puede probar si el sorteo no alcanza.
- Usar la duración real de mpv en vez de la de `mutagen` si en la práctica el error en VBR se nota.
- Crossfade entre temas (Spotify: ajuste de cuenta, a probar; local: a construir).

## Riesgos

- **El corte real puede correrse** respecto del estimado (VBR local, latencia de Soloist): la voz queda unos segundos más
  hacia un lado. Es aceptable porque la posición ya es aproximada, y la clase `neutra` de los marcos lo disimula.
- **Fundido cruzado de Spotify**: si se activa, el corte real se adelanta (empieza el fundido). Hay que revisarlo cuando
  se active.
- **Peticiones "antes" con poco margen**: caen más seguido en `inicio` (por la regla de tiempo de generación).

## Cómo se prueba

- Pruebas de unidad (TDD): sorteo y cálculo del inicio, bordes de duración, clasificación de textos (una prueba que
  garantiza al menos tres marcos por clase e idioma y que `final` nunca usa una frase *ahora* ni `inicio` una
  *adelante*), validación del pedido y de la configuración, temporizador de origen del locutor con reloj simulado (incluye
  saltear, sintonizar a mitad y cambiar de emisora), y que las peticiones sigan resolviéndose bien.
- Prueba real con el usuario: una emisora local y una de Spotify, con la frecuencia "cada tema" de la configuración de
  prueba actual, escuchando `inicio`, `entre`, `final` y `mixto`.
