import json
import socket
import threading
import time
import urllib.request
import wave
from pathlib import Path

import pytest

from cassette_fm.dj import cli, sintetizador as mod_sint
from cassette_fm.dj.config import ConfigServicioDJ, RutasDJ
from cassette_fm.dj.guiones import RegistroGuiones
from cassette_fm.dj.pedido import IDIOMAS
from cassette_fm.dj.sintetizador import ErrorModelos
from cassette_fm.dj.texto_voz import preparar


def fon_falso(texto, lang):
    return f"<{lang}:{texto}>"


class SintetizadorFalso:
    def __init__(self, voces=("em_santa", "em_alex")):
        self.llamadas = []
        self.textos = []
        self._voces = list(voces)

    def sintetizar(self, fonemas, voz, lang, salida, velocidad=None, texto=None):
        self.llamadas.append((fonemas, voz, lang, Path(salida)))
        self.textos.append(texto)
        Path(salida).parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(salida), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(8000)
            w.writeframes(b"\0\0" * 80)
        return 0.5

    def voces(self):
        return self._voces


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "c"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "s"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "k"))
    return RutasDJ(config=tmp_path / "c/cassette-dj/config.toml", estado=tmp_path / "s/cassette-dj",
                   clips=tmp_path / "k/cassette-dj/clips")


def cargar_guiones(rutas, items):
    g = RegistroGuiones(rutas.guiones)
    for i in items:
        g.anotar(**i)
    return g


def guion(texto, marcado=None, idioma="es", **extra):
    return dict(id="x", estacion="Power", idioma=idioma, voz="em_santa", fuente="plantilla",
                texto=texto, marcado=marcado or texto, **extra)


def test_voz_prueba_resintetiza_los_guiones_tal_cual(entorno, tmp_path, capsys):
    cargar_guiones(entorno, [
        guion("Seguimos con Daddy Yankee y su tema Gasolina para todos.",
              "Seguimos con {en-us:Daddy Yankee} y su tema {es:Gasolina} para todos."),
        guion("Esto es un descartado que no debe usarse en la prueba de voz.", descartado=True),
        guion("Esto falló y no tiene texto utilizable en la prueba de voz.", error="boom"),
        guion("Coming up next we have the best music for you tonight.", idioma="en"),
    ])
    sint = SintetizadorFalso()
    salida = tmp_path / "salida"
    rc = cli.main(["voz-prueba", "--voz", "em_santa", "--voz", "em_alex", "--idioma", "es", "--salida", str(salida)],
                  sintetizador=sint, fonemizar=fon_falso)
    assert rc == 0
    assert sorted(p.name for p in salida.iterdir()) == ["01-em_alex.wav", "01-em_santa.wav"]
    esperado = preparar("Seguimos con {en-us:Daddy Yankee} y su tema {es:Gasolina} para todos.", "es", fon_falso).fonemas
    assert [c[0] for c in sint.llamadas] == [esperado, esperado]
    assert [c[1] for c in sint.llamadas] == ["em_santa", "em_alex"]
    assert "Seguimos con Daddy Yankee" in capsys.readouterr().out


def test_voz_prueba_le_pasa_el_texto_a_piper(entorno, tmp_path):
    cargar_guiones(entorno, [guion("Seguimos con la mejor música para todos ustedes.")])
    sint = SintetizadorFalso()
    assert cli.main(["voz-prueba", "--voz", "piper:es_AR-daniela-high", "--salida", str(tmp_path / "s")],
                    sintetizador=sint, fonemizar=fon_falso) == 0
    assert sint.textos == ["Seguimos con la mejor música para todos ustedes."]


def test_voz_prueba_toma_los_ultimos_n_en_orden(entorno, tmp_path):
    cargar_guiones(entorno, [guion(f"Texto número {i} de prueba para la voz del programa.") for i in range(6)])
    sint = SintetizadorFalso()
    cli.main(["voz-prueba", "--voz", "em_santa", "--ultimos", "2", "--salida", str(tmp_path / "o")],
             sintetizador=sint, fonemizar=fon_falso)
    assert [c[0].count("número") for c in sint.llamadas] == [1, 1]
    assert "número 4" in sint.llamadas[0][0] and "número 5" in sint.llamadas[1][0]
    assert sorted(p.name for p in (tmp_path / "o").iterdir()) == ["01-em_santa.wav", "02-em_santa.wav"]


