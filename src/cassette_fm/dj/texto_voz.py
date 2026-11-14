"""Prepara el texto del DJ para la voz (reglas de docs/relevamiento/texto-para-voz.md)."""
import re
from collections.abc import Callable
from dataclasses import dataclass

_MARCA = re.compile(r"\{([A-Za-z]{2,3}(?:-[A-Za-z]{2,3})?):([^{}]*)\}")
_COMILLAS = '"“”'
_INICIO, _FIN = "", ""        # delimitan un nombre marcado mientras se limpia la puntuación
_HOLDER = re.compile(f"{_INICIO}(\\d+){_FIN}")
_SEPARADORES = ",;:—–"


@dataclass(frozen=True)
class Preparado:
    texto: str       # lo que se dice, limpio y sin marcas de idioma
    marcado: str     # el texto limpio con las marcas {lang:Nombre}: se puede volver a sintetizar tal cual
    fonemas: str     # lo que se le pasa a Kokoro con is_phonemes=True


def marcar(nombre: str, lang: str) -> str:
    limpio = re.sub(r"[{}" + _COMILLAS + "]", "", nombre)
    limpio = re.sub(r"\s+", " ", limpio).strip()
    if not limpio:
        raise ValueError("el nombre está vacío")
    return "{" + lang + ":" + limpio + "}"


def tramos(marcado: str, lang_base: str) -> list[tuple[str, str]]:
    salida = []
    cursor = 0
    for m in _MARCA.finditer(marcado):
        resto = marcado[cursor:m.start()].strip()
        if resto:
            salida.append((resto, lang_base))
        nombre = m.group(2).strip()
        if nombre:
            salida.append((nombre, m.group(1)))
        cursor = m.end()
    resto = marcado[cursor:].strip()
    if resto:
        salida.append((resto, lang_base))
    return salida


def aplicar_seseo(fonemas: str) -> str:
    return fonemas.replace("θ", "s")


def _y(lang_base: str) -> str:
    return "and" if lang_base.lower().startswith("en") else "y"


def _palabras(fragmento: str, nombres: list[str]) -> int:
    total = 0
    for token in fragmento.split():
        m = _HOLDER.search(token)
        if m:
            total += max(1, len(nombres[int(m.group(1))].split()))
        elif any(c.isalnum() for c in token):
            total += 1
    return total


def _minuscula_inicial(oracion: str) -> str:
    if oracion and oracion[0].isalpha():
        return oracion[0].lower() + oracion[1:]
    return oracion


def _unir(anterior: str, siguiente: str) -> str:
    return f"{re.sub(r'[.?]+$', '', anterior).rstrip()} {_minuscula_inicial(siguiente)}"


