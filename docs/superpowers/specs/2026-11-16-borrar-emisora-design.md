# Borrar una emisora con un comando

Diseño corto, aprobado por el usuario el 2026-11-16. Complementa a [`cassette nueva`](2026-11-16-emisora-nueva-design.md).

## Para qué

Sacar una emisora sin editar `estaciones.json` a mano: `cassette borrar "sing"`. Sin interfaz en el applet.

## Enfoques

- **Que pregunte antes de borrar** (elegido por el usuario): `¿Borro «Sing» (Spotify)? (s/N)`; `--si` no pregunta.
  Un error de tipeo no borra nada, y una emisora de carpeta o con ajustes del DJ a mano cuesta rearmarla.
- **Borrar directo:** más rápido, sin red de seguridad.

## Diseño

```
$ cassette borrar "sing"
¿Borro «Sing» (Spotify)? (s/N) s
✗ Sing · ya no está en estaciones.json
▶ Happy Eighties · Spotify (vol 60)
```

1. **Buscar** por nombre sin distinguir mayúsculas ni espacios alrededor (NFC + casefold, como el chequeo de nombre
   repetido de `cassette nueva`). Si no existe: error que lista las emisoras que hay. Si el archivo no existe o está
   roto: error sin tocarlo. Las otras emisoras no se validan (la que se borra puede ser justo la rota).
2. **Confirmar:** `¿Borro «Nombre» (Spotify | carpeta <ruta>)? (s/N)`; sirven `s`, `si`, `sí`, `y`, `yes` (sin
   mayúsculas); cualquier otra cosa → `No se borró nada.` y sale con 1. Sin terminal (stdin no es una tty) y sin
   `--si` → error que pide `--si` (no se queda esperando).
3. **Guardar:** el resto de las emisoras tal cual, con la misma escritura atómica de `cassette nueva`.
4. **Rescan:** `POST /rescan` e imprimir el estado (si sonaba la borrada, la radio pasa a la primera; sin emisoras, se
   apaga: ya lo hace `Radio.rescan`). Radio sin correr → `La radio no está corriendo: el cambio se ve al prenderla.`
   y sale con 0; otro error → por stderr y 1.

**Fuera:** la caché de Spotify (otra emisora puede usar la misma playlist), los guiones y clips del DJ, la carpeta de
música. Interfaz en el applet.
