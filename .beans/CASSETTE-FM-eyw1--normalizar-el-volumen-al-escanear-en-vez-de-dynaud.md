---
# CASSETTE-FM-eyw1
title: Normalizar el volumen al escanear (en vez de dynaudnorm en vivo)
status: todo
type: task
created_at: 2026-11-14T05:25:16Z
updated_at: 2026-11-14T05:25:16Z
---

dynaudnorm en vivo (por CPU, en mpv) a veces mete artefactos raros. Opción 2 de la discusión original: calcular la ganancia de cada tema al escanear la biblioteca (ReplayGain/loudnorm de pasada única o dos pasadas), guardarla en la caché de duraciones.json y aplicarla por tema con mpv (replaygain-fallback / af volume) sin filtro en vivo. Afecta biblioteca.py (caché), reproductor.py/mpv.py y la voz del DJ, que hoy se ajusta con ganancia_voz_db contra la música normalizada. Pedido del usuario el 14/11.
