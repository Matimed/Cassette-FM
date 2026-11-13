set -e
ES="¡Qué tal, gente! Son las nueve y veinte en Buenos Aires, dieciocho grados. Seguimos a todo volumen: Daddy Yankee, Gasolina. ¡Esto es Regueton dos mil!"
EN="Nine twenty here in Buenos Aires, a cool sixty four degrees. Keep it right here, this is Foreigner, Waiting for a Girl Like You, on Lentos FM."
mix(){ ffmpeg -loglevel error -y -sseof -10 -i "$1" -t 22 -i "$2" -i /tmp/v.mp3 -filter_complex \
 "[0:a]afade=t=out:st=6:d=4,aresample=44100,aformat=channel_layouts=stereo[a];[2:a]aresample=44100,aformat=channel_layouts=stereo,adelay=7500|7500,apad,asplit[v1][v2];[1:a]aresample=44100,aformat=channel_layouts=stereo[b];[a][b]acrossfade=d=3[ab];[ab][v1]sidechaincompress=threshold=0.03:ratio=8:attack=50:release=600[duck];[duck][v2]amix=inputs=2:duration=first:normalize=0[out]" \
 -map "[out]" -b:a 160k "$3"; }
n=1
for v in es-AR-ElenaNeural es-MX-JorgeNeural es-US-AlonsoNeural es-CO-GonzaloNeural es-ES-XimenaNeural en-US-AndrewMultilingualNeural; do
  edge-tts --voice $v --rate=+8% --text "$ES" --write-media /tmp/v.mp3 2>/dev/null
  mix "/m/Regueton 2000/Don Omar - Angelito.mp3" "/m/Regueton 2000/Daddy Yankee - Gasolina.mp3" "/o/$(printf %02d $n)-ES-$v.mp3"; echo "ok $v"; n=$((n+1))
done
for v in en-US-BrianMultilingualNeural en-US-AvaMultilingualNeural en-US-EmmaMultilingualNeural en-AU-WilliamMultilingualNeural en-GB-RyanNeural en-US-ChristopherNeural; do
  edge-tts --voice $v --rate=+5% --text "$EN" --write-media /tmp/v.mp3 2>/dev/null
  mix "/m/Lentos/Whitesnake - Is This Love.mp3" "/m/Lentos/Foreigner - Waiting for a Girl like You.mp3" "/o/$(printf %02d $n)-EN-$v.mp3"; echo "ok $v"; n=$((n+1))
done
