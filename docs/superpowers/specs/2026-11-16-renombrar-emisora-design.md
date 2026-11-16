# Renombrar una emisora con un comando

Diseño corto, aprobado por el usuario el 2026-11-16. Hermano de [`cassette borrar`](2026-11-16-borrar-emisora-design.md).

## Para qué

Cambiarle el nombre a una emisora sin editar `estaciones.json`: `cassette renombrar "sing" "Cantemos"`.

## Enfoques

- **Renombrar simple** (elegido): cambia el nombre y listo. Como el orden de los temas sale del nombre
  (`agenda.py`), la emisora queda en otro punto y con otro orden; el corrimiento de los pedidos (guardado por nombre)
  se pierde. Al usuario no le importa.
- **Conservar el orden:** guardar aparte el nombre del que sale el orden y que el servicio mude la agenda al nombre
  nuevo. Mucho más trabajo para algo que no importa.

## Diseño

```
$ cassette renombrar "sing" "Cantemos"
✎ Sing → Cantemos
▶ Cantemos · Spotify (vol 60)
```

1. **Buscar** la emisora como `cassette borrar` (sin mayúsculas ni espacios alrededor; si no existe, error con las
   que hay). **Nombre nuevo:** sin espacios alrededor, no vacío y que no lo tenga otra emisora (cambiar solo las
   mayúsculas de la misma vale). Si queda idéntico: `«Sing» ya se llama así.` y sale con 0 sin tocar nada.
2. **No pregunta** (no se pierde nada importante).
3. **Guardar** con la escritura atómica de siempre; los demás campos y el orden de la lista no cambian.
4. **Radio:** antes de guardar se pide `GET /estado` para saber si sonaba esa emisora; después `POST /rescan` y, si
   sonaba, `POST /sintonizar` con el nombre nuevo (el rescan sola la mandaría a la primera). Se imprime el estado
   final. Radio sin correr → `La radio no está corriendo: el cambio se ve al prenderla.` y 0; otro error → stderr y 1.

**Fuera:** conservar el orden o el corrimiento; renombrar desde el applet.
