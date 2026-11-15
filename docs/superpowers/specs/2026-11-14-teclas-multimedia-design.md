# Teclas multimedia y botones del parlante (MPRIS) — diseño corto

## Intención

El usuario escucha la radio en un parlante Bluetooth (JBL Go 3) y quiere cambiar de emisora con el botón del
parlante, sin tocar la compu. Hoy el botón no le hace nada a la radio.

## Cómo llega el botón

El parlante aparece como un teclado («JBL Go 3 (AVRCP)») que manda las teclas multimedia (play/pausa, siguiente,
anterior). `csd-media-keys` de Cinnamon no se las da a cualquier programa: las manda al reproductor MPRIS que empezó a
sonar último. La radio no se anuncia por MPRIS, así que no recibe nada.

## Enfoques

- **Anunciar la radio como reproductor MPRIS (elegido).** Anda con el parlante, con las teclas multimedia del teclado
  y con auriculares, y la radio aparece en el applet de sonido de Cinnamon. Mientras suena, las teclas la controlan a
  ella; si otro reproductor empieza a sonar después, pasan a ese (es lo que hace Cinnamon con todos).
- Reasignar las teclas multimedia a `cassette next` con los atajos de Cinnamon: descartado, les roba las teclas a los
  demás reproductores aunque la radio esté apagada.
- Leer el dispositivo de entrada del parlante: descartado, Cinnamon igual procesa la tecla (doble acción) y pide
  permisos sobre `/dev/input`.

## Decidido con el usuario

- Siguiente (dos toques en el JBL) → siguiente emisora. Anterior → emisora anterior.
- Play/pausa (un toque) → prende o apaga la radio; al volver entra con el tema en curso, como siempre.
  Play → prender; Pause y Stop → apagar.
- Mismas acciones que `cassette next`, `prev` y `toggle`, con el mismo aviso de escritorio.

## Diseño

- El servicio `cassette-fm` publica `org.mpris.MediaPlayer2.cassette_fm` en el bus de sesión, en `/org/mpris/MediaPlayer2`,
  con las interfaces `org.mpris.MediaPlayer2` (Identity «cassette-fm», sin Raise ni Quit) y
  `org.mpris.MediaPlayer2.Player`.
- `PlaybackStatus`: «Playing» con la radio prendida, «Stopped» apagada. `Metadata`: título, artista y la emisora como
  álbum (más `mpris:trackid` y, si se sabe, `mpris:length`). Cada cambio de tema, de emisora o de prendido/apagado se
  avisa con `PropertiesChanged`, que es lo que hace que Cinnamon elija a la radio y que el applet la muestre.
- `CanGoNext`, `CanGoPrevious`, `CanPlay`, `CanPause`, `CanControl` en verdadero; `CanSeek` en falso. Volumen, seek,
  posición y abrir ventana: no soportados (Seek/SetPosition/OpenUri no hacen nada).
- Librería: `dbus-fast` (Python puro, sin paquetes del sistema). Decisión de Claude.
- Si no hay bus de sesión o no se puede tomar el nombre, la radio anda igual y lo registra en el log.

## Fuera de alcance

Volumen por MPRIS, seek, carátula, abrir la interfaz.

## Verificación

Primera tarea: comprobar con una tecla multimedia simulada (`xdotool key XF86AudioNext`) que Cinnamon le pasa la tecla
a un reproductor MPRIS nuevo que está sonando. Al final, prueba real con el botón del JBL.

## Para quien construye

Cómo engancha el servicio MPRIS los cambios de estado de la radio (callback, sondeo) y en qué hilo corre el loop de
`dbus-fast`.
