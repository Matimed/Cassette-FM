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
                  rampa_bajada_segundos=0.05, rampa_subida_segundos=0.05, frecuencia=Frecuencia("temas", 1, 1))
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
