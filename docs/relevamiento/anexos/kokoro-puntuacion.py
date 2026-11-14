import re, sys, time
from pathlib import Path
import soundfile as sf
from kokoro_onnx import Kokoro

base = Path(sys.argv[1])
k = Kokoro(str(base / "modelos/kokoro-v1.0.onnx"), str(base / "modelos/voices-v1.0.bin"))

def fonemas(marcado, lang_base):
    out = []
    for p in re.split(r"(\{\w[\w-]*:[^}]*\})", marcado):
        if not p.strip():
            continue
        m = re.fullmatch(r"\{(\w[\w-]*):([^}]*)\}", p)
        lang, txt = (m.group(1), m.group(2)) if m else (lang_base, p)
        out.append(k.tokenizer.phonemize(txt.strip(), lang))
    return " ".join(out)

PRE = "Qué tal gente. "
POST = " Seguimos a todo volumen. {en-us:Daddy Yankee}. Gasolina. Esto es Regueton dos mil."
VARIANTES = {
    "0-referencia-punto": "Son las nueve y veinte en Buenos Aires. Dieciocho grados.",
    "1-coma": "Son las nueve y veinte en Buenos Aires, dieciocho grados.",
    "2-conector": "Son las nueve y veinte en Buenos Aires con dieciocho grados.",
    "3-verbo": "Son las nueve y veinte en Buenos Aires. Hay dieciocho grados.",
}
for nombre, frase in VARIANTES.items():
    ph = fonemas(PRE + frase + POST, "es")
    audio, sr = k.create(ph, voice="em_santa", speed=1.05, lang="es", is_phonemes=True)
    sf.write(base / "clips" / f"puntuacion-{nombre}.wav", audio, sr)
    fr = ph.split(".")[1] if "." in ph else ph
    print(f"{nombre}: {len(audio)/sr:.1f}s | {ph[ph.find('nwˈeβe'):ph.find('seɣ')]}")
