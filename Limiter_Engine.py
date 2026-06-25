import numpy as np
import soundfile as sf
import pyloudnorm as pyln


def db_to_linear(db: float) -> float:
    return 10 ** (db / 20)


def linear_to_db(x: float) -> float:
    x = max(float(x), 1e-12)
    return 20 * np.log10(x)


def peak_db(audio: np.ndarray) -> float:
    return linear_to_db(np.max(np.abs(audio)))


def lookahead_limiter(
    audio: np.ndarray,
    sample_rate: int,
    ceiling_db: float = -1.0,
    lookahead_ms: float = 5.0,
    release_ms: float = 80.0,
    return_gain_reduction_trace: bool = False,
):
    """
    Basic stereo-linked peak limiter.

    This is still a sample-peak limiter, not a true-peak limiter.
    Gain-reduction trace is returned as positive dB reduction.
    """
    ceiling = db_to_linear(ceiling_db)

    was_mono = False
    if audio.ndim == 1:
        audio = audio[:, None]
        was_mono = True

    lookahead_samples = max(0, int(sample_rate * lookahead_ms / 1000))
    release_coeff = np.exp(-1.0 / max(1.0, (sample_rate * release_ms / 1000)))

    output = np.zeros_like(audio)

    gain = 1.0
    max_reduction_db = 0.0

    gain_reduction_trace = None
    if return_gain_reduction_trace:
        gain_reduction_trace = np.zeros(len(audio), dtype=np.float32)

    for i in range(len(audio)):

        if lookahead_samples > 0:
            lookahead_end = min(len(audio), i + lookahead_samples + 1)
            detected_peak = np.max(np.abs(audio[i:lookahead_end]))
        else:
            detected_peak = np.max(np.abs(audio[i]))

        if detected_peak > ceiling:
            target_gain = ceiling / detected_peak
        else:
            target_gain = 1.0

        if target_gain < gain:
            gain = target_gain
        else:
            gain = release_coeff * gain + (1 - release_coeff) * target_gain

        output[i] = audio[i] * gain

        reduction_db = linear_to_db(gain)

        if reduction_db < max_reduction_db:
            max_reduction_db = reduction_db

        if gain_reduction_trace is not None:
            gain_reduction_trace[i] = max(0.0, -reduction_db)

    if was_mono:
        output = output[:, 0]

    if return_gain_reduction_trace:
        return output, max_reduction_db, gain_reduction_trace

    return output, max_reduction_db


def prevent_final_clip(audio: np.ndarray, ceiling_db: float):
    ceiling = db_to_linear(ceiling_db)
    current_peak = np.max(np.abs(audio))

    if current_peak > ceiling:
        scale = ceiling / current_peak
        audio = audio * scale
        return audio, max(0.0, -linear_to_db(scale))

    return audio, 0.0


def render_with_gain(
    audio: np.ndarray,
    sample_rate: int,
    gain_db: float,
    ceiling_db: float,
    lookahead_ms: float,
    release_ms: float,
    return_gain_reduction_trace: bool = False,
):
    gained_audio = audio * db_to_linear(gain_db)

    if return_gain_reduction_trace:
        limited_audio, max_reduction_db, gain_reduction_trace = lookahead_limiter(
            gained_audio,
            sample_rate,
            ceiling_db=ceiling_db,
            lookahead_ms=lookahead_ms,
            release_ms=release_ms,
            return_gain_reduction_trace=True,
        )

        limited_audio, final_safety_reduction = prevent_final_clip(limited_audio, ceiling_db)

        if final_safety_reduction > 0:

            gain_reduction_trace = gain_reduction_trace + final_safety_reduction
            max_reduction_db = -max(abs(max_reduction_db), final_safety_reduction)

        return limited_audio, max_reduction_db, gain_reduction_trace

    limited_audio, max_reduction_db = lookahead_limiter(
        gained_audio,
        sample_rate,
        ceiling_db=ceiling_db,
        lookahead_ms=lookahead_ms,
        release_ms=release_ms,
        return_gain_reduction_trace=False,
    )

    limited_audio, final_safety_reduction = prevent_final_clip(limited_audio, ceiling_db)

    if final_safety_reduction > 0:
        max_reduction_db = -max(abs(max_reduction_db), final_safety_reduction)

    return limited_audio, max_reduction_db


