import json
import urllib.error
import urllib.request

from cassette_fm.dj.config import ConfigServicioDJ


class ErrorLLM(Exception):
    """El LLM no respondió o respondió algo inusable; el mensaje está pensado para el log."""


class ClienteLLM:
    """Habla con un servidor compatible con la API de OpenAI (Ollama); todo fallo sale como ErrorLLM."""

    def __init__(self, config: ConfigServicioDJ):
        self._config = config
        self._base = config.llm_url.rstrip("/")

    def generar(self, sistema: str, usuario: str) -> str:
        c = self._config
        cuerpo = json.dumps({"model": c.llm_modelo, "temperature": c.llm_temperatura, "max_tokens": 300,
                             "stream": False,
                             "messages": [{"role": "system", "content": sistema},
                                          {"role": "user", "content": usuario}]}).encode("utf-8")
        req = urllib.request.Request(f"{self._base}/chat/completions", data=cuerpo, method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=c.llm_timeout_segundos) as r:
                datos = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise ErrorLLM(f"el LLM en {self._base} contestó {e.code}") from None
        except Exception as e:                     # red, timeout, JSON roto…
            raise ErrorLLM(f"el LLM no responde en {self._base} ({type(e).__name__}: {e})") from None
        try:
            texto = datos["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise ErrorLLM(f"la respuesta del LLM en {self._base} no tiene el formato esperado") from None
        if not isinstance(texto, str) or not texto.strip():
            raise ErrorLLM(f"el LLM en {self._base} contestó un texto vacío")
        return texto.strip()

    def disponible(self) -> bool:
        """¿Responde el servidor? (`GET {llm_url}/models`, 2 s). Nunca lanza."""
        try:
            with urllib.request.urlopen(f"{self._base}/models", timeout=2.0) as r:
                return r.status == 200
        except Exception:
            return False
