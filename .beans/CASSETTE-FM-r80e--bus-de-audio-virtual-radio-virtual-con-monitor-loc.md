---
# CASSETTE-FM-r80e
title: Bus de audio virtual radio_virtual con monitor local y volumen de radio
status: todo
type: feature
created_at: 2026-11-18T04:04:28Z
updated_at: 2026-11-18T04:04:28Z
parent: CASSETTE-FM-abja
---

cassette-fm es dueño de un bus (`AudioRouter`, ya escrito en `src/cassette_fm/audio_router.py`): el audio de mpv (música y voz) y de Soloist sale a `radio_virtual`, y lo que se oye en los parlantes es un monitor local (module-loopback) conmutable y con volumen propio. Base de la radio en red: cada monitor tiene su propio volumen.

Verificado el 2026-11-18: mpv necesita `--ao=pulse` + `PULSE_SINK`; Soloist (cliente PipeWire nativo) ignora `PULSE_SINK` y necesita `PIPEWIRE_NODE=radio_virtual` en su unit, con `PartOf`/`After` cassette-fm.service.

Falta: integrar en `servicio.py` y `ClienteMpv` (env); que `radio.volumen` pase a ser el volumen del monitor y las fuentes queden al 100 % salvo ducking y calibración; `POST /monitor` y `monitor_local` en `/estado`; toggle en el applet; unit de Soloist.
