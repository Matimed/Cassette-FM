import random
import re
from zoneinfo import ZoneInfo
from datetime import datetime, timedelta, timezone

import pytest

from cassette_fm.dj.lexico import Lexico
from cassette_fm.dj.pedido import Pedido, Tema
from cassette_fm.dj.plantillas import Redaccion, frase_hora, redactar, titulo_hablado
from cassette_fm.dj.texto_voz import limpiar

ZONA = timezone(timedelta(hours=-3))
MARCA = re.compile(r"\{([A-Za-z-]+):([^{}]*)\}")


def a(h, m):
    return datetime(2026, 11, 13, h, m, tzinfo=ZONA)


def pedido(idioma="es", album=True, anterior=True, momento=None, siguiente=("Foreigner", "Waiting for a Girl Like You")):
    return Pedido(
        id="x", estacion="Lentos", idioma=idioma, voz="v", momento=momento or a(21, 47),
        anterior=Tema("Whitesnake", "Is This Love", "Slip of the Tongue") if anterior else None,
        siguiente=Tema(siguiente[0], siguiente[1], "Records" if album else None),
    )


def palabras(r):
    return len(MARCA.sub(lambda m: m.group(2), r.marcado).split())


# --- frase_hora ---

@pytest.mark.parametrize("h,m,esperado", [
    (9, 0, "las nueve en punto"), (9, 2, "las nueve en punto"), (9, 3, "las nueve y cinco"),
    (9, 30, "las nueve y media"), (9, 47, "las diez menos cuarto"), (9, 48, "las diez menos diez"),
    (9, 53, "las diez menos cinco"), (9, 58, "las diez en punto"), (13, 0, "la una en punto"),
    (0, 0, "las doce en punto"), (12, 15, "las doce y cuarto"), (23, 50, "las doce menos diez"),
    (12, 50, "la una menos diez"), (9, 10, "las nueve y diez"), (9, 20, "las nueve y veinte"),
    (9, 25, "las nueve y veinticinco"), (9, 35, "las diez menos veinticinco"), (9, 40, "las diez menos veinte"),
])
def test_frase_hora_es(h, m, esperado):
    assert frase_hora(a(h, m), "es") == esperado


@pytest.mark.parametrize("h,m,esperado", [
    (9, 0, "nine o'clock"), (9, 15, "quarter past nine"), (9, 30, "half past nine"),
    (9, 45, "quarter to ten"), (21, 50, "ten to ten"), (23, 58, "twelve o'clock"),
    (9, 5, "five past nine"), (9, 25, "twenty five past nine"), (9, 35, "twenty five to ten"),
])
def test_frase_hora_en(h, m, esperado):
    for idioma in ("en", "en-us", "en-gb"):
        assert frase_hora(a(h, m), idioma) == esperado


