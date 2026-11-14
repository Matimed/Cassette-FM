import wave

import mutagen

from cassette_fm.clips import generar_clip_de_prueba


def _muestras(ruta):
    with wave.open(str(ruta), "rb") as w:
        assert w.getnchannels() == 1 and w.getsampwidth() == 2
        crudo = w.readframes(w.getnframes())
        return [int.from_bytes(crudo[i:i + 2], "little", signed=True) for i in range(0, len(crudo), 2)], w.getframerate()


def test_el_clip_de_prueba_dura_lo_pedido_y_tiene_sonido(tmp_path):
    ruta = generar_clip_de_prueba(tmp_path / "c.wav", 8.0)
    assert ruta == tmp_path / "c.wav"
    assert abs(mutagen.File(ruta).info.length - 8.0) < 0.05
    muestras, _ = _muestras(ruta)
    assert max(abs(m) for m in muestras) > 1000


def test_crea_los_directorios_padre(tmp_path):
    ruta = generar_clip_de_prueba(tmp_path / "a" / "b" / "c.wav", 2.0)
    assert ruta.exists()


def test_hay_silencios_entre_rafagas(tmp_path):
    muestras, fs = _muestras(generar_clip_de_prueba(tmp_path / "c.wav", 8.0))
    mejor = corrida = 0
    for m in muestras:
        corrida = corrida + 1 if abs(m) < 50 else 0
        mejor = max(mejor, corrida)
    assert mejor / fs >= 0.2


def test_estatica_es_un_wav_corto_con_nivel_moderado_y_bordes_en_silencio(tmp_path):
    import math
    import struct
    import wave
    from cassette_fm.clips import generar_estatica
    ruta = generar_estatica(tmp_path / "x" / "estatica.wav", 3.0)
    with wave.open(str(ruta)) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, 22050)
        n = w.getnframes()
        muestras = struct.unpack(f"<{n}h", w.readframes(n))
    assert abs(n / 22050 - 3.0) < 0.01
    rms = math.sqrt(sum(m * m for m in muestras) / n) / 32768
    assert -30 < 20 * math.log10(rms) < -18
    borde = int(0.005 * 22050)
    assert max(abs(m) for m in muestras[:borde]) < 2000 and max(abs(m) for m in muestras[-borde:]) < 2000
