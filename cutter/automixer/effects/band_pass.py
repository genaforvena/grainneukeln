import pydub.effects

def band_pass_filer(low, high, audio):
    lows_for_mids = pydub.effects.high_pass_filter(audio, low)
    mids = pydub.effects.low_pass_filter(lows_for_mids, high)
    return mids