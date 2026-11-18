import json

import pytest

from cassette_fm.audio_router import AudioRouter, AudioRouterError


class PactlFalso:
    """Un `pactl` en memoria: módulos cargados y sink-inputs, con los mismos formatos de salida."""

    def __init__(self, sink_predeterminado="alsa_output.parlantes"):
        self.llamadas: list[list[str]] = []
        self.modulos: dict[int, str] = {}      # id -> "module-x arg=valor ..."
        self.sink_inputs: list[dict] = []
        self.sink_predeterminado = sink_predeterminado
        self.fallar_carga: str | None = None
        self._siguiente = 100

    def __call__(self, *args: str) -> str:
        self.llamadas.append(list(args))
        if args[0] == "load-module":
            if self.fallar_carga == args[1]:
                raise AudioRouterError("Failure: Module initialization failed")
            id_ = self._siguiente
            self._siguiente += 1
            self.modulos[id_] = " ".join(args[1:])
            if args[1] == "module-loopback":
                self.sink_inputs.append({"index": 900 + id_, "owner_module": str(id_)})   # PipeWire: texto
            return f"{id_}\n"
        if args[0] == "unload-module":
            id_ = int(args[1])
            if id_ not in self.modulos:
                raise AudioRouterError("Failure: No such entity")
            del self.modulos[id_]
            self.sink_inputs = [s for s in self.sink_inputs if str(s["owner_module"]) != str(id_)]
            return ""
        if list(args[:3]) == ["list", "short", "modules"]:
            return "".join(f"{i}\t{c.split()[0]}\t{' '.join(c.split()[1:])}\n" for i, c in self.modulos.items())
        if list(args[:3]) == ["--format=json", "list", "sink-inputs"]:
            return json.dumps(self.sink_inputs)
        if args[0] == "get-default-sink":
            return self.sink_predeterminado + "\n"
        if args[0] == "set-sink-input-volume":
            return ""
        raise AssertionError(f"pactl inesperado: {args}")

    def volumenes(self) -> list[tuple[str, str]]:
        return [(c[1], c[2]) for c in self.llamadas if c[0] == "set-sink-input-volume"]


@pytest.fixture
def pactl():
    return PactlFalso()


@pytest.fixture
def router(pactl):
    return AudioRouter(pactl=pactl, reintentos_sink_input=2, espera_sink_input=0)


def test_crear_el_bus_carga_el_null_sink(router, pactl):
    router.create_bus()
    assert list(pactl.modulos.values()) == ["module-null-sink sink_name=radio_virtual"
                                            " sink_properties=device.description=Radio"]


def test_crear_el_bus_dos_veces_no_lo_duplica(router, pactl):
    router.create_bus()
    router.create_bus()
    assert len(pactl.modulos) == 1


def test_crear_el_bus_adopta_uno_huerfano_de_una_corrida_anterior(router, pactl):
    pactl.modulos[7] = "module-null-sink sink_name=radio_virtual"
    router.create_bus()
    router.close()
    assert pactl.modulos == {}          # lo descargó: lo que estaba con ese nombre era nuestro
    assert not [c for c in pactl.llamadas if c[:2] == ["load-module", "module-null-sink"]]


def test_falla_al_cargar_el_bus_levanta_error(router, pactl):
    pactl.fallar_carga = "module-null-sink"
    with pytest.raises(AudioRouterError):
        router.create_bus()


def test_env_apunta_los_procesos_al_bus_sin_tocar_el_entorno_base(router):
    base = {"HOME": "/h", "PULSE_SINK": "otro"}
    env = router.env(base)
    assert env == {"HOME": "/h", "PULSE_SINK": "radio_virtual"}
    assert base["PULSE_SINK"] == "otro"


def test_env_toma_os_environ_por_defecto(router, monkeypatch):
    monkeypatch.setenv("CASSETTE_PRUEBA", "1")
    env = router.env()
    assert env["CASSETTE_PRUEBA"] == "1" and env["PULSE_SINK"] == "radio_virtual"


def test_activar_el_monitor_carga_el_loopback_desde_el_monitor_del_bus(router, pactl):
    router.create_bus()
    router.enable_local_monitor()
    assert list(pactl.modulos.values())[-1] == ("module-loopback source=radio_virtual.monitor latency_msec=20")
    assert router.local_monitor_enabled


