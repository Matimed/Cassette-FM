---
# CASSETTE-FM-u8ea
title: 'Radio por la LAN: stream HTTP del bus, receptor liviano y applet remoto'
status: todo
type: feature
created_at: 2026-11-18T05:05:14Z
updated_at: 2026-11-18T05:05:14Z
parent: CASSETTE-FM-abja
---

Una segunda PC propia escucha la radio de esta (misma transmisión, volumen y encendido propios) con el mismo applet y sin backend. Servidor en :8765 (por defecto en la IP de Tailscale) con /status, /station/{id}, /stream (MP3 del bus; estática si la radio está apagada) y /icon/{id}; clave Bearer; `lan_receiver.py` (stdlib + mpv) dentro de la carpeta del applet; modo remoto del applet (is_remote, server_url, server_token). Diseño: docs/superpowers/specs/2026-11-18-radio-lan-design.md. Base: bus de audio (CASSETTE-FM-r80e). Los logos son la última etapa, separable.
