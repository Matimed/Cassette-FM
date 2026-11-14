import sys
from pathlib import Path
import soundfile as sf
from kokoro_onnx import Kokoro

base = Path(sys.argv[1])
k = Kokoro(str(base / "modelos/kokoro-v1.0.onnx"), str(base / "modelos/voices-v1.0.bin"))
TEXTO = ("Qué tal gente son las nueve y veinte en Buenos Aires con dieciocho grados y gracias a todos "
         "por acompañarnos en esta ciudad que no para con la mejor música de la zona sur y el centro "
         "de la cerveza fría")
ph = k.tokenizer.phonemize(TEXTO, "es")
for nombre, f in (("A-castellano", ph), ("B-seseo", ph.replace("θ", "s"))):
    audio, sr = k.create(f, voice="em_santa", speed=1.05, lang="es", is_phonemes=True)
    sf.write(base / "clips" / f"seseo-{nombre}.wav", audio, sr)
    print(nombre, f"{len(audio)/sr:.1f}s")
print(ph.count("θ"), "ocurrencias de θ en el texto")
