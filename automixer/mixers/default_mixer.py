import random

from pydub import AudioSegment
from tqdm import tqdm

from automixer.effects.band_pass import band_pass_filer
from automixer.effects.change_tempo import change_audioseg_tempo, snap_to_length
from automixer.iterators.rolling_window import rolling_window
from automixer.utils import calculate_step, apply_seed, concat_bit_identical


def _create_chunk(config, window):
    chunk = AudioSegment.silent(duration=config.sample_length)
    # Snap (issue #8) composes with the rw baseline: when on, a grain is cut at an off-length span
    # (as real off-grid material would be) then pitch-preservingly stretched back to the slot length.
    # When off, the cut is exactly sample_length — bit-identical to the pre-#8 baseline.
    snap = bool(getattr(config, "snap", False))
    for channel in config.channels_config:
        start_cut = random.choice(window)
        if snap:
            cut_len = max(1, int(config.sample_length * random.uniform(0.6, 1.4)))
            channel_chunk = config.audio[start_cut: start_cut + cut_len]
            channel_chunk = band_pass_filer(channel.low_pass, channel.high_pass, channel_chunk)
            if len(channel_chunk) != int(config.sample_length):
                channel_chunk = snap_to_length(channel_chunk, config.sample_length,
                                                verbose=config.is_verbose_mode_enabled)
        else:
            channel_chunk = config.audio[start_cut: start_cut + config.sample_length]
            channel_chunk = band_pass_filer(channel.low_pass, channel.high_pass, channel_chunk)
        chunk = chunk.overlay(channel_chunk)
    if config.sample_speed != 1.0:
        chunk = change_audioseg_tempo(chunk, config.sample_speed, verbose=config.is_verbose_mode_enabled)

    return chunk


class RandomWindowAutoMixer:
    def mix(self, config):
        apply_seed(config)
        pbar = tqdm(desc="Mixing")
        chunk_length_in_window = calculate_step(config.beats)
        # Collect window-chunks in a list and concat ONCE at the end — bit-identical to chained
        # ``mix.append(chunk, crossfade=0)`` (pydub ``append`` with crossfade=0 is ``b"".join`` of
        # the underlying ``_data``), but O(total_bytes) instead of O(total_bytes²). Pre-refactor this
        # was the dominant cost on long sources (28.7s on a 30s feed; the chunk-bloom made the
        # concat quadratic in the OUTPUT length, not the input).
        mix_parts = []
        for window in rolling_window(config.beats, config.window_divider):
            # Inner fill: build one window's chunk by appending grains until it reaches the
            # chunk-length target. Same collect-then-concat pattern at the inner scale; track the
            # accumulated length in a scalar so we don't re-walk the list (and don't read the LAST
            # grain's length by mistake, which would loop forever when grain_len < target).
            chunk_parts = [_create_chunk(config, window)]
            chunk_total = len(chunk_parts[0])
            while chunk_total < int(chunk_length_in_window):
                new = _create_chunk(config, window)
                chunk_parts.append(new)
                chunk_total += len(new)
            chunk1 = concat_bit_identical(chunk_parts)
            mix_parts.append(chunk1)
            pbar.update(len(chunk1))
        return concat_bit_identical(mix_parts)

# amc ss 0.5 s 1.5 c 1,250;500,15000 w 6
# amc ss 2.0 s 0.5 c 1,250;10000,15000
# amc ss 2.0 s 0.5 c 1,250;251,300;400,500;501,600;60,700;10000,15000
