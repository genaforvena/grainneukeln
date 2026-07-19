import gc
import random

from pydub import AudioSegment
from tqdm import tqdm

from automixer.effects.band_pass import band_pass_filer
from automixer.effects.change_tempo import change_audioseg_tempo, snap_to_length
from automixer.iterators.rolling_window import rolling_window
from automixer.utils import calculate_step, apply_seed, concat_bit_identical


def _create_chunk(config, window):
    chunk = AudioSegment.silent(duration=config.sample_length)
    snap = bool(getattr(config, "snap", False))
    for channel in config.channels_config:
        start_cut = random.choice(window)
        if snap:
            cut_len = max(1, int(config.sample_length * random.uniform(0.6, 1.4)))
            channel_chunk = config.audio[start_cut: start_cut + cut_len]
            if not channel.bypass:
                channel_chunk = band_pass_filer(channel.low_pass, channel.high_pass, channel_chunk)
            if len(channel_chunk) != int(config.sample_length):
                channel_chunk = snap_to_length(channel_chunk, config.sample_length,
                                                verbose=config.is_verbose_mode_enabled)
        else:
            channel_chunk = config.audio[start_cut: start_cut + config.sample_length]
            if not channel.bypass:
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
        low_memory = getattr(config, "low_memory", False)
        gc_interval = 10 if low_memory else 0
        if low_memory:
            # Streaming path: accumulate raw bytes into a single bytearray instead of holding a
            # list of AudioSegment wrappers. The original path held every chunk1 in ``mix_parts``
            # (O(N) AudioSegments + their _data) AND then ``concat_bit_identical(mix_parts)`` did
            # ``b"".join(s._data for s in mix_parts)`` — a SECOND O(N) copy at the final concat,
            # so peak was ~2x the output size. Long sources (90s+ feed × chunk_length_in_window ×
            # ~160 windows) blew past the 2500MB cgroup cap and the python was SIGKILLed (rc=137)
            # on every cron-driven grind for 2 days (2026-07-17..19) — interactive runs only
            # survived because they ran without the cap. Bit-identical to ``concat_bit_identical``
            # (both reduce to ``first._spawn(joined_bytes)``); verified by test_low_memory_bit_identity.
            mix_data = bytearray()
            first = None
            for i, window in enumerate(rolling_window(config.beats, config.window_divider)):
                chunk_parts = [_create_chunk(config, window)]
                chunk_total = len(chunk_parts[0])
                while chunk_total < int(chunk_length_in_window):
                    new = _create_chunk(config, window)
                    chunk_parts.append(new)
                    chunk_total += len(new)
                chunk1 = concat_bit_identical(chunk_parts)
                if first is None:
                    first = chunk1
                mix_data.extend(chunk1._data)
                pbar.update(len(chunk1))
                del chunk_parts, chunk1
                if gc_interval and (i % gc_interval == 0):
                    gc.collect()
            gc.collect()
            from pydub import AudioSegment
            if first is None:
                return AudioSegment.empty()
            return first._spawn(bytes(mix_data))
        mix_parts = []
        for i, window in enumerate(rolling_window(config.beats, config.window_divider)):
            chunk_parts = [_create_chunk(config, window)]
            chunk_total = len(chunk_parts[0])
            while chunk_total < int(chunk_length_in_window):
                new = _create_chunk(config, window)
                chunk_parts.append(new)
                chunk_total += len(new)
            chunk1 = concat_bit_identical(chunk_parts)
            mix_parts.append(chunk1)
            pbar.update(len(chunk1))
            if gc_interval and (i % gc_interval == 0):
                del chunk_parts
                gc.collect()
        if gc_interval:
            gc.collect()
        return concat_bit_identical(mix_parts)

# amc ss 0.5 s 1.5 c 1,250;500,15000 w 6
# amc ss 2.0 s 0.5 c 1,250;10000,15000
# amc ss 2.0 s 0.5 c 1,250;251,300;400,500;501,600;60,700;10000,15000
