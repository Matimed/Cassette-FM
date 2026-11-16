import json
import random
import wave
from pathlib import Path

import pytest

from cassette_fm.dj.config import ConfigServicioDJ, RutasDJ
from cassette_fm.dj.guiones import RegistroGuiones
from cassette_fm.dj.lexico import Lexico
from cassette_fm.dj.pedido import IDIOMAS, Pedido, Tema
from cassette_fm.dj.produccion import Productor, Resultado
from cassette_fm.dj.sintetizador import ErrorModelos
from cassette_fm.dj.texto_voz import preparar
from datetime import datetime, timezone


def fonemizar(texto, lang):
    return f"<{lang}:{texto}>"


class SintetizadorFalso:
    def __init__(self, duraciones=(5.0,), error=None):
        self.duraciones = list(duraciones)
        self.llamadas = []
        self.velocidades = []
        self.textos = []
        self.error = error

    def sintetizar(self, fonemas, voz, lang, salida, velocidad=None, texto=None):
        self.llamadas.append((fonemas, voz, lang, Path(salida)))
        self.velocidades.append(velocidad)
        self.textos.append(texto)
        if self.error:
            raise self.error
        dur = self.duraciones.pop(0) if len(self.duraciones) > 1 else self.duraciones[0]
        salida = Path(salida)
        salida.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(salida), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(8000)
            w.writeframes(b"\0\0" * 80)
        return dur


@pytest.fixture
def montaje(tmp_path):
    rutas = RutasDJ(config=tmp_path / "cfg" / "config.toml", estado=tmp_path / "estado", clips=tmp_path / "clips")
    guiones = RegistroGuiones(rutas.guiones)

    def crear(sintetizador=None, lexico=None, config=None, **kw):
        s = sintetizador or SintetizadorFalso()
        return Productor(config or ConfigServicioDJ(), rutas, s, fonemizar,
                         lexico or Lexico({"Daddy Yankee": "en-us"}), guiones, azar=random.Random(1), **kw), s

    return crear, rutas, guiones


def test_produce_el_clip_en_clips_y_anota_el_guion(montaje, hacer_pedido):
    crear, rutas, guiones = montaje
    productor, _ = crear()
    r = productor.producir(hacer_pedido("abc"))
    assert isinstance(r, Resultado) and r.audio == rutas.clips / "abc.wav" and r.audio.exists()
    assert r.duracion == 5.0 and r.voz == "em_santa" and r.idioma == "es" and "cancion" in r.ingredientes
    (g,) = guiones.ultimos(10)
    for campo in ("ts", "id", "estacion", "idioma", "voz", "momento", "anterior", "siguiente", "fuente",
                  "ingredientes", "texto", "marcado", "fonemas", "duracion", "audio"):
        assert campo in g, campo
    assert g["fuente"] == "plantilla" and g["id"] == "abc" and g["siguiente"]["artista"] == "Foreigner"
    assert "{" not in g["texto"] and "{" in g["marcado"]
    assert g["texto"] == r.texto and g["marcado"] == r.marcado


def test_el_guion_alcanza_para_volver_a_sintetizar(montaje, hacer_pedido):
    crear, _, guiones = montaje
    productor, _ = crear()
    productor.producir(hacer_pedido("abc", idioma="en"))
    (g,) = guiones.ultimos(1)
    again = preparar(g["marcado"], IDIOMAS[g["idioma"]], fonemizar)
    assert again.fonemas == g["fonemas"] and again.texto == g["texto"]


def test_reintenta_si_el_clip_es_demasiado_largo(montaje, hacer_pedido):
    crear, rutas, guiones = montaje
    productor, sint = crear(SintetizadorFalso(duraciones=[20.0, 20.0, 5.0]))
    r = productor.producir(hacer_pedido("abc", duracion_maxima_segundos=10))
    assert r.duracion == 5.0 and len(sint.llamadas) == 3
    assert [p.name for p in rutas.clips.iterdir()] == ["abc.wav"]      # los descartados no quedan en disco
    registros = guiones.ultimos(10)
    assert [bool(x.get("descartado")) for x in registros] == [True, True, False]


