# Teclas multimedia y botones del parlante (MPRIS) — diseño corto

## Intención

El usuario escucha la radio en un parlante Bluetooth (JBL Go 3) y quiere cambiar de emisora con el botón del
parlante, sin tocar la compu. Hoy el botón no le hace nada a la radio.

## Cómo llega el botón

El parlante aparece como un teclado («JBL Go 3 (AVRCP)») que manda las teclas multimedia (play/pausa, siguiente,
anterior). `csd-media-keys` de Cinnamon (6.4) las reparte así, verificado con una tecla simulada y `dbus-monitor`:

1. Si algún programa pidió las teclas con `GrabMediaPlayerKeys` (`org.gnome.SettingsDaemon`,
   `/org/gnome/SettingsDaemon/MediaKeys`), le manda la señal `MediaPlayerKeyPressed(aplicación, tecla)` al último que
   las pidió.
2. Si no, se las manda por MPRIS al **primer** reproductor que se anunció (hoy Opera), y no cambia hasta que ese se
   cierra. No mira cuál está sonando.

Por eso anunciarse por MPRIS no alcanza: la radio además pide las teclas.

## Enfoques

- **Pedir las teclas a Cinnamon y anunciar la radio como reproductor MPRIS (elegido).** Anda con el parlante, con las
  teclas multimedia del teclado y con auriculares, y la radio aparece en el applet de sonido de Cinnamon.
- **Cuándo retener las teclas (decidido con el usuario, «1 por ahora»): siempre, mientras corre el servicio.** Así un
  toque que apagó la radio la vuelve a prender. Costo aceptado: Opera/YouTube no reciben las teclas multimedia mientras
  la radio corre. Descartado por ahora: retenerlas solo con la radio prendida (el toque que la apaga suelta las teclas
  y el siguiente toque va a Opera).
- Reasignar las teclas multimedia a `cassette next` con los atajos de Cinnamon: descartado, les roba las teclas a los
  demás reproductores aunque la radio esté apagada.
- Leer el dispositivo de entrada del parlante: descartado, Cinnamon igual procesa la tecla (doble acción) y pide
  permisos sobre `/dev/input`.

## Decidido con el usuario

- Siguiente (dos toques en el JBL) → siguiente emisora. Anterior → emisora anterior.
- Play/pausa (un toque) → prende o apaga la radio; al volver entra con el tema en curso, como siempre.
  Por las teclas (`MediaPlayerKeyPressed`), Play y Pause alternan y Stop apaga. Por MPRIS (el applet), Play prende y
  Pause y Stop apagan.
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
- Al arrancar, el servicio llama `GrabMediaPlayerKeys("cassette-fm", 0)` y escucha `MediaPlayerKeyPressed` con
  aplicación `cassette-fm`: `Next` → siguiente emisora, `Previous` → anterior, `Play` y `Pause` → prender/apagar
  (alternar: el parlante puede mandar una u otra según lo que él cree que está pasando), `Stop` → apagar. Si
  `csd-media-keys` se reinicia (el nombre `org.gnome.SettingsDaemon` cambia de dueño), vuelve a pedirlas. Al cerrar,
  `ReleaseMediaPlayerKeys("cassette-fm")`.
- Librería: `dbus-fast` (Python puro, sin paquetes del sistema). Decisión de Claude.
- Si no hay bus de sesión, no se puede tomar el nombre o no está `csd-media-keys`, la radio anda igual y lo registra
  en el log.

## Fuera de alcance

Volumen por MPRIS, seek, carátula, abrir la interfaz.

## Verificación

Primera tarea (hecha): con `xdotool key XF86AudioNext` se comprobó que un reproductor MPRIS nuevo no recibe la tecla
(va a Opera) y que un programa que pidió las teclas con `GrabMediaPlayerKeys` sí. Al final, prueba real con el botón
del JBL.

## Para quien construye

Cómo engancha el servicio MPRIS los cambios de estado de la radio (callback, sondeo) y en qué hilo corre el loop de
`dbus-fast`.
