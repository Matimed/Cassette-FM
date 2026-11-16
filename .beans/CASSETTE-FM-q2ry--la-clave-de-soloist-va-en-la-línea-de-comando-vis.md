---
# CASSETTE-FM-q2ry
title: La clave de Soloist va en la línea de comando (visible con ps)
status: completed
type: bug
priority: high
created_at: 2026-11-16T03:25:51Z
updated_at: 2026-11-16T03:40:29Z
---

cassette-soloist.service pasa la clave con -k "$(cat soloist.key)": queda en los argumentos del proceso, visible para cualquier usuario local con ps y en systemctl status (así se filtró una vez el 2026-11-16; el usuario la rotó). Ver si Soloist la acepta por variable de entorno o archivo y cambiar la unidad.



Decisión del usuario (2026-11-16): se deja como está. Soloist solo acepta la clave por -k (sin variable de entorno ni archivo); se descartó un shim LD_PRELOAD. Regla: no correr comandos que muestren la línea de comando de Soloist (systemctl status, ps con argumentos, /proc/<pid>/cmdline); usar is-active, show -p ActiveEnterTimestamp y journalctl.