def test_los_reintentos_acortan_el_texto(montaje, hacer_pedido):
    crear, _, guiones = montaje
    productor, _ = crear(SintetizadorFalso(duraciones=[30.0, 5.0]))
    productor.producir(hacer_pedido("abc", duracion_maxima_segundos=10))
    primero, segundo = guiones.ultimos(2)
    assert len(segundo["texto"].split()) <= len(primero["texto"].split())


def test_falla_si_ningun_intento_entra(montaje, hacer_pedido):
    crear, rutas, guiones = montaje
    productor, _ = crear(SintetizadorFalso(duraciones=[20.0]))
    with pytest.raises(ValueError) as exc:
        productor.producir(hacer_pedido("abc", duracion_maxima_segundos=10))
    assert "20.0" in str(exc.value) and "10" in str(exc.value)
    assert not list(rutas.clips.glob("*"))
    assert "error" in guiones.ultimos(10)[-1]


def test_propaga_ErrorModelos_y_lo_anota(montaje, hacer_pedido):
    crear, _, guiones = montaje
    productor, _ = crear(SintetizadorFalso(error=ErrorModelos("faltan los modelos: corré `cassette-dj modelos`")))
    with pytest.raises(ErrorModelos):
        productor.producir(hacer_pedido("abc"))
    assert "cassette-dj modelos" in guiones.ultimos(1)[0]["error"]


def test_el_id_no_puede_escapar_de_clips(montaje, tmp_path):
    crear, rutas, _ = montaje
    productor, sint = crear()
    malo = Pedido(id="../fuera", estacion="L", idioma="es", voz="v", momento=datetime(2026, 1, 1, tzinfo=timezone.utc),
                  anterior=None, siguiente=Tema("A", "B"))
    with pytest.raises(ValueError):
        productor.producir(malo)
    assert sint.llamadas == [] and not (tmp_path / "fuera.wav").exists()


def test_usa_el_idioma_y_la_voz_del_pedido(montaje, hacer_pedido):
    crear, _, _ = montaje
    productor, sint = crear()
    productor.producir(hacer_pedido("a", idioma="en-gb", voz="bm_george"))
    fonemas, voz, lang, _ = sint.llamadas[0]
    assert voz == "bm_george" and lang == "en-gb" and "<en-gb:" in fonemas


def test_los_nombres_en_otro_idioma_llevan_su_marca(montaje, hacer_pedido):
    crear, _, guiones = montaje
    productor, _ = crear()
    for i in range(30):
        productor.producir(hacer_pedido(f"p{i}", siguiente={"artista": "Daddy Yankee", "titulo": "Gasolina"}))
    marcados = [g["marcado"] for g in guiones.ultimos(100)]
    assert any("{en-us:Daddy Yankee}" in m for m in marcados)
    assert all("{es:Daddy Yankee}" not in m for m in marcados)


def test_el_productor_habla_en_la_zona_horaria_configurada(montaje, hacer_pedido):
    crear, _, guiones = montaje
    productor, _ = crear()
    for i in range(40):
        productor.producir(hacer_pedido(f"z{i}", momento="2026-11-14T00:47:00+00:00"))   # 21:47 en Buenos Aires
    textos = [g["texto"] for g in guiones.ultimos(100) if "hora" in g.get("ingredientes", [])]
    assert textos and all("diez menos cuarto" in t for t in textos)


def test_la_velocidad_del_pedido_llega_al_sintetizador(montaje, hacer_pedido):
    crear, _, _ = montaje
    productor, sint = crear()
    productor.producir(hacer_pedido("v1", velocidad=1.2))
    productor.producir(hacer_pedido("v2"))
    assert [v for v in sint.velocidades] == [1.2, None]


def test_el_texto_limpio_llega_al_sintetizador_para_los_motores_que_no_usan_fonemas(montaje, hacer_pedido):
    crear, _, _ = montaje
    productor, sint = crear()
    r = productor.producir(hacer_pedido("t1"))
    from cassette_fm.dj.texto_voz import texto_para_piper
    assert sint.textos == [texto_para_piper(r.marcado)]


# --- hechos reales (parte 3) ---

