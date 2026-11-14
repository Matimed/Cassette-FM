import os

from cassette_fm import biblioteca
from cassette_fm.biblioteca import escanear, leer_pista


def test_leer_pista_con_tags(tmp_path, crear_mp3):
    p = crear_mp3(tmp_path / "t.mp3", 3, titulo="Tema", artista="Artista")
    pista = leer_pista(p)
    assert pista.titulo == "Artista - Tema"
    assert abs(pista.duracion - 3) < 0.05
    assert pista.fuente == "local"


def test_leer_pista_sin_tags_usa_nombre_de_archivo(tmp_path, crear_mp3):
    solo_titulo = crear_mp3(tmp_path / "a.mp3", 2, titulo="Tema")
    assert leer_pista(solo_titulo).titulo == "Tema"
    sin_tags = crear_mp3(tmp_path / "Mi Canción.mp3", 2)
    assert leer_pista(sin_tags).titulo == "Mi Canción"


def test_leer_pista_ilegible_devuelve_none(tmp_path):
    p = tmp_path / "roto.mp3"
    p.write_text("esto no es audio")
    assert leer_pista(p) is None


def test_escanear_subcarpetas_son_estaciones(tmp_path, crear_mp3):
    crear_mp3(tmp_path / "Lentos" / "a.mp3")
    crear_mp3(tmp_path / "Regueton 2000" / "sub" / "b.mp3")
    crear_mp3(tmp_path / "suelto.mp3")
    crear_mp3(tmp_path / ".oculta" / "c.mp3")
    (tmp_path / "Vacía").mkdir()
    (tmp_path / "Vacía" / "cover.jpg").write_bytes(b"x")
    estaciones = escanear(tmp_path)
    assert [e.nombre for e in estaciones] == ["Lentos", "Regueton 2000"]
    assert [len(e.pistas) for e in estaciones] == [1, 1]


def test_escanear_orden_alfabetico_sin_mayusculas(tmp_path, crear_mp3):
    for n in ("b", "A", "c"):
        crear_mp3(tmp_path / n / "t.mp3")
    assert [e.nombre for e in escanear(tmp_path)] == ["A", "b", "c"]


def test_escanear_pistas_ordenadas_por_ruta(tmp_path, crear_mp3):
    for n in ("z.mp3", "a.mp3", "m.mp3"):
        crear_mp3(tmp_path / "E" / n)
    rutas = [str(p.ruta) for p in escanear(tmp_path)[0].pistas]
    assert rutas == sorted(rutas)


def test_escanear_ignora_ilegibles_y_no_audio(tmp_path, crear_mp3):
    crear_mp3(tmp_path / "E" / "bueno.mp3")
    (tmp_path / "E" / "roto.mp3").write_text("basura")
    (tmp_path / "E" / "notas.txt").write_text("hola")
    (tmp_path / "E" / "cover.jpg").write_bytes(b"x")
    assert len(escanear(tmp_path)[0].pistas) == 1


def test_escanear_acepta_extension_en_mayusculas(tmp_path, crear_mp3):
    crear_mp3(tmp_path / "E" / "A.MP3")
    assert len(escanear(tmp_path)[0].pistas) == 1


def test_escanear_raiz_inexistente_devuelve_vacio(tmp_path):
    assert escanear(tmp_path / "no-existe") == []


def test_cache_evita_releer(tmp_path, crear_mp3, monkeypatch):
    raiz = tmp_path / "m"
    a = crear_mp3(raiz / "E" / "a.mp3", 2)
    b = crear_mp3(raiz / "E" / "b.mp3", 2)
    cache = tmp_path / "cache" / "duraciones.json"
    llamadas = []
    original = biblioteca.leer_pista

    def contando(ruta):
        llamadas.append(ruta)
        return original(ruta)

    monkeypatch.setattr(biblioteca, "leer_pista", contando)
    escanear(raiz, cache)
    assert len(llamadas) == 2
    llamadas.clear()
    escanear(raiz, cache)
    assert llamadas == []
    crear_mp3(b, 4)  # cambia tamaño y mtime
    os.utime(b, (1, 1))
    estaciones = escanear(raiz, cache)
    assert llamadas == [b]
    duraciones = {p.ruta.name: p.duracion for p in estaciones[0].pistas}
    assert abs(duraciones["b.mp3"] - 4) < 0.05
    assert abs(duraciones["a.mp3"] - 2) < 0.05


def _crear_bytes(raiz, *partes):
    ruta = os.path.join(os.fsencode(raiz), *[os.fsencode(p) if isinstance(p, str) else p for p in partes])
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    return ruta


