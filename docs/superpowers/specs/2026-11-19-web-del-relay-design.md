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

Entre elegir otra emisora y que el audio nuevo suene hay un silencio (el pedido, el buffer del stream). Se tapa con
estática generada en el navegador (Web Audio: ruido blanco con chisporroteo, filtrado, al volumen del control × 0,22).
Arranca al elegir (con el audio viejo silenciado), se apaga con el evento `playing` del audio nuevo y tiene un tope de
8 s. No suena con clave de solo escucha (no puede cambiar), ni si el cambio vuelve a la emisora que ya suena, ni si se
pausó. En iPhone el contexto de audio se crea en el primer cambio (hace falta un gesto) y se suspende al terminar.

## Ícono

`branding/casete.png` (Flaticon, el que eligió el usuario) sobre un cuadrado naranja: favicon, ícono táctil y ícono del
applet, generados con `scripts/renderizar-icono.py`. La cabecera de la página usa el mismo PNG como máscara, en blanco.

## Queda para después

Que el resplandor tome el color del logo; temas claros; instalarla como app.
