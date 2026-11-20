import json
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request

import pytest

from cassette_fm import cli, servicio
from cassette_fm.config import Config, Rutas
from cassette_fm.servicio import servir


def puerto_libre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def llamar(puerto, metodo, ruta, cuerpo=None):
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{puerto}{ruta}", data=datos, method=metodo)
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def esperar_servicio(puerto):
    fin = time.monotonic() + 5
    while time.monotonic() < fin:
        try:
            return llamar(puerto, "GET", "/estado")
        except OSError:
            time.sleep(0.05)
    raise AssertionError("el servicio no arrancó")


def test_servir_de_punta_a_punta(tmp_path, dir_corto, crear_mp3):
    musica = tmp_path / "musica"
    crear_mp3(musica / "A" / "a.mp3", 30, titulo="Tema A")
    crear_mp3(musica / "B" / "b.mp3", 30, titulo="Tema B")
    rutas = Rutas(config=tmp_path / "config.toml", estado=tmp_path / "st" / "estado.json",
                  cache=tmp_path / "cache" / "d.json", runtime=dir_corto)
    puerto = puerto_libre()
    parar = threading.Event()
    hilo = threading.Thread(target=servir, kwargs=dict(
        config=Config(raiz_musica=musica, puerto=puerto, avisos=False), rutas=rutas,
        parar=parar, extra_args_mpv=["--ao=null"]), daemon=True)
    hilo.start()
    try:
        estado = esperar_servicio(puerto)
        assert estado["encendida"] is False  # arranca en silencio
        assert estado["estaciones"] == ["A", "B"]
        assert llamar(puerto, "POST", "/encender")["estacion"] == "A"
        e = llamar(puerto, "POST", "/siguiente")
        assert e["estacion"] == "B" and e["encendida"] is True
        assert json.loads(rutas.estado.read_text())["estacion"] == "B"
        assert llamar(puerto, "POST", "/apagar")["encendida"] is False
    finally:
        parar.set()
        hilo.join(3)
    assert not hilo.is_alive()
    assert subprocess.run(["pgrep", "-f", str(dir_corto / "mpv.sock")],
                          capture_output=True).returncode == 1


def test_servir_con_biblioteca_vacia_arranca(tmp_path, dir_corto):
    rutas = Rutas(config=tmp_path / "c.toml", estado=tmp_path / "e.json",
                  cache=tmp_path / "d.json", runtime=dir_corto)
    puerto = puerto_libre()
    parar = threading.Event()
    hilo = threading.Thread(target=servir, kwargs=dict(
        config=Config(raiz_musica=tmp_path / "no-existe", puerto=puerto), rutas=rutas,
        parar=parar, extra_args_mpv=["--ao=null"]), daemon=True)
    hilo.start()
    try:
        assert esperar_servicio(puerto)["estaciones"] == []
        req = urllib.request.Request(f"http://127.0.0.1:{puerto}/encender", data=b"", method="POST")
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req)
        assert exc.value.code == 409
        assert str(rutas.emisoras) in json.loads(exc.value.read())["error"]
    finally:
        parar.set()
        hilo.join(3)


