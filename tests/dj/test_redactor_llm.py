import random
import re
from datetime import datetime, timedelta, timezone

import pytest

from cassette_fm.dj.hechos import Hechos
from cassette_fm.dj.hechos.clima import Clima
from cassette_fm.dj.hechos.musicbrainz import DatosTema
from cassette_fm.dj.hechos.wikipedia import Resumen
from cassette_fm.dj.lexico import Lexico
from cassette_fm.dj.pedido import Pedido, Tema
from cassette_fm.dj.redactor_llm import (campos_de_voz, construir_peticion, limpiar_salida, marcar_nombres,
                                         corregir_momento, numeros_a_palabras, salvar, verificar)
from cassette_fm.dj.texto_voz import preparar

ZONA = timezone(timedelta(hours=-3))
WIKI = Resumen("A-ha es una banda noruega de pop rock, formada en Oslo en 1982. Su álbum debut salió en 1985.",
               "A-ha", "es", "https://es.wikipedia.org/wiki/A-ha")
HECHOS = Hechos(Clima(22, "lluvia", True), DatosTema(1984, "NO", 1983, True, "u", "Q1"), WIKI)


def pedido(idioma="es", album=True, anterior=True, personalidad="", siguiente=("a-ha", "Take On Me")):
    return Pedido(id="x", estacion="Whisper F.M.", idioma=idioma, voz="v",
                  momento=datetime(2026, 11, 14, 2, 10, tzinfo=ZONA),
                  anterior=Tema("Don Omar", "Dale Don Dale") if anterior else None,
                  siguiente=Tema(siguiente[0], siguiente[1], "Hunting High and Low" if album else None),
                  personalidad=personalidad)


def peticion(ingredientes, hechos=HECHOS, p=None, maximo=45):
    p = p or pedido()
    return construir_peticion(p, ingredientes, hechos, campos_de_voz(p, hechos), maximo)


# --- construir_peticion ---

def test_el_prompt_lleva_solo_los_ingredientes_elegidos():
    pet = peticion(["cancion", "hora"])
    assert "Take On Me" in pet.usuario and "a-ha" in pet.usuario and "las dos y diez" in pet.usuario
    for ausente in ("grados", "Hunting High and Low", "noruega", "Don Omar", "1984", "lloviendo"):
        assert ausente not in pet.usuario, ausente


def test_la_hora_lleva_el_momento_del_dia_para_que_no_confunda_mediodia_con_noche():
    es = peticion(["cancion", "hora"])
    assert "Hora: las dos y diez (esta madrugada)" in es.usuario
    p = pedido("en")
    p = Pedido(**{**p.__dict__, "momento": datetime(2026, 11, 14, 12, 20, tzinfo=ZONA)})
    en = peticion(["cancion", "hora"], p=p)
    assert "Time: twenty past twelve (this afternoon)" in en.usuario


def test_todos_los_ingredientes_aparecen_cuando_se_eligen():
    pet = peticion(["cancion", "estacion", "hora", "momento", "album", "anterior", "clima", "dato"])
    for esperado in ("Whisper F.M.", "las dos y diez", "esta madrugada", "Hunting High and Low", "Don Omar",
                     "Dale Don Dale", "veintidós grados", "está lloviendo", "A-ha es una banda noruega"):
        assert esperado in pet.usuario, esperado


def test_el_prompt_pone_la_personalidad_y_el_idioma():
    es = peticion(["cancion"], p=pedido("es", personalidad="cálido, de madrugada"))
    assert "cálido, de madrugada" in es.sistema and "español" in es.sistema and "Whisper F.M." in es.sistema
    en = peticion(["cancion"], p=pedido("en"))
    assert "English" in en.sistema and "español" not in en.sistema
    assert "Tono:" in es.sistema and "Tono:" not in peticion(["cancion"]).sistema


@pytest.mark.parametrize("artista, texto, idioma", [
    ("Wisin & Yandel", "Ahora suena Mírala Bien de Wisin y Yandel, un tema para bailar toda la noche.", "es"),
    ("Ñejo & Dalmata", "Buenas tardes, ahora suena Mírala Bien de Ñejo y Dalmata para todos ustedes.", "es"),
    ("Zion & Lennox", "Now playing Mírala Bien by Zion and Lennox, a song for dancing all night.", "en"),
    ("Zion y Lennox", "Now playing Mírala Bien by Zion & Lennox, a song for dancing all night.", "en"),
])
def test_y_and_ampersand_son_lo_mismo_al_nombrar_al_artista(artista, texto, idioma):
    p = pedido(idioma, siguiente=(artista, "Mírala Bien"))
    pet = construir_peticion(p, ["cancion"], HECHOS, campos_de_voz(p, HECHOS), 45)
    assert verificar(texto, p, pet, 45) is None


