import json
import stat
from types import SimpleNamespace

from cassette_fm.lan_acceso import (direccion_de_escucha, direccion_para_mostrar, ip_tailscale, leer_o_crear_token,
                                    regenerar_token)


def test_token_se_crea_una_vez_con_modo_600(tmp_path):
    ruta = tmp_path / "x" / "lan.token"
    token = leer_o_crear_token(ruta)
    assert len(token) >= 32 and leer_o_crear_token(ruta) == token
    assert stat.S_IMODE(ruta.stat().st_mode) == 0o600


def test_regenerar_cambia_el_token_y_lo_guarda(tmp_path):
    ruta = tmp_path / "lan.token"
    viejo = leer_o_crear_token(ruta)
    nuevo = regenerar_token(ruta)
    assert nuevo != viejo and leer_o_crear_token(ruta) == nuevo
    assert stat.S_IMODE(ruta.stat().st_mode) == 0o600


def _ip(direccion):
    salida = json.dumps([{"ifname": "tailscale0", "addr_info": [{"family": "inet", "local": direccion}]}])
    return lambda *a, **k: SimpleNamespace(returncode=0, stdout=salida)


def test_ip_tailscale_parsea_la_salida_de_ip():
    assert ip_tailscale(_ip("100.104.222.41")) == "100.104.222.41"


def test_ip_tailscale_fuera_de_rango_o_sin_interfaz_es_none():
    assert ip_tailscale(_ip("192.168.0.5")) is None
    assert ip_tailscale(lambda *a, **k: SimpleNamespace(returncode=1, stdout="")) is None

    def sin_ip(*a, **k):
        raise FileNotFoundError

    assert ip_tailscale(sin_ip) is None


def test_auto_usa_tailscale_y_sin_el_todas_las_interfaces():
    assert direccion_de_escucha("auto", lambda: "100.104.222.41") == "100.104.222.41"
    assert direccion_de_escucha("auto", lambda: None) == "0.0.0.0"
    assert direccion_de_escucha("192.168.0.157", lambda: "100.1.1.1") == "192.168.0.157"


def test_direccion_para_mostrar_prefiere_tailscale_y_cae_a_la_ruta_por_defecto():
    assert direccion_para_mostrar("auto", lambda: "100.104.222.41", lambda: "192.168.0.157") == "100.104.222.41"
    assert direccion_para_mostrar("auto", lambda: None, lambda: "192.168.0.157") == "192.168.0.157"
    assert direccion_para_mostrar("auto", lambda: None, lambda: None) == "127.0.0.1"
    assert direccion_para_mostrar("10.0.0.9", lambda: "100.1.1.1", lambda: "1.2.3.4") == "10.0.0.9"
