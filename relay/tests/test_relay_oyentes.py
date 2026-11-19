import asyncio
import time

from cassette_relay.oyentes import Oyentes


def correr(escenario, **kw):
    """Corre `escenario(oyentes, avisos)` en un loop nuevo; devuelve lo que devuelva."""
    async def principal():
        avisos = []
        oyentes = Oyentes(avisos.append, **kw)
        return await escenario(oyentes, avisos)
    return asyncio.run(principal())


def test_primer_oyente_pide_al_instante():
    async def escenario(o, avisos):
        o.agregar(96)
        assert avisos == [[96]] and o.pedidas() == [96] and o.cuantos(96) == 1
    correr(escenario)


def test_segundo_oyente_no_repite_la_demanda():
    async def escenario(o, avisos):
        o.agregar(96)
        o.agregar(96)
        assert avisos == [[96]] and o.cuantos(96) == 2
    correr(escenario)


def test_ultimo_que_se_va_espera_la_gracia():
    async def escenario(o, avisos):
        uno = o.agregar(96)
        o.quitar(uno)
        assert avisos == [[96]] and o.cuantos(96) == 0 and o.pedidas() == [96]
        await asyncio.sleep(0.2)
        assert avisos == [[96], []] and o.pedidas() == []
    correr(escenario, gracia=0.1)


def test_volver_dentro_de_la_gracia_no_corta():
    async def escenario(o, avisos):
        o.quitar(o.agregar(96))
        await asyncio.sleep(0.05)
        o.agregar(96)
        await asyncio.sleep(0.2)
        assert avisos == [[96]]
    correr(escenario, gracia=0.1)


def test_dos_calidades():
    async def escenario(o, avisos):
        o.agregar(64)
        o.agregar(160)
        assert avisos == [[64], [64, 160]]
    correr(escenario)


def test_reparte_a_todos_los_de_esa_calidad():
    async def escenario(o, avisos):
        a, b, c = o.agregar(96), o.agregar(96), o.agregar(64)
        o.repartir(96, b"abc")
        assert await a.tomar(0.5) == b"abc" and await b.tomar(0.5) == b"abc"
        assert await c.tomar(0.05) is None
    correr(escenario)


def test_tomar_junta_lo_encolado():
    async def escenario(o, avisos):
        a = o.agregar(96)
        o.repartir(96, b"a")
        o.repartir(96, b"b")
        assert await a.tomar(0.5) == b"ab"
    correr(escenario)


def test_cola_llena_salta_al_vivo_una_vez():
    async def escenario(o, avisos):
        a = o.agregar(64)                       # tope: 1 s × 64 kbps = 8000 bytes
        for i in range(5):
            o.repartir(64, bytes([i]) * 2000)
        assert a.saltos == 1
        assert await a.tomar(0.5) == bytes([4]) * 2000
    correr(escenario, cola_segundos=1.0)


def test_tomar_sin_datos_devuelve_none():
    async def escenario(o, avisos):
        inicio = time.monotonic()
        assert await o.agregar(96).tomar(0.05) is None
        assert time.monotonic() - inicio < 0.5
    correr(escenario)


def test_cerrar_despierta_al_que_espera():
    async def escenario(o, avisos):
        a = o.agregar(96)
        tarea = asyncio.create_task(a.tomar(5))
        await asyncio.sleep(0.05)
        inicio = time.monotonic()
        a.cerrar()
        assert await tarea == b"" and a.cerrado
        assert time.monotonic() - inicio < 0.5
    correr(escenario)


def test_quitar_dos_veces_no_rompe():
    async def escenario(o, avisos):
        a = o.agregar(96)
        o.quitar(a)
        o.quitar(a)
        assert o.cuantos(96) == 0
    correr(escenario, gracia=0.01)


def test_oyente_quitado_no_recibe_mas():
    async def escenario(o, avisos):
        a = o.agregar(96)
        o.quitar(a)
        o.repartir(96, b"x")
        assert await a.tomar(0.05) in (None, b"")
    correr(escenario, gracia=0.01)


def test_cortar_fuera_cierra_solo_a_las_claves_que_no_estan():
    async def escenario(o, avisos):
        a, b, maestra, otro = o.agregar(96, "aaaaaaaa"), o.agregar(96, "bbbbbbbb"), o.agregar(96), o.agregar(64, "bbbbbbbb")
        assert o.cortar_fuera({"aaaaaaaa"}) == 2
        assert (a.cerrado, b.cerrado, maestra.cerrado, otro.cerrado) == (False, True, False, True)
        o.repartir(96, b"x")
        assert await a.tomar(0.1) == b"x" and await b.tomar(0.1) == b""
        assert o.cortar_fuera(set()) == 1 and a.cerrado and not maestra.cerrado
    correr(escenario)
