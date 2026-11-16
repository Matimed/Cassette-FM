---
# CASSETTE-FM-49ga
title: Bucle de re-sintonía con un tema que Soloist no puede reproducir
status: completed
type: bug
priority: high
created_at: 2026-11-16T03:08:36Z
updated_at: 2026-11-16T13:28:20Z
---

2026-11-16 00:06 en Happy Eighties (playlist de Spotify): 'The Power Of Love' (spotify:track:49zeNqC8dkKofXLqG9kFTr) figura reproducible en la API (market=from_token) pero Soloist lo saltea a los ~15 ms, sin error en su log. La radio ve a Spotify ~230 s adelantado y re-sintoniza al lugar de ese tema cada ~2 s mientras dura su hueco (tartamudeo). Propuesta: si tras una (re)sintonía Soloist pasa del tema pedido al siguiente en menos de 1-2 s, anotarlo como no reproducible (persistente), no re-sintonizar hacia él y excluirlo de la emisora en el próximo rescan.



Segundo caso (2026-11-16 00:17:45, Pop Hits F.M.): en un cambio natural de tema Soloist registró 'FRIENDS' en [0:05] y saltó en 1,5 s por Lights, Hello e I Don't Care, sin error en su log; la radio re-sintonizó y FRIENDS sonó bien. O sea que no siempre es un tema irreproducible: a veces Soloist falla al cargar el siguiente. Antes de arreglar, mirar el log de Soloist con más detalle (¿nivel debug?) y si un reinicio de cassette-soloist lo cambia.



Tercer caso (2026-11-16 00:55:46, Happy Eighties): la radio pide 'I Ran (So Far Away)' en 3:34 (Soloist dice que dura 5:08) y Soloist pasa al siguiente en <1 s, en bucle cada ~0,8 s. Hipótesis: el audio que Soloist tiene de algunos temas es más corto que la duración de los metadatos (versión relinkeada/alternativa), y pedirlo pasado ese largo lo termina al instante. Con la sintonía más rápida (a0d17ba) cada vuelta del bucle dura menos.



Resuelto (5b6599c, 5860ddc): la causa está en Soloist (falla de a ratos al cargar algunos temas) y no se puede arreglar desde la radio. La radio acepta los saltos: un cambio de tema a menos de 2 s del anterior corre la agenda en vez de re-sintonizar, y otra versión del tema esperado cuenta como ese tema. Prueba real 2026-11-16: salteos forzados (uno y tres seguidos) aceptados sin re-sintonía, un salto lento re-sintoniza una vez, y a las 10:18:17 en Happy Eighties Soloist salteó solo Queen, Guns N' Roses y The Beatles en 1,5 s: la radio siguió desde Whitney Houston sin ninguna re-sintonía.