def test_el_guion_anota_los_hechos_y_sus_fuentes(montaje, hacer_pedido):
    from cassette_fm.dj.hechos import Hechos
    from cassette_fm.dj.hechos.clima import Clima
    from cassette_fm.dj.hechos.musicbrainz import DatosTema

    class Fuente:
        def reunir(self, pedido, con_wikipedia=False, hasta=None):
            return (Hechos(Clima(22, "lluvia", True), DatosTema(1984, "NO", 1983, True, "https://mb/x")),
                    {"clima": {"temperatura": 22}, "musicbrainz": {"fuente": "https://mb/x"}})

    crear, _, guiones = montaje
    productor, _ = crear()
    productor._hechos = Fuente()
    productor._config = ConfigServicioDJ(pesos_ingredientes={k: 1.0 for k in ("estacion", "hora", "momento", "album",
                                                                              "anterior", "clima", "dato")})
    productor.producir(hacer_pedido("h1"))
    (g,) = guiones.ultimos(5)
    assert g["hechos"] == {"clima": {"temperatura": 22}, "musicbrainz": {"fuente": "https://mb/x"}}
    assert "cancion" in g["ingredientes"]


def test_sin_fuente_de_hechos_funciona_como_antes(montaje, hacer_pedido):
    crear, _, guiones = montaje
    productor, _ = crear()
    productor.producir(hacer_pedido("h2"))
    assert "hechos" not in guiones.ultimos(1)[0]


def test_los_reintentos_por_duracion_no_vuelven_a_pedir_hechos(montaje, hacer_pedido):
    from cassette_fm.dj.hechos import Hechos

    class Fuente:
        llamadas = 0

        def reunir(self, pedido, con_wikipedia=False, hasta=None):
            Fuente.llamadas += 1
            return Hechos(), {"clima": None, "musicbrainz": None}

    crear, _, _ = montaje
    productor, _ = crear(SintetizadorFalso(duraciones=(30.0, 30.0, 4.0)))
    productor._hechos = Fuente()
    productor.producir(hacer_pedido("h3", duracion_maxima_segundos=10.0))
    assert Fuente.llamadas == 1


def test_los_recientes_del_pedido_llegan_al_selector(montaje, hacer_pedido, monkeypatch):
    from cassette_fm.dj import plantillas
    vistos = []
    original = plantillas.elegir_ingredientes

    def espia(disponibles, pesos, recientes, azar, maximo=3, penalizacion=0.3):
        vistos.append((tuple(recientes), maximo, penalizacion))
        return original(disponibles, pesos, recientes, azar, maximo, penalizacion)

    monkeypatch.setattr(plantillas, "elegir_ingredientes", espia)
    crear, _, _ = montaje
    productor, _ = crear()
    productor._config = ConfigServicioDJ(ingredientes_max=2, penalizacion_reciente=0.5)
    productor.producir(hacer_pedido("h4", recientes=["hora", "clima"]))
    assert vistos == [(("hora", "clima"), 2, 0.5)]



# --- modo llm (parte 4) ---

from cassette_fm.dj.hechos import Hechos as _Hechos  # noqa: E402
from cassette_fm.dj.hechos.wikipedia import Resumen as _Resumen  # noqa: E402
from cassette_fm.dj.llm import ErrorLLM  # noqa: E402
from cassette_fm.dj.modo import ModoDJ  # noqa: E402

MOMENTO = datetime.fromisoformat("2026-11-13T21:47:00-03:00").timestamp()


class RelojFalso:
    def __init__(self, t=MOMENTO - 600):
        self.t = t

    def __call__(self):
        return self.t


BUENA = "Ahora suena Waiting for a Girl Like You de Foreigner para todos ustedes esta noche."


class LLMFalso:
    def __init__(self, *respuestas):
        self.respuestas = list(respuestas) or [BUENA]
        self.llamadas = []
        self.reloj, self.consume = None, 0

    def generar(self, sistema, usuario, timeout=None):
        self.llamadas.append((sistema, usuario))
        self.timeouts = getattr(self, "timeouts", []) + [timeout]
        if self.reloj is not None and self.consume:
            self.reloj.t += self.consume
        r = self.respuestas.pop(0) if len(self.respuestas) > 1 else self.respuestas[0]
        if isinstance(r, Exception):
            raise r
        return r


class FuenteWiki:
    def __init__(self, tema=None):
        self.llamadas = []
        self.tema = tema

    def reunir(self, pedido, con_wikipedia=False, hasta=None):
        self.llamadas.append(con_wikipedia)
        self.plazos = getattr(self, "plazos", []) + [hasta]
        wiki = _Resumen("Foreigner es una banda de rock.", "Foreigner", "es", "https://es.wikipedia.org/wiki/Foreigner") \
            if con_wikipedia else None
        return _Hechos(tema=self.tema, wikipedia=wiki), {"clima": None, "musicbrainz": None,
                                         "wikipedia": {"url": wiki.url, "titulo": wiki.titulo, "idioma": "es"} if wiki else None}


