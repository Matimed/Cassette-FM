---
# CASSETTE-FM-ta67
title: Apagar la radio sola cuando no hay oyentes y despertarla al volver uno
status: todo
type: feature
created_at: 2026-11-20T05:11:07Z
updated_at: 2026-11-20T05:11:07Z
parent: CASSETTE-FM-abja
blocked_by:
    - CASSETTE-FM-u8ea
---

Si no queda ningún oyente (ni local, ni por /stream web, ni applet remoto) la reproducción se detiene igual que al apagar, para no dejar Spotify sonando en silencio gastando recursos. Lo inverso: si cualquiera de esas fuentes se conecta con la radio apagada, el servicio se despierta y sintoniza. Hay que definir qué cuenta como oyente (cliente local del applet/CLI, conexiones abiertas a /stream, receptores remotos) y un margen de gracia antes de apagar para evitar cortes por reconexiones.
