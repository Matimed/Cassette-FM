# La radio acepta los temas que Soloist saltea

Diseño corto, aprobado por el usuario el 2026-11-16. Beans CASSETTE-FM-49ga.

## Qué pasa

Con algunos temas (The Power Of Love, I Ran, Lose Yourself, ROXANNE… en Happy Eighties y Pop Hits) Soloist a veces
no logra cargar el audio: los arranca y en <1 s pasa al siguiente de la lista. Es intermitente y no depende de la
posición pedida ni de si el play viene por la Web API o por el WebSocket (experimentos del 2026-11-16); a veces
Soloist toca otra versión del tema (otra URI, p. ej. «The Power Of Love – From "Back To The Future" Soundtrack»).
La Web API los da por reproducibles. No se puede arreglar desde la radio; lo que sí: la radio reaccionaba
re-sintonizando hacia el tema que falla, en bucle mientras dura su hueco (tirones cada 1–2 s).

## Diseño

1. **Salteo aceptado.** Si llega un `track_changed` de un tema de la agenda a menos de `SALTEO_SEGUNDOS` (2 s) del
   anterior, distinto de él, y la emisora no tiene pedidos en curso, la radio acepta el salto en vez de re-sintonizar:
   busca ese tema en las próximas transiciones de la agenda y corre el corrimiento para que empiece *ahora*
   (corrimiento −= cuánto faltaba). Avisa el cambio de agenda (se guarda; el planificador lo ve) y loguea
   «Soloist salteó …». Si no lo encuentra en las próximas transiciones, sigue como hoy (re-sintoniza).
2. **Otra versión del tema esperado.** Si llega un `track_changed` de una URI que no es de la emisora ni un pedido, y
   su nombre empieza con el nombre del tema que la radio esperaba en ese momento (el esperado de la sintonía, o el que
   la agenda tiene sonando ahora), se toma como ese tema (para el desfase, el DJ y el estado).

- Los saltos manuales rápidos desde la app (<2 s) también se aceptan: la radio sigue lo que suena en vez de volver.
- **Descartado:** marcar los temas como irreproducibles y sacarlos de la emisora (la falla es intermitente: el mismo
  tema suena bien otras veces).