def test_alcanza_con_nombrar_a_uno_de_los_artistas():
    en = pedido("en", siguiente=("Hilight Tribe, Vini Vici", "Free Tibet - Vini Vici Remix"))
    texto = "Now playing Free Tibet by Highlight Tribe and Vini Vici, an incredible journey."
    pet = construir_peticion(en, ["cancion"], HECHOS, campos_de_voz(en, HECHOS), 45)
    assert verificar(texto, en, pet, 45) is None
    assert "tema o el artista" in verificar("Now playing Free Tibet by somebody else entirely.", en, pet, 45)


def test_el_prompt_da_el_titulo_sin_sufijos_de_version():
    p = pedido("en", siguiente=("Ellie Goulding", "Lights - Single Version"), anterior=True)
    p = Pedido(**{**p.__dict__, "anterior": Tema("Robin Schulz", "Prayer in C - Robin Schulz Radio Edit")})
    u = peticion(["cancion", "anterior"], p=p).usuario
    assert "Song: Lights by Ellie Goulding" in u and "Previous song: Prayer in C by Robin Schulz" in u
    assert "Version" not in u and "Radio Edit" not in u


def test_la_estacion_sin_puntos_no_es_un_nombre_nuevo():
    en = pedido("en")
    assert ver("Good afternoon listeners, Whisper FM is bringing you Take On Me by a-ha, a lovely song.", p=en) is None
    assert ver("Buenas tardes, Whisper FM les trae Take On Me de a-ha, una canción hermosa.") is None


def test_el_prompt_prohibe_mencionar_momento_dia_o_clima_que_no_se_dieron():
    assert "momento del día" in peticion(["cancion"]).sistema
    assert "time of day" in peticion(["cancion"], p=pedido("en")).sistema


def test_el_prompt_insiste_en_no_hacer_enfasis_en_la_popularidad():
    es = peticion(["cancion"]).sistema
    assert "NUNCA" in es and "popular" in es and "éxito" in es and "listas" in es
    en = peticion(["cancion"], p=pedido("en")).sistema
    assert "NEVER" in en and "popular" in en and "hit" in en and "charts" in en


def test_el_prompt_no_lleva_el_feat_del_titulo():
    p = pedido(siguiente=("Cardi B & 21 Savage", "Bartier Cardi (feat 21 Savage)"))
    u = peticion(["cancion", "anterior"], p=p).usuario
    assert "Bartier Cardi de" in u and "feat" not in u


def test_una_oracion_que_termina_en_comilla_cierra_la_oracion():
    en = pedido("en")
    assert ver("Get ready for Take On Me by a-ha, “a classic.” It’s the perfect sound for this afternoon.", p=en) is None
    assert ver("Get ready for Take On Me by a-ha, \"a classic.\" Alright, let us go.", p=en) is None


def test_el_prompt_pide_unir_los_datos_con_conectores():
    assert "conectores" in peticion(["cancion"]).sistema
    assert "connectors" in peticion(["cancion"], p=pedido("en")).sistema


def test_el_prompt_pide_un_rango_de_palabras_y_prohibe_inventar():
    pet = peticion(["cancion", "estacion", "hora", "momento"], maximo=40)
    assert "entre 20 y 40" in pet.sistema
    assert re.search(r"no inventes", pet.sistema, re.I)


def test_con_pocos_hechos_el_prompt_pide_una_frase_corta_para_que_no_rellene_inventando():
    solo_tema = peticion(["cancion"], maximo=75).sistema
    assert "entre 10 y 20 palabras" in solo_tema
    assert "pocos datos" in solo_tema and "few facts" in peticion(["cancion"], p=pedido("en")).sistema
    con_dos = peticion(["cancion", "estacion", "hora"], maximo=75).sistema
    assert "entre 25 y 50 palabras" in con_dos
    assert "entre 37 y 75 palabras" in peticion(["cancion", "estacion", "hora", "momento", "album"], maximo=75).sistema


