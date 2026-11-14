import re, sys, time
from pathlib import Path
import soundfile as sf
from kokoro_onnx import Kokoro

base = Path(sys.argv[1])
k = Kokoro(str(base / "modelos/kokoro-v1.0.onnx"), str(base / "modelos/voices-v1.0.bin"))

def fonemas(marcado, lang_base):
    """'texto {es:Buenos Aires} más texto' -> fonemas, cada tramo en su idioma."""
    partes = re.split(r"(\{\w[\w-]*:[^}]*\})", marcado)
    out = []
    for p in partes:
        if not p.strip():
            continue
        m = re.fullmatch(r"\{(\w[\w-]*):([^}]*)\}", p)
        lang, txt = (m.group(1), m.group(2)) if m else (lang_base, p)
        out.append(k.tokenizer.phonemize(txt.strip(), lang))
    return " ".join(out)

ES_E = "Qué tal gente. Son las nueve y veinte en Buenos Aires. Dieciocho grados. Seguimos a todo volumen. {en-us:Daddy Yankee}. Gasolina. Esto es Regueton dos mil."
EN_E = "Nine twenty here in {es:Buenos Aires}. A cool sixty four degrees. Keep it right here. This is Foreigner. Waiting for a Girl Like You. On {es:Lentos} FM."
juegos = [("es", "em_santa", "es", ES_E), ("en", "am_michael", "en-us", EN_E), ("en", "af_heart", "en-us", EN_E)]
for idioma, voz, lang, marcado in juegos:
    ph = fonemas(marcado, lang)
    t = time.time()
    audio, sr = k.create(ph, voice=voz, speed=1.05, lang=lang, is_phonemes=True)
    ruta = base / "clips" / f"{idioma}-{voz}-E-hibrido.wav"
    sf.write(ruta, audio, sr)
    print(f"{ruta.name}: {len(audio)/sr:.1f}s en {time.time()-t:.1f}s\n   {ph[:200]}", flush=True)
