# Bus de audio virtual (`radio_virtual`) — diseño

Fecha: 18/11/2026. Tarea: CASSETTE-FM-r80e. Base de [`2026-11-18-radio-en-red-design.md`](2026-11-18-radio-en-red-design.md).

## Intención

Todo lo que suena (música de mpv, voz del DJ, Soloist) sale a un sink virtual, `radio_virtual`, que es la señal de la
radio. Lo que se oye en esta PC es un **monitor local**, un `module-loopback` desde `radio_virtual.monitor` a la salida
predeterminada, que se prende y apaga sin tocar el bus y tiene su propio volumen. Una retransmisión por red lee el mismo
monitor y recibe siempre la señal completa: **cada monitor tiene su propio volumen**.

## Piezas

- `audio_router.py` — `AudioRouter`: `create_bus`, `env`, `enable_local_monitor`, `disable_local_monitor`,
  `set_local_volume`, `close`. Maneja todo con `pactl` (PulseAudio y PipeWire). Reutiliza un bus o un loopback
  huérfano de una corrida que murió, se niega a prender el monitor si la salida predeterminada es el propio bus
  (realimentación) y recuerda el volumen local aunque el monitor esté apagado.
- Config: `bus_audio` (por defecto `true`). Sin `pactl` el servicio arranca igual sin bus y deja un error en el log que
  recomienda `bus_audio = false`. `Estado.monitor_local` recuerda si el monitor estaba prendido.
- **Abstracción de volumen** (`Radio._poner_volumen`): el volumen de la radio es el del monitor local. Las fuentes
  (mpv, voz, Soloist) quedan siempre al 100 % y solo se mueven para el ducking del DJ y la calibración de
  Spotify (`ajuste_volumen_db`), que siguen dentro de la señal del bus.
- **Apagar vs. silenciar** (decidido el 18/11 con el usuario): con el bus la radio es una transmisión que sigue sonando en
  `radio_virtual` aunque nadie la escuche en esta PC. Todo lo que antes "apagaba" ahora solo **silencia el monitor**
  (`Radio.silenciar`): el clic izquierdo del applet, Pause/Stop/PlayPause de MPRIS y de las teclas multimedia, y el volumen
  en 0 (las fuentes y la voz no se tocan). Subir el volumen, Play, sintonizar o abrir el dial lo vuelven a prender sin
  re-sintonizar (con volumen 0 parte de 50). **Solo corta la transmisión** el "Apagar" del menú del clic derecho,
  `cassette off` y `POST /apagar`. Sin bus, `silenciar` es `apagar`: nada cambia. En MPRIS, silenciado se ve como
  "Stopped". Se descartó el interruptor "Escuchar en esta PC" del applet: era una segunda forma de lo mismo.
- API: `POST /silenciar` (y `cassette mute`); `POST /monitor {"activo": bool}`; `/estado` suma `monitor_local` (solo con bus). 409 sin bus, 503 si falla `pactl`.
  `/volumen` no cambia de forma: el applet, MPRIS y las teclas multimedia siguen igual.

## Cómo llega el audio al bus (verificado el 18/11 en este equipo)

- **mpv**: la salida por defecto en PipeWire (`--ao=pipewire`) ignora `PULSE_SINK`; hace falta `--ao=pulse` más
  `PULSE_SINK=radio_virtual` (lo hace el servicio).
- **Soloist** es un cliente PipeWire nativo: ignora `PULSE_SINK` y se dirige al bus con `PIPEWIRE_NODE=radio_virtual`. Va en
  un drop-in de su unidad con `PartOf=` y `After=cassette-fm.service` (así arranca con el bus creado y se reinicia
  con la radio, que descarga el bus al salir): `scripts/instalar-bus.sh` lo instala y `scripts/instalar-bus.sh quitar`
  lo revierte junto con `bus_audio = false`.
- En PipeWire el `owner_module` del sink-input del loopback viene como texto (`'536870914'`), y el porcentaje de `pactl`
  es cúbico, igual que el de mpv y el de Soloist: el mismo número suena igual que antes.

## Costos conocidos

- Reiniciar `cassette-fm` reinicia Soloist (por `PartOf`).
- Un salto más en el camino (loopback de 20 ms) y un punto más de falla: si el loopback no carga, suena el bus pero no los
  parlantes.
- Sin el bus (falta `pactl`) y con el drop-in puesto, Soloist queda apuntando a un nodo inexistente: no se probó qué hace;
  la salida es `scripts/instalar-bus.sh quitar`.
- Sin verificar: si el loopback sigue a la salida predeterminada al cambiar de parlantes a auriculares.