def test_nunca_hay_digitos_en_la_hora():
    for idioma in ("es", "en"):
        for minutos in range(0, 24 * 60, 7):
            assert not re.search(r"\d", frase_hora(a(minutos // 60, minutos % 60), idioma))


# --- redactar ---

def test_redactar_marca_los_nombres_con_el_idioma_del_lexico():
    p = pedido(siguiente=("Daddy Yankee", "Gasolina"))
    lex = Lexico({"Daddy Yankee": "en-us"})
    vistos = 0
    for s in range(200):
        r = redactar(p, lex, random.Random(s), 45)
        sin_marcas = MARCA.sub("", r.marcado)
        assert "Daddy Yankee" not in sin_marcas            # nunca sin marcar
        for lang, nombre in MARCA.findall(r.marcado):
            assert lang == ("en-us" if nombre == "Daddy Yankee" else "es")
            vistos += nombre == "Daddy Yankee"
    assert vistos > 100


@pytest.mark.parametrize("idioma", ["es", "en", "en-gb"])
@pytest.mark.parametrize("album,anterior", [(True, True), (False, False), (True, False), (False, True)])
@pytest.mark.parametrize("hora", [(7, 10), (15, 30), (21, 47), (2, 5)])
def test_invariantes_de_todas_las_plantillas(idioma, album, anterior, hora):
    p = pedido(idioma, album, anterior, a(*hora))
    for s in range(300):
        r = redactar(p, Lexico(), random.Random(s), 45)
        assert isinstance(r, Redaccion)
        assert not re.search("[¡!¿]", r.marcado)
        limpio = limpiar(r.marcado, p.lang)
        original = re.split(r"(?<=[.?])\s+", r.marcado.strip())
        despues = re.split(r"(?<=[.?])\s+", limpio.strip())
        assert len(despues) == len(original)               # ninguna oración se unió: ninguna era corta
        for oracion in despues:
            assert len(MARCA.sub(lambda m: m.group(2), oracion).split()) >= 4
        assert palabras(r) <= 45
        assert "cancion" in r.ingredientes
        assert not re.search(r"\d", MARCA.sub("", r.marcado))   # la hora y todo lo que pone la plantilla, sin dígitos


@pytest.mark.parametrize("idioma", ["es", "en"])
def test_hay_variedad_real(idioma):
    p = pedido(idioma)
    ingredientes, esqueletos = set(), set()
    for s in range(300):
        r = redactar(p, Lexico(), random.Random(s), 45)
        ingredientes.add(r.ingredientes)
        esqueletos.add(MARCA.sub("N", r.marcado))
    assert len(ingredientes) >= 5 and len(esqueletos) >= 5


@pytest.mark.parametrize("idioma", ["es", "en"])
def test_una_plantilla_con_album_solo_si_el_pedido_lo_trae(idioma):
    sin = pedido(idioma, album=False)
    con = pedido(idioma, album=True)
    assert all("album" not in redactar(sin, Lexico(), random.Random(s), 45).ingredientes for s in range(200))
    assert any("album" in redactar(con, Lexico(), random.Random(s), 45).ingredientes for s in range(200))
    for s in range(200):
        r = redactar(sin, Lexico(), random.Random(s), 45)
        assert "Records" not in r.marcado


@pytest.mark.parametrize("idioma", ["es", "en"])
def test_una_plantilla_con_anterior_solo_si_hay_anterior(idioma):
    sin = pedido(idioma, anterior=False)
    assert all("anterior" not in redactar(sin, Lexico(), random.Random(s), 45).ingredientes for s in range(200))
    assert all("Whitesnake" not in redactar(sin, Lexico(), random.Random(s), 45).marcado for s in range(200))
    assert any("anterior" in redactar(pedido(idioma), Lexico(), random.Random(s), 45).ingredientes for s in range(200))


def test_respeta_palabras_maximas():
    p = pedido("es")
    minimo_global = min(palabras(redactar(p, Lexico(), random.Random(s), 1000)) for s in range(300))
    for s in range(100):
        r = redactar(p, Lexico(), random.Random(s), 12)
        assert palabras(r) <= max(12, minimo_global)


@pytest.mark.parametrize("titulo, hablado", [
    ("Remember the Name (feat. Styles of Beyond)", "Remember the Name"),
    ("Bartier Cardi (feat 21 Savage)", "Bartier Cardi"),
    ("Hola [ft. Alguien]", "Hola"),
    ("Dákiti (with Jhay Cortez)", "Dákiti"),
    ("Song (Featuring Someone Else) (Live)", "Song (Live)"),
    ("Song - feat. Someone", "Song"),
    ("(I Can't Get No) Satisfaction", "(I Can't Get No) Satisfaction"),
    ("Love Tonight (Edit)", "Love Tonight (Edit)"),
    ("Without Me", "Without Me"),
])
def test_titulo_hablado_saca_el_feat(titulo, hablado):
    assert titulo_hablado(titulo) == hablado


def test_las_plantillas_no_repiten_el_feat_del_titulo():
    p = Pedido(id="x", estacion="Power", idioma="en", voz="v", momento=a(12, 30),
               anterior=Tema("Fort Minor", "Remember the Name (feat. Styles of Beyond)"),
               siguiente=Tema("Cardi B & 21 Savage", "Bartier Cardi (feat 21 Savage)"))
    for s in range(100):
        r = redactar(p, Lexico(), random.Random(s), 45)
        assert "feat" not in r.marcado.lower() and "(" not in r.marcado, r.marcado


def test_nombres_con_comillas_y_ampersand():
    p = pedido(siguiente=('Héctor "El Father"', "Zion & Lennox"))
    for s in range(100):
        r = redactar(p, Lexico(), random.Random(s), 45)
        assert '"' not in r.marcado
        limpio = limpiar(r.marcado, p.lang)
        assert "&" not in limpio and "{" in limpio


def test_el_momento_del_dia_se_adapta():
    textos = {redactar(pedido("es", momento=a(h, 0)), Lexico(), random.Random(s), 45).marcado
              for h in (8, 15, 23) for s in range(100)}
    junto = " ".join(textos)
    assert "esta mañana" in junto and "esta tarde" in junto and "esta noche" in junto


def test_es_determinista_con_la_misma_semilla():
    p = pedido("es")
    assert redactar(p, Lexico(), random.Random(7), 45) == redactar(p, Lexico(), random.Random(7), 45)


def test_la_hora_usa_la_zona_horaria_configurada():
    """Review: el `momento` puede venir en otra zona (UTC); se habla en la hora local configurada."""
    utc = datetime(2026, 11, 14, 0, 47, tzinfo=timezone.utc)          # 21:47 en Buenos Aires
    p = pedido("es", momento=utc)
    ba = ZoneInfo("America/Argentina/Buenos_Aires")
    con_hora = [redactar(p, Lexico(), random.Random(s), 45, ba) for s in range(80)]
    con_hora = [r for r in con_hora if "hora" in r.ingredientes]
    assert con_hora and all("diez menos cuarto" in r.marcado for r in con_hora)
    sin_zona = [redactar(p, Lexico(), random.Random(s), 45) for s in range(80)]
    assert any("una menos cuarto" in r.marcado for r in sin_zona if "hora" in r.ingredientes)   # tal cual vino


def test_el_momento_del_dia_tambien_usa_la_zona():
    utc = datetime(2026, 11, 14, 0, 47, tzinfo=timezone.utc)          # de noche en Buenos Aires, 00 h en UTC
    ba = ZoneInfo("America/Argentina/Buenos_Aires")
    p = pedido("es", momento=utc)
    textos = " ".join(redactar(p, Lexico(), random.Random(s), 45, ba).marcado for s in range(80))
    assert "esta noche" in textos
    mediodia_utc = datetime(2026, 11, 13, 15, 0, tzinfo=timezone.utc)  # 12 h en Buenos Aires: tarde
    textos = " ".join(redactar(pedido("es", momento=mediodia_utc), Lexico(), random.Random(s), 45, ba).marcado
                      for s in range(80))
    assert "esta tarde" in textos and "esta noche" not in textos


def test_redactar_dice_la_pronunciacion_del_lexico_y_el_idioma_del_nombre_original():
    p = pedido(siguiente=("Nicky Jam", "Tu Y Yo"))
    p = p.__class__(**{**p.__dict__, "estacion": "Regueton 2000"})
    lex = Lexico({"Nicky Jam": "en-us"}, {"Regueton 2000": "Reguetón 2000"})
    for s in range(60):
        r = redactar(p, lex, random.Random(s), 45)
        assert "Regueton" not in r.marcado
        if "Reguetón" in r.marcado:
            assert ("es", "Reguetón 2000") in MARCA.findall(r.marcado)
        assert ("en-us", "Nicky Jam") in MARCA.findall(r.marcado) or "Nicky" not in r.marcado


# --- hechos reales (parte 3) ---

from cassette_fm.dj.config import PESOS_POR_DEFECTO  # noqa: E402
from cassette_fm.dj.hechos import Hechos  # noqa: E402
from cassette_fm.dj.hechos.clima import Clima  # noqa: E402
from cassette_fm.dj.hechos.musicbrainz import DatosTema  # noqa: E402
from cassette_fm.dj.plantillas import ingredientes_disponibles  # noqa: E402

CLIMA = Clima(22, "lluvia", True)
TEMA = DatosTema(1984, "NO", 1983, True, "https://musicbrainz.org/artist/x")
TODO = Hechos(CLIMA, TEMA)
ALTOS = {k: 1.0 for k in PESOS_POR_DEFECTO}


def sin_marcas(r):
    return MARCA.sub(lambda m: m.group(2), r.marcado)


def test_ingredientes_disponibles_segun_los_datos():
    base = {"cancion", "estacion", "hora", "momento", "album", "anterior"}
    assert ingredientes_disponibles(pedido()) == base
    assert ingredientes_disponibles(pedido(album=False, anterior=False)) == {"cancion", "estacion", "hora", "momento"}
    assert ingredientes_disponibles(pedido(), Hechos(clima=CLIMA)) == base | {"clima"}
    assert ingredientes_disponibles(pedido(), Hechos(tema=TEMA)) == base | {"dato"}
    # un tema sin nada utilizable no ofrece "dato"
    assert "dato" not in ingredientes_disponibles(pedido(), Hechos(tema=DatosTema(None, "ZZ", None, False, "u")))


def test_sin_hechos_nunca_dice_clima_ni_dato():
    for s in range(300):
        r = redactar(pedido("es"), Lexico(), random.Random(s), 45, pesos=ALTOS)
        assert "clima" not in r.ingredientes and "dato" not in r.ingredientes
        assert "grados" not in r.marcado and "salió" not in r.marcado


@pytest.mark.parametrize("idioma", ["es", "en"])
def test_con_hechos_a_veces_los_usa_y_con_pesos_en_cero_nunca(idioma):
    p = pedido(idioma)
    usados = [redactar(p, Lexico(), random.Random(s), 60, hechos=TODO, pesos=ALTOS) for s in range(200)]
    assert any("clima" in r.ingredientes for r in usados) and any("dato" in r.ingredientes for r in usados)
    ceros = dict(ALTOS, clima=0.0, dato=0.0)
    for s in range(200):
        r = redactar(p, Lexico(), random.Random(s), 60, hechos=TODO, pesos=ceros)
        assert "clima" not in r.ingredientes and "dato" not in r.ingredientes


def test_el_clima_se_dice_en_palabras_y_con_menos():
    textos = {}
    for temp, esperado_es, esperado_en in [(22, "veintidós grados", "twenty two degrees"),
                                           (-3, "menos tres grados", "minus three degrees"),
                                           (1, "un grado", "one degree"), (-1, "menos un grado", "minus one degree"),
                                           (0, "cero grados", "zero degrees"),
                                           (21, "veintiún grados", "twenty one degrees"),
                                           (31, "treinta y un grados", "thirty one degrees"),
                                           (-21, "menos veintiún grados", "minus twenty one degrees")]:
        h = Hechos(Clima(temp, "nublado", True))
        for idioma, esperado in (("es", esperado_es), ("en", esperado_en)):
            vistos = [redactar(pedido(idioma), Lexico(), random.Random(s), 60, hechos=h, pesos=ALTOS, maximo=9)
                      for s in range(100)]
            assert any(esperado in sin_marcas(r) for r in vistos if "clima" in r.ingredientes), (temp, idioma)
            assert all(not re.search(r"\d", sin_marcas(r)) for r in vistos)


def test_el_cielo_de_noche_despejado_es_la_noche():
    h = Hechos(Clima(18, "despejado", False))
    junto = " ".join(sin_marcas(redactar(pedido("es"), Lexico(), random.Random(s), 60, hechos=h, pesos=ALTOS, maximo=9))
                     for s in range(150))
    assert "la noche está despejada" in junto
    assert "el cielo está despejado" not in junto


def test_el_dato_usa_solo_lo_que_hay():
    solo_anio = Hechos(tema=DatosTema(1984, None, None, False, "u"))
    solo_pais = Hechos(tema=DatosTema(None, "NO", None, False, "u"))
    for s in range(200):
        a = sin_marcas(redactar(pedido("es"), Lexico(), random.Random(s), 60, hechos=solo_anio, pesos=ALTOS, maximo=9))
        assert "viene de" not in a and "empezó" not in a
        b = sin_marcas(redactar(pedido("es"), Lexico(), random.Random(s), 60, hechos=solo_pais, pesos=ALTOS, maximo=9))
        assert "salió" not in b and "que es de" not in b and "empezó" not in b


def test_el_anio_va_en_palabras_y_el_pais_con_nombre():
    junto = " ".join(sin_marcas(redactar(pedido("es"), Lexico(), random.Random(s), 60, hechos=TODO, pesos=ALTOS,
                                         maximo=9)) for s in range(200))
    assert "mil novecientos ochenta y cuatro" in junto and "mil novecientos ochenta y tres" in junto
    assert "Noruega" in junto and "NO " not in junto
    en = " ".join(sin_marcas(redactar(pedido("en"), Lexico(), random.Random(s), 60, hechos=TODO, pesos=ALTOS,
                                      maximo=9)) for s in range(200))
    assert "nineteen eighty four" in en and "Norway" in en


def test_solo_un_grupo_tiene_comienzo():
    persona = Hechos(tema=DatosTema(1984, "PR", 1977, False, "u"))
    for s in range(200):
        r = redactar(pedido("es"), Lexico(), random.Random(s), 60, hechos=persona, pesos=ALTOS, maximo=9)
        assert "empezó" not in r.marcado and "mil novecientos setenta y siete" not in r.marcado


def test_un_pais_fuera_de_la_tabla_no_se_dice():
    h = Hechos(tema=DatosTema(None, "ZZ", None, False, "u"))
    assert "dato" not in ingredientes_disponibles(pedido(), h)


@pytest.mark.parametrize("idioma", ["es", "en"])
@pytest.mark.parametrize("album,anterior", [(True, True), (False, False)])
@pytest.mark.parametrize("hechos", [Hechos(), TODO, Hechos(clima=CLIMA)])
def test_invariantes_de_todas_las_combinaciones(idioma, album, anterior, hechos):
    p = pedido(idioma, album, anterior, a(2, 5))
    for s in range(300):
        r = redactar(p, Lexico(), random.Random(s), 45, hechos=hechos, pesos=ALTOS)
        limpio = limpiar(r.marcado, p.lang)
        original = re.split(r"(?<=[.?])\s+", r.marcado.strip())
        assert len(re.split(r"(?<=[.?])\s+", limpio.strip())) == len(original)      # ninguna oración corta se unió
        assert palabras(r) <= 45 and r.marcado.rstrip().endswith(".") and "cancion" in r.ingredientes
        assert not re.search(r"\d", MARCA.sub("", r.marcado))
        assert "{" not in MARCA.sub("", r.marcado) and "}" not in MARCA.sub("", r.marcado)
        assert len(set(r.ingredientes)) == len(r.ingredientes) <= 3


def test_si_no_entra_se_descartan_primero_dato_clima_anterior_album():
    p = pedido("es")
    for tope in (14, 20, 26, 34):
        vistos = set()
        for s in range(150):
            r = redactar(p, Lexico(), random.Random(s), tope, hechos=TODO, pesos=ALTOS, maximo=9)
            assert palabras(r) <= tope and "cancion" in r.ingredientes
            ing = set(r.ingredientes)
            vistos.add(frozenset(ing))
            # se saca de a uno y en este orden: lo que se saca después sigue estando si quedó algo de lo anterior
            # (el álbum no entra cuando sale el clima: un solo comienzo enganchado por frase)
            if "dato" in ing:
                assert {"clima", "anterior"} <= ing
            if "clima" in ing:
                assert "anterior" in ing
        assert len(vistos) >= 1
    chico = redactar(p, Lexico(), random.Random(1), 8, hechos=TODO, pesos=ALTOS, maximo=9)
    assert chico.ingredientes == ("cancion",)           # el marco nunca se descarta


def test_la_variedad_en_cientos_de_pedidos():
    marcos = {}
    frases = set()
    for s in range(500):
        r = redactar(pedido("es"), Lexico(), random.Random(s), 60, hechos=TODO)
        frases.add(r.marcado)
        for marco in ("Seguimos con", "Ahora suena", "Con ustedes", "Sigue", "Llega"):
            if marco in sin_marcas(r):
                marcos[marco] = marcos.get(marco, 0) + 1
    assert len(marcos) >= 5 and len(frases) >= 150 and max(marcos.values()) <= 0.4 * 500


def test_respeta_los_recientes():
    p = pedido("es")
    base = sum("hora" in redactar(p, Lexico(), random.Random(s), 60).ingredientes for s in range(1000))
    con_recientes = p.__class__(**{**p.__dict__, "recientes": ("hora",) * 4})
    menos = sum("hora" in redactar(con_recientes, Lexico(), random.Random(s), 60).ingredientes for s in range(1000))
    assert base > 200 and menos < base * 0.2


def test_los_dias_de_la_semana_se_dicen():
    junto = " ".join(sin_marcas(redactar(pedido("es", momento=a(15, 0)), Lexico(), random.Random(s), 60, pesos=ALTOS))
                     for s in range(200))
    assert "este viernes" in junto                       # 13/11/2026 es viernes
    en = " ".join(sin_marcas(redactar(pedido("en", momento=a(15, 0)), Lexico(), random.Random(s), 60, pesos=ALTOS))
                  for s in range(200))
    assert "this Friday" in en


def test_la_madrugada_tiene_su_frase():
    junto = " ".join(sin_marcas(redactar(pedido("es", momento=a(3, 0)), Lexico(), random.Random(s), 60, pesos=ALTOS))
                     for s in range(200))
    assert "esta madrugada" in junto and "esta noche" not in junto


def test_un_clima_absurdo_no_se_ofrece_y_no_tumba_la_frase():
    for clima in (Clima(150, "lluvia", True), Clima(-120, "lluvia", True), Clima(20, "granizo", True)):
        h = Hechos(clima=clima)
        assert "clima" not in ingredientes_disponibles(pedido(), h)
        for s in range(100):
            assert "clima" not in redactar(pedido("es"), Lexico(), random.Random(s), 45, hechos=h, pesos=ALTOS).ingredientes


# --- datos enganchados en la misma oración (feedback del 14/11) ---

def oraciones(r):
    return [o for o in re.split(r"(?<=[.?])\s+", r.marcado.strip()) if o]


@pytest.mark.parametrize("idioma", ["es", "en"])
def test_el_dato_va_pegado_al_nombre_al_que_se_refiere(idioma):
    """Nada de oraciones sueltas con un dato al final: el año se cuelga del tema y el país, del artista."""
    p = pedido(idioma, album=False, anterior=False, siguiente=("Foreigner", "Waiting for a Girl Like You"))
    con_anio = con_pais = 0
    for s in range(400):
        r = redactar(p, Lexico(), random.Random(s), 60, hechos=TODO, pesos=dict(ALTOS, hora=0, estacion=0, momento=0,
                                                                                 clima=0), maximo=2)
        for o in oraciones(r):
            if re.search(r"salió en|came out in|from nineteen|que es de", MARCA.sub(lambda m: m.group(2), o)):
                assert "Waiting for a Girl Like You" in o and "Foreigner" in o      # misma oración que el marco
                con_anio += 1
            if re.search(r"viene de|from Norway|comes from|empezó|started in", MARCA.sub(lambda m: m.group(2), o)):
                assert "Foreigner" in o and "Waiting for a Girl Like You" in o
                con_pais += 1
        assert len(oraciones(r)) == 1                # solo marco + dato: una única oración
    assert con_anio > 20 and con_pais > 20


def test_el_dato_del_anio_cuelga_del_tema_y_el_del_pais_del_artista():
    p = pedido("es", album=False, anterior=False)
    pesos = dict(ALTOS, hora=0, estacion=0, momento=0, clima=0)
    solo_anio = Hechos(tema=DatosTema(1984, None, None, False, "u"))
    solo_pais = Hechos(tema=DatosTema(None, "NO", None, False, "u"))
    for s in range(150):
        a = redactar(p, Lexico(), random.Random(s), 60, hechos=solo_anio, pesos=pesos, maximo=2).marcado
        if "dato" in redactar(p, Lexico(), random.Random(s), 60, hechos=solo_anio, pesos=pesos, maximo=2).ingredientes:
            assert re.search(r"\{es:Waiting for a Girl Like You\}, (que salió en|que es de) mil novecientos ochenta y cuatro\.$", a), a
        b = redactar(p, Lexico(), random.Random(s), 60, hechos=solo_pais, pesos=pesos, maximo=2).marcado
        if "dato" in redactar(p, Lexico(), random.Random(s), 60, hechos=solo_pais, pesos=pesos, maximo=2).ingredientes:
            assert re.search(r"\{es:Foreigner\}, que viene de Noruega\.$", b), b


def test_el_clima_se_engancha_delante_del_marco_en_la_misma_oracion():
    p = pedido("es", album=False, anterior=False)
    pesos = dict(ALTOS, hora=0, estacion=0, momento=0, dato=0)
    vistos = 0
    for s in range(200):
        r = redactar(p, Lexico(), random.Random(s), 60, hechos=Hechos(clima=CLIMA), pesos=pesos, maximo=2)
        if "clima" in r.ingredientes:
            vistos += 1
            assert len(oraciones(r)) == 1
            assert re.match(r"(Con veintidós grados afuera|Afuera hay veintidós grados y está lloviendo), [a-záéíóú]", r.marcado), r.marcado
    assert vistos > 50


def test_el_album_tambien_se_engancha_y_no_compite_con_el_clima():
    p = pedido("es", album=True, anterior=False)
    pesos = dict(ALTOS, hora=0, estacion=0, momento=0, dato=0, clima=0.5)
    con_album = 0
    for s in range(200):
        r = redactar(p, Lexico(), random.Random(s), 60, hechos=Hechos(clima=CLIMA), pesos=pesos, maximo=3)
        assert not ("album" in r.ingredientes and "clima" in r.ingredientes)       # un solo comienzo enganchado
        assert len(oraciones(r)) == 1
        con_album += "album" in r.ingredientes
    assert con_album > 20


def test_hora_estacion_momento_y_anterior_siguen_siendo_oraciones_propias():
    p = pedido("es")
    pesos = dict(ALTOS, clima=0, dato=0, album=0)
    for s in range(100):
        r = redactar(p, Lexico(), random.Random(s), 80, pesos=pesos, maximo=5)
        sueltos = [i for i in r.ingredientes if i in ("hora", "estacion", "momento", "anterior")]
        # cada uno suma una oración (la hora y la estación pueden ir juntas en una sola)
        assert len(oraciones(r)) in (1 + len(sueltos), len(sueltos))
def test_un_artista_repetido_en_el_tag_no_se_dice_dos_veces():
    p = pedido(siguiente=("R.K.M & Ken-Y, Ken-Y", "Down"))
    for s in range(60):
        r = redactar(p, Lexico(), random.Random(s), 60)
        assert r.marcado.count("Ken-Y") == 1


@pytest.mark.parametrize("idioma, lang, union", [("es", "es", " y "), ("en", "en-us", " and ")])
def test_varios_artistas_se_unen_con_y(idioma, lang, union):
    p = pedido(idioma, siguiente=("Lil Nas X, Billy Ray Cyrus", "Old Town Road"))
    esperado = "{%s:Lil Nas X}%s{%s:Billy Ray Cyrus}" % (lang, union, lang)
    for s in range(60):
        assert esperado in redactar(p, Lexico(), random.Random(s), 60).marcado


@pytest.mark.parametrize("album, recopilatorio", [
    ("Die ultimative Chartshow: Die beliebtesten Hits aller Zeiten", True),
    ("40 of the World’s Greatest Love Songs", True), ("Live in Zürich, Vol. 2", True),
    ("The Dan Hill Collection", True), ("Frosh Eighties", True), ("All Night Love", False),
    ("Now That's What I Call Music! 45", True), ("Grandes Éxitos", True), ("Lo Mejor de Wisin & Yandel", True),
    ("Seth Troxler b2b Skream at fabric (DJ Mix)", True), ("Hunting High and Low", False), ("Look Sharp!", False),
    ("La historia de el dúo, vol. 1", True), ("Slip of the Tongue", False), ("Tm Century Gold disc 905", True),
])
def test_un_album_recopilatorio_no_es_ingrediente(album, recopilatorio):
    from cassette_fm.dj.plantillas import es_recopilatorio, ingredientes_disponibles
    assert es_recopilatorio(album) is recopilatorio
    p = Pedido(id="x", estacion="E", idioma="es", voz="v", momento=a(12, 0), anterior=None,
               siguiente=Tema("A", "T", album))
    assert ("album" in ingredientes_disponibles(p)) is (not recopilatorio)


# --- peticiones ---

from dataclasses import replace as _replace

_ANTES = {"es": ("Llega una petición especial del público.", "Tenemos una petición especial para ustedes."),
          "en": ("Here comes a special request from a listener.", "We have a special request for you.")}


@pytest.mark.parametrize("idioma", ["es", "en"])
def test_plantilla_antes_empieza_con_la_peticion(idioma):
    p = _replace(pedido(idioma=idioma), peticion="antes")
    for semilla in range(20):
        texto = MARCA.sub(lambda m: m.group(2), redactar(p, Lexico(), random.Random(semilla), 45, zona=ZONA).marcado)
        assert texto.startswith(_ANTES[idioma]), texto


@pytest.mark.parametrize("idioma,inicio", [("es", "Eso fue una petición especial: Is This Love de Whitesnake."),
                                           ("en", "That was a special request: Is This Love by Whitesnake.")])
def test_plantilla_despues_nombra_el_tema_pedido(idioma, inicio):
    p = _replace(pedido(idioma=idioma), peticion="despues")
    for semilla in range(20):
        r = redactar(p, Lexico(), random.Random(semilla), 45, zona=ZONA)
        texto = MARCA.sub(lambda m: m.group(2), r.marcado)
        assert texto.startswith(inicio), texto
        assert texto.count("Whitesnake") == 1 and "anterior" not in r.ingredientes
        assert "Waiting for a Girl Like You" in texto


def test_plantilla_peticion_entra_aunque_falten_palabras():
    p = _replace(pedido(), peticion="antes")
    for semilla in range(10):
        texto = MARCA.sub(lambda m: m.group(2), redactar(p, Lexico(), random.Random(semilla), 12, zona=ZONA).marcado)
        assert texto.startswith(_ANTES["es"]) and "Waiting for a Girl Like You" in texto
