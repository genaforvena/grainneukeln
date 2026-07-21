"""Per-grain measurement + clustering for the library mixer (issue #7).

The **one** measure tract for grainneukeln (mesh doctrine: never add a second librosa analyzer). Each
grain is measured on three axes — spectral centroid (brightness), RMS (loudness), and rhythm-density
(onsets/sec) — then the axes are **rank-calibrated against the actual grain set** so no axis can
saturate or constant-out (memory: an assumed 0..1 axis whose real values pin at 1.0 becomes a constant
and silently drops out of the distance metric). Clustering + a Markov policy over clusters then drive
sequenced (non-random) grain selection.
"""

AXES = ("centroid", "rms", "rhythm_density", "hpss_ratio")


def _to_mono_float(seg):
    import numpy as np

    s = np.array(seg.get_array_of_samples()).astype(np.float32)
    if seg.channels == 2:
        s = s.reshape((-1, 2)).mean(axis=1)
    peak = np.max(np.abs(s)) if s.size else 0.0
    if peak > 0:
        s = s / peak
    return s, seg.frame_rate


def measure_grain(seg):
    """Measure one grain (a pydub ``AudioSegment``) on the four axes.

    ``rhythm_density`` is onsets per second *within the grain* — it discriminates real, rhythmic
    material (many onsets/sec) from an isolated impulse (a single transient in the window → ~0).
    ``hpss_ratio`` is percussive energy / (harmonic + percussive energy) via
    ``librosa.effects.hpss`` — the SAME measure tract (no second analyzer), giving `lib con`
    (contrast) a real percussive-vs-tonal axis to jump across, not just loudness/brightness/density."""
    import numpy as np
    import librosa

    y, sr = _to_mono_float(seg)
    if y.size < 128:
        return {"centroid": 0.0, "rms": 0.0, "rhythm_density": 0.0, "hpss_ratio": 0.0}
    centroid = float(np.mean(librosa.feature.spectral_centroid(y=y, sr=sr)))
    rms = float(np.mean(librosa.feature.rms(y=y)))
    dur = len(y) / float(sr)
    try:
        onsets = librosa.onset.onset_detect(y=y, sr=sr, units="time")
    except Exception:
        onsets = []
    rhythm_density = (len(onsets) / dur) if dur > 0 else 0.0
    harmonic, percussive = librosa.effects.hpss(y)
    h_energy = float(np.sum(harmonic ** 2))
    p_energy = float(np.sum(percussive ** 2))
    total_energy = h_energy + p_energy
    hpss_ratio = (p_energy / total_energy) if total_energy > 0 else 0.0
    return {
        "centroid": centroid, "rms": rms, "rhythm_density": float(rhythm_density),
        "hpss_ratio": float(hpss_ratio),
    }


def calibrate(feature_dicts, axes=AXES):
    """Rank-normalize each axis to [0, 1] **against the corpus itself**.

    Rank (percentile) normalization is self-calibrating by construction: the values spread uniformly
    across [0, 1] no matter the raw scale or distribution, so an axis that saturates in raw units
    (e.g. tone pinned at 1.0) still contributes real spread here. Returns an (n, len(axes)) array."""
    import numpy as np

    n = len(feature_dicts)
    out = np.zeros((n, len(axes)), dtype=float)
    if n == 0:
        return out
    for j, ax in enumerate(axes):
        vals = np.array([f[ax] for f in feature_dicts], dtype=float)
        if n == 1:
            out[:, j] = 0.5
            continue
        order = vals.argsort(kind="mergesort")
        ranks = np.empty(n, dtype=float)
        ranks[order] = np.arange(n)
        # average ranks for ties so identical grains land together (stable clustering)
        uniq, inv, counts = np.unique(vals, return_inverse=True, return_counts=True)
        if len(uniq) < n:
            csum = np.cumsum(counts)
            starts = csum - counts
            avg = (starts + csum - 1) / 2.0
            ranks = avg[inv]
        out[:, j] = ranks / (n - 1)
    return out


def cluster(norm, k):
    """Cluster the calibrated feature rows into ``k`` clusters (k-means, scipy).

    Returns ``(labels, centroids)``. Degrades honestly: ``k`` is clamped to the grain count, and with
    <= 1 grain (or k == 1) everything is one cluster — the caller reports the degradation rather than
    faking a full clustering."""
    import numpy as np
    from scipy.cluster.vq import kmeans2

    n = len(norm)
    k = max(1, min(int(k), n))
    if k <= 1 or n <= 1:
        centroid = norm.mean(axis=0, keepdims=True) if n else np.zeros((1, norm.shape[1] if norm.ndim == 2 else len(AXES)))
        return np.zeros(n, dtype=int), centroid
    centroids, labels = kmeans2(norm, k, minit="points", missing="warn")
    # kmeans2 can leave an empty cluster; recompute centroids from actual membership so distances
    # between cluster centroids are meaningful.
    present = sorted(set(int(l) for l in labels))
    remap = {c: i for i, c in enumerate(present)}
    labels = np.array([remap[int(l)] for l in labels], dtype=int)
    real_centroids = np.array([norm[labels == i].mean(axis=0) for i in range(len(present))])
    return labels, real_centroids


def next_cluster(current, centroids, policy, rng):
    """Markov step over clusters. ``similarity`` favors near clusters (stay coherent), ``contrast``
    favors distant clusters (jump, glitch). Returns the next cluster index."""
    import numpy as np

    k = len(centroids)
    if k <= 1:
        return 0
    d = np.linalg.norm(centroids - centroids[current], axis=1)
    if policy == "contrast":
        w = d.copy()  # far = likely; self-distance 0 -> won't stay
    else:  # similarity
        w = 1.0 / (0.15 + d)  # near (incl. self) = likely
    total = w.sum()
    if total <= 0:
        return int(rng.integers(k))
    return int(rng.choice(k, p=w / total))
