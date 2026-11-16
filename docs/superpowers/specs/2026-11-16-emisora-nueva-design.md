# Crear una emisora de Spotify con un comando

Diseño corto, aprobado por el usuario el 2026-11-16.

## Para qué

Armar una emisora nueva en segundos: un link de playlist y un nombre, y queda sonando con un DJ de voz propia. Hoy es
editar `estaciones.json` a mano, elegir voz e idioma y correr el rescan. Segundo paso (aparte, después): un botón en
el listado de emisoras del applet que abra un modal con estas mismas opciones; por eso la lógica va en un módulo
propio que el comando usa y que el applet podrá invocar por la línea de comando.

## Enfoques

- **El comando `cassette` hace todo** (elegido): valida la playlist con la API, elige la voz, agrega la emisora a
  `estaciones.json` y le pide a la radio el rescan y la sintonía que ya existen. El servicio no cambia.
- **Una orden nueva del servicio** que haga lo mismo: útil si el applet no pudiera correr comandos; hoy es más código
  sin ganancia (el applet ya corre `cassette`).

## Diseño

```
cassette nueva "Synthwave F.M." https://open.spotify.com/playlist/…  [--voz sarah] [--idioma es]
✓ Synthwave F.M. (87 temas) · DJ: jessica (en)
▶ Synthwave F.M. · Spotify (vol 60)
```

1. **Validar antes de escribir nada:** el nombre no puede repetir otra emisora (sin distinguir mayúsculas, como
   `leer_emisoras`); el link tiene que ser de una playlist (`playlist_de`); Spotify tiene que dejar leerla y no puede
   estar vacía. Se baja con el catálogo de Spotify (el mismo de `cassette spotify estado`), que la deja en la caché:
   el rescan de la radio después no la vuelve a bajar.
2. **Voz:** al azar entre los alias de `[voces]` de `~/.config/cassette-dj/config.toml` que no use ninguna emisora
   (`dj.voz` en `estaciones.json`). `--idioma es|en` filtra por idioma; `--voz X` la elige (un alias o un nombre de
   voz crudo). Si todos los alias del idioma están en uso, repite uno de los menos usados y lo avisa. Sin alias
   válidos: error que dice dónde se definen.
3. **Idioma del DJ, deducido de la voz** (resuelta por el alias; en una mezcla `a+b`, la primera): Kokoro `a?_` →
   `en`, `b?_` → `en-gb`, `e?_` → `es`; Piper `piper:es_…` → `es`, `piper:en_GB…` → `en-gb`, `piper:en_…` → `en`.
   Otras (francés, japonés…) no sirven: la radio solo habla inglés y español. Con `--voz` y `--idioma` que no
   coinciden, error.
4. **Guardar:** se agrega `{"nombre", "fuente": {"spotify": <link tal cual>}, "dj": {"idioma", "voz"}}` al final de
   `estaciones.json`, reescrito entero con `json.dumps(…, ensure_ascii=False, indent=2)` y escritura atómica (se
   pierden detalles de formato a mano, no contenido). Si el archivo no existe o está roto, error sin tocarlo.
5. **Rescan y sintonía:** `POST /rescan` y después `POST /sintonizar` con el nombre; se imprimen las dos líneas. Si la
   radio no está corriendo, la emisora queda guardada y el mensaje dice que aparece al arrancarla.

**Fuera:** emisoras de carpetas locales, editar o borrar emisoras, velocidad y personalidad (se editan a mano).
