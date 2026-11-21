---
name: adaptar-iconos
description: Separa y adapta los logos de emisoras de cassette-fm a partir de una foto o imagen con uno o varios íconos, y los deja como PNG de 512 px con fondo transparente en ~/.config/cassette-fm/iconos/. Usala siempre que el usuario pase una imagen con logos, íconos, escudos o stickers de emisoras ("nuevos iconos", "separalos", "recortá estos logos", "dejalos en mi carpeta de iconos", "adaptá este ícono"), aunque no nombre la skill ni diga "recortar".
---

# Adaptar íconos de emisoras

El usuario genera los logos de las emisoras con IA y los pasa juntos en una sola imagen (hasta ahora, tres o seis
sobre un fondo oscuro). El dial de cassette-fm necesita cada logo por separado: **PNG cuadrado de 512 px, RGBA, fondo
transparente**, en `~/.config/cassette-fm/iconos/`. Esa es la carpeta donde viven los logos del usuario; en el repo
solo está el genérico del applet (`applet/cassette-fm@cassette-fm/icon.png`), que no se toca.

El recorte sigue el borde real de cada logo y no un círculo, porque varios tienen partes que salen del círculo
(llamas, cadenas, rayos, gotas). Un recorte circular los mutilaría.

## Pasos

1. **Ubicar la imagen.** Si el usuario la pegó en el chat, el sistema indica su ruta (`source: /tmp/.../images/N.jpg`);
   usá esa. Si la dio por ruta, usá la ruta.
2. **Decidir los nombres.** Un nombre de archivo por logo, en minúsculas, sin tildes y con guiones, sacado del texto
   del logo ("FRECUENCIA GRIS" → `frecuencia-gris`, "LETS RAVE F.M." → `lets-rave`, "Power F.M." → `power`; se omite el
   "F.M."). Si algún logo no tiene texto o el nombre es dudoso, preguntale al usuario. Se numeran de izquierda a
   derecha y, si hay varias filas, de arriba hacia abajo: los nombres tienen que ir en ese orden.
3. **Correr el script** con el python del sistema (el `.venv` del proyecto no tiene Pillow ni scipy). Primero a una
   carpeta de prueba, para ver el resultado antes de tocar la carpeta real:

   ```bash
   /usr/bin/python3 .claude/skills/adaptar-iconos/scripts/recortar_iconos.py IMAGEN \
       --nombres a,b,c --salida "$SCRATCHPAD/iconos" --previa "$SCRATCHPAD/previa"
   ```

   (`$SCRATCHPAD` es el directorio temporal de la sesión.) Detecta el fondo solo, así que sirve para fondos oscuros y
   claros. Si el script dice que detectó otra cantidad de logos que de nombres, mirá la imagen y ajustá `--cantidad`
   o `--umbral` (más bajo si se pierden partes tenues del logo, más alto si se cuela ruido del fondo).
4. **Revisar a ojo.** Abrí `previa/tira.png` con Read (muestra los logos sobre gris, donde se ve cualquier resto de
   fondo o mordida en el borde). Mirá en particular:
   - que no falten partes que salen del círculo ni queden pedazos de otro logo;
   - que el borde no tenga un halo raro. El contorno negro del sticker se conserva a propósito (`--contorno`, 8 por
     defecto en fondo oscuro): se funde con el dial oscuro y se ve como un borde fino sobre fondo claro. Si molesta,
     probá `--contorno 3`.
   Si algo falla, reintentá con otros parámetros; si queda un defecto que el script no resuelve (por ejemplo las
   gotas sueltas de un logo), decíselo al usuario y ofrecele retocarlo en lugar de esconderlo.
5. **Dejarlos en la carpeta real.** Corré el mismo comando sin `--salida` (usa `~/.config/cassette-fm/iconos/`). El
   script se niega a pisar un archivo existente; si el nombre ya está, preguntá si es una versión nueva (`--sobrescribir`)
   o conviene otro nombre. Verificá con `file ~/.config/cassette-fm/iconos/*.png` que sean 512×512 RGBA.
6. **Informar** qué archivos quedaron y qué defectos tienen, si alguno. No los asignes a una emisora por tu cuenta: el
   usuario no siempre tiene la emisora creada. Si la emisora existe en `~/.config/cassette-fm/estaciones.json`,
   ofrecé correr `cassette icono "Emisora" iconos/<archivo>.png`; si no existe, avisá cuáles faltan y que cuando las
   cree el comando es ese (o `cassette nueva --icono`).

## Notas

- Si la imagen trae logos que ya están hechos y el usuario quiere solo alguno, el script igual necesita un nombre por
  cada logo detectado: corrélo a una carpeta de prueba con nombres de relleno (`x1,x2,nombre-real`) y copiá solo el
  que sirve a `~/.config/cassette-fm/iconos/`.
- Un solo logo en la imagen funciona igual (`--nombres uno`). El logo genérico del applet, si el usuario lo pide, sale
  del mismo recorte pero va a `applet/cassette-fm@cassette-fm/icon.png` (`--salida` a una carpeta de prueba y copiar).
- Los logos ya existentes de la carpeta no se tocan. No hace falta commitear nada: `~/.config` queda fuera del repo.
- Contexto de diseño: `docs/superpowers/specs/2026-11-16-dial-de-emisoras-design.md`, sección "Recorte de los seis logos".
