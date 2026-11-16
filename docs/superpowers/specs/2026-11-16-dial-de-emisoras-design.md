# El dial: selector de emisoras estilo GTA 4

Diseño de la etapa 5 (épica CASSETTE-FM-qyz0), 2026-11-16. Reemplaza la "rueda radial" de la tarea CASSETTE-FM-inkb.

## Para qué

Cambiar de emisora mirando: una tira horizontal de logos (como la radio de GTA 4, no la rueda del 5) que se abre con
un atajo, muestra la emisora que suena agrandada en el centro y deja moverse con el teclado. Los atajos rápidos que ya
existen (Super+Alt+flechas) siguen cambiando sin mostrar nada.

Cada emisora tiene su logo. El usuario tiene una imagen de referencia con seis logos circulares de estilo neón
(Happy Eighties, Más Gasolina F.M., Pop Hits F.M., Power F.M., Whisper F.M., Xcelerate F.M.); hay que separarlos en
imágenes individuales sin fondo. Las emisoras sin logo (hoy Sing y Estacion trap, de las 8 que hay, y las que se creen después) usan uno genérico.

**Éxito:** apretar el atajo, ver la tira con los logos, ir y venir con ◀ ▶ oyendo la estática, ajustar el volumen con
▲ ▼ y que la tira se vaya sola o con Escape, sin que el panel ni el escritorio se traben.

**No es:** un reemplazo del menú del applet, ni algo que aparezca solo con cada cambio de emisora (eso quedó para
después: con el dial propio no hace falta que el applet se entere al instante de cambios hechos por otros lados).

## Enfoques

- **Dentro del applet de Cinnamon** (elegido): Cinnamon dibuja la tira encima de todo con sus componentes (St y
  Clutter, los mismos del cartel de volumen y del selector de ventanas), con animaciones de tamaño, posición y
  transparencia. Usa lo que el applet ya tiene (lista de emisoras, pedidos a la API) y Cinnamon deja que un applet
  registre su propio atajo (como el calendario). Límite: los efectos de brillo o desenfoque son más pobres que en una
  web; con logos ya brillantes sobre una barra oscura semitransparente alcanza.
- **Un programa aparte (Python + GTK)** que el atajo abre como ventana transparente: más fácil de probar en Python,
  pero otro programa, que tarda en abrir y tiene que pelear para quedar arriba y tomar el teclado. Descartado.
- **Que la tira aparezca sola en cada cambio** (sin atajo propio): necesitaba un aviso inmediato desde la radio para
  los cambios por Bluetooth o por la terminal (el applet hoy consulta cada 2 s). Queda para más adelante.
- **Logos por nombre de archivo** (`iconos/Power F.M.png`) en vez de un campo: el usuario prefirió el campo en
  `estaciones.json` porque deja compartir una imagen entre emisoras. **Logos en el repo:** no, son configuración del
  usuario; en el repo va solo el genérico.

## Partes, en orden (cada una se puede usar sola)

### 1. Volumen: prender sube a 50

La API ya trata el volumen 0 como apagada: bajar a 0 apaga (y detiene Spotify y el DJ), subir estando apagada
prende, y prender con el volumen en 0 lo sube a `VOLUMEN_MINIMO`. El usuario quiere que eso valga siempre (en todas
las vías: atajos, applet, terminal, dial) y que el valor al prender desde 0 sea **50** (hoy 10). Cambio: la constante
y el texto que la menciona (README, comentarios, tests). **Subir el volumen desde 0 no cambia** (decisión del
usuario): prende la radio en lo que sumó la tecla (Super+Alt+Arriba → 10, ▲ del dial → 5), para poder prenderla
bajita; solo prender por emisora (`/encender`, `/sintonizar`, `/alternar`, ◀ ▶, abrir el dial) sube a 50.

### 2. Logos de las emisoras

- **Campo opcional `"icono"`** en cada emisora de `estaciones.json`: la ruta de una imagen (PNG, JPG o SVG), absoluta
  o relativa a `~/.config/cassette-fm/`. Si no es un texto, error de configuración como los demás campos. Si el
  archivo no existe, la emisora usa el genérico y el servicio lo avisa una vez en el log (no rompe la radio).
- **La API** (`GET /estado` y las respuestas que devuelven el estado) suma `"iconos": {"<emisora>": "<ruta absoluta>"}`
  solo con las emisoras cuyo archivo existe. La lista `estaciones` no cambia (el applet ya la usa así).
- **`cassette nueva --icono RUTA`:** copia la imagen a `~/.config/cassette-fm/iconos/` (si no está ya ahí adentro) y
  guarda la ruta relativa (`iconos/<archivo>`). Si ya hay otro archivo con ese nombre y distinto contenido, se le agrega
  un sufijo (`power-2.png`); si es el mismo contenido, se reusa. Así borrar la imagen original no deja a la emisora sin
  logo, y elegir la misma imagen para dos emisoras no la duplica. *(Decisión propia.)*
- **`cassette icono "Emisora" RUTA`** y **`cassette icono "Emisora" --quitar`:** ponerle o sacarle el logo a una
  emisora existente, con la misma copia; rescan al final. Hace falta para las seis de hoy sin editar el JSON a mano.
  *(Decisión propia.)*
- **Modal de emisora nueva:** una fila "Logo" con una miniatura (el genérico si no hay), un botón **Examinar…** y uno
  **Quitar**. Examinar corre `zenity --file-selection` con filtro de imágenes, de forma asíncrona (el panel no se
  traba); la ruta elegida va a `cassette nueva --icono`. Se bloquea junto con el resto mientras dice "Creando…".
