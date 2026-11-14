import json
import logging

import pytest

from cassette_fm.config import ConfigSpotify
from cassette_fm.spotify.api import ClienteSpotify, ErrorSpotify
from cassette_fm.spotify.catalogo import CatalogoSpotify, pista_de

ITEM = {"is_local": False, "item": {"type": "track", "uri": "spotify:track:44AyOl4qVkzS48vBsbNXaC",
                                    "name": "Can't Help Falling in Love", "duration_ms": 185877, "is_playable": True,
                                    "is_local": False, "artists": [{"name": "Elvis Presley"}],
                                    "album": {"name": "Blue Hawaii"}, "external_ids": {"isrc": "USRC16101350"}}}


def item(n, **cambios):
    return {**ITEM, "item": {**ITEM["item"], "uri": f"spotify:track:{n:022d}", "name": f"Tema {n}", **cambios}}


def test_pista_de_un_item():
    p = pista_de(ITEM)
    assert (p.clave, p.duracion, p.artista, p.cancion, p.album, p.isrc, p.titulo, p.fuente, p.ruta) == (
        "spotify:track:44AyOl4qVkzS48vBsbNXaC", 185.877, "Elvis Presley", "Can't Help Falling in Love",
        "Blue Hawaii", "USRC16101350", "Elvis Presley - Can't Help Falling in Love", "spotify", None)


@pytest.mark.parametrize("cambio", [{"item": None}, {"is_local": True}, {"item": {**ITEM["item"], "type": "episode"}},
                                    {"item": {**ITEM["item"], "is_playable": False}},
                                    {"item": {**ITEM["item"], "duration_ms": 0}},
                                    {"item": {**ITEM["item"], "uri": None}}, {"item": "basura"}])
def test_items_que_se_saltean(cambio):
    assert pista_de({**ITEM, **cambio}) is None


def test_varios_artistas_van_con_coma_y_sin_album_ni_isrc_igual_sirve():
    p = pista_de(item(1, artists=[{"name": "Cardi B"}, {"name": "21 Savage"}], album=None, external_ids={}))
    assert p.artista == "Cardi B, 21 Savage" and p.album is None and p.isrc is None
    assert p.titulo == "Cardi B, 21 Savage - Tema 1"


class SesionFalsa:
    def token(self, forzar=False):
        return "A"


def montar(servidor_http, tmp_path, items_por_pagina, snapshot="S1", codigo_items=200):
    base = servidor_http.url + "/v1"
    servidor_http.reglas.clear()
    servidor_http.responder("/v1/playlists/P/items?offset=", lambda ruta: (codigo_items, {
        "items": items_por_pagina[int(ruta.split("offset=")[1])], "next": None}))
    servidor_http.responder("/v1/playlists/P/items", lambda ruta: (codigo_items, {
        "items": items_por_pagina[0], "next": f"{base}/playlists/P/items?offset=1" if len(items_por_pagina) > 1 else None}
        if codigo_items == 200 else {"error": {"status": codigo_items, "message": "Forbidden"}}))
    servidor_http.responder("/v1/playlists/P", {"snapshot_id": snapshot, "name": "Sing"})
    cliente = ClienteSpotify(SesionFalsa(), ConfigSpotify(api_url=base, timeout_segundos=1.0), dormir=lambda s: None)
    return CatalogoSpotify(cliente, tmp_path / "spotify.json")


def pedidos_de_items(servidor_http):
    return [r for r, _ in servidor_http.pedidos if "/items" in r]


def test_lee_todas_las_paginas_en_orden_y_cachea(servidor_http, tmp_path):
    cat = montar(servidor_http, tmp_path, [[item(1), item(2)], [item(3)]])
    assert [p.cancion for p in cat.pistas("P")] == ["Tema 1", "Tema 2", "Tema 3"]
    assert "limit=50" in pedidos_de_items(servidor_http)[0]
    cache = json.loads((tmp_path / "spotify.json").read_text())
    assert cache["P"]["snapshot_id"] == "S1" and cache["P"]["nombre"] == "Sing" and len(cache["P"]["pistas"]) == 3


def test_mismo_snapshot_no_pide_los_temas(servidor_http, tmp_path):
    cat = montar(servidor_http, tmp_path, [[item(1)]])
    primera = cat.pistas("P")
    servidor_http.pedidos.clear()
    assert cat.pistas("P") == primera and pedidos_de_items(servidor_http) == []