def test_cli_serve_llama_a_servir(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    llamadas = []
    monkeypatch.setattr(servicio, "servir", lambda config, rutas, **kw: llamadas.append((config, rutas)))
    assert cli.main(["serve"]) == 0
    assert len(llamadas) == 1 and llamadas[0][0] == Config()


def test_cli_serve_respeta_puerto(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    llamadas = []
    monkeypatch.setattr(servicio, "servir", lambda config, rutas, **kw: llamadas.append(config))
    assert cli.main(["serve", "--puerto", "7999"]) == 0
    assert llamadas[0].puerto == 7999


def test_apagado_cierra_mpv_aunque_apagar_falle(tmp_path, dir_corto, monkeypatch):
    cerrado = []
    real_mpv, real_radio = servicio.ClienteMpv, servicio.Radio

    class MpvEspia(real_mpv):
        def cerrar(self):
            cerrado.append(1)
            super().cerrar()

    class RadioRota(real_radio):
        def apagar(self):
            raise RuntimeError("falla al apagar")

    monkeypatch.setattr(servicio, "ClienteMpv", MpvEspia)
    monkeypatch.setattr(servicio, "Radio", RadioRota)
    parar = threading.Event()
    parar.set()
    rutas = Rutas(tmp_path / "c.toml", tmp_path / "e.json", tmp_path / "d.json", dir_corto)
    servir(Config(raiz_musica=tmp_path / "x", puerto=0), rutas, parar=parar,
           extra_args_mpv=["--ao=null"])
    assert cerrado == [1]


def test_servir_loguea_el_arranque(tmp_path, dir_corto, caplog):
    import logging
    caplog.set_level(logging.INFO, logger="cassette_fm")
    parar = threading.Event()
    parar.set()
    rutas = Rutas(tmp_path / "c.toml", tmp_path / "e.json", tmp_path / "d.json", dir_corto)
    servir(Config(raiz_musica=tmp_path / "x", puerto=0), rutas, parar=parar,
           extra_args_mpv=["--ao=null"])
    assert "0 estaciones" in caplog.text


def _correr_un_instante(tmp_path, dir_corto, **cfg):
    parar = threading.Event()
    parar.set()
    rutas = Rutas(tmp_path / "c.toml", tmp_path / "st" / "estado.json", tmp_path / "ca" / "d.json", dir_corto)
    servir(Config(raiz_musica=tmp_path / "x", puerto=0, avisos=False, **cfg), rutas, parar=parar,
           extra_args_mpv=["--ao=null"])
    return rutas


def test_con_el_dj_apagado_no_se_crea_nada(tmp_path, dir_corto):
    rutas = _correr_un_instante(tmp_path, dir_corto)
    assert not rutas.intervenciones.exists() and not rutas.clips.exists()
    assert subprocess.run(["pgrep", "-f", str(dir_corto / "voz.sock")], capture_output=True).returncode == 1


def test_con_el_dj_activo_cierra_sin_dejar_ningun_mpv(tmp_path, dir_corto):
    from cassette_fm.config import ConfigDJ
    _correr_un_instante(tmp_path, dir_corto, dj=ConfigDJ(activo=True))
    for socket_ in ("mpv.sock", "voz.sock"):
        assert subprocess.run(["pgrep", "-f", str(dir_corto / socket_)], capture_output=True).returncode == 1


def test_con_el_dj_activo_el_registro_se_carga_del_disco(tmp_path, dir_corto, crear_wav):
    from cassette_fm.config import ConfigDJ
    rutas = Rutas(tmp_path / "c.toml", tmp_path / "st" / "estado.json", tmp_path / "ca" / "d.json", dir_corto)
    audio = crear_wav(rutas.clips / "k.wav", 3.0)
    rutas.intervenciones.parent.mkdir(parents=True)
    rutas.intervenciones.write_text(json.dumps([{
        "id": "k", "estacion": "E", "inicio": time.time() + 600, "duracion": 3.0,
        "audio": str(audio), "texto": "guardada antes del reinicio", "pista_destino": "/m/t.mp3"}]))
    puerto = puerto_libre()
    parar = threading.Event()
    hilo = threading.Thread(target=servir, kwargs=dict(
        config=Config(raiz_musica=tmp_path / "x", puerto=puerto, avisos=False, dj=ConfigDJ(activo=True)),
        rutas=rutas, parar=parar, extra_args_mpv=["--ao=null"]), daemon=True)
    hilo.start()
    try:
        esperar_servicio(puerto)
        (item,) = llamar(puerto, "GET", "/dj")["intervenciones"]
        assert item["texto"] == "guardada antes del reinicio" and item["estacion"] == "E"
    finally:
        parar.set()
        hilo.join(5)


def test_dj_de_punta_a_punta(tmp_path, dir_corto, crear_mp3, crear_wav):
    from cassette_fm.config import ConfigDJ
    musica = tmp_path / "musica"
    for n in range(3):
        crear_mp3(musica / "A" / f"t{n}.mp3", 3, titulo=f"Tema {n}")
    clip = crear_wav(tmp_path / "voz.wav", 3.0)
    rutas = Rutas(config=tmp_path / "config.toml", estado=tmp_path / "st" / "estado.json",
                  cache=tmp_path / "cache" / "d.json", runtime=dir_corto)
    puerto = puerto_libre()
    dj = ConfigDJ(activo=True, retraso_voz_segundos=0.1, rampa_bajada_segundos=0.05, rampa_subida_segundos=0.05)
    parar = threading.Event()
    hilo = threading.Thread(target=servir, kwargs=dict(
        config=Config(raiz_musica=musica, puerto=puerto, avisos=False, dj=dj), rutas=rutas,
        parar=parar, extra_args_mpv=["--ao=null"]), daemon=True)
    hilo.start()
    try:
        assert esperar_servicio(puerto)["encendida"] is False
        assert llamar(puerto, "POST", "/encender")["estacion"] == "A"
        r = llamar(puerto, "POST", "/dj/probar", {"audio": str(clip), "en_segundos": 1})
        assert r["estacion"] == "A" and r["duracion"] == pytest.approx(3.0, abs=0.1)
        estado = llamar(puerto, "GET", "/dj")
        assert estado["activo"] is True and len(estado["intervenciones"]) == 1
        habló = False
        fin = time.monotonic() + 12
        while time.monotonic() < fin:
            hablando = llamar(puerto, "GET", "/dj")["hablando"]
            habló = habló or hablando
            if habló and not hablando:
                break
            time.sleep(0.05)
        assert habló, "la voz nunca empezó"
        assert llamar(puerto, "GET", "/dj")["hablando"] is False, "la voz no terminó"
        assert llamar(puerto, "POST", "/apagar")["encendida"] is False
    finally:
        parar.set()
        hilo.join(5)
    assert not hilo.is_alive()
    assert subprocess.run(["pgrep", "-f", str(dir_corto / "voz.sock")], capture_output=True).returncode == 1


def test_dj_apagado_responde_estado_y_409_al_probar(tmp_path, dir_corto):
    rutas = Rutas(tmp_path / "c.toml", tmp_path / "e.json", tmp_path / "d.json", dir_corto)
    puerto = puerto_libre()
    parar = threading.Event()
    hilo = threading.Thread(target=servir, kwargs=dict(
        config=Config(raiz_musica=tmp_path / "x", puerto=puerto, avisos=False), rutas=rutas,
        parar=parar, extra_args_mpv=["--ao=null"]), daemon=True)
    hilo.start()
    try:
        esperar_servicio(puerto)
        assert llamar(puerto, "GET", "/dj")["activo"] is False
        req = urllib.request.Request(f"http://127.0.0.1:{puerto}/dj/probar", data=b"", method="POST")
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req)
        assert exc.value.code == 409
    finally:
        parar.set()
        hilo.join(5)


# --- planificador del DJ ---

def _arrancar(tmp_path, dir_corto, config):
    rutas = Rutas(config=tmp_path / "config.toml", estado=tmp_path / "st" / "estado.json",
                  cache=tmp_path / "cache" / "d.json", runtime=dir_corto)
    parar = threading.Event()
    hilo = threading.Thread(target=servir, kwargs=dict(config=config, rutas=rutas, parar=parar,
                                                        extra_args_mpv=["--ao=null"]), daemon=True)
    hilo.start()
    return rutas, parar, hilo


def _nombres_de_hilos():
    return {t.name for t in threading.enumerate()}


def test_con_dj_activo_sin_url_no_hay_planificador(tmp_path, dir_corto):
    from cassette_fm.config import ConfigDJ
    puerto = puerto_libre()
    _, parar, hilo = _arrancar(tmp_path, dir_corto,
                               Config(raiz_musica=tmp_path / "x", puerto=puerto, avisos=False,
                                      dj=ConfigDJ(activo=True)))
    try:
        esperar_servicio(puerto)
        assert llamar(puerto, "GET", "/dj")["planificador"] is None
        assert "planificador-dj" not in _nombres_de_hilos()
        req = urllib.request.Request(f"http://127.0.0.1:{puerto}/dj/pedir", data=b"", method="POST")
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req)
        assert exc.value.code == 409
    finally:
        parar.set()
        hilo.join(5)