def test_el_resumen_de_wikipedia_solo_si_el_ingrediente_dato():
    assert "A-ha es una banda noruega" not in peticion(["cancion", "clima"]).usuario
    assert "A-ha es una banda noruega" in peticion(["cancion", "dato"]).usuario
    sin_wiki = Hechos(HECHOS.clima, HECHOS.tema, None)
    assert "A-ha es una banda noruega" not in peticion(["cancion", "dato"], hechos=sin_wiki).usuario


def test_los_anios_de_musicbrainz_van_con_cifras_y_el_pais_con_nombre():
    sin_wiki = Hechos(None, HECHOS.tema, None)
    u = peticion(["cancion", "dato"], hechos=sin_wiki).usuario
    assert "Año de la canción (no del álbum): 1984" in u and "Año en que empezó la banda: 1983" in u
    assert "Noruega" in u
    en = peticion(["cancion", "dato"], hechos=sin_wiki, p=pedido("en")).usuario
    assert "Song year (the song, not the album): 1984" in en and "Year the band started: 1983" in en
    assert "mil novecientos" not in u
    assert "convertir" not in u and "1984" in peticion(["cancion", "dato"], hechos=sin_wiki).permitido


def test_permitido_incluye_nombres_hechos_y_las_cifras():
    pet = peticion(["cancion", "clima", "dato"])
    for esperado in ("a-ha", "Take On Me", "Whisper F.M.", "Oslo", "1984", "1983", "22", "1985"):
        assert esperado in pet.permitido, esperado


# --- limpiar_salida ---

@pytest.mark.parametrize("crudo, esperado", [
    ("Aquí tienes: «Ahora suena Take On Me de a-ha»", "Ahora suena Take On Me de a-ha"),
    ("```\nAhora suena Take On Me de a-ha.\n```", "Ahora suena Take On Me de a-ha."),
    ('"Ahora suena Take On Me."', "Ahora suena Take On Me."),
    ("**Ahora** suena _Take On Me_ de a-ha.", "Ahora suena Take On Me de a-ha."),
    ("# Intervención\nAhora suena Take On Me.", "Ahora suena Take On Me."),
    ("Okay, here’s the announcement:\n\n“We’re kicking things off. It’s Take On Me by a-ha.”",
     "We’re kicking things off. It’s Take On Me by a-ha."),
    ("Okay, here we go!\n\n“That was Prayer in C. Now, Take On Me.”", "That was Prayer in C. Now, Take On Me."),
    ("Here’s the announcement for Power F.M.:\n\n“Get ready to move.”\n\nLet me know if you want changes.",
     "Get ready to move."),
    ("Aquí tenés la intervención:\n\nAhora suena Take On Me de a-ha.", "Ahora suena Take On Me de a-ha."),
    ("Claro, acá va:\n\nAhora suena Take On Me de a-ha.\n\nSi querés otra, decime.", "Ahora suena Take On Me de a-ha."),
    ("(Sound of a gentle guitar intro fades in)\n\nRight now, we’re playing Take On Me by a-ha.",
     "Right now, we’re playing Take On Me by a-ha."),
    ("*soft music fades in*\n\nAhora suena Take On Me de a-ha.", "Ahora suena Take On Me de a-ha."),
    ("[Intro music]\n\nHello there, a-ha is next.", "Hello there, a-ha is next."),
    ("(Sound of piano) Right now we play Take On Me by a-ha.", "Right now we play Take On Me by a-ha."),
    ("Ahora suena Take On Me 🎶 de a-ha 🔥.", "Ahora suena Take On Me de a-ha."),
    ("Ahora suena Take On Me.\n\nY seguimos con más música.", "Ahora suena Take On Me."),
    ("Here is the announcement:\nNow playing Take On Me.", "Now playing Take On Me."),
    ("Ahora   suena\tTake  On Me.", "Ahora suena Take On Me."),
    ("Ahora suena {Take On Me}.", "Ahora suena Take On Me."),
    ("", ""), ("   \n  ", ""), ("```\n```", ""),
])
def test_limpiar_salida(crudo, esperado):
    assert limpiar_salida(crudo) == esperado


# --- verificar ---

def ver(texto, ingredientes=("cancion", "clima", "dato"), p=None, maximo=45, hechos=HECHOS):
    p = p or pedido()
    pet = construir_peticion(p, list(ingredientes), hechos, campos_de_voz(p, hechos), maximo)
    return verificar(texto, p, pet, maximo)


def test_una_frase_correcta_pasa():
    assert ver("Ahora suena Take On Me de a-ha, una banda noruega que salió en 1984 con veintidós grados afuera.") is None
    assert ver("Seguimos con a-ha y su tema Take On Me para acompañar la madrugada.") is None