def limpiar(marcado: str, lang_base: str, minimo_palabras: int = 4) -> str:
    nombres: list[str] = []
    marcado = marcado.replace(_INICIO, "").replace(_FIN, "")     # no se pueden inyectar los marcadores internos

    def guardar(m: re.Match) -> str:
        nombre = re.sub("[" + _COMILLAS + "]", "", m.group(2))
        nombre = re.sub(r"\s*&\s*", f" {_y(m.group(1))} ", nombre)     # "and"/"y" según el idioma del NOMBRE
        # Kokoro trata . ! ? , ; : como marcas de pausa también adentro de un nombre ("Mr. Big", "Panic! At...")
        nombre = re.sub(r"[¡¿!?.,;:—–]", " ", nombre)
        nombre = re.sub(r"\s+", " ", nombre).strip()
        if not any(c.isalnum() for c in nombre):
            return " "
        nombres.append("{" + m.group(1) + ":" + nombre + "}")
        return f" {_INICIO}{len(nombres) - 1}{_FIN} "

    t = _MARCA.sub(guardar, marcado)
    nombres_planos = [re.sub(r"^\{[^:]*:|\}$", "", n) for n in nombres]
    t = t.replace("¡", "").replace("¿", "").replace("!", ".")
    t = re.sub("[" + _COMILLAS + "]", "", t)
    t = re.sub(r"(?<=\w)[‘’](?=\w)", "'", t)
    t = re.sub(r"[‘’]", "", t)
    t = re.sub(r"\s*&\s*", f" {_y(lang_base)} ", t)
    t = t.replace("…", ".")
    t = re.sub(r"\.{2,}", ".", t)
    t = re.sub(r"\s+", " ", t).strip()
    if not t:
        return ""

    oraciones = []
    for o in re.split(r"(?<=[.?])\s+", t):
        marca = re.search(r"[.?]+$", o)
        final = marca.group(0)[-1] if marca else ""
        cuerpo = o[:marca.start()] if marca else o
        partes = re.split(r"\s*([" + re.escape(_SEPARADORES) + r"])\s*", cuerpo)
        clausulas = [c.strip() for c in partes[0::2] if c.strip()]
        if not clausulas:
            continue
        armada = clausulas[0]
        for izq, der in zip(clausulas, clausulas[1:]):
            largas = (_palabras(izq, nombres_planos) >= minimo_palabras
                      and _palabras(der, nombres_planos) >= minimo_palabras)
            armada += (", " if largas else " ") + der
        oraciones.append(armada + final)

    while len(oraciones) > 1:
        corta = next((i for i, o in enumerate(oraciones) if _palabras(o, nombres_planos) < minimo_palabras), None)
        if corta is None:
            break
        if corta > 0:
            oraciones[corta - 1:corta + 1] = [_unir(oraciones[corta - 1], oraciones[corta])]
        else:
            oraciones[0:2] = [_unir(oraciones[0], oraciones[1])]

    if not oraciones:
        return ""
    if not re.search(r"[.?]$", oraciones[-1]):
        oraciones[-1] += "."
    texto = " ".join(oraciones)
    texto = re.sub(r"\s+([.?,])", r"\1", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    return _HOLDER.sub(lambda m: nombres[int(m.group(1))], texto)


def preparar(marcado: str, lang_base: str, fonemizar: Callable[[str, str], str],
             minimo_palabras: int = 4) -> Preparado:
    limpio = limpiar(marcado, lang_base, minimo_palabras)
    # los tramos contiguos del mismo idioma se fonemizan juntos: por separado, una palabra suelta ("de") sale
    # acentuada y se oye una pausa antes del nombre
    unidos: list[list[str]] = []
    for texto, lang in tramos(limpio, lang_base):
        if unidos and unidos[-1][1] == lang:
            unidos[-1][0] += " " + texto
        else:
            unidos.append([texto, lang])
    trozos = []
    for texto, lang in unidos:
        fon = fonemizar(texto, lang)
        trozos.append(aplicar_seseo(fon) if lang == "es" else fon)
    return Preparado(texto=_MARCA.sub(lambda m: m.group(2), limpio), marcado=limpio, fonemas=" ".join(trozos))


def texto_para_piper(marcado: str) -> str:
    """El texto limpio con una coma donde se respira, para motores que no hacen pausas solos (Piper).

    Una sola por oración: después del último nombre marcado, si la oración tiene al menos dos nombres y todavía le
    siguen dos palabras o más (la cola: "…de Dadi Yanki, para todos nosotros"). Más comas suenan entrecortadas."""
    salida = []
    for oracion in re.split(r"(?<=[.?])\s+", marcado.strip()):
        marcas = list(_MARCA.finditer(oracion))
        if len(marcas) >= 2:
            ultima = marcas[-1]
            cola = [w for w in oracion[ultima.end():].split() if any(c.isalnum() for c in w)]
            if len(cola) >= 2 and not oracion[ultima.end():].lstrip().startswith(","):
                oracion = oracion[:ultima.end()] + "," + oracion[ultima.end():]
        salida.append(_MARCA.sub(lambda m: m.group(2).strip(), oracion))
    return re.sub(r"\s+", " ", " ".join(salida)).strip()