def test_con_url_se_crea_el_planificador_y_se_cierra_limpio(tmp_path, dir_corto):
    from cassette_fm.config import ConfigDJ
    puerto = puerto_libre()
    antes = _nombres_de_hilos()
    _, parar, hilo = _arrancar(tmp_path, dir_corto,
                               Config(raiz_musica=tmp_path / "x", puerto=puerto, avisos=False,
                                      dj=ConfigDJ(activo=True, url=f"http://127.0.0.1:{puerto_libre()}")))
    try:
        esperar_servicio(puerto)
        assert llamar(puerto, "GET", "/dj")["planificador"]["servicio"] == "ok"
        assert "planificador-dj" in _nombres_de_hilos()
    finally:
        parar.set()
        hilo.join(5)
    assert not hilo.is_alive()
    assert "planificador-dj" not in _nombres_de_hilos()
    for socket_ in ("mpv.sock", "voz.sock"):
        assert subprocess.run(["pgrep", "-f", str(dir_corto / socket_)], capture_output=True).returncode == 1


def test_dj_de_punta_a_punta_con_el_servicio_real(tmp_path, dir_corto, crear_mp3, servicio_dj):
    from dataclasses import replace
    from cassette_fm.config import ConfigDJ, Frecuencia
    svc = servicio_dj(duracion=3.0)
    musica = tmp_path / "musica"
    for n in range(3):
        crear_mp3(musica / "A" / f"t{n}.mp3", 3, titulo=f"Tema {n}", artista=f"Artista {n}")
    puerto = puerto_libre()
    dj = ConfigDJ(activo=True, url=svc.url, margen_minutos=0.02, retraso_voz_segundos=0.1,
                  rampa_bajada_segundos=0.05, rampa_subida_segundos=0.05, frecuencia=Frecuencia("temas", 1, 1),
                  posicion_voz="inicio")      # con temas de 3 s un clip no cabe antes del corte: esta prueba es del recorrido
    rutas, parar, hilo = _arrancar(tmp_path, dir_corto,
                                   Config(raiz_musica=musica, puerto=puerto, avisos=False, dj=dj))
    try:
        assert esperar_servicio(puerto)["encendida"] is False
        assert llamar(puerto, "POST", "/encender")["estacion"] == "A"
        intervencion = None
        fin = time.monotonic() + 20
        while time.monotonic() < fin and intervencion is None:
            lista = llamar(puerto, "GET", "/dj")["intervenciones"]
            intervencion = lista[0] if lista else None
            time.sleep(0.05)
        assert intervencion is not None, "el DJ nunca reservó una intervención"
        assert intervencion["estacion"] == "A" and intervencion["texto"] and intervencion["texto"] != "(clip de prueba)"
        hablo = False
        fin = time.monotonic() + 25
        while time.monotonic() < fin:
            hablando = llamar(puerto, "GET", "/dj")["hablando"]
            hablo = hablo or hablando
            if hablo and not hablando:
                break
            time.sleep(0.05)
        assert hablo, "la voz nunca empezó"
        assert llamar(puerto, "GET", "/dj")["hablando"] is False
        guiones = svc.guiones.ultimos(10)
        assert guiones and all(g["fuente"] == "plantilla" for g in guiones)
        assert llamar(puerto, "POST", "/apagar")["encendida"] is False
    finally:
        parar.set()
        hilo.join(8)
    assert not hilo.is_alive()
    for socket_ in ("mpv.sock", "voz.sock"):
        assert subprocess.run(["pgrep", "-f", str(dir_corto / socket_)], capture_output=True).returncode == 1


def test_el_servicio_dj_caido_no_afecta_a_la_radio(tmp_path, dir_corto, crear_mp3):
    from cassette_fm.config import ConfigDJ, Frecuencia
    musica = tmp_path / "musica"
    for estacion in "AB":
        for n in range(3):
            crear_mp3(musica / estacion / f"t{n}.mp3", 30, titulo=f"Tema {n}", artista=f"Artista {n}")
    puerto = puerto_libre()
    dj = ConfigDJ(activo=True, url=f"http://127.0.0.1:{puerto_libre()}", margen_minutos=0.0,
                  espera_reintento_segundos=0.1, espera_reintento_maxima_segundos=0.2, timeout_http_segundos=0.5,
                  frecuencia=Frecuencia("temas", 1, 1))
    _, parar, hilo = _arrancar(tmp_path, dir_corto, Config(raiz_musica=musica, puerto=puerto, avisos=False, dj=dj))
    try:
        esperar_servicio(puerto)
        assert llamar(puerto, "POST", "/encender")["encendida"] is True
        assert llamar(puerto, "POST", "/siguiente")["estacion"] == "B"
        fin = time.monotonic() + 8
        while time.monotonic() < fin and llamar(puerto, "GET", "/dj")["planificador"]["servicio"] != "no responde":
            time.sleep(0.1)
        plan = llamar(puerto, "GET", "/dj")["planificador"]
        assert plan["servicio"] == "no responde" and "no responde" in plan["error"]
        assert llamar(puerto, "POST", "/anterior")["estacion"] == "A"
        assert llamar(puerto, "POST", "/apagar")["encendida"] is False
    finally:
        parar.set()
        hilo.join(8)
    assert not hilo.is_alive()


def test_la_voz_lleva_compresor_y_ganancia_configurables():
    from cassette_fm.config import ConfigDJ
    args = servicio.argumentos_voz(ConfigDJ(ganancia_voz_db=12), ["--ao=null"])
    assert args[0] == "--ao=null"
    filtro = next(a for a in args if a.startswith("--af="))
    assert "volume=12dB" in filtro and "acompressor" in filtro and "alimiter" in filtro
    assert not any(a.startswith("--af=") for a in servicio.argumentos_voz(ConfigDJ(ganancia_voz_db=0), []))