def test_voz_prueba_sin_guiones_explica_que_hacer(entorno, tmp_path, capsys):
    rc = cli.main(["voz-prueba", "--voz", "em_santa", "--salida", str(tmp_path / "o")],
                  sintetizador=SintetizadorFalso(), fonemizar=fon_falso)
    assert rc == 1 and "guiones" in capsys.readouterr().err


def test_voz_prueba_exige_al_menos_una_voz(entorno, capsys):
    with pytest.raises(SystemExit):
        cli.main(["voz-prueba"], sintetizador=SintetizadorFalso(), fonemizar=fon_falso)


def test_guiones_imprime_los_ultimos(entorno, capsys):
    cargar_guiones(entorno, [guion("Primero para probar el listado de guiones del servicio."),
                             guion("Segundo para probar el listado de guiones del servicio.")])
    assert cli.main(["guiones", "--ultimos", "1"]) == 0
    salida = capsys.readouterr().out
    assert "Segundo" in salida and "Primero" not in salida and "Power" in salida and "em_santa" in salida


def test_guiones_sin_registro_lo_dice(entorno, capsys):
    assert cli.main(["guiones"]) == 0
    assert "no hay guiones" in capsys.readouterr().out.lower()


def test_modelos_dice_que_ya_estan(entorno, monkeypatch, capsys):
    llamadas = []
    monkeypatch.setattr(mod_sint, "faltan_modelos", lambda d: [])
    monkeypatch.setattr(mod_sint, "descargar_modelos", lambda *a, **k: llamadas.append(a) or [])
    assert cli.main(["modelos"]) == 0
    assert llamadas == [] and "ya están" in capsys.readouterr().out


def test_modelos_error_de_red_da_codigo_1(entorno, monkeypatch, capsys):
    import urllib.error
    monkeypatch.setattr(mod_sint, "faltan_modelos", lambda d: [Path("x")])

    def falla(*a, **k):
        raise urllib.error.URLError("sin red")

    monkeypatch.setattr(mod_sint, "descargar_modelos", falla)
    assert cli.main(["modelos"]) == 1
    assert "No se pudieron bajar" in capsys.readouterr().err


def test_modelos_baja_los_que_faltan(entorno, monkeypatch, capsys):
    monkeypatch.setattr(mod_sint, "faltan_modelos", lambda d: [Path("kokoro-v1.0.onnx")])
    monkeypatch.setattr(mod_sint, "descargar_modelos", lambda d, **k: [Path("kokoro-v1.0.onnx")])
    assert cli.main(["modelos"]) == 0


def test_voces_lista_las_voces(entorno, capsys):
    assert cli.main(["voces"], sintetizador=SintetizadorFalso(("a_voz", "b_voz"))) == 0
    salida = capsys.readouterr().out
    assert "  a_voz\n  b_voz\n" in salida and "ninguno" in salida      # sin alias definidos, lo dice


def test_voces_separa_los_alias_kokoro_y_piper(entorno, capsys):
    entorno.config.parent.mkdir(parents=True)
    entorno.config.write_text('[voces]\nheart = "af_heart"\ndaniela = "piper:es_AR-daniela-high"\n'
                              'mezcla = "em_alex+em_santa"\nrota = "af_nadie"\n')
    disponibles = ("af_heart", "em_alex", "em_santa", "piper:es_AR-daniela-high", "heart", "daniela", "mezcla", "rota")
    assert cli.main(["voces"], sintetizador=SintetizadorFalso(disponibles)) == 0
    assert capsys.readouterr().out.splitlines() == [
        f"Alias ([voces] de {entorno.config}):",
        "  heart     → af_heart",
        "  daniela   → piper:es_AR-daniela-high",
        "  mezcla    → em_alex+em_santa",
        "  rota      → af_nadie   ¡esa voz no existe!",
        "",
        "Kokoro:",
        "  af_heart   (alias: heart)",
        "  em_alex    (alias: mezcla)",
        "  em_santa   (alias: mezcla)",
        "",
        "Piper:",
        "  piper:es_AR-daniela-high   (alias: daniela)",
    ]