@pytest.mark.parametrize("texto, motivo", [
    ("", "vacío"), ("Take On Me", "demasiado corto"),
    (" ".join(["palabra"] * 80) + " Take On Me a-ha.", "demasiado largo"),
])
def test_vacia_larga_y_corta(texto, motivo):
    assert motivo in ver(texto)


@pytest.mark.parametrize("texto", ["Mirá en https://wikipedia.org esto: Take On Me de a-ha.",
                                   "Ahora suena Take On Me de a-ha #radio #pop.",
                                   "Escribinos a @radio: ahora suena Take On Me de a-ha."])
def test_enlaces_y_etiquetas(texto):
    assert "enlaces" in ver(texto)


@pytest.mark.parametrize("texto", ["Ahora suena una canción de a-ha para todos ustedes.",
                                   "Ahora suena Take On Me para todos ustedes siempre."])
def test_sin_tema_o_sin_artista(texto):
    assert "no nombra" in ver(texto)


def test_un_anio_inventado_no_pasa_y_uno_de_los_hechos_si():
    assert ver("Ahora suena Take On Me de a-ha que salió en 1984 y suena genial.") is None
    assert "número" in ver("Ahora suena Take On Me de a-ha que salió en 1986 y suena genial.")


def test_un_nombre_propio_inventado_no_pasa():
    motivo = ver("Ahora suena Take On Me de a-ha, tan famosos como Michael Jackson en esa época.")
    assert "nombre propio" in motivo and "Michael" in motivo


def test_un_nombre_del_resumen_de_wikipedia_pasa_y_uno_que_no_esta_no():
    assert "Morten" in ver("Ahora suena Take On Me de a-ha, con Morten Harket de vocalista y mucho más.",
                           ingredientes=("cancion", "dato"))


def test_nombres_del_pedido_y_de_wikipedia_si_pasan():
    assert ver("Ahora suena Take On Me de a-ha, banda de Oslo formada en Noruega.",
               ingredientes=("cancion", "dato")) is None
    assert ver("Desde el álbum Hunting High and Low suena Take On Me de a-ha.", ingredientes=("cancion", "album")) is None


def test_las_excepciones_de_nombres_comunes():
    assert ver("Este sábado en Buenos Aires suena Take On Me de a-ha para todos.") is None
    assert ver("Un sábado de noviembre suena Take On Me de a-ha para todos ustedes.") is None
    en = pedido("en")
    assert ver("This Saturday we play Take On Me by a-ha and I hope you enjoy it.", p=en) is None


def test_inicio_de_oracion_comun_no_cuenta_como_nombre():
    assert ver("Madrugada tranquila. Ahora suena Take On Me de a-ha. Gracias por escuchar.") is None


def test_no_hay_limite_de_oraciones_solo_de_palabras():
    assert ver("Hola gente linda. Ahora suena Take On Me de a-ha. Es un clásico. Gracias por escuchar. Un abrazo.") is None


def test_un_dia_de_la_semana_que_no_es_hoy_no_pasa():
    # el pedido es un sábado
    assert "viernes" in ver("Ahora suena Take On Me de a-ha, una gran forma de empezar tu viernes.")
    assert ver("Ahora suena Take On Me de a-ha, una gran forma de pasar tu sábado.") is None
    en = pedido("en")
    assert "Friday" in ver("Now playing Take On Me by a-ha, a fantastic way to start your Friday.", p=en)
    assert ver("Now playing Take On Me by a-ha, a fantastic way to enjoy your Saturday.", p=en) is None


def test_el_dia_se_cuenta_en_la_zona_horaria_de_la_radio():
    from datetime import timezone
    p = Pedido(**{**pedido("en").__dict__, "momento": datetime(2026, 11, 14, 1, 30, tzinfo=timezone.utc)})
    pet = construir_peticion(p, ["cancion"], HECHOS, campos_de_voz(p, HECHOS, ZONA), 45)
    texto = "Now playing Take On Me by a-ha, a fantastic way to end your Friday."
    assert verificar(texto, p, pet, 45, ZONA) is None          # en Buenos Aires todavía es viernes
    assert "Friday" in verificar(texto, p, pet, 45)             # en UTC ya es sábado


def test_un_dia_dentro_del_titulo_no_cuenta():
    p = pedido("en", siguiente=("The Cure", "Friday I'm in Love"))
    assert ver("Now playing Friday I'm in Love by The Cure, a fantastic song.", p=p) is None