def llm_listo(montaje, *respuestas, modo="llm", config=None):
    crear, rutas, guiones = montaje
    llm = LLMFalso(*respuestas)
    fuente = FuenteWiki()
    productor, sint = crear(config=config, modo=ModoDJ(modo), llm=llm, hechos=fuente, reloj=RelojFalso())
    return productor, sint, llm, fuente, guiones


def test_en_plantillas_no_se_llama_al_llm_ni_a_wikipedia(montaje, hacer_pedido):
    productor, _, llm, fuente, guiones = llm_listo(montaje, modo="plantillas")
    productor.producir(hacer_pedido("m1"))
    assert llm.llamadas == [] and fuente.llamadas == [False]
    assert guiones.ultimos(1)[0]["fuente"] == "plantilla" and "motivo" not in guiones.ultimos(1)[0]


def test_en_llm_usa_la_frase_del_llm_y_la_anota(montaje, hacer_pedido):
    productor, sint, llm, fuente, guiones = llm_listo(montaje)
    r = productor.producir(hacer_pedido("m2"))
    assert fuente.llamadas == [True] and len(llm.llamadas) == 1
    assert r.texto == BUENA and "cancion" in r.ingredientes
    (g,) = guiones.ultimos(5)
    assert g["fuente"] == "llm" and g["crudo"] == BUENA and g["modelo"] == "gemma3:4b" and g["intento"] == 1
    assert g["sistema"] and "Waiting for a Girl Like You" in g["usuario"] and "descartado" not in g
    assert g["hechos"]["wikipedia"]["url"] == "https://es.wikipedia.org/wiki/Foreigner"
    assert "{es:Waiting for a Girl Like You}" in g["marcado"] and "{es:Foreigner}" in g["marcado"]


def test_en_llm_el_dato_va_siempre_que_haya_uno_y_se_respeta_el_maximo(montaje, hacer_pedido):
    productor, _, _, _, _ = llm_listo(montaje, *([BUENA] * 40))
    for i in range(40):
        r = productor.producir(hacer_pedido(f"d{i}"))
        assert "dato" in r.ingredientes and "cancion" in r.ingredientes
        assert len(r.ingredientes) <= 3


def test_el_tope_de_palabras_del_llm_sale_de_la_duracion_maxima_del_pedido(montaje, hacer_pedido):
    muchos = ConfigServicioDJ(pesos_ingredientes={"estacion": 1.0, "hora": 1.0, "momento": 1.0, "album": 1.0,
                                                  "anterior": 1.0, "clima": 1.0, "dato": 1.0}, ingredientes_max=8)
    productor, _, _, _, guiones = llm_listo(montaje, config=muchos)
    productor.producir(hacer_pedido("m3", duracion_maxima_segundos=25))
    productor.producir(hacer_pedido("m4", duracion_maxima_segundos=15, voz="af_heart"))   # voz sin clips medidos
    largo, corto = guiones.ultimos(5)[-2:]
    assert "entre 37 y 75 palabras" in largo["sistema"]
    assert "entre 22 y 45 palabras" in corto["sistema"]


def test_el_texto_del_llm_pasa_por_numeros_y_marcado(montaje, hacer_pedido):
    from cassette_fm.dj.hechos.musicbrainz import DatosTema
    crear, _, guiones = montaje
    llm = LLMFalso("Ahora suena Waiting for a Girl Like You de Foreigner que salió en 1984 para todos ustedes.")
    cfg = ConfigServicioDJ(pesos_ingredientes={"estacion": 0.0, "hora": 0.0, "momento": 0.0, "album": 0.0,
                                               "anterior": 0.0, "clima": 0.0, "dato": 1.0})
    productor, _ = crear(config=cfg, modo=ModoDJ("llm"), llm=llm,
                         hechos=FuenteWiki(DatosTema(1984, "GB", 1976, True, "u", "Q1")), reloj=RelojFalso())
    r = productor.producir(hacer_pedido("m3"))
    assert "mil novecientos ochenta y cuatro" in r.texto and "1984" not in r.texto
    (g,) = guiones.ultimos(5)
    assert "1984" in g["crudo"] and "{es:Foreigner}" in g["marcado"]


