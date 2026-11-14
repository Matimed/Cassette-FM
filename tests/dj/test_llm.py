import socket
import time

import pytest

from cassette_fm.dj.config import ConfigServicioDJ
from cassette_fm.dj.llm import ClienteLLM, ErrorLLM


def cliente(l, **cfg):
    return ClienteLLM(ConfigServicioDJ(llm_url=l.url, llm_timeout_segundos=cfg.pop("timeout", 5.0), **cfg))


def test_genera_con_el_formato_de_openai(llm_falso):
    cliente(llm_falso, llm_modelo="gemma3:4b", llm_temperatura=0.5).generar("Sos un locutor.", "Tema: X")
    (p,) = llm_falso.pedidos
    assert p["model"] == "gemma3:4b" and p["temperature"] == 0.5 and p["stream"] is False and p["max_tokens"] == 300
    assert p["messages"] == [{"role": "system", "content": "Sos un locutor."}, {"role": "user", "content": "Tema: X"}]


def test_devuelve_el_texto_crudo(llm_falso):
    llm_falso.respuestas = ["  Hola gente.\n"]
    assert cliente(llm_falso).generar("s", "u") == "Hola gente."


def test_servidor_caido_da_ErrorLLM_claro():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        puerto = s.getsockname()[1]
    c = ClienteLLM(ConfigServicioDJ(llm_url=f"http://127.0.0.1:{puerto}/v1", llm_timeout_segundos=1))
    with pytest.raises(ErrorLLM) as e:
        c.generar("s", "u")
    assert "no responde" in str(e.value) and str(puerto) in str(e.value)


def test_timeout_da_ErrorLLM(llm_falso):
    llm_falso.demora = 1.5
    t0 = time.monotonic()
    with pytest.raises(ErrorLLM, match="no responde"):
        cliente(llm_falso, timeout=0.3).generar("s", "u")
    assert time.monotonic() - t0 < 1.2


@pytest.mark.parametrize("codigo", [500, 404, 503])
def test_http_de_error_da_ErrorLLM(llm_falso, codigo):
    llm_falso.codigo = codigo
    llm_falso.cuerpo_crudo = "ocupado"
    with pytest.raises(ErrorLLM, match=str(codigo)):
        cliente(llm_falso).generar("s", "u")


@pytest.mark.parametrize("cuerpo", ["<html>no</html>", "[1, 2]", "{}", '{"choices": []}', '{"choices": [1]}',
                                    '{"choices": [{"message": {"content": null}}]}',
                                    '{"choices": [{"message": {"content": ["a"]}}]}',
                                    '{"choices": [{"message": {"content": ""}}]}',
                                    '{"choices": [{"message": {"content": "   "}}]}', ""])
def test_respuestas_basura(llm_falso, cuerpo):
    llm_falso.cuerpo_crudo = cuerpo
    with pytest.raises(ErrorLLM):
        cliente(llm_falso).generar("s", "u")


def test_disponible(llm_falso):
    assert cliente(llm_falso).disponible() is True
    llm_falso.codigo_modelos = 404
    assert cliente(llm_falso).disponible() is False
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        puerto = s.getsockname()[1]
    t0 = time.monotonic()
    assert ClienteLLM(ConfigServicioDJ(llm_url=f"http://127.0.0.1:{puerto}/v1")).disponible() is False
    assert time.monotonic() - t0 < 3
