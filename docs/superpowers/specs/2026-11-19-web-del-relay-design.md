# La web del relay: el dial en el navegador y en el celular

Diseño corto (2026-11-19). Reemplaza la página de prueba de `relay/web/index.html`. Aprobado por el usuario en la
conversación; se construye rápido y se itera con lo que él pruebe.

## Para qué

Escuchar y cambiar de emisora desde cualquier dispositivo con una interfaz liviana y con estilo, en la onda del dial del
applet ([`2026-11-16-dial-de-emisoras-design.md`](2026-11-16-dial-de-emisoras-design.md)): logos que flotan y se
difuminan hacia los costados, la actual más grande al centro, recuadro oscuro semitransparente con el nombre, el tema y
el volumen.

**No es:** una app instalable, ni un control del volumen de la PC (el volumen es de cada dispositivo, ver el spec del
puente), ni algo con librerías o paso de compilación.

## Enfoque

Una sola página (`relay/web/index.html`, HTML + CSS + JS a mano, sin dependencias) que cambia de presentación con
`matchMedia` (celular hasta 720 px de ancho). Descartado: dos páginas (duplican la lógica). El dial es DOM con
transformaciones CSS y un bucle `requestAnimationFrame` que anima una posición fraccionaria; sin canvas.

## Web (más de 720 px)

- Fondo oscuro con un resplandor: el logo de la emisora, grande y desenfocado, detrás (se cruza en un fundido al cambiar).
- Fila de logos: la actual de 160 px al centro, las vecinas de 96 px, 5 visibles, con difuminado en los bordes.
- Debajo, el recuadro (`rgba(20,20,26,.6)`, esquinas de 18 px): nombre, tema, volumen.
- Barra integrada: ⏮ ▶/⏸ ⏭, calidad (64 · 96 · 160) y Salir.
- Teclado: ← → emisora, ↑ ↓ volumen de a 5, espacio play/pausa. Rueda sobre la fila: emisora. Clic en un logo: sintoniza;
  en el del centro: play/pausa.

## Celular

- Un logo grande al centro y las dos vecinas más chicas, difuminadas (blur y transparencia), asomando por los costados.
- Se desliza hacia los costados (seguimiento del dedo, inercia, ajuste a la emisora más cercana). Al soltar se manda solo
  el destino final. Tocar el logo del centro: play/pausa.
- El volumen va debajo del título; la calidad y Salir, en un menú ⋮ en la esquina.

## Comportamiento común

- Mientras se desliza o se aprieta, la pantalla se mueve en el acto y los pedidos a la radio van de a uno (a los 220 ms
  de quieto), mandando solo el último destino. El sondeo de `/api/estado` (3 s) no pisa el movimiento ni un pedido en
  curso. Si el pedido falla, vuelve a la emisora que suena.
- Clave de solo escucha: se ven las emisoras pero no se deslizan ni hay ⏮ ⏭; una pastilla "solo escucha" lo dice.
- Radio apagada o fuera de línea: el texto lo dice ("Radio apagada · estática", "Fuera de línea"); el audio sigue
  reintentando mientras se quiera escuchar.
- Emisora sin logo: círculo de color con las iniciales.
- Volumen: `audio.volume`; en iPhone (Safari lo ignora) se pasa por un nodo de ganancia de Web Audio solo cuando se mueve
  el control, para no tocar la reproducción en segundo plano de quien no lo usa. **Sin verificar en iPhone.**
- Media Session (pantalla de bloqueo): título, emisora, logo y los botones de play/pausa y siguiente/anterior.
- Se recuerdan en el navegador la calidad y el volumen.

## Estática al cambiar de emisora

Entre elegir otra emisora y que el audio nuevo suene hay un silencio (el pedido, el buffer del stream). Se tapa con la
**misma estática que la PC** (`clips.generar_estatica`: ruido blanco con algo de grave, −24 dBFS, fundidos de 30 ms; portada a
JS y comprobada: mismo nivel, autocorrelación y picos), al volumen del control. Arranca al elegir y se apaga con el evento
`playing` del audio nuevo; tope de 12 s, y si a los 5 s de pedir el audio nuevo no sonó, se pide de nuevo. No suena con clave
de solo escucha, ni si el cambio vuelve a la emisora que ya suena, ni si se pausó.

**La señal vieja no se silencia** (ni `muted` ni volumen 0): se baja a volumen 0,1 donde se puede (no en iPhone). Chrome en
Android no cuenta como "reproduciendo" a un audio mudo: tira el control multimedia y, con la app minimizada, congela la página
(con `muted`, cambiar de emisora desde la notificación cortaba todo y nunca sintonizaba). Con la app minimizada la página sigue
sondeando el estado mientras suena, para que el título del control multimedia esté al día.

## App instalada (Android)

`/manifest.webmanifest` (`display: standalone`, `background_color` y `theme_color` `#0e0e13`, íconos de 192 y 512 y uno
*maskable* a sangre completa) y un service worker mínimo (`/sw.js`, sin `fetch` que intercepte nada: el audio en vivo no puede
pasar por ahí). Chrome ya no muestra su barra, y el splash es oscuro. Chrome da el visto bueno de instalabilidad (se comprobó
con `Page.getInstallabilityErrors`). Quien tenía un acceso directo creado antes del manifest tiene que borrarlo y volver a
instalar. El menú ⋮ trae un ítem **Instalar app** (entre la calidad y Salir) que solo aparece si Chrome ofreció instalarla
(`beforeinstallprompt`) y se esconde al usarlo o cuando la app queda instalada (`appinstalled`); Safari no tiene ese evento, así
que en iPhone no aparece. No se pidió `fullscreen`: `standalone` es lo normal (queda la barra de estado del sistema).

## Ícono

`branding/casete.png` (Flaticon, el que eligió el usuario) en blanco con la ventana de la cinta en naranja: favicon, ícono
táctil e `icon.png` del applet sobre fondo oscuro; la cabecera de la página lo usa sin fondo. Se generan con
`scripts/renderizar-icono.py`. Un primer intento con fondo naranja no gustó.

**Applet (panel), tres estados:** apagada, el casete blanco sin fondo (`casete-panel.png`); sonando, en lugar del ícono,
cuatro columnas de cuatro puntos blancos que suben y bajan (solo los prendidos se dibujan; la grilla ocupa el 62 % del alto
del ícono para dejar aire arriba y abajo; ≈ 11 cuadros por segundo, solo mientras suena; `puntos.js` y un `St.DrawingArea`
con Cairo) y al lado el nombre de la emisora; prendida pero muteada en este monitor (`monitor_local: false`), solo el nombre.
Ojo: `ReloadXlet` no vuelve a leer los módulos auxiliares (`logic.js`, `puntos.js`); si cambian, hace falta reiniciar
Cinnamon (o darles un nombre nuevo, como pasó con `barras.js` → `puntos.js`).

## Escala en la web de escritorio

Todo (CSS y geometría del dial) escala con una unidad `--u` y un factor entre 1 y 1,5 según el tamaño de la ventana
(`min(ancho / 853, alto / 480, 1.5)`), como el zoom al 150 % que el usuario probó en el navegador. En el celular el factor
es 1. El botón Salir va arriba a la derecha (en el celular, en el menú ⋮).

## Queda para después

Que el resplandor tome el color del logo; temas claros; instalarla como app.