@pytest.mark.parametrize("texto, idioma", [
    ("Now playing Take On Me by a-ha, a really popular track that fans love.", "en"),
    ("Now playing Take On Me by a-ha, a huge hit that keeps climbing the charts.", "en"),
    ("Ahora suena Take On Me de a-ha, un tema muy popular que todos conocen.", "es"),
])
def test_mencionar_la_popularidad_no_descarta_la_frase(texto, idioma):
    assert ver(texto, p=pedido(idioma)) is None


@pytest.mark.parametrize("texto", ["Ahora suena Take On Me de a-ha con 1,5 millones de fans.",
                                   "Ahora suena Take On Me de a-ha con 3000 fans en 1984."])
def test_cifras_raras_no_se_pueden_decir(texto):
    assert ver(texto, ingredientes=("cancion", "dato")) is not None


# --- numeros_a_palabras ---

@pytest.mark.parametrize("texto, idioma, esperado", [
    ("salió en 1984", "es", "salió en mil novecientos ochenta y cuatro"),
    ("came out in 1984", "en", "came out in nineteen eighty four"),
    ("hay 22 grados", "es", "hay veintidós grados"), ("it is 22 degrees", "en", "it is twenty two degrees"),
    ("hay 21 grados", "es", "hay veintiún grados"), ("hay 1 grado", "es", "hay un grado"),
    ("en 2005 y 1999", "es", "en dos mil cinco y mil novecientos noventa y nueve"),
    ("sin números", "es", "sin números"),
])
def test_numeros_a_palabras(texto, idioma, esperado):
    assert numeros_a_palabras(texto, idioma) == esperado


@pytest.mark.parametrize("texto", ["1000 fans", "1,5 millones", "3000 personas", "12345"])
def test_numeros_a_palabras_que_no_se_pueden_decir(texto):
    with pytest.raises(ValueError):
        numeros_a_palabras(texto, "es")


# --- marcar_nombres ---

def test_marca_los_nombres_con_el_idioma_del_lexico():
    p = pedido()
    lex = Lexico({"a-ha": "en-us"})
    m = marcar_nombres("Ahora suena Take On Me de a-ha en Whisper F.M. del disco Hunting High and Low.", p, HECHOS, lex)
    assert "{en-us:a-ha}" in m and "{es:Take On Me}" in m and "{es:Whisper F.M.}" in m
    assert "{es:Hunting High and Low}" in m


def test_usa_la_pronunciacion_del_lexico():
    lex = Lexico({}, {"Whisper F.M.": "Whisper efe eme"})
    m = marcar_nombres("Estás en Whisper F.M. con Take On Me de a-ha.", pedido(), HECHOS, lex)
    assert "{es:Whisper efe eme}" in m


def test_no_pisa_marcas_ni_parte_palabras():
    p = pedido(siguiente=("Ken", "Down"))
    m = marcar_nombres("Ahora suena Down de Ken y también de Kendrick.", p, HECHOS, Lexico())
    assert "{es:Ken}" in m and "Kendrick" in m and "{es:Ken}drick" not in m
    assert m.count("{es:Down}") == 1


def test_marca_cada_aparicion_y_sin_distinguir_mayusculas():
    m = marcar_nombres("take on me, sí, TAKE ON ME de a-ha.", pedido(), HECHOS, Lexico())
    assert m.count("{es:Take On Me}") == 2


def test_el_titulo_limpio_tambien_se_marca():
    p = pedido(siguiente=("Foreigner", "Waiting for a Girl Like You - 2008 Remaster"))
    m = marcar_nombres("Ahora suena Waiting for a Girl Like You de Foreigner.", p, Hechos(), Lexico())
    assert "{es:Waiting for a Girl Like You}" in m


def test_varios_artistas_se_marcan_por_separado():
    p = pedido(siguiente=("Lil Nas X, Billy Ray Cyrus", "Old Town Road"))
    m = marcar_nombres("Suena Old Town Road de Lil Nas X y Billy Ray Cyrus.", p, Hechos(), Lexico())
    assert "{es:Lil Nas X}" in m and "{es:Billy Ray Cyrus}" in m


def test_el_resultado_pasa_por_el_texto_para_voz():
    p = pedido(siguiente=("Héctor \"El Father\"", "Zion & Lennox"))
    m = marcar_nombres("Ahora suena Zion & Lennox de Héctor \"El Father\" para todos ustedes.", p, Hechos(), Lexico())
    prep = preparar(m, p.lang, lambda t, l: t)
    assert "{" not in prep.texto and "}" not in prep.texto and "&" not in prep.texto