def test_voces_sin_archivo_explica(entorno, capsys):
    class Sin:
        def voces(self):
            raise ErrorModelos("falta voices-v1.0.bin: corré `cassette-dj modelos`")

    assert cli.main(["voces"], sintetizador=Sin()) == 1
    assert "cassette-dj modelos" in capsys.readouterr().err


def test_config_invalida_da_mensaje_y_codigo_1(entorno, capsys):
    entorno.config.parent.mkdir(parents=True)
    entorno.config.write_text('puerto = "x"\n')
    assert cli.main(["voces"]) == 1
    assert "config.toml" in capsys.readouterr().err


def test_serve_arranca_aunque_falten_modelos(entorno, tmp_path):
    pytest.importorskip("kokoro_onnx")       # el fonemizador es del extra [dj]
    from cassette_fm.dj.servidor import servir
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        puerto = s.getsockname()[1]
    cfg = ConfigServicioDJ(puerto=puerto, modelos_dir=tmp_path / "vacio")
    parar = threading.Event()
    hilo = threading.Thread(target=servir, args=(cfg, entorno, parar), daemon=True)
    hilo.start()
    try:
        fin = time.monotonic() + 5
        datos = None
        while time.monotonic() < fin and datos is None:
            try:
                datos = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{puerto}/salud").read())
            except OSError:
                time.sleep(0.05)
        assert datos and datos["ok"] is True and datos["faltan_modelos"]
    finally:
        parar.set()
        hilo.join(5)
    assert not hilo.is_alive()


def test_serve_sin_el_extra_da_un_mensaje_claro_y_codigo_1(entorno, monkeypatch, capsys):
    from cassette_fm.dj import servidor

    def sin_extra():
        raise ErrorModelos("falta instalar el extra [dj] (pip install -e '.[dj]')")

    monkeypatch.setattr(servidor, "fonemizador", sin_extra)
    assert cli.main(["serve"]) == 1
    assert "extra [dj]" in capsys.readouterr().err


def test_cassette_dj_hechos_imprime_clima_y_tema(entorno, capsys):
    from cassette_fm.dj.hechos.clima import Clima
    from cassette_fm.dj.hechos.musicbrainz import DatosTema

    class ClimaF:
        def actual(self):
            return Clima(22, "lluvia", False)

    class MBF:
        def datos_del_tema(self, artista, titulo, isrc=None):
            self.visto = (artista, titulo, isrc)
            return DatosTema(1984, "NO", 1983, True, "https://musicbrainz.org/artist/x")

    mb = MBF()
    assert cli.main(["hechos", "--artista", "a-ha", "--titulo", "Take On Me", "--isrc", "NOA018500001"],
                clientes=(ClimaF(), mb)) == 0
    salida = capsys.readouterr().out
    assert "22" in salida and "lluvia" in salida and "noche" in salida
    assert "1984" in salida and "NO" in salida and "grupo" in salida and "1983" in salida
    assert "https://musicbrainz.org/artist/x" in salida and mb.visto == ("a-ha", "Take On Me", "NOA018500001")


def test_cassette_dj_hechos_sin_datos_lo_dice(entorno, capsys):
    class Nada:
        def actual(self):
            return None

        def datos_del_tema(self, *a, **k):
            return None

    assert cli.main(["hechos", "--artista", "x", "--titulo", "y"], clientes=(Nada(), Nada())) == 0
    salida = capsys.readouterr().out
    assert "sin datos" in salida.lower() or "no hay" in salida.lower()


def test_cassette_dj_hechos_sin_tema_solo_el_clima(entorno, capsys):
    class ClimaF:
        def actual(self):
            return None

    assert cli.main(["hechos"], clientes=(ClimaF(), None)) == 0
    assert "clima" in capsys.readouterr().out.lower()


def test_artista_y_titulo_van_juntos(entorno, capsys):
    with pytest.raises(SystemExit):
        cli.main(["hechos", "--artista", "x"])


