---
# CASSETTE-FM-ta67
title: Radio por oyentes, se duerme sola sin oyentes y la despierta el primero que llega
status: in-progress
type: feature
created_at: 2026-11-20T05:11:07Z
updated_at: 2026-11-20T05:11:07Z
parent: CASSETTE-FM-abja
blocked_by:
    - CASSETTE-FM-u8ea
---

La radio pasa a ser un servicio que cualquier consumidor puede despertar y que se duerme sola cuando no tiene oyentes; esta PC es un oyente más, sin un "apagar" propio. El único apagado definitivo es `cassette stop` (`systemctl`).

- Oyente = monitor local prendido + conexiones de audio abiertas (LAN y nube). Volumen en 0 = dejé de escuchar, en todas las interfaces (receptor remoto incluido).
- Sin oyentes durante `segundos_hasta_dormir` (60 s) la radio se duerme; abrir un stream o elegir emisora con cero oyentes la despierta y te vuelve el primer oyente (volumen mínimo 50). Con otro oyente, next/prev/rueda solo cambian la emisora.
- Se quitan `/apagar`, `cassette off` y "Apagar" del applet; `cassette stop`/`start` apagan y levantan radio, Soloist, DJ y Ollama; `cassette on` y el clic del applet levantan el servicio caído.

Diseño: docs/superpowers/specs/2026-11-20-radio-por-oyentes-design.md. Plan: docs/superpowers/plans/2026-11-20-radio-por-oyentes.md.