- **Recorte de los seis logos** (una sola vez, no queda en el repo): de la imagen de referencia (fondo gris oscuro con
  textura) se separa cada logo siguiendo el borde contra el fondo, no con un círculo, porque varios tienen partes que
  salen del círculo (la cinta del cassette, las llamas y el bidón, el rayo, los autos). Salida: PNG cuadrado de 512 px
  con transparencia, en `~/.config/cassette-fm/iconos/` (`happy-eighties.png`, …), y `cassette icono` para cada
  emisora. Se le muestran al usuario antes de dar la parte por terminada; alguno puede necesitar retoque.
- **Genérico** (en el repo, junto al applet, porque es el respaldo del applet y no configuración): sale de una
  imagen que el usuario pasa cuando se llegue a esta parte, con el fondo sacado igual que los seis; PNG de 512 px.

### 3. El dial

```
 Super+Alt+Espacio
┌──────────────────────────────────────────────────────────────┐
│   (◯)    (◯)    (  ◉ POWER  )    (◯)    (◯)    (◯)    (◯)    │
│                     Power F.M.                               │
│               The Police - Every Breath You Take             │
│           ◀ ▶ emisora · ▲ ▼ volumen ▮▮▮▮▮▮▱▱▱ 60 · Esc        │
└──────────────────────────────────────────────────────────────┘
```

- **Abrir:** un atajo propio del applet, configurable en sus ajustes (tipo keybinding), por defecto
  **Super+Alt+Espacio**. Al abrir: si la radio está apagada, se prende en la emisora de siempre (`/encender`; por la
  parte 1, con el volumen en 0 sube a 50). El mismo atajo o Escape la cierran.
- **Teclado** (mientras está abierta se queda con el teclado): ◀ ▶ cambian de emisora en el acto (con la estática,
  como el atajo rápido); ▲ ▼ suben y bajan el volumen de a 5; bajar a 0 apaga la radio (la tira queda abierta,
  mostrando "Apagada", y ▲ la prende). Con la radio apagada, ◀ ▶ la prenden en la emisora elegida, a volumen 50
  (lo pidió el usuario para la API en general: cambiar de emisora estando apagada sube a 50).
- **El mismo atajo cierra:** mientras el dial tiene el teclado tomado, el atajo de Cinnamon no se dispara; el dial
  reconoce esa combinación (la del ajuste) en su propio manejo de teclas.
- **Mouse:** clic en un logo sintoniza esa emisora; clic fuera de la tira la cierra; la rueda sobre la tira cambia de
  emisora.
- **Se cierra sola** a los 5 s sin tocar nada (si no, alguien que se olvida queda sin teclado). Cada tecla o clic
  reinicia la cuenta.
- **Aspecto:** barra oscura semitransparente con bordes redondeados, en el tercio superior de la pantalla, centrada en
  el monitor principal. Los logos en fila, en el orden de `estaciones.json`; la emisora actual en el centro, más
  grande (≈160 px contra ≈96 px) y opaca; las demás más chicas y algo transparentes. Debajo, el nombre de la emisora,
  el tema que suena y la barra de volumen. Con más de 7 emisoras se ven 3 a cada lado de la actual (la fila es
  circular, como el cambio con ◀ ▶). Cambiar de emisora corre la fila con una animación corta (~150 ms); abrir y
  cerrar, con un fundido. *(Medidas y posición: decisión propia; se ajustan viéndolo.)*
- **Teclas rápidas:** la tira se mueve en el acto con cada tecla; los pedidos a la radio van de a uno: si llega otra
  tecla mientras uno está en curso, al terminar se manda solo el último destino (`/sintonizar`). Así apretar ▶ cinco
  veces seguidas no encola cinco cambios. *(Decisión propia.)*
- **Sin radio** (el servicio no responde): la tira se abre con el mensaje "cassette-fm no responde" y se cierra sola.

## Cómo se prueba

- Python: la constante de volumen; el campo `icono` (validación, rutas relativas, archivo que falta); `iconos` en la
  API; la copia de `--icono` y `cassette icono`.
- `logic.js` (Node): qué logos se ven y en qué lugar y tamaño según la cantidad y la actual; qué hace cada tecla; la
  regla de "un pedido a la vez, después solo el último"; el texto de la barra de volumen; la ruta del logo de cada
  emisora (con el genérico de respaldo).
- Cinnamon real: recargar el applet (y reiniciar Cinnamon si cambió `logic.js`, porque `ReloadXlet` no lo recarga),
  abrir el dial con el atajo y por Eval, capturas de pantalla; la prueba con el teclado la hace el usuario.

## Queda para quien lo construye

- Cómo pasa el campo `icono` desde `DefEmisora` hasta `Radio.estado()` / la API.
- `cassette icono --quitar` y `cassette borrar` no borran el archivo de `iconos/` (puede compartirlo otra emisora).
- El volumen desde el dial conviene mandarlo en valor absoluto (`{"valor": n}`) y agrupar teclas como con las
  emisoras; mientras hay un pedido en curso, no hacer caso al sondeo de cada 2 s del applet.
- La distribución de los logos con 7 emisoras o menos (todos visibles, la actual en el centro de la fila circular).

Cómo cargar las imágenes en St (por ejemplo `St.Icon` con un `Gio.FileIcon`, o fondo CSS con `background-size`), cómo
tomar el teclado (`Main.pushModal` u otro), el detalle de las animaciones y la técnica del recorte (por distancia de
color contra el fondo y relleno desde los bordes, con un margen suave en el contorno).
