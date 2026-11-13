import sys, soundfile as sf
from kokoro_onnx import Kokoro
k = Kokoro("/opt/kokoro/kokoro-v1.0.onnx", "/opt/kokoro/voices-v1.0.bin")
voice, lang, speed, text, out = sys.argv[1:6]
a, sr = k.create(text, voice=voice, speed=float(speed), lang=lang)
sf.write(out, a, sr)
