---
# CASSETTE-FM-le4x
title: Aviso de escritorio solo al cambiar de radio, no de tema
status: completed
type: task
priority: normal
created_at: 2026-11-14T05:25:16Z
updated_at: 2026-11-18T02:53:38Z
---

La notificación en cada cambio de tema hace ruido. Dejar el aviso solo al sintonizar otra estación (el nombre del tema se ve yendo y volviendo, o con cassette status). Idealmente con una opción en config.toml (avisos_tema = false por defecto). Toca avisos.py, radio.py (_al_cambiar_pista) y el README. Pedido del usuario el 14/11.



## Resuelto
Commit 4b46556: los avisos de escritorio vienen apagados (`avisos = true` en la config los prende); no hay aviso por tema ni por cambio de emisora.
