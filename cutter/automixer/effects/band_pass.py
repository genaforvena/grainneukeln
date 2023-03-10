import pydub.effects
from pydub.audio_segment import AudioSegment


def band_pass_filer(low: int, high: int, audio: AudioSegment):
    lows_for_mids = pydub.effects.high_pass_filter(audio, low)
    return pydub.effects.low_pass_filter(lows_for_mids, high)