def test_un_numero_inventado_se_descarta_y_se_anota(montaje, hacer_pedido):
    productor, _, _, _, guiones = llm_listo(
        montaje, "Ahora suena Waiting for a Girl Like You de Foreigner con 22 grados afuera esta noche.")
    productor._config = ConfigServicioDJ(pesos_ingredientes={k: 0.0 for k in ("estacion", "hora", "momento", "album",
                                                                                "anterior", "clima", "dato")})
    productor.producir(hacer_pedido("m3b"))
    assert any(x.get("motivo", "").startswith("número") for x in guiones.ultimos(5))


def test_si_la_frase_no_pasa_la_verificacion_se_pide_otra_y_se_anota_la_descartada(montaje, hacer_pedido):
    inventada = "Ahora suena Waiting for a Girl Like You de Foreigner, como Michael Jackson en esa época dorada."
    productor, _, llm, _, guiones = llm_listo(montaje, inventada, BUENA)
    r = productor.producir(hacer_pedido("m4"))
    assert len(llm.llamadas) == 2 and r.texto == BUENA
    primero, segundo = guiones.ultimos(5)
    assert primero["descartado"] is True and "nombre propio" in primero["motivo"] and primero["intento"] == 1
    assert "descartado" not in segundo and segundo["intento"] == 2


def test_agotados_los_intentos_sale_la_plantilla_con_el_motivo(montaje, hacer_pedido):
    productor, _, llm, _, guiones = llm_listo(montaje, "Hola.", "Hola de nuevo.")
    r = productor.producir(hacer_pedido("m5"))
    assert len(llm.llamadas) == 2 and r.texto
    *descartados, ultimo = guiones.ultimos(5)
    assert [d["fuente"] for d in descartados] == ["llm", "llm"] and all(d["descartado"] for d in descartados)
    assert ultimo["fuente"] == "plantilla" and ultimo["motivo"] and "descartado" not in ultimo


def test_error_del_llm_cae_a_plantillas_y_avisa_una_vez(montaje, hacer_pedido, caplog):
    import logging
    productor, _, llm, _, guiones = llm_listo(montaje, ErrorLLM("el LLM no responde en x"))
    with caplog.at_level(logging.WARNING, logger="cassette_fm"):
        productor.producir(hacer_pedido("m6"))
        productor.producir(hacer_pedido("m7"))
    assert len([r for r in caplog.records if r.levelno == logging.WARNING and "LLM" in r.getMessage()]) == 1
    ultimo = guiones.ultimos(1)[0]
    assert ultimo["fuente"] == "plantilla" and "no responde" in ultimo["motivo"]


def test_el_aviso_se_rearma_despues_de_un_exito(montaje, hacer_pedido, caplog):
    import logging
    productor, _, llm, _, _ = llm_listo(montaje, ErrorLLM("el LLM caído"), BUENA, ErrorLLM("el LLM otra vez"))
    llm.respuestas = [ErrorLLM("el LLM caído"), BUENA, ErrorLLM("el LLM de nuevo")]
    with caplog.at_level(logging.WARNING, logger="cassette_fm"):
        productor.producir(hacer_pedido("m8"))       # falla: aviso 1
        productor.producir(hacer_pedido("m9"))       # éxito
        productor.producir(hacer_pedido("m10"))      # falla: aviso 2
    assert len([r for r in caplog.records if r.levelno == logging.WARNING and "LLM" in r.getMessage()]) == 2


def test_llm_pedido_sin_cliente_usa_plantillas(montaje, hacer_pedido):
    crear, _, guiones = montaje
    productor, _ = crear(modo=ModoDJ("llm"), llm=None, hechos=FuenteWiki(), reloj=RelojFalso())
    productor.producir(hacer_pedido("m11"))
    g = guiones.ultimos(1)[0]
    assert g["fuente"] == "plantilla" and "LLM" in g["motivo"]


CORTA = "Suena Waiting for a Girl Like You de Foreigner."