def test_un_nombre_dentro_de_otro_no_se_marca_adentro():
    p = pedido(siguiente=("Ken", "Ken Y Down"))
    m = marcar_nombres("Suena Ken Y Down de Ken.", p, Hechos(), Lexico())
    assert m == "Suena {es:Ken Y Down} de {es:Ken}."


# --- revisión final ---

def test_la_primera_palabra_de_una_oracion_no_se_toma_por_un_nombre():
    en = pedido("en")
    assert ver("Alright listeners, get ready. We have Take On Me by a-ha blasting through. Let's hear it.", p=en) is None
    assert ver("Madonna grabó Take On Me de a-ha. Ahora suena en la radio.") is None


@pytest.mark.parametrize("texto", ["Elton John compuso Take On Me de a-ha. Ahora suena en la radio.",
                                   "Suena Take On Me de a-ha. Hoy Prince la adoraba, eso dicen."])
def test_un_nombre_inventado_que_no_abre_la_oracion_o_tiene_dos_palabras_no_pasa(texto):
    assert "nombre propio" in ver(texto)


def test_los_anios_en_palabras_inventados_no_pasan():
    assert "año" in ver("Suena Take On Me de a-ha que salió en mil novecientos ochenta y seis para todos.")
    assert ver("Suena Take On Me de a-ha que salió en mil novecientos ochenta y cuatro para todos.") is None
    assert "año" in ver("Suena Take On Me de a-ha que salió en dos mil diez para todos ustedes.")
    en = pedido("en")
    assert "año" in ver("Now playing Take On Me by a-ha which came out in nineteen eighty six for all.", p=en)
    assert ver("Now playing Take On Me by a-ha which came out in nineteen eighty four for all.", p=en) is None


@pytest.mark.parametrize("texto, idioma", [
    ("Sure! Here is your announcement: Take On Me by a-ha is next on the air tonight.", "es"),
    ("Ahora suena Take On Me de a-ha para vos y para todos los que nos escuchan, amigo.", "en"),
])
def test_el_idioma_equivocado_no_pasa(texto, idioma):
    assert ver(texto, p=pedido(idioma)).startswith("no está en ")


def test_un_titulo_en_otro_idioma_no_hace_fallar_el_idioma():
    p = pedido("es", siguiente=("Foreigner", "Waiting for a Girl Like You"))
    pet = construir_peticion(p, ["cancion"], Hechos(), campos_de_voz(p, Hechos()), 45)
    assert verificar("Ahora suena Waiting for a Girl Like You de Foreigner para todos ustedes.", p, pet, 45) is None


@pytest.mark.parametrize("crudo, esperado", [
    ("¡Claro! Aquí va la intervención: suena Take On Me de a-ha.", "suena Take On Me de a-ha."),
    ("Sure! Here's the announcement: Now playing Take On Me.", "Now playing Take On Me."),
    ("Por supuesto. Aquí tienes: Ahora suena Take On Me.", "Ahora suena Take On Me."),
])
def test_los_preambulos_con_interjeccion_se_sacan(crudo, esperado):
    assert limpiar_salida(crudo) == esperado


@pytest.mark.parametrize("texto", ["Visitá es.wikipedia.org/wiki/A-ha para más. Suena Take On Me de a-ha.",
                                   "Más en wikipedia.org. Suena Take On Me de a-ha ahora mismo.",
                                   "Suena Take On Me de a-ha. Escuchanos en radio.com.ar todo el día."])
def test_una_url_sin_esquema_no_pasa(texto):
    assert "enlaces" in ver(texto)


def test_los_numeros_dentro_de_los_nombres_no_cuentan_ni_se_convierten():
    p = pedido(siguiente=("U2", "With or Without You"))
    pet = construir_peticion(p, ["cancion"], Hechos(), campos_de_voz(p, Hechos()), 45)
    assert verificar("Ahora suena With or Without You de U2 para todos ustedes.", p, pet, 45) is None
    m = marcar_nombres("Ahora suena With or Without You de U2 con 22 grados.", p, Hechos(), Lexico({"U2": "en-us"}))
    assert numeros_a_palabras(m, "es") == ("Ahora suena {es:With or Without You} de {en-us:U2} con veintidós grados.")
    p2 = pedido(siguiente=("Blink-182", "All the Small Things"))
    pet2 = construir_peticion(p2, ["cancion"], Hechos(), campos_de_voz(p2, Hechos()), 45)
    assert verificar("Ahora suena All the Small Things de Blink-182 para todos ustedes.", p2, pet2, 45) is None