def test_snapshot_nuevo_vuelve_a_leer(servidor_http, tmp_path):
    montar(servidor_http, tmp_path, [[item(1)]]).pistas("P")
    cat = montar(servidor_http, tmp_path, [[item(1), item(2)]], snapshot="S2")
    assert len(cat.pistas("P")) == 2


def test_spotify_caido_usa_la_cache_y_avisa(servidor_http, tmp_path, caplog):
    montar(servidor_http, tmp_path, [[item(1)]]).pistas("P")
    servidor_http.reglas.clear()
    servidor_http.responder("/v1/playlists/P", {"error": {"status": 503, "message": "down"}}, 503)
    cat = CatalogoSpotify(ClienteSpotify(SesionFalsa(), ConfigSpotify(api_url=servidor_http.url + "/v1"),
                                         dormir=lambda s: None), tmp_path / "spotify.json")
    with caplog.at_level(logging.WARNING, logger="cassette_fm"):
        assert [p.cancion for p in cat.pistas("P")] == ["Tema 1"]
    assert "temas guardados" in caplog.text


def test_spotify_caido_sin_cache_propaga(servidor_http, tmp_path):
    servidor_http.responder("/v1/playlists/P", {"error": {"status": 503, "message": "down"}}, 503)
    cat = CatalogoSpotify(ClienteSpotify(SesionFalsa(), ConfigSpotify(api_url=servidor_http.url + "/v1"),
                                         dormir=lambda s: None), tmp_path / "spotify.json")
    with pytest.raises(ErrorSpotify):
        cat.pistas("P")


def test_playlist_ajena_dice_que_hacer(servidor_http, tmp_path):
    cat = montar(servidor_http, tmp_path, [[item(1)]], codigo_items=403)
    with pytest.raises(ErrorSpotify, match="no es tuya.*copiala"):
        cat.pistas("P")


def test_cache_corrupta_se_ignora(servidor_http, tmp_path):
    (tmp_path / "spotify.json").write_text("{basura")
    assert len(montar(servidor_http, tmp_path, [[item(1)]]).pistas("P")) == 1


def test_los_temas_se_piden_con_market_para_que_spotify_marque_los_no_disponibles(servidor_http, tmp_path):
    montar(servidor_http, tmp_path, [[item(1)]]).pistas("P")
    assert "market=from_token" in pedidos_de_items(servidor_http)[0]


def test_solo_cache_no_toca_spotify(servidor_http, tmp_path):
    cat = montar(servidor_http, tmp_path, [[item(1)]])
    cat.pistas("P")
    servidor_http.pedidos.clear()
    assert [p.cancion for p in cat.pistas("P", solo_cache=True)] == ["Tema 1"] and servidor_http.pedidos == []
    with pytest.raises(ErrorSpotify, match="sin conexión"):
        cat.pistas("OTRA", solo_cache=True)


def test_sin_red_queda_marcado_aunque_se_use_la_cache(tmp_path):
    from cassette_fm.spotify.api import ClienteSpotify as C
    import socket as _s
    with _s.socket() as x:
        x.bind(("127.0.0.1", 0))
        puerto = x.getsockname()[1]
    cache = tmp_path / "spotify.json"
    cache.write_text(json.dumps({"P": {"snapshot_id": "S1", "nombre": "Sing", "pistas": [
        {"uri": "spotify:track:1", "duracion": 1.0, "titulo": "A - T", "artista": "A", "cancion": "T",
         "album": None, "isrc": None}]}}))
    cat = CatalogoSpotify(C(SesionFalsa(), ConfigSpotify(api_url=f"http://127.0.0.1:{puerto}/v1", timeout_segundos=1.0),
                            dormir=lambda s: None), cache)
    assert len(cat.pistas("P")) == 1 and cat.sin_red is True


def test_escrituras_simultaneas_de_la_cache_no_chocan(tmp_path):
    import threading
    a, b = CatalogoSpotify(None, tmp_path / "spotify.json"), CatalogoSpotify(None, tmp_path / "spotify.json")
    errores = []

    def muchas(c):
        try:
            for i in range(300):
                c._guardar_cache({"P": {"snapshot_id": str(i), "nombre": "x", "pistas": []}})
        except Exception as e:      # noqa: BLE001
            errores.append(e)
    hilos = [threading.Thread(target=muchas, args=(c,)) for c in (a, b)]
    [h.start() for h in hilos]
    [h.join(20) for h in hilos]
    assert errores == [] and [p.name for p in tmp_path.iterdir()] == ["spotify.json"]