def _servicio_en_marcha(entorno, tmp_path, **cfg):
    pytest.importorskip("kokoro_onnx")
    from cassette_fm.dj.servidor import servir
    with socket.socket() as sk:
        sk.bind(("127.0.0.1", 0))
        puerto = sk.getsockname()[1]
    entorno.config.parent.mkdir(parents=True, exist_ok=True)
    entorno.config.write_text(f"puerto = {puerto}\n")
    parar = threading.Event()
    hilo = threading.Thread(target=servir, args=(ConfigServicioDJ(puerto=puerto, modelos_dir=tmp_path / "v", **cfg),
                                                 entorno, parar), daemon=True)
    hilo.start()
    fin = time.monotonic() + 5
    while time.monotonic() < fin:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{puerto}/salud").read()
            break
        except OSError:
            time.sleep(0.05)
    return parar, hilo


def test_cassette_dj_modo_muestra_y_cambia(entorno, tmp_path, capsys):
    parar, hilo = _servicio_en_marcha(entorno, tmp_path)
    try:
        assert cli.main(["modo"]) == 0
        assert capsys.readouterr().out.strip() == "Modo del DJ: plantillas."
        assert cli.main(["modo", "llm"]) == 0
        assert "Modo del DJ: llm" in capsys.readouterr().out
        assert cli.main(["modo"]) == 0
        assert "llm" in capsys.readouterr().out
        assert cli.main(["modo", "plantillas"]) == 0
        assert capsys.readouterr().out.strip() == "Modo del DJ: plantillas."
    finally:
        parar.set()
        hilo.join(5)


def test_cassette_dj_modo_sin_servicio_da_error_claro(entorno, capsys):
    with socket.socket() as sk:
        sk.bind(("127.0.0.1", 0))
        puerto = sk.getsockname()[1]
    entorno.config.parent.mkdir(parents=True, exist_ok=True)
    entorno.config.write_text(f"puerto = {puerto}\n")
    assert cli.main(["modo"]) == 1
    assert "no responde" in capsys.readouterr().err


def test_cassette_dj_modo_argumento_invalido(entorno):
    with pytest.raises(SystemExit):
        cli.main(["modo", "otro"])


def _config_llm(entorno, llm_falso, extra=""):
    entorno.config.parent.mkdir(parents=True, exist_ok=True)
    entorno.config.write_text(f'llm_url = "{llm_falso.url}"\n{extra}')


def test_llm_estado_con_el_modelo_descargado(entorno, llm_falso, capsys):
    _config_llm(entorno, llm_falso)
    assert cli.main(["llm", "estado"]) == 0
    salida = capsys.readouterr().out
    assert llm_falso.url in salida and "gemma3:4b" in salida
    assert "servidor: responde" in salida and "modelo descargado: sí" in salida


def test_llm_estado_con_el_llm_caido(entorno, llm_falso, capsys):
    import socket as _s
    with _s.socket() as sk:
        sk.bind(("127.0.0.1", 0))
        puerto = sk.getsockname()[1]
    entorno.config.parent.mkdir(parents=True, exist_ok=True)
    entorno.config.write_text(f'llm_url = "http://127.0.0.1:{puerto}/v1"\n')
    assert cli.main(["llm", "estado"]) == 1
    salida = capsys.readouterr().out
    assert "servidor: no responde" in salida and "instalar-llm.sh" in salida


def test_llm_estado_sin_el_modelo(entorno, llm_falso, capsys):
    llm_falso.modelos = [{"id": "otro:7b"}]
    _config_llm(entorno, llm_falso)
    assert cli.main(["llm", "estado"]) == 1
    salida = capsys.readouterr().out
    assert "servidor: responde" in salida and "modelo descargado: no" in salida
    assert "ollama pull gemma3:4b" in salida


def test_llm_modelo_imprime_solo_el_nombre(entorno, llm_falso, capsys):
    _config_llm(entorno, llm_falso, 'llm_modelo = "qwen3:4b"\n')
    assert cli.main(["llm", "modelo"]) == 0
    assert capsys.readouterr().out == "qwen3:4b\n"


def test_llm_sin_subcomando_es_un_error_de_uso():
    with pytest.raises(SystemExit):
        cli.main(["llm"])


def _script():
    return Path(__file__).resolve().parents[2] / "scripts" / "instalar-llm.sh"