def test_servir_migra_y_usa_el_json(tmp_path, dir_corto, crear_mp3):
    musica = tmp_path / "musica"
    crear_mp3(musica / "A" / "a.mp3", 30, titulo="Tema A")
    crear_mp3(musica / "B" / "b.mp3", 30, titulo="Tema B")
    crear_mp3(tmp_path / "afuera" / "c.mp3", 30, titulo="Tema C")
    rutas = Rutas(config=tmp_path / "cfg" / "config.toml", estado=tmp_path / "st" / "estado.json",
                  cache=tmp_path / "cache" / "d.json", runtime=dir_corto)
    puerto = puerto_libre()
    parar = threading.Event()
    hilo = threading.Thread(target=servir, kwargs=dict(
        config=Config(raiz_musica=musica, puerto=puerto, avisos=False), rutas=rutas,
        parar=parar, extra_args_mpv=["--ao=null"]), daemon=True)
    hilo.start()
    try:
        assert esperar_servicio(puerto)["estaciones"] == ["A", "B"]
        assert [e["nombre"] for e in json.loads(rutas.emisoras.read_text())] == ["A", "B"]
        rutas.emisoras.write_text(json.dumps([
            {"nombre": "B", "fuente": {"carpeta": str(musica / "B")}},
            {"nombre": "A", "fuente": {"carpeta": str(musica / "A")}},
            {"nombre": "Afuera", "fuente": {"carpeta": str(tmp_path / "afuera")}}]))
        assert llamar(puerto, "POST", "/rescan")["estaciones"] == ["B", "A", "Afuera"]
        rutas.emisoras.write_text("[{")
        req = urllib.request.Request(f"http://127.0.0.1:{puerto}/rescan", method="POST")
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req)
        assert e.value.code == 400
        assert llamar(puerto, "GET", "/estado")["estaciones"] == ["B", "A", "Afuera"]
    finally:
        parar.set()
        hilo.join(3)


def _hilos_soloist():
    return [t for t in threading.enumerate() if t.name == "soloist-ws" and t.is_alive()]


def _servir_en_hilo(config, rutas):
    parar = threading.Event()
    hilo = threading.Thread(target=servir, kwargs=dict(config=config, rutas=rutas, parar=parar,
                                                       extra_args_mpv=["--ao=null"]), daemon=True)
    hilo.start()
    esperar_servicio(config.puerto)
    return parar, hilo


def test_servir_sin_spotify_no_arranca_soloist(tmp_path, dir_corto):
    from cassette_fm.config import ConfigSpotify
    rutas = Rutas(tmp_path / "c.toml", tmp_path / "e.json", tmp_path / "d.json", dir_corto)
    config = Config(raiz_musica=tmp_path / "nada", puerto=puerto_libre(), avisos=False,
                    spotify=ConfigSpotify(activo=False))
    parar, hilo = _servir_en_hilo(config, rutas)
    try:
        assert _hilos_soloist() == [] and not (dir_corto / "estatica.wav").exists()
    finally:
        parar.set()
        hilo.join(3)


def test_servir_con_spotify_conecta_a_soloist_y_lo_cierra(tmp_path, dir_corto):
    from websockets.sync.server import serve
    from cassette_fm.config import ConfigSpotify
    conectado = threading.Event()

    def atender(ws):
        conectado.set()
        for _ in ws:
            pass
    puerto_ws = puerto_libre()
    servidor_ws = serve(atender, "127.0.0.1", puerto_ws)
    threading.Thread(target=servidor_ws.serve_forever, daemon=True).start()
    rutas = Rutas(tmp_path / "c.toml", tmp_path / "e.json", tmp_path / "d.json", dir_corto)
    config = Config(raiz_musica=tmp_path / "nada", puerto=puerto_libre(), avisos=False,
                    spotify=ConfigSpotify(soloist_ws=f"ws://127.0.0.1:{puerto_ws}", api_url="http://127.0.0.1:9/v1"))
    parar, hilo = _servir_en_hilo(config, rutas)
    try:
        assert conectado.wait(5) and (dir_corto / "estatica.wav").exists()
    finally:
        parar.set()
        hilo.join(5)
        servidor_ws.shutdown()
    assert not hilo.is_alive()
    fin = time.monotonic() + 3
    while _hilos_soloist() and time.monotonic() < fin:
        time.sleep(0.05)
    assert _hilos_soloist() == []


def _mpris_next(direccion):
    import asyncio
    from dbus_fast import Message, MessageType
    from dbus_fast.aio import MessageBus

    async def llamar_next():
        bus = await MessageBus(bus_address=direccion).connect()
        try:
            r = await bus.call(Message(destination="org.mpris.MediaPlayer2.cassette_fm",
                                       path="/org/mpris/MediaPlayer2", interface="org.mpris.MediaPlayer2.Player",
                                       member="Next"))
            assert r.message_type == MessageType.METHOD_RETURN, r.body
        finally:
            bus.disconnect()
    asyncio.run(llamar_next())


def test_servir_publica_mpris_y_next_cambia_de_emisora(tmp_path, dir_corto, crear_mp3, bus_privado):
    musica = tmp_path / "musica"
    crear_mp3(musica / "A" / "a.mp3", 30, titulo="Tema A")
    crear_mp3(musica / "B" / "b.mp3", 30, titulo="Tema B")
    rutas = Rutas(config=tmp_path / "config.toml", estado=tmp_path / "st" / "estado.json",
                  cache=tmp_path / "cache" / "d.json", runtime=dir_corto)
    puerto = puerto_libre()
    parar = threading.Event()
    hilo = threading.Thread(target=servir, kwargs=dict(
        config=Config(raiz_musica=musica, puerto=puerto, avisos=False), rutas=rutas,
        parar=parar, extra_args_mpv=["--ao=null"], bus_mpris=bus_privado), daemon=True)
    hilo.start()
    try:
        esperar_servicio(puerto)
        assert llamar(puerto, "POST", "/encender")["estacion"] == "A"
        _mpris_next(bus_privado)
        fin = time.monotonic() + 3
        while llamar(puerto, "GET", "/estado")["estacion"] != "B" and time.monotonic() < fin:
            time.sleep(0.05)
        assert llamar(puerto, "GET", "/estado")["estacion"] == "B"
    finally:
        parar.set()
        hilo.join(5)
    assert not hilo.is_alive()
    assert not any(t.name == "mpris" and t.is_alive() for t in threading.enumerate())


