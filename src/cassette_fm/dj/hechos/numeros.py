"""Números y años en palabras (las plantillas no llevan dígitos: Kokoro los lee mal)."""

_UNIDADES_ES = ["cero", "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve", "diez", "once",
                "doce", "trece", "catorce", "quince", "dieciséis", "diecisiete", "dieciocho", "diecinueve",
                "veinte", "veintiuno", "veintidós", "veintitrés", "veinticuatro", "veinticinco", "veintiséis",
                "veintisiete", "veintiocho", "veintinueve"]
_DECENAS_ES = {3: "treinta", 4: "cuarenta", 5: "cincuenta", 6: "sesenta", 7: "setenta", 8: "ochenta", 9: "noventa"}
_UNIDADES_EN = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven",
                "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
_DECENAS_EN = {2: "twenty", 3: "thirty", 4: "forty", 5: "fifty", 6: "sixty", 7: "seventy", 8: "eighty", 9: "ninety"}


def _idioma(idioma: str) -> str:
    if idioma not in ("es", "en"):
        raise ValueError(f"idioma no soportado: {idioma!r}")
    return idioma


def _positivo(n: int, idioma: str) -> str:
    if idioma == "es":
        if n < 30:
            return _UNIDADES_ES[n]
        d, u = divmod(n, 10)
        return _DECENAS_ES[d] + (f" y {_UNIDADES_ES[u]}" if u else "")
    if n < 20:
        return _UNIDADES_EN[n]
    d, u = divmod(n, 10)
    return _DECENAS_EN[d] + (f" {_UNIDADES_EN[u]}" if u else "")


def en_palabras(n: int, idioma: str) -> str:
    """Enteros de −99 a 99 ("veintidós", "minus three")."""
    idioma = _idioma(idioma)
    if not -99 <= n <= 99:
        raise ValueError(f"número fuera de rango: {n}")
    texto = _positivo(abs(n), idioma)
    return (f"menos {texto}" if idioma == "es" else f"minus {texto}") if n < 0 else texto


def anio_en_palabras(a: int, idioma: str) -> str:
    """Años de 1900 a 2099 ("mil novecientos ochenta y cuatro", "nineteen eighty four")."""
    idioma = _idioma(idioma)
    if not 1900 <= a <= 2099:
        raise ValueError(f"año fuera de rango: {a}")
    resto = a % 100
    if idioma == "es":
        base = "mil novecientos" if a < 2000 else "dos mil"
        return base if resto == 0 else f"{base} {_positivo(resto, 'es')}"
    if a < 2000:
        if resto == 0:
            return "nineteen hundred"
        return f"nineteen oh {_positivo(resto, 'en')}" if resto < 10 else f"nineteen {_positivo(resto, 'en')}"
    if resto == 0:
        return "two thousand"
    if resto < 10:
        return f"two thousand {_positivo(resto, 'en')}"
    return f"twenty {_positivo(resto, 'en')}"