def test_el_script_de_instalacion_es_bash_valido():
    import subprocess
    assert _script().is_file() and _script().stat().st_mode & 0o111
    assert subprocess.run(["bash", "-n", str(_script())], capture_output=True).returncode == 0
    assert "set -euo pipefail" in _script().read_text()


def test_el_script_cita_las_variables_y_no_publica_el_puerto_afuera():
    import re
    texto = _script().read_text()
    for linea in texto.splitlines():
        if linea.lstrip().startswith(("#", "echo")):
            continue
        if linea.lstrip().startswith(("docker ", "mkdir ", "-v ")):
            assert not re.search(r'(?<!")\$\{?[A-Za-z_]+\}?(?!")', re.sub(r'"[^"]*"', "", linea)), linea
    assert "127.0.0.1:11434:11434" in texto and "0.0.0.0" not in texto
    assert "--restart unless-stopped" in texto and "ollama pull" in texto and "docker rm -f cassette-ollama" in texto
    # `docker ps | grep -q` con pipefail da 141 si docker sigue escribiendo: se pregunta por el contenedor directo
    assert "docker container inspect" in texto and "| grep -qx" not in texto
    assert "command -v curl" in texto


def test_guiones_muestra_la_fuente_y_el_motivo_de_los_del_llm(entorno, capsys):
    cargar_guiones(entorno, [
        {"id": "a", "estacion": "Power", "voz": "am_onyx", "idioma": "en", "fuente": "llm", "texto": None,
         "descartado": True, "motivo": "nombre propio que no está en los hechos: Michael", "crudo": "x"},
        {"id": "b", "estacion": "Power", "voz": "am_onyx", "idioma": "en", "fuente": "plantilla",
         "texto": "Now playing something for everybody out there.", "motivo": "el LLM no responde en x"},
        {"id": "c", "estacion": "Power", "voz": "am_onyx", "idioma": "en", "fuente": "llm",
         "texto": "Now playing a song by somebody for you.", "marcado": "x"}])
    assert cli.main(["guiones"]) == 0
    lineas = capsys.readouterr().out.strip().splitlines()
    assert "[llm] [descartado: nombre propio que no está en los hechos: Michael]" in lineas[0] 
    assert "[plantilla: el LLM no responde en x]" in lineas[1]
    assert lineas[2].endswith("[llm]")


def test_cassette_dj_modo_avisa_si_falta_el_modelo(entorno, tmp_path, capsys, monkeypatch):
    from cassette_fm.dj import servidor
    parar, hilo = _servicio_en_marcha(entorno, tmp_path)
    try:
        assert cli.main(["modo", "llm"]) == 0
        salida = capsys.readouterr().out
        assert "Modo del DJ: llm" in salida
    finally:
        parar.set()
        hilo.join(5)


def test_muestra_guarda_e_imprime_la_ruta_y_la_segunda_vez_no_pide(entorno, monkeypatch, capsys):
    from cassette_fm.cliente_dj import ClienteDJ
    pedidos = []
    monkeypatch.setattr(ClienteDJ, "muestra", lambda self, v, i, r: pedidos.append((v, i, r)) or b"RIFFwav")
    assert cli.main(["muestra", "--voz", "dora", "--idioma", "es", "--radio", "Sing"]) == 0
    ruta = Path(capsys.readouterr().out.strip())
    assert ruta.read_bytes() == b"RIFFwav" and ruta.parent == entorno.muestras
    assert cli.main(["muestra", "--voz", "dora", "--idioma", "es", "--radio", "Sing"]) == 0
    assert capsys.readouterr().out.strip() == str(ruta) and pedidos == [("dora", "es", "Sing")]


def test_muestra_con_el_servicio_caido_da_una_linea(entorno, monkeypatch, capsys):
    from cassette_fm.cliente_dj import ClienteDJ, ErrorDJ

    def caido(self, *a):
        raise ErrorDJ("el servicio DJ no responde en http://127.0.0.1:7720 (Connection refused)")
    monkeypatch.setattr(ClienteDJ, "muestra", caido)
    assert cli.main(["muestra", "--voz", "dora", "--idioma", "es"]) == 1
    error = capsys.readouterr().err
    assert "no responde" in error and error.count("\n") == 1