def test_servir_sin_bus_igual_arranca(tmp_path, dir_corto, caplog):
    rutas = Rutas(config=tmp_path / "c.toml", estado=tmp_path / "e.json",
                  cache=tmp_path / "d.json", runtime=dir_corto)
    puerto = puerto_libre()
    parar = threading.Event()
    hilo = threading.Thread(target=servir, kwargs=dict(
        config=Config(raiz_musica=tmp_path / "x", puerto=puerto, avisos=False), rutas=rutas,
        parar=parar, extra_args_mpv=["--ao=null"], bus_mpris=f"unix:path={tmp_path}/no-hay"), daemon=True)
    with caplog.at_level("WARNING", logger="cassette_fm"):
        hilo.start()
        try:
            assert esperar_servicio(puerto)["encendida"] is False
            assert "MPRIS" in caplog.text
        finally:
            parar.set()
            hilo.join(5)
    assert not hilo.is_alive()


class RouterDeServicioFalso:
    instancias = []

    def __init__(self):
        self.llamadas = []
        self.local_monitor_enabled = False
        RouterDeServicioFalso.instancias.append(self)

    def create_bus(self): self.llamadas.append("bus")
    def env(self): return {"PULSE_SINK": "radio_virtual"}
    def set_local_volume(self, p): self.llamadas.append(f"vol {p}")
    def enable_local_monitor(self): self.local_monitor_enabled = True; self.llamadas.append("on")
    def disable_local_monitor(self): self.local_monitor_enabled = False; self.llamadas.append("off")
    def close(self): self.llamadas.append("close")


def test_servir_con_bus_de_audio_crea_el_bus_expone_el_monitor_y_lo_cierra(tmp_path, dir_corto, crear_mp3, monkeypatch):
    RouterDeServicioFalso.instancias.clear()
    monkeypatch.setattr(servicio, "AudioRouter", RouterDeServicioFalso)
    musica = tmp_path / "musica"
    crear_mp3(musica / "A" / "a.mp3", 30, titulo="Tema A")
    rutas = Rutas(config=tmp_path / "config.toml", estado=tmp_path / "st" / "estado.json",
                  cache=tmp_path / "cache" / "d.json", runtime=dir_corto)
    puerto = puerto_libre()
    parar = threading.Event()
    hilo = threading.Thread(target=servir, kwargs=dict(
        config=Config(raiz_musica=musica, puerto=puerto, avisos=False, bus_audio=True), rutas=rutas,
        parar=parar, extra_args_mpv=["--ao=null"]), daemon=True)
    hilo.start()
    try:
        assert esperar_servicio(puerto)["monitor_local"] is True
        assert llamar(puerto, "POST", "/monitor", {"activo": False})["monitor_local"] is False
        assert json.loads(rutas.estado.read_text())["monitor_local"] is False
    finally:
        parar.set()
        hilo.join(3)
    (router,) = RouterDeServicioFalso.instancias
    assert router.llamadas[0] == "bus" and router.llamadas[-1] == "close"


def test_servir_sin_pactl_arranca_igual_sin_bus(tmp_path, dir_corto, crear_mp3, monkeypatch, caplog):
    from cassette_fm.audio_router import AudioRouterError

    class SinPactl(RouterDeServicioFalso):
        def create_bus(self): raise AudioRouterError("no se encontró `pactl`")

    monkeypatch.setattr(servicio, "AudioRouter", SinPactl)
    musica = tmp_path / "musica"
    crear_mp3(musica / "A" / "a.mp3", 30, titulo="Tema A")
    rutas = Rutas(config=tmp_path / "config.toml", estado=tmp_path / "st" / "estado.json",
                  cache=tmp_path / "cache" / "d.json", runtime=dir_corto)
    puerto = puerto_libre()
    parar = threading.Event()
    hilo = threading.Thread(target=servir, kwargs=dict(
        config=Config(raiz_musica=musica, puerto=puerto, avisos=False, bus_audio=True), rutas=rutas,
        parar=parar, extra_args_mpv=["--ao=null"]), daemon=True)
    hilo.start()
    try:
        assert "monitor_local" not in esperar_servicio(puerto)
        assert "bus_audio = false" in caplog.text      # el error recomienda cómo apagarlo
    finally:
        parar.set()
        hilo.join(3)


# --- radio por la LAN ---

class DifusorDeServicioFalso:
    def __init__(self):
        self.revisiones = 0
        self.cerrado = False

    def revisar_fuente(self): self.revisiones += 1
    def suscribir(self): raise AssertionError("no se usa")
    def desuscribir(self, cola): pass
    def cerrar(self): self.cerrado = True
    def cortar_oyentes(self): self.cortados = getattr(self, "cortados", 0) + 1


class RadioDeLan:
    encendida = True

    def estado(self): return {"encendida": True, "estacion": "A", "estaciones": ["A"]}
    def estaciones(self): return []


def _rutas_lan(tmp_path):
    return Rutas(config=tmp_path / "c" / "config.toml", estado=tmp_path / "e.json", cache=tmp_path / "d.json",
                 runtime=tmp_path)


def _http(puerto, ruta="/status", token=None):
    import http.client
    c = http.client.HTTPConnection("127.0.0.1", puerto, timeout=3)
    c.request("GET", ruta, headers={"Authorization": f"Bearer {token}"} if token else {})
    r = c.getresponse()
    r.read()
    c.close()
    return r.status


def _lan(puerto, **kw):
    from cassette_fm.config import ConfigLan
    return Config(bus_audio=True, lan=ConfigLan(activo=True, puerto=puerto, escuchar=kw.pop("escuchar", "127.0.0.1"), **kw))


def test_lan_apagado_no_abre_ningun_puerto(tmp_path):
    assert servicio.iniciar_lan(Config(), _rutas_lan(tmp_path), RadioDeLan(), object()) is None