def test_un_clip_largo_del_llm_se_reintenta_mas_corto(montaje, hacer_pedido):
    crear, _, guiones = montaje
    llm = LLMFalso(BUENA, CORTA)
    productor, _ = crear(sintetizador=SintetizadorFalso(duraciones=(30.0, 4.0)), modo=ModoDJ("llm"), llm=llm,
                         hechos=FuenteWiki(), reloj=RelojFalso())
    r = productor.producir(hacer_pedido("m12", duracion_maxima_segundos=10.0))
    assert r.duracion == 4.0 and r.texto == CORTA
    g = guiones.ultimos(5)
    assert [x["fuente"] for x in g] == ["llm", "llm"] and g[0]["descartado"] and g[0]["motivo"].startswith("el clip dura")
    assert llm.llamadas[1][0] != llm.llamadas[0][0]            # el segundo pedido pide menos palabras


def test_si_el_clip_del_llm_sigue_largo_cae_a_plantillas(montaje, hacer_pedido):
    crear, _, guiones = montaje
    productor, _ = crear(sintetizador=SintetizadorFalso(duraciones=(30.0, 30.0, 4.0)), modo=ModoDJ("llm"),
                         llm=LLMFalso(BUENA, CORTA), hechos=FuenteWiki(), reloj=RelojFalso())
    r = productor.producir(hacer_pedido("m12b", duracion_maxima_segundos=10.0))
    assert r.duracion == 4.0
    g = guiones.ultimos(5)
    assert [x["fuente"] for x in g] == ["llm", "llm", "plantilla"]
    assert g[0]["descartado"] and g[1]["descartado"] and g[2]["motivo"].startswith("el clip dura")


def test_el_modo_se_lee_una_sola_vez_por_pedido(montaje, hacer_pedido):
    modo = ModoDJ("llm")
    crear, _, guiones = montaje
    llm = LLMFalso(BUENA)
    original = llm.generar

    def cambia_el_modo(sistema, usuario, timeout=None):
        modo.poner("plantillas")                     # a mitad del pedido
        return original(sistema, usuario, timeout)

    llm.generar = cambia_el_modo
    productor, _ = crear(modo=modo, llm=llm, hechos=FuenteWiki(), reloj=RelojFalso())
    productor.producir(hacer_pedido("m13"))
    assert guiones.ultimos(1)[0]["fuente"] == "llm"          # terminó como empezó
    productor.producir(hacer_pedido("m14"))                  # el siguiente ya usa el modo nuevo
    assert guiones.ultimos(1)[0]["fuente"] == "plantilla" and len(llm.llamadas) == 1


def test_los_ingredientes_reales_se_devuelven(montaje, hacer_pedido):
    productor, _, llm, _, _ = llm_listo(montaje)
    productor._config = ConfigServicioDJ(pesos_ingredientes={"estacion": 1.0, "hora": 0.0, "momento": 0.0,
                                                              "album": 0.0, "anterior": 0.0, "clima": 0.0, "dato": 0.0},
                                         ingredientes_max=3)
    r = productor.producir(hacer_pedido("m15"))
    sistema, usuario = llm.llamadas[0]
    assert set(r.ingredientes) == {"cancion", "estacion", "dato"}            # el dato va siempre que haya uno
    assert "Estación" in usuario and "Dato" in usuario and "Hora" not in usuario and "Álbum" not in usuario


def test_los_guiones_descartados_no_entran_en_voz_prueba(montaje, hacer_pedido):
    productor, _, _, _, guiones = llm_listo(montaje, "Hola.", "Hola otra vez.")
    productor.producir(hacer_pedido("m16"))
    validos = [g for g in guiones.ultimos(10) if not g.get("descartado") and g.get("marcado") and g.get("texto")]
    assert len(validos) == 1 and validos[0]["fuente"] == "plantilla"


# --- presupuesto de tiempo y orden de las conversiones (revisión final) ---

def test_sin_tiempo_para_el_llm_va_directo_a_plantillas(montaje, hacer_pedido):
    crear, _, guiones = montaje
    llm = LLMFalso()
    productor, _ = crear(modo=ModoDJ("llm"), llm=llm, hechos=FuenteWiki(), reloj=RelojFalso(MOMENTO - 20))
    productor.producir(hacer_pedido("t1"))
    assert llm.llamadas == []
    g = guiones.ultimos(1)[0]
    assert g["fuente"] == "plantilla" and "tiempo" in g["motivo"]