def find_safe_gain(
    audio: np.ndarray,
    sample_rate: int,
    requested_gain_db: float,
    ceiling_db: float,
    lookahead_ms: float,
    release_ms: float,
    max_allowed_reduction_db: float,
):
    if max_allowed_reduction_db <= 0:
        return requested_gain_db, False

    if requested_gain_db <= 0:
        return requested_gain_db, False

    _, test_reduction = render_with_gain(
        audio,
        sample_rate,
        requested_gain_db,
        ceiling_db,
        lookahead_ms,
        release_ms,
    )

    if abs(test_reduction) <= max_allowed_reduction_db:
        return requested_gain_db, False

    low = 0.0
    high = requested_gain_db

    for _ in range(24):
        mid = (low + high) / 2

        _, mid_reduction = render_with_gain(
            audio,
            sample_rate,
            mid,
            ceiling_db,
            lookahead_ms,
            release_ms,
        )

        if abs(mid_reduction) <= max_allowed_reduction_db:
            low = mid
        else:
            high = mid

    return low, True


def process_file(
    input_path: str,
    output_path: str,
    target_lufs: float = -14.0,
    ceiling_db: float = -1.0,
    lookahead_ms: float = 5.0,
    release_ms: float = 80.0,
    max_allowed_reduction_db: float = 4.0,
    output_subtype: str = "PCM_24",
):
    audio, sample_rate = sf.read(input_path, always_2d=False, dtype="float64")

    meter = pyln.Meter(sample_rate)

    original_lufs = meter.integrated_loudness(audio)
    original_peak = peak_db(audio)

    requested_gain_db = target_lufs - original_lufs

    safe_gain_db, safety_limited = find_safe_gain(
        audio=audio,
        sample_rate=sample_rate,
        requested_gain_db=requested_gain_db,
        ceiling_db=ceiling_db,
        lookahead_ms=lookahead_ms,
        release_ms=release_ms,
        max_allowed_reduction_db=max_allowed_reduction_db,
    )

    limited_audio, max_reduction_db = render_with_gain(
        audio=audio,
        sample_rate=sample_rate,
        gain_db=safe_gain_db,
        ceiling_db=ceiling_db,
        lookahead_ms=lookahead_ms,
        release_ms=release_ms,
    )

    final_lufs = meter.integrated_loudness(limited_audio)
    final_peak = peak_db(limited_audio)

    sf.write(output_path, limited_audio, sample_rate, subtype=output_subtype)

    return {
        "input_path": input_path,
        "output_path": output_path,
        "sample_rate": sample_rate,
        "original_lufs": original_lufs,
        "original_peak": original_peak,
        "target_lufs": target_lufs,
        "requested_gain": requested_gain_db,
        "applied_gain": safe_gain_db,
        "safety_limited": safety_limited,
        "max_allowed_reduction": max_allowed_reduction_db,
        "max_reduction": max_reduction_db,
        "final_lufs": final_lufs,
        "final_peak": final_peak,
        "output_subtype": output_subtype,
    }


def render_preview(
    input_path: str,
    target_lufs: float = -14.0,
    ceiling_db: float = -1.0,
    lookahead_ms: float = 5.0,
    release_ms: float = 80.0,
    max_allowed_reduction_db: float = 4.0,
):
    audio, sample_rate = sf.read(input_path, always_2d=False, dtype="float64")

    meter = pyln.Meter(sample_rate)

    original_lufs = meter.integrated_loudness(audio)
    original_peak = peak_db(audio)

    requested_gain_db = target_lufs - original_lufs

    safe_gain_db, safety_limited = find_safe_gain(
        audio=audio,
        sample_rate=sample_rate,
        requested_gain_db=requested_gain_db,
        ceiling_db=ceiling_db,
        lookahead_ms=lookahead_ms,
        release_ms=release_ms,
        max_allowed_reduction_db=max_allowed_reduction_db,
    )

    limited_audio, max_reduction_db, gain_reduction_trace = render_with_gain(
        audio=audio,
        sample_rate=sample_rate,
        gain_db=safe_gain_db,
        ceiling_db=ceiling_db,
        lookahead_ms=lookahead_ms,
        release_ms=release_ms,
        return_gain_reduction_trace=True,
    )

    final_lufs = meter.integrated_loudness(limited_audio)
    final_peak = peak_db(limited_audio)

    if limited_audio.ndim == 1:
        preview_audio = limited_audio[:, None]
    else:
        preview_audio = limited_audio

    preview_audio = np.asarray(preview_audio, dtype=np.float32)

    report = {
        "sample_rate": sample_rate,
        "original_lufs": original_lufs,
        "original_peak": original_peak,
        "target_lufs": target_lufs,
        "requested_gain": requested_gain_db,
        "applied_gain": safe_gain_db,
        "safety_limited": safety_limited,
        "max_allowed_reduction": max_allowed_reduction_db,
        "max_reduction": max_reduction_db,
        "final_lufs": final_lufs,
        "final_peak": final_peak,
        "max_trace_reduction": float(np.max(gain_reduction_trace)) if len(gain_reduction_trace) else 0.0,
    }

    return preview_audio, sample_rate, report, gain_reduction_trace
