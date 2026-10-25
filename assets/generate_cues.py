"""Rebuild eight original, quiet, monophonic feedback tones offline.

These mathematical tones were created for Bouncebound; no sampled or external
sound source is used. Standard-library only; output is 16-bit mono PCM at 22050 Hz.
"""

from math import sin, pi
from pathlib import Path
import struct
import wave

RATE = 22050
# Base frequency, end frequency, duration, harmonic strength.
CUES = {
    'shoot': (700, 1000, .09, .2), 'bounce': (1050, 700, .055, .1),
    'hit': (420, 180, .07, .35), 'death': (180, 65, .16, .45),
    'spellcast': (480, 920, .18, .3), 'damage': (220, 130, .13, .4),
    'victory': (660, 990, .28, .2), 'defeat': (300, 90, .28, .3),
}


def generate(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for name, (start, end, duration, harmonic) in CUES.items():
        samples = []
        count = round(RATE * duration)
        for index in range(count):
            time = index / RATE
            progress = index / count
            phase = 2*pi*(start*time + (end-start)*time*time/(2*duration))
            envelope = min(1, progress*25) * (1-progress)**2
            value = (sin(phase) + harmonic*sin(phase*2)) / (1+harmonic)
            samples.append(struct.pack('<h', round(value * envelope * 6000)))
        with wave.open(str(root/f'{name}.wav'), 'wb') as output:
            output.setnchannels(1); output.setsampwidth(2); output.setframerate(RATE)
            output.writeframes(b''.join(samples))


if __name__ == '__main__':
    generate(Path(__file__).resolve().parent/'sounds')