def test_un_numero_inventado_junto_a_un_nombre_con_numero_sigue_sin_pasar():
    p = pedido(siguiente=("U2", "With or Without You"))
    pet = construir_peticion(p, ["cancion"], Hechos(), campos_de_voz(p, Hechos()), 45)
    assert "número" in verificar("Ahora suena With or Without You de U2 que salió en 1987 para todos.", p, pet, 45)


@pytest.mark.parametrize("texto, idioma, esperado", [
    ("hay -3 grados", "es", "hay menos tres grados"), ("hay −3 grados", "es", "hay menos tres grados"),
    ("it is -3 degrees", "en", "it is minus three degrees"),
])
def test_los_grados_bajo_cero_dicen_menos(texto, idioma, esperado):
    assert numeros_a_palabras(texto, idioma) == esperado


def test_los_marcadores_no_se_tocan_al_convertir():
    assert numeros_a_palabras("de {en-us:Maroon 5} en 1984", "es") == "de {en-us:Maroon 5} en mil novecientos ochenta y cuatro"


@pytest.mark.parametrize("crudo, esperado", [
    ("¡Claro! Suena Take On Me de a-ha.", "Suena Take On Me de a-ha."),
    ("Sure, now playing Take On Me.", "now playing Take On Me."),
    ("Dale! Ahora suena Take On Me.", "Ahora suena Take On Me."),
])
def test_una_interjeccion_suelta_al_principio_se_saca(crudo, esperado):
    assert limpiar_salida(crudo) == esperado


def test_sin_anio_del_tema_el_prompt_dice_que_es_desconocido():
    assert "Año de la canción: desconocido" in peticion(["cancion"]).usuario
    sin_anio = Hechos(None, DatosTema(None, "NO", 1983, True, "u", "Q1"), WIKI)
    assert "Song year: unknown" in peticion(["cancion", "dato"], hechos=sin_anio, p=pedido("en")).usuario
    con_anio = peticion(["cancion", "dato"]).usuario
    assert "desconocido" not in con_anio and "Año de la canción (no del álbum): 1984" in con_anio


def _salvar(texto, ingredientes=("cancion", "clima", "dato"), p=None):
    p = p or pedido()
    pet = construir_peticion(p, list(ingredientes), HECHOS, campos_de_voz(p, HECHOS), 45)
    return salvar(texto, p, pet, 45)


def test_salvar_saca_la_unica_oracion_con_un_dato_inventado():
    texto = "Ahora suena Take On Me de a-ha. Salió en 1986 y la escuchó todo el mundo. Seguimos con más música para vos."
    assert ver(texto) is not None
    assert _salvar(texto) == "Ahora suena Take On Me de a-ha. Seguimos con más música para vos."


def test_salvar_no_puede_sacar_la_oracion_que_nombra_el_tema_ni_dos_oraciones_malas():
    assert _salvar("Ahora suena Take On Me de a-ha, que salió en 1986 y la escuchó todo el mundo.") is None
    assert _salvar("Ahora suena Take On Me de a-ha. Salió en 1986 y gustó. Y en 1987 llegó a Madonna.") is None


def test_salvar_no_deja_una_frase_demasiado_corta():
    assert _salvar("Ahora suena Take On Me. De a-ha. Salió en 1986 y la escuchó todo el mundo.") is None


def test_de_wikipedia_solo_van_las_dos_primeras_oraciones():
    largo = Resumen("Roxette es un dúo sueco. Lo formaron Gessle y Fredriksson en 1986. Gessle venía de Gyllene "
                    "Tider. Hoy sigue con Lena Philipsson.", "Roxette", "es", "https://x")
    pet = peticion(["cancion", "dato"], hechos=Hechos(None, None, largo))
    assert "Roxette es un dúo sueco. Lo formaron Gessle y Fredriksson en 1986." in pet.usuario
    assert "Gyllene" not in pet.usuario and "Philipsson" not in pet.usuario
    assert "Gyllene" in ver("Ahora suena Take On Me de a-ha, y Gessle venía de Gyllene Tider.",
                            ingredientes=("cancion", "dato"), hechos=Hechos(None, None, largo))


