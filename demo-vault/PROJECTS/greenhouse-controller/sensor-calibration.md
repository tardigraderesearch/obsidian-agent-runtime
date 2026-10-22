# Sensor Calibration

Raw readings are 12-bit ADC counts. Lower = wetter.

## Method

1. Dry reading: probe in open air, average 20 samples.
2. Wet reading: probe submerged to the line in a glass of tap water, average 20 samples.
3. Moisture % = (dry - raw) / (dry - wet) * 100.

## Offset table

| Probe | Dry | Wet | Notes |
|---|---|---|---|
| A | 3010 | 1420 | Calibrated 2026-03-02 |
| B | 2950 | 1300 | Provisional; reads ~6% wetter than A in the same pot (2026-03-09) |

## Open questions

- Is probe B's offset from the probe itself or from a longer cable run? Swap cables to test.