def test_lan_con_bus_arranca_en_el_puerto_y_exige_la_clave(tmp_path):
    rutas, puerto, difusor = _rutas_lan(tmp_path), puerto_libre(), DifusorDeServicioFalso()
    cerrar = servicio.iniciar_lan(_lan(puerto), rutas, RadioDeLan(), object(), crear_difusor=lambda *a, **k: difusor)
    try:
        assert esperar(lambda: _intentar(lambda: _http(puerto)) == 401)
        token = rutas.lan_token.read_text().strip()
        assert _http(puerto, token=token) == 200
        assert esperar(lambda: difusor.revisiones >= 1, 3)
    finally:
        cerrar()
    assert difusor.cerrado
    with pytest.raises(OSError):
        _http(puerto)


def _intentar(f):
    try:
        return f()
    except OSError:
        return None


def esperar(condicion, timeout=3.0):
    fin = time.monotonic() + timeout
    while time.monotonic() < fin:
        if condicion():
            return True
        time.sleep(0.02)
    return False


def test_lan_usa_el_difusor_160_del_registro_y_no_lo_cierra(tmp_path):
    class Registro:
        def __init__(self):
            self.pedidos, self.cerrado, self.difusor = [], False, DifusorDeServicioFalso()

        def de(self, kbps):
            self.pedidos.append(kbps)
            return self.difusor

        def revisar_fuente(self): pass
        def cortar_oyentes(self): pass
        def cerrar(self): self.cerrado = True

    registro, puerto = Registro(), puerto_libre()
    cerrar = servicio.iniciar_lan(_lan(puerto), _rutas_lan(tmp_path), RadioDeLan(), object(), difusores=registro)
    try:
        assert esperar(lambda: _intentar(lambda: _http(puerto)) == 401)
    finally:
        cerrar()
    assert set(registro.pedidos) == {160} and not registro.cerrado and not registro.difusor.cerrado


def test_lan_sin_bus_no_abre_el_puerto_y_deja_el_error_en_el_log(tmp_path, caplog):
    puerto = puerto_libre()
    assert servicio.iniciar_lan(_lan(puerto), _rutas_lan(tmp_path), RadioDeLan(), None) is None
    assert "bus_audio" in caplog.text and _intentar(lambda: _http(puerto)) is None


def test_si_la_ip_de_tailscale_aparece_despues_el_servidor_reintenta(tmp_path):
    puerto, difusor, llamadas = puerto_libre(), DifusorDeServicioFalso(), []

    def ip_ts():
        llamadas.append(1)
        return "127.0.0.1" if len(llamadas) > 3 else None

    cerrar = servicio.iniciar_lan(_lan(puerto, escuchar="auto"), _rutas_lan(tmp_path), RadioDeLan(), object(),
                                  crear_difusor=lambda *a, **k: difusor, ip_ts=ip_ts, tailscale_instalado=lambda: True,
                                  intervalo_reintento=0.05)
    try:
        assert esperar(lambda: _intentar(lambda: _http(puerto)) == 401)
        assert len(llamadas) > 3
    finally:
        cerrar()


def test_el_bind_que_falla_reintenta_en_vez_de_caerse(tmp_path):
    import socket as _s
    puerto, difusor = puerto_libre(), DifusorDeServicioFalso()
    ocupado = _s.socket()
    ocupado.bind(("127.0.0.1", puerto))
    ocupado.listen()
    cerrar = servicio.iniciar_lan(_lan(puerto), _rutas_lan(tmp_path), RadioDeLan(), object(),
                                  crear_difusor=lambda *a, **k: difusor, intervalo_reintento=0.05)
    try:
        time.sleep(0.3)
        ocupado.close()
        assert esperar(lambda: _intentar(lambda: _http(puerto)) == 401)
    finally:
        cerrar()


def test_regenerar_la_clave_rige_sin_reiniciar_y_corta_a_los_oyentes(tmp_path):
    from cassette_fm import lan_acceso
    rutas, puerto, difusor = _rutas_lan(tmp_path), puerto_libre(), DifusorDeServicioFalso()
    cerrar = servicio.iniciar_lan(_lan(puerto), rutas, RadioDeLan(), object(), crear_difusor=lambda *a, **k: difusor,
                                  intervalo_revision=0.05)
    try:
        vieja = rutas.lan_token.read_text().strip()
        assert esperar(lambda: _intentar(lambda: _http(puerto, token=vieja)) == 200)
        nueva = lan_acceso.regenerar_token(rutas.lan_token)
        assert esperar(lambda: _intentar(lambda: _http(puerto, token=nueva)) == 200)
        assert _http(puerto, token=vieja) == 401
        assert esperar(lambda: getattr(difusor, "cortados", 0) >= 1)
    finally:
        cerrar()


def test_si_iniciar_lan_falla_el_servicio_local_sigue_andando(tmp_path, dir_corto, crear_mp3, monkeypatch):
    def explota(*a, **k):
        raise PermissionError("no se puede escribir lan.token")

    monkeypatch.setattr(servicio, "iniciar_lan", explota)
    musica = tmp_path / "musica"
    crear_mp3(musica / "A" / "a.mp3", 30, titulo="Tema A")
    rutas = Rutas(config=tmp_path / "config.toml", estado=tmp_path / "st" / "estado.json",
                  cache=tmp_path / "cache" / "d.json", runtime=dir_corto)
    puerto, parar = puerto_libre(), threading.Event()
    hilo = threading.Thread(target=servir, kwargs=dict(
        config=Config(raiz_musica=musica, puerto=puerto, avisos=False), rutas=rutas, parar=parar,
        extra_args_mpv=["--ao=null"]), daemon=True)
    hilo.start()
    try:
        assert esperar_servicio(puerto)["estaciones"] == ["A"]
    finally:
        parar.set()
        hilo.join(3)


# --- puente a la nube ---

class PuenteFalso:
    creados = []

    def __init__(self, radio, difusores, url, token):
        self.radio, self.difusores, self.url, self.token = radio, difusores, url, token
        self.iniciado = self.cerrado = False
        self.reconexiones = 0
        self.listas = []                 # cada lista de claves que se le puso, en orden
        self.listas_al_iniciar = None
        PuenteFalso.creados.append(self)

    def poner_claves(self, claves): self.listas.append(claves)

    def iniciar(self):
        self.iniciado = True
        self.listas_al_iniciar = list(self.listas)
    def cerrar(self): self.cerrado = True
    def reconectar(self): self.reconexiones += 1
    def info(self): return {"conectado": True, "conectado_hace": 12.0, "error": None, "subiendo": [96]}