def test_cada_llamada_al_llm_tiene_a_lo_sumo_el_tiempo_que_queda(montaje, hacer_pedido):
    crear, _, _ = montaje
    llm = LLMFalso()
    cfg = ConfigServicioDJ(llm_timeout_segundos=240.0, llm_margen_segundos=45.0)
    productor, _ = crear(config=cfg, modo=ModoDJ("llm"), llm=llm, hechos=FuenteWiki(), reloj=RelojFalso(MOMENTO - 100))
    productor.producir(hacer_pedido("t2"))
    assert llm.timeouts == [pytest.approx(55.0)]
    llm2 = LLMFalso()
    productor, _ = crear(config=cfg, modo=ModoDJ("llm"), llm=llm2, hechos=FuenteWiki(), reloj=RelojFalso(MOMENTO - 600))
    productor.producir(hacer_pedido("t3"))
    assert llm2.timeouts == [pytest.approx(240.0)]


def test_si_el_primer_intento_gasta_el_tiempo_no_hay_segundo(montaje, hacer_pedido):
    crear, _, guiones = montaje
    reloj = RelojFalso(MOMENTO - 120)
    llm = LLMFalso("Hola.", "Hola otra vez.")
    llm.reloj, llm.consume = reloj, 75.0                  # la primera llamada gasta 75 s: no queda tiempo
    productor, _ = crear(config=ConfigServicioDJ(llm_margen_segundos=45.0), modo=ModoDJ("llm"), llm=llm,
                         hechos=FuenteWiki(), reloj=reloj)
    productor.producir(hacer_pedido("t4"))
    assert len(llm.llamadas) == 1
    assert guiones.ultimos(1)[0]["fuente"] == "plantilla" and "tiempo" in guiones.ultimos(1)[0]["motivo"]


def test_un_nombre_con_numero_llega_marcado_y_sin_convertir(montaje, hacer_pedido):
    crear, _, guiones = montaje
    llm = LLMFalso("Ahora suena With or Without You de U2 para todos ustedes esta noche.")
    productor, _ = crear(modo=ModoDJ("llm"), llm=llm, hechos=FuenteWiki(), reloj=RelojFalso(),
                         lexico=Lexico({"U2": "en-us"}))
    r = productor.producir(hacer_pedido("t5", siguiente={"artista": "U2", "titulo": "With or Without You"}))
    assert "U2" in r.texto and "Udos" not in r.texto
    assert "{en-us:U2}" in guiones.ultimos(1)[0]["marcado"]


class FuenteSinDatos:
    def __init__(self):
        self.llamadas = []

    def reunir(self, pedido, con_wikipedia=False, hasta=None):
        self.llamadas.append(con_wikipedia)
        return _Hechos(tema=None, wikipedia=None), {"clima": None, "musicbrainz": None, "wikipedia": None}


def test_sin_ningun_dato_real_no_se_llama_al_llm_y_sale_la_plantilla(montaje, hacer_pedido):
    crear, _, guiones = montaje
    llm = LLMFalso()
    productor, _ = crear(modo=ModoDJ("llm"), llm=llm, hechos=FuenteSinDatos(), reloj=RelojFalso())
    r = productor.producir(hacer_pedido("sd1"))
    assert llm.llamadas == [] and r.texto
    g = guiones.ultimos(1)[0]
    assert g["fuente"] == "plantilla" and "sin datos" in g["motivo"]


def test_una_oracion_con_un_dato_inventado_se_saca_y_la_frase_se_usa(montaje, hacer_pedido):
    mala = ("Ahora suena Waiting for a Girl Like You de Foreigner. Salió en 1981 y la escuchó todo el mundo. "
            "Seguimos con más música para todos ustedes esta noche.")
    productor, _, llm, _, guiones = llm_listo(montaje, mala)
    r = productor.producir(hacer_pedido("sv1"))
    assert len(llm.llamadas) == 1 and "1981" not in r.texto and "mil" not in r.texto
    assert r.texto.startswith("Ahora suena Waiting for a Girl Like You de Foreigner.")
    g = guiones.ultimos(1)[0]
    assert g["fuente"] == "llm" and "descartado" not in g and g["recortado"].startswith("número")


_MUCHOS = ConfigServicioDJ(pesos_ingredientes={"estacion": 1.0, "hora": 1.0, "momento": 1.0, "album": 1.0,
                                               "anterior": 1.0, "clima": 1.0, "dato": 1.0}, ingredientes_max=8)


