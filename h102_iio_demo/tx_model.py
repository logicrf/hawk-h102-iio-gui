"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file       tx_model.py
@brief      Validate TX requests and create bounded cyclic IQ without hardware access.
@details    Generate 65,536 complex LE IQ16 samples with complex peak at most 8192.
            Read original files without modification and bind hashes to actual preloaded bytes.
@author     LogicRF Technologies
@architect  LogicRF
@email      info@logicrf.com
@website    https://www.logicrf.com
@version    0.6.0
@date       2026-10-15
"""
from dataclasses import dataclass
import hashlib
import math
from pathlib import Path

import numpy as np

SAMPLES = 65536
MAX_PEAK = 8192


def waveform(raw: bytes) -> dict:
    """Reject truncated, zero or excessive-peak IQ without modifying or rescaling the source."""
    if len(raw) != SAMPLES * 4:
        raise ValueError('IQ must contain 65536 complex samples, 262144 bytes of LE interleaved IQ16')
    iq = np.frombuffer(raw, dtype='<i2').reshape(-1, 2).astype(np.int64)
    peak2 = int(np.max(np.sum(iq * iq, axis=1)))
    if not 0 < peak2 <= MAX_PEAK ** 2:
        raise ValueError('Complex IQ peak must be greater than zero and at most 8192; normalize the file first')
    return dict(samples=SAMPLES, bytes=len(raw), format='le:s16-I,s16-Q',
                peak=math.sqrt(peak2), sha256=hashlib.sha256(raw).hexdigest())


def tone(sample_rate: int, bandwidth: int, offset: float, peak: int = 4096):
    """Generate a phase-continuous cyclic tone and return actual quantized offset plus raw bytes."""
    if (type(sample_rate) is not int or type(bandwidth) is not int
            or not 0 < bandwidth <= sample_rate or not math.isfinite(offset)
            or type(peak) is not int or not 1 <= peak <= MAX_PEAK):
        raise ValueError('Invalid TX waveform parameters')
    bins = round(offset * SAMPLES / sample_rate)
    actual = bins * sample_rate / SAMPLES
    if bins == 0 or abs(actual) >= min(sample_rate, bandwidth) * .45:
        raise ValueError('Tone offset must be nonzero and within 45% of the actual bandwidth')
    phase = 2 * np.pi * bins * np.arange(SAMPLES) / SAMPLES
    # Truncation keeps each IQ vector within the specified complex peak.
    raw = np.column_stack((peak * np.cos(phase), peak * np.sin(phase))).astype('<i2').tobytes()
    meta = waveform(raw)
    meta.update(kind='tone', requested_offset_hz=offset, offset_hz=actual, bins=bins,
                sample_rate_hz=sample_rate, rf_bandwidth_hz=bandwidth)
    return raw, meta


@dataclass(frozen=True)
class TxPlan:
    """Freeze one TX request; attenuation is positive while hardwaregain uses its negative value."""
    channels: tuple[int, ...]
    frequency_hz: int
    attenuation_db: float = 40.0
    seconds: int = 10
    offset_hz: float = 250000.0
    peak: int = 4096
    iq_path: Path | None = None

    def prepare(self, info: dict):
        """Generate channels from actual readback; equal RX frequency alone does not imply shared LO."""
        if self.channels not in ((1,), (2,), (1, 2)):
            raise ValueError('Select TX1, TX2 or both TX channels')
        if type(self.frequency_hz) is not int or not 50_000_000 <= self.frequency_hz <= 5_800_000_000:
            raise ValueError('TX center frequency must be 50-5800 MHz')
        if (not math.isfinite(self.attenuation_db) or not 20 <= self.attenuation_db <= 40
                or abs(self.attenuation_db * 20 - round(self.attenuation_db * 20)) > 1e-6):
            raise ValueError('TX attenuation must be 20-40 dB in 0.05-dB steps')
        if type(self.seconds) is not int or not 1 <= self.seconds <= 300:
            raise ValueError('TX duration must be 1-300 seconds')
        mapping = info['radio']['mapping']
        tx_los = {mapping[f'tx{c}LoSelect'] for c in self.channels}
        frequencies = info['radio'].get('rx_center_frequency_hz', {})
        for channel in (1, 2):
            if mapping[f'rx{channel}LoSelect'] in tx_los:
                frequency = frequencies.get(str(channel))
                if type(frequency) is not int or frequency != self.frequency_hz:
                    raise ValueError('Shared-LO TX frequency must match every shared RX carrier')
        data, metadata = {}, {}
        file_raw = None
        if self.iq_path is not None:
            with self.iq_path.open('rb') as source:
                file_raw = source.read(SAMPLES * 4 + 1)
            waveform(file_raw)
        for channel in self.channels:
            params = next(p for p in info['parameters']['tx'] if p['channel'] == channel)
            if file_raw is None:
                raw, meta = tone(params['sample_rate_hz'], params['rf_bandwidth_hz'], self.offset_hz, self.peak)
            else:
                raw, meta = file_raw, waveform(file_raw)
                meta.update(kind='file', sample_rate_hz=params['sample_rate_hz'],
                            rf_bandwidth_hz=params['rf_bandwidth_hz'], spectral_occupancy_verified=False)
            data[channel], metadata[str(channel)] = raw, meta
        request = dict(channels=list(self.channels), frequency_hz=self.frequency_hz,
                       attenuation_db=self.attenuation_db, seconds=self.seconds, waveforms=metadata)
        return request, data


# End of file: tx_model.py
# Architect : LogicRF
# Contact   : info@logicrf.com
# Website   : https://www.logicrf.com