def _nube(url="wss://relay.ejemplo.com"):
    from cassette_fm.config import ConfigNube
    return Config(bus_audio=True, nube=ConfigNube(activo=True, url=url))


def test_nube_apagada_no_arranca_nada(tmp_path):
    PuenteFalso.creados.clear()
    antes = set(threading.enumerate())
    assert servicio.iniciar_nube(Config(), _rutas_lan(tmp_path), RadioDeLan(), object(), object(),
                                 crear_puente=PuenteFalso) is None
    assert PuenteFalso.creados == [] and set(threading.enumerate()) == antes
    assert not _rutas_lan(tmp_path).nube_token.exists()


def test_nube_sin_bus_no_arranca(tmp_path, caplog):
    PuenteFalso.creados.clear()
    assert servicio.iniciar_nube(_nube(), _rutas_lan(tmp_path), RadioDeLan(), None, None,
                                 crear_puente=PuenteFalso) is None
    assert PuenteFalso.creados == [] and "bus_audio" in caplog.text


def test_nube_arranca_con_la_clave_y_cierra(tmp_path):
    PuenteFalso.creados.clear()
    rutas, difusores = _rutas_lan(tmp_path), object()
    cerrar, info = servicio.iniciar_nube(_nube(), rutas, RadioDeLan(), object(), difusores, crear_puente=PuenteFalso)
    p = PuenteFalso.creados[0]
    assert p.iniciado and p.difusores is difusores and p.url == "wss://relay.ejemplo.com"
    assert p.token() == rutas.nube_token.read_text().strip() and len(p.token()) >= 32
    assert info() == {"conectado": True, "conectado_hace": 12.0, "error": None, "subiendo": [96]}
    cerrar()
    assert p.cerrado


def test_nube_clave_regenerada_reconecta(tmp_path):
    from cassette_fm import lan_acceso
    PuenteFalso.creados.clear()
    rutas = _rutas_lan(tmp_path)
    cerrar, _ = servicio.iniciar_nube(_nube(), rutas, RadioDeLan(), object(), object(), crear_puente=PuenteFalso,
                                      intervalo_revision=0.05)
    try:
        lan_acceso.regenerar_token(rutas.nube_token)
        assert esperar(lambda: PuenteFalso.creados[0].reconexiones >= 1)
        assert PuenteFalso.creados[0].token() == rutas.nube_token.read_text().strip()
    finally:
        cerrar()


def test_si_iniciar_nube_falla_el_servicio_local_sigue_andando(tmp_path, dir_corto, crear_mp3, monkeypatch):
    def explota(*a, **k):
        raise PermissionError("no se puede escribir nube.token")

    monkeypatch.setattr(servicio, "iniciar_nube", explota)
    musica = tmp_path / "musica"
    crear_mp3(musica / "A" / "a.mp3", 30, titulo="Tema A")
    rutas = Rutas(config=tmp_path / "config.toml", estado=tmp_path / "st" / "estado.json",
                  cache=tmp_path / "cache" / "d.json", runtime=dir_corto)
    puerto, parar = puerto_libre(), threading.Event()
    hilo = threading.Thread(target=servir, kwargs=dict(
        config=Config(raiz_musica=musica, puerto=puerto, avisos=False), rutas=rutas, parar=parar,
        extra_args_mpv=["--ao=null"]), daemon=True)
    hilo.start()
    try:
        assert "nube" not in esperar_servicio(puerto)
    finally:
        parar.set()
        hilo.join(3)


def test_nube_pone_las_claves_antes_de_iniciar(tmp_path):
    from cassette_fm import claves
    PuenteFalso.creados.clear()
    rutas = _rutas_lan(tmp_path)
    cerrar, _ = servicio.iniciar_nube(_nube(), rutas, RadioDeLan(), object(), object(), crear_puente=PuenteFalso)
    cerrar()
    assert PuenteFalso.creados[0].listas_al_iniciar == [[]]          # sin archivo: lista vacía
    PuenteFalso.creados.clear()
    _, registro = claves.crear(rutas.claves, "Mamá", "escucha")
    cerrar, _ = servicio.iniciar_nube(_nube(), rutas, RadioDeLan(), object(), object(), crear_puente=PuenteFalso)
    cerrar()
    assert PuenteFalso.creados[0].listas_al_iniciar == [claves.para_relay([registro])]


def test_nube_cambio_en_claves_json_llega_al_puente(tmp_path):
    from cassette_fm import claves
    PuenteFalso.creados.clear()
    rutas = _rutas_lan(tmp_path)
    cerrar, _ = servicio.iniciar_nube(_nube(), rutas, RadioDeLan(), object(), object(), crear_puente=PuenteFalso,
                                      intervalo_revision=0.05)
    try:
        p = PuenteFalso.creados[0]
        _, registro = claves.crear(rutas.claves, "Mamá", "completa")
        assert esperar(lambda: p.listas[-1:] == [claves.para_relay([registro])])
        claves.borrar(rutas.claves, "Mamá")
        assert esperar(lambda: p.listas[-1:] == [[]])
        n = len(p.listas)
        time.sleep(0.3)
        assert len(p.listas) == n                                      # sin cambios no repite
    finally:
        cerrar()


def test_nube_archivo_roto_mantiene_la_ultima_lista(tmp_path, caplog):
    from cassette_fm import claves
    PuenteFalso.creados.clear()
    rutas = _rutas_lan(tmp_path)
    _, registro = claves.crear(rutas.claves, "Mamá", "escucha")
    cerrar, _ = servicio.iniciar_nube(_nube(), rutas, RadioDeLan(), object(), object(), crear_puente=PuenteFalso,
                                      intervalo_revision=0.05)
    try:
        p = PuenteFalso.creados[0]
        buena = rutas.claves.read_text()
        rutas.claves.write_text("{roto")
        assert esperar(lambda: "claves.json" in caplog.text)
        time.sleep(0.3)
        assert p.listas == [claves.para_relay([registro])]
        assert registro["huella"] not in caplog.text
        assert caplog.text.count("no se puede leer") == 1                  # un aviso por episodio, no uno por vuelta
        rutas.claves.write_text(buena)                                 # vuelve a ser válido y sin cambios: no repite
        claves.crear(rutas.claves, "Papá", "completa")
        assert esperar(lambda: len(p.listas) == 2 and len(p.listas[-1]) == 2)
    finally:
        cerrar()


