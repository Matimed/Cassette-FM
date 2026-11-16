---
# CASSETTE-FM-49ga
title: Bucle de re-sintonía con un tema que Soloist no puede reproducir
status: todo
type: bug
priority: high
created_at: 2026-11-16T03:08:36Z
updated_at: 2026-11-16T03:18:35Z
---

2026-11-16 00:06 en Happy Eighties (playlist de Spotify): 'The Power Of Love' (spotify:track:49zeNqC8dkKofXLqG9kFTr) figura reproducible en la API (market=from_token) pero Soloist lo saltea a los ~15 ms, sin error en su log. La radio ve a Spotify ~230 s adelantado y re-sintoniza al lugar de ese tema cada ~2 s mientras dura su hueco (tartamudeo). Propuesta: si tras una (re)sintonía Soloist pasa del tema pedido al siguiente en menos de 1-2 s, anotarlo como no reproducible (persistente), no re-sintonizar hacia él y excluirlo de la emisora en el próximo rescan.



Segundo caso (2026-11-16 00:17:45, Pop Hits F.M.): en un cambio natural de tema Soloist registró 'FRIENDS' en [0:05] y saltó en 1,5 s por Lights, Hello e I Don't Care, sin error en su log; la radio re-sintonizó y FRIENDS sonó bien. O sea que no siempre es un tema irreproducible: a veces Soloist falla al cargar el siguiente. Antes de arreglar, mirar el log de Soloist con más detalle (¿nivel debug?) y si un reinicio de cassette-soloist lo cambia.
