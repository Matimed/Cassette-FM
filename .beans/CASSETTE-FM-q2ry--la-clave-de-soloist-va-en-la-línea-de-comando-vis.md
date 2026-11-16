---
# CASSETTE-FM-q2ry
title: La clave de Soloist va en la línea de comando (visible con ps)
status: todo
type: bug
priority: high
created_at: 2026-11-16T03:25:51Z
updated_at: 2026-11-16T03:25:51Z
---

cassette-soloist.service pasa la clave con -k "$(cat soloist.key)": queda en los argumentos del proceso, visible para cualquier usuario local con ps y en systemctl status (así se filtró una vez el 2026-11-16; el usuario la rotó). Ver si Soloist la acepta por variable de entorno o archivo y cambiar la unidad.