def test_activar_el_monitor_sin_bus_lo_crea(router, pactl):
    router.enable_local_monitor()
    assert [c.split()[0] for c in pactl.modulos.values()] == ["module-null-sink", "module-loopback"]


def test_activar_el_monitor_dos_veces_no_duplica_el_loopback(router, pactl):
    router.enable_local_monitor()
    router.enable_local_monitor()
    assert sum(c.startswith("module-loopback") for c in pactl.modulos.values()) == 1


def test_no_activa_el_monitor_si_la_salida_predeterminada_es_el_bus(router, pactl):
    pactl.sink_predeterminado = "radio_virtual"
    with pytest.raises(AudioRouterError, match="realimentaci"):
        router.enable_local_monitor()
    assert not any(c.startswith("module-loopback") for c in pactl.modulos.values())


def test_desactivar_el_monitor_descarga_solo_el_loopback(router, pactl):
    router.enable_local_monitor()
    router.disable_local_monitor()
    assert [c.split()[0] for c in pactl.modulos.values()] == ["module-null-sink"]
    assert not router.local_monitor_enabled


def test_desactivar_sin_monitor_activo_no_hace_nada(router, pactl):
    router.create_bus()
    router.disable_local_monitor()
    assert len(pactl.modulos) == 1


def test_el_volumen_se_aplica_al_sink_input_del_loopback_y_no_a_otros(router, pactl):
    router.enable_local_monitor()
    id_loopback = next(i for i, c in pactl.modulos.items() if c.startswith("module-loopback"))
    pactl.sink_inputs.append({"index": 5, "owner_module": None})        # p. ej. el navegador
    pactl.sink_inputs.append({"index": 6, "owner_module": str(id_loopback + 50)})
    pactl.llamadas.clear()
    router.set_local_volume(35)
    assert pactl.volumenes() == [(str(900 + id_loopback), "35%")]


def test_el_volumen_acepta_owner_module_numerico_como_en_pulseaudio(router, pactl):
    router.enable_local_monitor()
    for si in pactl.sink_inputs:
        si["owner_module"] = int(si["owner_module"])
    router.set_local_volume(20)
    assert pactl.volumenes()[-1][1] == "20%"


def test_el_volumen_se_recuerda_y_se_aplica_al_reactivar_el_monitor(router, pactl):
    router.set_local_volume(30)               # sin monitor: solo se guarda
    assert pactl.volumenes() == []
    router.enable_local_monitor()
    assert [v for _, v in pactl.volumenes()] == ["30%"]
    router.disable_local_monitor()
    router.enable_local_monitor()
    assert [v for _, v in pactl.volumenes()] == ["30%", "30%"]


def test_volumen_0_mutea_el_monitor(router, pactl):
    router.enable_local_monitor()
    router.set_local_volume(0)
    assert pactl.volumenes()[-1][1] == "0%"
    assert router.local_volume == 0


@pytest.mark.parametrize("malo", [-1, 101, 50.5, True, "50"])
def test_volumen_fuera_de_rango_o_de_otro_tipo_se_rechaza(router, malo):
    with pytest.raises(ValueError):
        router.set_local_volume(malo)


def test_si_el_sink_input_no_aparece_levanta_error(router, pactl):
    router.enable_local_monitor()
    pactl.sink_inputs.clear()
    with pytest.raises(AudioRouterError, match="sink-input"):
        router.set_local_volume(40)


def test_close_descarga_el_loopback_y_despues_el_bus(router, pactl):
    router.enable_local_monitor()
    router.close()
    descargas = [c[1] for c in pactl.llamadas if c[0] == "unload-module"]
    assert len(descargas) == 2 and pactl.modulos == {}
    assert int(descargas[0]) > int(descargas[1])       # el loopback (cargado después) primero


def test_close_es_idempotente(router, pactl):
    router.create_bus()
    router.close()
    router.close()
    assert pactl.modulos == {}


def test_close_sigue_aunque_un_modulo_ya_no_exista(router, pactl):
    router.enable_local_monitor()
    pactl.modulos.clear()                      # alguien los descargó por afuera
    router.close()                             # no levanta


def test_como_context_manager_limpia_al_salir(pactl):
    with AudioRouter(pactl=pactl, espera_sink_input=0) as r:
        r.enable_local_monitor()
        assert pactl.modulos
    assert pactl.modulos == {}
