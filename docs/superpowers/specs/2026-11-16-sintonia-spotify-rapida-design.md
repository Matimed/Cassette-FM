# Sintonía de Spotify más rápida

Diseño corto, aprobado por el usuario el 2026-11-16 ("siento que cambiar de estación tarda mucho con Spotify").

## Medición (2026-11-16, 3 cambios entre emisoras de Spotify)

Desde la orden hasta que suena: ~1,7–2,0 s (3,3 s la primera vez tras reiniciar la radio).

- ~1,2 s: `PUT /me/player/shuffle` y `PUT /me/player/repeat` de la Web API (~0,6 s cada uno), en cada sintonía.
- ~0,6 s: `PUT /me/player/play` (imprescindible: solo la Web API acepta una lista de URIs con posición).
- ~0,4–0,6 s: Soloist, del play al sonido.

## Diseño

- Shuffle y repeat se apagan con **comandos locales del WebSocket de Soloist**, justo antes del play:
  `{"type":"command","command":"set_shuffle","enabled":false}`, `set_repeat_context` y `set_repeat_track` (mismo
  formato; Soloist contesta `command_result`, y `error` a un comando desconocido). Formato tomado de lo que manda
  `soloist ctl` y probado contra el Soloist real.
- `ControlSpotify.reproducir` deja de mandar los PUT de shuffle y repeat: solo el play (y la búsqueda del dispositivo).
- Si un comando local falla (Soloist desconectado), la sintonía falla como hoy (sin Soloist no hay play posible).
- **Aproximaciones descartadas:** los tres PUT en paralelo (no garantiza shuffle apagado antes del play); reproducir
  con comandos locales (no aceptan una lista con posición).
- Esperado: ~0,6–1,0 s por cambio de emisora.