def test_el_tope_de_palabras_usa_lo_que_de_verdad_habla_cada_voz(montaje, hacer_pedido):
    crear, _, guiones = montaje
    guiones.anotar(voz="em_santa", texto=" ".join(["palabra"] * 40), duracion=20.0)    # voz lenta: 2 por segundo
    productor, _ = crear(config=_MUCHOS, modo=ModoDJ("llm"), llm=LLMFalso(), hechos=FuenteWiki(), reloj=RelojFalso())
    productor.producir(hacer_pedido("v1", duracion_maxima_segundos=25))
    productor.producir(hacer_pedido("v2", duracion_maxima_segundos=25, voz="af_heart"))
    lenta, otra = [g for g in guiones.ultimos(10) if g.get("fuente") == "llm"]
    assert "y 47 palabras" in lenta["sistema"]              # 25 s × 2 palabras/s × 0,95
    assert "y 75 palabras" in otra["sistema"]               # sin historial: 3 palabras por segundo


def test_la_velocidad_de_la_voz_se_aprende_con_cada_clip(montaje, hacer_pedido):
    crear, _, guiones = montaje
    sint = SintetizadorFalso(duraciones=(60.0, 5.0))       # el primer clip sale larguísimo: la voz es lenta
    productor, _ = crear(sintetizador=sint, config=_MUCHOS, modo=ModoDJ("llm"), llm=LLMFalso(),
                         hechos=FuenteWiki(), reloj=RelojFalso())
    productor.producir(hacer_pedido("a1"))
    productor.producir(hacer_pedido("a2", duracion_maxima_segundos=25))
    ultimo = [g for g in guiones.ultimos(10) if g.get("fuente") == "llm"][-1]
    tope = int(ultimo["sistema"].split(" palabras")[0].split()[-1])
    assert tope < 40


def test_el_llm_que_saluda_con_el_momento_equivocado_se_corrige(montaje, hacer_pedido):
    mala = "Buenos días, esta mañana suena Waiting for a Girl Like You de Foreigner para todos ustedes."
    productor, _, _, _, _ = llm_listo(montaje, mala)
    r = productor.producir(hacer_pedido("cm1"))             # el pedido es a las 21:47
    assert r.texto.startswith("Buenas noches") and "esta noche suena" in r.texto


def test_el_arranque_del_prompt_se_sortea_entre_pedidos(montaje, hacer_pedido):
    from cassette_fm.dj.redactor_llm import ARRANQUES
    productor, _, llm, _, _ = llm_listo(montaje)
    for i in range(8):
        productor.producir(hacer_pedido(f"ar{i}"))
    usados = {clave for sistema, _ in llm.llamadas for clave, (es, _en) in ARRANQUES.items() if es in sistema}
    assert len(usados) > 1
    assert all(sum(es in sistema for es, _en in ARRANQUES.values()) == 1 for sistema, _ in llm.llamadas)


@pytest.mark.parametrize("modo, reserva", [("llm", 60.0), ("plantillas", 0.0)])
def test_los_hechos_se_esperan_hasta_lo_que_deja_la_voz_y_el_llm(montaje, hacer_pedido, modo, reserva):
    productor, _, _, fuente, _ = llm_listo(montaje, modo=modo)
    productor.producir(hacer_pedido("pz1"))
    assert fuente.plazos == [MOMENTO - ConfigServicioDJ().llm_margen_segundos - reserva]


def test_el_ritmo_medido_con_el_nombre_crudo_vale_para_su_alias(montaje, hacer_pedido):
    from dataclasses import replace
    crear, _, guiones = montaje
    guiones.anotar(voz="em_santa", texto=" ".join(["palabra"] * 40), duracion=20.0)    # 2 palabras por segundo
    config = replace(_MUCHOS, voces={"santa": "em_santa"})
    productor, _ = crear(config=config, modo=ModoDJ("llm"), llm=LLMFalso(), hechos=FuenteWiki(), reloj=RelojFalso())
    productor.producir(hacer_pedido("al1", duracion_maxima_segundos=25, voz="santa"))
    (g,) = [g for g in guiones.ultimos(10) if g.get("fuente") == "llm"]
    assert "y 47 palabras" in g["sistema"]