def test_nube_archivo_borrado_manda_lista_vacia(tmp_path):
    from cassette_fm import claves
    PuenteFalso.creados.clear()
    rutas = _rutas_lan(tmp_path)
    claves.crear(rutas.claves, "Mamá", "escucha")
    cerrar, _ = servicio.iniciar_nube(_nube(), rutas, RadioDeLan(), object(), object(), crear_puente=PuenteFalso,
                                      intervalo_revision=0.05)
    try:
        p = PuenteFalso.creados[0]
        rutas.claves.unlink()
        assert esperar(lambda: p.listas[-1:] == [[]])
    finally:
        cerrar()


def test_nube_archivo_binario_no_rompe_el_arranque_y_manda_lista_vacia(tmp_path, caplog):
    from cassette_fm import claves
    PuenteFalso.creados.clear()
    rutas = _rutas_lan(tmp_path)
    rutas.claves.parent.mkdir(parents=True, exist_ok=True)
    rutas.claves.write_bytes(b"\xff\xfe\x00garbage")
    cerrar, _ = servicio.iniciar_nube(_nube(), rutas, RadioDeLan(), object(), object(), crear_puente=PuenteFalso,
                                      intervalo_revision=0.05)
    try:
        p = PuenteFalso.creados[0]
        assert p.iniciado and p.listas_al_iniciar == [[]]            # nunca hubo una buena: vacía (fallar cerrado)
        time.sleep(0.3)
        assert "Traceback" not in caplog.text and caplog.text.count("no se puede leer") == 1
        claves.crear(rutas.claves.with_name("otro.json"), "x", "escucha")
        rutas.claves.unlink()
        _, registro = claves.crear(rutas.claves, "Mamá", "escucha")
        assert esperar(lambda: p.listas[-1:] == [claves.para_relay([registro])])
    finally:
        cerrar()


# --- último recurso: reiniciar el servicio y retomar la emisora ---

class RadioFalsaRecuperacion:
    def __init__(self):
        self.ultimo_recurso = None
        self.sintonizadas = []

    def sintonizar(self, nombre, oir_aca=True):
        self.sintonizadas.append((nombre, oir_aca))


def _rutas(tmp_path):
    return Rutas(config=tmp_path / "config.toml", estado=tmp_path / "st" / "estado.json",
                 cache=tmp_path / "cache" / "d.json", runtime=tmp_path / "rt")


def test_preparar_recuperacion_conecta_el_ultimo_recurso_de_la_radio(tmp_path, monkeypatch):
    from cassette_fm import recuperacion
    from cassette_fm.biblioteca import Estacion
    pedidos = []
    monkeypatch.setattr(recuperacion, "pedir_reinicio", lambda ruta, estacion, motivo, **kw: pedidos.append((ruta, estacion, motivo)) or True)
    rutas, radio = _rutas(tmp_path), RadioFalsaRecuperacion()
    assert servicio.preparar_recuperacion(radio, rutas, soloist=None) is None        # sin marcador no hay nada que retomar
    assert radio.ultimo_recurso(Estacion("Power", (), fuente="spotify"), "no suena") is True
    assert pedidos == [(rutas.reinicio, "Power", "no suena")]
    assert not radio.ultimo_recurso(Estacion("Carpeta", (), fuente="carpeta"), "sin temas")     # reiniciar no lo arregla
    assert len(pedidos) == 1


def test_preparar_recuperacion_retoma_la_emisora_cuando_soloist_esta_listo(tmp_path):
    from cassette_fm import recuperacion
    rutas, radio = _rutas(tmp_path), RadioFalsaRecuperacion()
    assert recuperacion.pedir_reinicio(rutas.reinicio, "Power F.M.", "no suena", bajo_systemd=lambda: True, reiniciar=lambda: None)
    soloist = type("S", (), {"conectado": True})()
    hilo = servicio.preparar_recuperacion(radio, rutas, soloist)
    hilo.join(5)
    assert radio.sintonizadas == [("Power F.M.", False)]
    assert servicio.preparar_recuperacion(RadioFalsaRecuperacion(), rutas, soloist) is None       # una sola vez


def test_servir_retoma_la_emisora_tras_un_reinicio_por_falla(tmp_path, dir_corto, crear_mp3):
    from cassette_fm import recuperacion
    musica = tmp_path / "musica"
    crear_mp3(musica / "A" / "a.mp3", 30, titulo="Tema A")
    crear_mp3(musica / "B" / "b.mp3", 30, titulo="Tema B")
    rutas = Rutas(config=tmp_path / "config.toml", estado=tmp_path / "st" / "estado.json",
                  cache=tmp_path / "cache" / "d.json", runtime=dir_corto)
    recuperacion.pedir_reinicio(rutas.reinicio, "B", "no suena", bajo_systemd=lambda: True, reiniciar=lambda: None)
    puerto, parar = puerto_libre(), threading.Event()
    hilo = threading.Thread(target=servir, kwargs=dict(
        config=Config(raiz_musica=musica, puerto=puerto, avisos=False), rutas=rutas,
        parar=parar, extra_args_mpv=["--ao=null"]), daemon=True)
    hilo.start()
    try:
        esperar_servicio(puerto)
        fin = time.monotonic() + 5
        estado = llamar(puerto, "GET", "/estado")
        while not estado["encendida"] and time.monotonic() < fin:
            time.sleep(0.05)
            estado = llamar(puerto, "GET", "/estado")
        assert estado["encendida"] is True and estado["estacion"] == "B"      # arrancó en silencio pero retomó la emisora
    finally:
        parar.set()
        hilo.join(10)
