# Uso diario

Cómo se maneja cassette-fm una vez instalado ([`setup.md`](setup.md)): comandos, applet, dial, atajos, emisoras y
Spotify. El DJ tiene su propio documento: [`dj.md`](dj.md).

## La idea en una línea

Todas las emisoras "están sonando" todo el tiempo, pero **la radio solo suena si alguien la escucha**. Esta PC es un
oyente más (su monitor local), igual que otra PC por la red o el teléfono por la nube. Cuando nadie escucha durante
un minuto, la radio se duerme sola; abrir un stream o elegir una emisora sin oyentes la despierta. No hay un "apagar":
dejar de escuchar en todos lados es apagarla, y `cassette stop` la baja del todo.

## Comandos

| Comando | Qué hace |
|---|---|
| `cassette on` / `mute` / `toggle` | empezar a escuchar acá, dejar de escuchar acá o alternar (al escuchar suena lo que corresponde *ahora*; si el servicio estaba detenido, `on` lo levanta) |
| `cassette next` / `prev` | emisora siguiente o anterior (en el orden de `estaciones.json`, con vuelta); si nadie escuchaba, te vuelve el primer oyente |
| `cassette tune <nombre>` | sintoniza por nombre o por el comienzo (`cassette tune reg`) |
| `cassette vol 70` / `+5` / `-5` | volumen; en 0 dejás de escuchar acá (como un mute) y subirlo vuelve a escuchar |
| `cassette status` | qué suena y cuántos oyentes tiene (`dormida` si nadie escucha) |
| `cassette list` | emisoras y cantidad de temas |
| `cassette rescan` | vuelve a leer `estaciones.json` y la música de cada emisora |
| `cassette stop` / `start` | apaga o levanta todo (radio, Soloist, DJ y el contenedor de Ollama); `stop` libera la memoria, sobre todo la del DJ |
| `cassette serve` | levanta el servicio a mano (sin systemd) |