@pytest.mark.parametrize("texto, idioma, esperado", [
    ("They sold over 200 million records", "en", "They sold over two hundred million records"),
    ("Vendieron 250 millones de discos", "es", "Vendieron doscientos cincuenta millones de discos"),
    ("Vendieron 21 millones de discos", "es", "Vendieron veintiún millones de discos"),
    ("He rose to fame in the 1970s", "en", "He rose to fame in the nineteen seventies"),
    ("a hit of the 2000s and the 80s", "en", "a hit of the two thousands and the eighties"),
    ("released on February 3, 2024", "en", "released on February third, twenty twenty four"),
    ("from March 21 2001", "en", "from March twenty first two thousand one"),
])
def test_cifras_grandes_decadas_y_fechas_se_dicen_bien(texto, idioma, esperado):
    assert numeros_a_palabras(texto, idioma) == esperado


def test_una_cifra_de_wikipedia_hasta_999_pasa_la_verificacion():
    wiki = Resumen("Los Eagles vendieron más de 200 millones de discos.", "Eagles", "es", "https://x")
    assert ver("Ahora suena Take On Me de a-ha; los Eagles vendieron 200 millones de discos.",
               ingredientes=("cancion", "dato"), hechos=Hechos(None, None, wiki)) is None


@pytest.mark.parametrize("texto", [
    "Now playing Take On Me by a-ha, the UK-based synth-pop group everyone knows.",
    "Now playing Take On Me by a-ha, a band from the UK with a long career.",
    "Now playing Take On Me by a-ha, a band that toured the US and the USA many times.",
])
def test_siglas_de_paises_y_compuestos_con_minuscula_no_son_nombres_nuevos(texto):
    assert ver(texto, p=pedido("en")) is None


def test_el_momento_se_dice_como_dia_y_parte_del_dia():
    es = peticion(["cancion", "momento"]).usuario
    assert "Momento: sábado de madrugada" in es
    p = Pedido(**{**pedido("en").__dict__, "momento": datetime(2026, 11, 14, 13, 20, tzinfo=ZONA)})
    assert "Moment: Saturday afternoon" in peticion(["cancion", "momento"], p=p).usuario


@pytest.mark.parametrize("hora, texto, idioma, esperado", [
    (14, "Good morning listeners, tonight we play {en-us:Walk Of Life}.", "en",
     "Good afternoon listeners, this afternoon we play {en-us:Walk Of Life}."),
    (14, "We play {en-us:Love Tonight} by {en-us:Shouse} tonight.", "en",
     "We play {en-us:Love Tonight} by {en-us:Shouse} this afternoon."),
    (22, "Good afternoon, this evening we have a song.", "en", "Good evening, tonight we have a song."),
    (9, "Tonight we play a song.", "en", "This morning we play a song."),
    (14, "Buenas noches, esta noche suena {es:Ese Amor}.", "es", "Buenas tardes, esta tarde suena {es:Ese Amor}."),
    (3, "Buen día, esta mañana suena un tema.", "es", "Buenas noches, esta madrugada suena un tema."),
    (14, "Buenas tardes, esta tarde suena un tema.", "es", "Buenas tardes, esta tarde suena un tema."),
])
def test_corregir_momento_cambia_saludos_y_partes_del_dia_equivocadas(hora, texto, idioma, esperado):
    assert corregir_momento(texto, datetime(2026, 11, 14, hora, 0, tzinfo=ZONA), idioma) == esperado


# --- peticiones ---

from dataclasses import replace as _replace


@pytest.mark.parametrize("idioma,valor,linea", [
    ("es", "antes", "Este tema es una petición especial del público: presentalo como tal."),
    ("en", "antes", "This song is a special request from a listener: introduce it as such."),
    ("es", "despues", "El tema anterior fue una petición especial del público: mencionalo y presentá el siguiente."),
    ("en", "despues", "The previous song was a special request from a listener: mention it and introduce the next one."),
])
def test_prompt_llm_marca_la_peticion(idioma, valor, linea):
    p = _replace(pedido(idioma=idioma), peticion=valor)
    pet = peticion(["cancion"], p=p)
    assert linea in pet.usuario
    if valor == "despues":
        assert "Dale Don Dale" in pet.usuario       # el tema pedido va aunque "anterior" no se haya elegido


def test_prompt_sin_peticion_no_la_menciona():
    pet = peticion(["cancion"])
    assert "petición" not in pet.usuario and "request" not in pet.usuario
