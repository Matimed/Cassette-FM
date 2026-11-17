# Sintonía instantánea: el primer tema por Soloist, la lista por la Web API

Diseño corto, aprobado por el usuario el 2026-11-16. Sigue a la
[sintonía rápida](2026-11-16-sintonia-spotify-rapida-design.md).

## Para qué

Cambiar de emisora de Spotify tarda lo que tarde `PUT /me/player/play` de la Web API: ~0,6 s en un buen momento, pero
el 2026-11-16 a la noche iba de 3 a 10 s (9 veces en una hora), con la estática sonando todo ese tiempo. Es molesto
desde los atajos y desde el dial por igual (medido: el pedido a la radio tarda 2–4 ms; la demora es de Spotify).

## Lo que se midió contra el Soloist real

- El WebSocket de Soloist (`ws://127.0.0.1:9787`) acepta `{"type":"command","command":"play","uri":<tema>}`: un solo
  tema, sin lista (con `uris` lo toma como "seguir") ni posición (`position_ms` adentro de `play` se ignora).
- `play` del tema y `{"command":"seek","position_ms":…}` **al llegar su `track_changed`** (antes se ignora): suena en
  **0,27–0,32 s**, en la posición pedida.
- La Web API sigue siendo la única que acepta la lista (100 temas) con posición. Si su `play` llega mientras Soloist
  todavía carga el tema local, no se nota nada; si llega con el tema sonando (Spotify lento), Soloist lo recarga en el
  mismo punto: **~0,1 s de silencio** y arranca atrasado lo que tardó el pedido (la posición se calcula al mandarlo).

## Enfoques

- **Híbrido** (elegido, con el microcorte aceptado por el usuario): el primer tema por Soloist (instantáneo) y en
  paralelo la lista por la Web API; si la Web API tardó, un `seek` local corrige la posición.
- **Todo por Soloist** con `add-to-queue` para los temas que siguen: la cola de Spotify es la de los pedidos del
  usuario (etapa 7a): mezclaría los temas de la emisora con las peticiones. Descartado.
- **Solo Web API** (hoy): sin cortes, pero la espera es la de Spotify.

## Diseño

1. **Al sintonizar** (`ReproductorSpotify.sintonizar`): después del volumen, el shuffle y el repeat, se manda por
   Soloist `play` del primer tema y se anota un **seek pendiente** (sintonía, URI, posición). Enseguida, el `play` de
   siempre por la Web API con la lista.
2. **Seek al cargar:** cuando llega `track_changed` del tema esperado con el seek pendiente de esa sintonía, se manda
   `seek` con la posición calculada en ese momento (`_posicion_al_play`), y el pendiente se borra.
3. **Corrección después de la Web API:** cuando vuelve su `play`, si la sintonía sigue siendo la misma y tardó más
   de **0,5 s**, un `seek` local a la posición de ese momento (si volvió antes, el tema local quizá todavía no cargó y
   un seek se ignoraría: para eso está el del `track_changed`). Así lo atrasado del pedido
   no se oye como un retroceso. *(Umbral: decisión propia.)*
4. **Si el `play` local falla** (Soloist rechaza o se cortó), se sigue solo con la Web API, como hoy.
5. **Las re-sintonías** (`_resintonizar`, en un borde de tema, para corregir el desfase o renovar la lista) siguen
   solo por la Web API: no son una espera del usuario, y un `play` local del mismo tema que ya suena podría no dar
   `track_changed` y arrancarlo de cero. *(Decisión propia.)*
6. **Sin cambios:** la estática se corta con el primer `playing` del tema esperado (llega por el `play` local), el
   reloj, los pedidos, los salteos.

**Límite conocido:** las órdenes a Spotify siguen saliendo de a una (`_orden_lock`). Si se cambia varias veces seguidas
con Spotify lento, el `play` local de la última espera a que vuelva el pedido de la anterior a la Web API. El caso
común (un cambio) es instantáneo. *(Decisión propia: soltar el candado haría que un pedido viejo de la Web API
vuelva a poner la emisora anterior.)*