Los comandos de emisoras ([`nueva`, `borrar`, `renombrar`, `icono`](#emisoras)), de Spotify
([`spotify login`, `spotify estado`](#spotify)), del DJ (`dj …`, ver [`dj.md`](dj.md)) y de acceso por red (`lan`,
`nube`, `claves`, ver [`setup.md`](setup.md#4-escuchar-desde-otra-pc-opcional)) están en sus secciones.

## Applet de Cinnamon

Un ícono en el panel con el nombre de la emisora (vacío si la radio está dormida).

| Acción | Efecto |
|---|---|
| Rueda del mouse | hacia arriba, emisora siguiente; hacia abajo, la anterior (sin prender el sonido de esta PC si otro la está escuchando) |
| Clic izquierdo | escuchar o dejar de escuchar acá (con el servicio detenido, lo levanta) |
| Clic derecho | lista de emisoras para elegir una, y **Nueva emisora…** |
| Pasar el mouse | tooltip con emisora, tema y volumen; si el servicio no está, dice que no responde |

En los ajustes del applet se cambia el puerto, si se muestra el nombre y el atajo del dial.

**Nueva emisora…** abre un modal para crear una emisora de Spotify: nombre, link, idioma, voz (con ▶ para escucharla) y
logo (*Examinar…*).

### El dial

`Super+Alt+Espacio` abre una tira con los logos de las emisoras, la que suena agrandada en el centro:

| Tecla / gesto | Efecto |
|---|---|
| ◀ ▶ | cambia de emisora |
| ▲ ▼ | volumen de a 5 (en 0 se apaga) |
| Barra espaciadora | mutea / desmutea (igual que el clic en el applet o la tecla de pausa) |
| Enter, Escape o el mismo atajo | lo cierra (también se cierra solo a los 3 s sin tocar nada) |
| Clic en un logo / rueda | sintoniza / cambia de emisora |

Si la radio estaba apagada, abrir el dial la prende. Las emisoras sin logo usan uno genérico (ver [Logos](#logos)).

## Atajos de teclado

`cassette atajos` (ya lo hace `instalar-escritorio.sh`) registra estas teclas sin pisar las que ya uses ni las que cambies a mano:

| Tecla | Acción |
|---|---|
| `Super+Alt+→` / `Super+Alt+←` | emisora siguiente / anterior |
| `Super+Alt+↑` / `Super+Alt+↓` | volumen +10 / −10 (en 0 se apaga; subir lo enciende) |

El atajo del dial (`Super+Alt+Espacio`) se cambia en los ajustes del applet.

### Teclas multimedia y parlantes Bluetooth

Mientras corre el servicio, la radio se queda con las teclas multimedia (las del teclado y los botones de un parlante o
auriculares Bluetooth, que llegan como teclas) y aparece en el applet de sonido de Cinnamon con el tema, el artista y la
emisora:

| Tecla / botón | Acción |
|---|---|
| Siguiente (dos toques en un JBL) | emisora siguiente |
| Anterior (tres toques) | emisora anterior |
| Play/pausa (un toque) | prende o apaga la radio (al volver entra con el tema en curso) |

Mientras la radio corre, otros reproductores (un video en el navegador, por ejemplo) no reciben esas teclas: Cinnamon se
las da al último programa que las pidió.

## Emisoras

Las emisoras viven en `~/.config/cassette-fm/estaciones.json`, una lista en el orden en que se rotan. Formato completo en
[`configuracion.md`](configuracion.md#estacionesjson-las-emisoras). Se manejan con comandos, sin editar el archivo:

| Comando | Qué hace |
|---|---|
| `cassette nueva "Synthwave F.M." <link>` | crea una emisora de Spotify con un DJ de voz propia y la sintoniza (ver abajo) |
| `cassette borrar "sing"` | la saca de `estaciones.json`, preguntando antes (`--si` no pregunta); si sonaba, pasa a la primera. No toca la música ni la caché de Spotify |
| `cassette renombrar "sing" "Cantemos"` | le cambia el nombre (si sonaba, sigue en ella). El orden de los temas sale del nombre: después de renombrarla queda en otro punto de su lista |
| `cassette icono "Power F.M." ~/Descargas/power.png` | le pone un logo (`--quitar` se lo saca) |
| `cassette voces` | lista los alias de voz que puede usar una emisora nueva, con su idioma y las emisoras que ya los usan (`--json`, para el applet) |

El nombre de las emisoras se busca sin importar mayúsculas. También se puede editar `estaciones.json` a mano y aplicarlo
con `cassette rescan` (sin cortar la música). Si quedó mal escrito, la radio sigue con las emisoras que tenía y el
comando muestra el error con la línea; si está mal escrito **al arrancar**, el servicio no levanta
(`journalctl --user -u cassette-fm -n 20`).

**`cassette nueva`** agrega la emisora a `estaciones.json` con un alias de `[voces]` (de cassette-dj) que no use otra
emisora, al azar; el idioma sale de la voz. `--voz sarah` elige una, `--idioma es` pide una en español, `--icono` le
pone logo. Si la playlist no es tuya o está vacía, no se guarda nada. Dos emisoras pueden usar la misma playlist: cada una
va por otro tema (el orden sale del nombre).

### Logos

Cada emisora puede tener un `"icono"` (PNG, JPG o SVG; ruta absoluta o relativa a `~/.config/cassette-fm/`).
`cassette icono` copia la imagen a `~/.config/cassette-fm/iconos/` y se la asigna. Sin logo (o si el archivo no está), el
applet y el dial usan uno genérico, que es el único que viene en el repositorio.

## Spotify

Cómo se instala está en [`setup.md`](setup.md#2-emisoras-de-spotify-opcional). Una vez andando:

- `cassette spotify estado` muestra la cuenta y cuántos temas tiene cada emisora de Spotify, y avisa cuando al build de
  Soloist le quedan menos de 14 días. `cassette spotify login` vuelve a pedir el permiso en el navegador si hiciera falta.
- Una emisora de Spotify se comporta como una local: el mismo orden mezclado, se entra con el tema empezado y el DJ
  habla igual, con la música bajada. Spotify encadena los temas sin cortes.
- Al sintonizar suena un segundo de estática hasta que arranca la música. El primer tema sale directo por Soloist
  (~0,3 s) y la lista de los que siguen viaja en paralelo; si Spotify tarda (hay noches de 3–10 s), puede oírse un
  microcorte de una décima cuando llega.
- Los temas se guardan en `~/.cache/cassette-fm/spotify.json`: el `rescan` solo los vuelve a bajar si la playlist cambió,
  y si Spotify no responde usa los guardados.
- **Una sola cuenta, un solo dispositivo.** Premium reproduce en un dispositivo a la vez: si ponés Spotify en otro
  dispositivo (el celular), la radio se apaga y avisa. Y si sintonizás una emisora de Spotify, la radio toma el control
  de tu cuenta.
- A veces Soloist no logra cargar un tema (le pasa a algunos, de a ratos, aunque en la app suenen) y pasa al siguiente en
  menos de un segundo, o toca otra versión del tema. La radio lo acepta (en el log: «Soloist salteó …») y sigue desde lo
  que suena. Lo mismo si salteás rápido desde la app.
- Si una emisora no empieza a sonar, la radio se recupera sola (reintenta, cambia de emisora, reinicia el servicio con un
  freno de 10 minutos); el detalle está en [`arquitectura.md`](arquitectura.md#recuperación-cuando-spotify-no-arranca).

### Peticiones

Mientras suena una emisora de Spotify, agregá un tema a la cola desde la app de Spotify (en la compu o el celular):
cuando termina el tema actual suena el tuyo y el DJ lo anuncia como **petición especial**.

- **Antes o después:** si quedan al menos `peticion_margen_segundos` (30 por defecto) del tema actual, el DJ lo presenta al
  arrancar («y ahora, una petición especial…»); si no llega, lo anuncia al terminar («eso fue una petición especial…»).
  Necesita que el tema tenga artista y título, y que el DJ esté activo.
- **La agenda se corre:** la emisora no pierde temas: mientras suena el pedido su agenda se detiene y después sigue con el
  tema que venía. Se corre lo que sonó de verdad: menos si lo salteás desde la app, y hasta 15 s más si Spotify tarda en
  pasar al siguiente (más que eso es una pausa, y la radio sigue siendo un reloj).
- **Pedidos seguidos:** varios encolados se encadenan. Si el segundo entra con tiempo, el DJ cierra el primero y presenta
  el segundo en un solo anuncio («eso fue una petición especial: …; y llega otra»). Si encolás dos con menos del margen,
  el primero queda sin mención.
- **Anuncios que ya no van:** si sacás un tema de la cola o salteás un pedido, su anuncio se descarta y no frena las
  intervenciones normales.
- Cuenta como petición todo lo que viene de la cola, aunque sea un tema de la playlist o justo el siguiente.
- Si cambiás de emisora (o reiniciás la radio) a mitad de un pedido y volvés, sigue el pedido en el segundo que
  corresponde. Los pedidos se guardan en `estado.json` (`agendas`).
- Encolar mientras habla el DJ no lo corta: solo se descarta lo que estaba previsto desde el pedido en adelante.
- Para ver qué manda Soloist al encolar: `.venv/bin/python scripts/herramientas/capturar-cola-soloist.py SALIDA.jsonl` (solo escucha;
  no cambia lo que suena).

## Escuchar en otro lado

- **Otra PC propia** (applet en modo remoto): [`setup.md`, paso 4](setup.md#4-escuchar-desde-otra-pc-opcional).
- **Teléfono, tablet o navegador** (relay en la nube): [`setup.md`, paso 5](setup.md#5-escuchar-desde-cualquier-lado-opcional).

En los dos casos hay una sola transmisión: cambiar de emisora desde cualquier lado la cambia para todos, y cada
dispositivo tiene su propio volumen y su propia escucha.

## Si algo falla

`journalctl --user -u cassette-fm -e` para el servicio; `Alt+F2`, escribir `lg`, pestaña *Errors* (Looking Glass) para el
applet. Más en [Problemas frecuentes](setup.md#problemas-frecuentes).