def test_nombres_que_no_son_utf8_se_saltean(tmp_path, crear_mp3):
    import shutil
    modelo = crear_mp3(tmp_path / "modelo.mp3", 2)
    crear_mp3(tmp_path / "m" / "Buena" / "ok.mp3", 2)
    # archivo con nombre latin-1 dentro de una estación buena
    shutil.copy(modelo, _crear_bytes(tmp_path / "m", "Buena", b"Canci\xf3n.mp3"))
    # estación entera con nombre latin-1
    shutil.copy(modelo, _crear_bytes(tmp_path / "m", b"M\xfasica", "a.mp3"))
    cache = tmp_path / "cache" / "d.json"
    estaciones = escanear(tmp_path / "m", cache)
    assert [e.nombre for e in estaciones] == ["Buena"]
    assert [p.ruta.name for p in estaciones[0].pistas] == ["ok.mp3"]
    assert cache.exists()


def test_orden_ignora_acentos(tmp_path, crear_mp3):
    for n in ("Zeta", "Árbol", "abeja"):
        crear_mp3(tmp_path / n / "t.mp3")
    assert [e.nombre for e in escanear(tmp_path)] == ["abeja", "Árbol", "Zeta"]


def test_cache_con_entradas_incompletas_se_relee(tmp_path, crear_mp3):
    import json
    raiz = tmp_path / "m"
    a = crear_mp3(raiz / "E" / "a.mp3", 2)
    st = a.stat()
    cache = tmp_path / "d.json"
    cache.write_text(json.dumps({str(a): {"mtime_ns": st.st_mtime_ns, "tamano": st.st_size}}))
    assert len(escanear(raiz, cache)[0].pistas) == 1


def test_raiz_sin_permisos_devuelve_vacio(tmp_path, crear_mp3):
    raiz = tmp_path / "m"
    crear_mp3(raiz / "E" / "a.mp3")
    raiz.chmod(0)
    try:
        assert escanear(raiz) == []
    finally:
        raiz.chmod(0o755)


def test_leer_pista_separa_artista_cancion_album_e_isrc(tmp_path, crear_mp3):
    p = crear_mp3(tmp_path / "t.mp3", 2, titulo="Tema", artista="Artista", album="Disco", isrc="ESA011234567")
    pista = leer_pista(p)
    assert (pista.artista, pista.cancion, pista.album, pista.isrc) == ("Artista", "Tema", "Disco", "ESA011234567")
    assert pista.titulo == "Artista - Tema"


def test_leer_pista_sin_tags_deja_none(tmp_path, crear_mp3):
    pista = leer_pista(crear_mp3(tmp_path / "Mi Canción.mp3", 2))
    assert (pista.artista, pista.cancion, pista.album, pista.isrc) == (None, None, None, None)
    assert pista.titulo == "Mi Canción"


def test_tags_vacios_o_con_espacios_dan_none(tmp_path, crear_mp3):
    p = crear_mp3(tmp_path / "t.mp3", 2, titulo="  Tema  ", artista="   ", album="")
    pista = leer_pista(p)
    assert (pista.artista, pista.cancion, pista.album, pista.isrc) == (None, "Tema", None, None)


def test_el_cache_guarda_los_campos_nuevos_y_los_devuelve(tmp_path, crear_mp3, monkeypatch):
    raiz = tmp_path / "m"
    crear_mp3(raiz / "E" / "a.mp3", 2, titulo="Tema", artista="Artista", album="Disco", isrc="ESA011234567")
    cache = tmp_path / "cache.json"
    escanear(raiz, cache)
    llamadas = []
    original = biblioteca.leer_pista
    monkeypatch.setattr(biblioteca, "leer_pista", lambda r: (llamadas.append(r), original(r))[1])
    pista = escanear(raiz, cache)[0].pistas[0]
    assert llamadas == []
    assert (pista.artista, pista.cancion, pista.album, pista.isrc) == ("Artista", "Tema", "Disco", "ESA011234567")


def test_una_entrada_de_cache_en_formato_viejo_se_vuelve_a_leer(tmp_path, crear_mp3):
    import json
    raiz = tmp_path / "m"
    a = crear_mp3(raiz / "E" / "a.mp3", 2, titulo="Tema", artista="Artista")
    st = a.stat()
    cache = tmp_path / "cache.json"
    cache.write_text(json.dumps({str(a): {"mtime_ns": st.st_mtime_ns, "tamano": st.st_size,
                                          "duracion": 2.0, "titulo": "Artista - Tema"}}))
    pista = escanear(raiz, cache)[0].pistas[0]
    assert (pista.artista, pista.cancion) == ("Artista", "Tema")
    assert "artista" in json.loads(cache.read_text())[str(a)]


def test_la_clave_de_una_pista_local_es_su_ruta(tmp_path, crear_mp3):
    p = leer_pista(crear_mp3(tmp_path / "x.mp3", 2, titulo="T", artista="A"))
    assert p.clave == str(tmp_path / "x.mp3")
