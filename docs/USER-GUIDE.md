# Using the H102 IIO GUI

The LogicRF Hawk H102 IIO GUI is a Linux desktop application for device configuration, single/dual RX IQ, spectrum/waterfall display, center-frequency tuning, segmented sweeps, recording and explicit TX control. The interface supports English and Simplified Chinese.

This branch currently contains English documentation and provenance. The application/source package is supplied separately; this branch is not a complete installable GUI distribution.

## Connect

Install the matching GUI package and host prerequisites, then enter the H102 IP. Ordinary operation requires no Linux username or SSH password. An administrator must install the matching device-control services first.

Use the language selector in the title bar for English. The selection is remembered without reconnecting. A supported command-line launch can select English for one session with `--language en`.

## Receive

Choose RX1, RX2 or both, then select a built-in sample-rate/bandwidth profile that fits Gigabit Ethernet. Start with dual RX at 8 MSPS / 4 MHz. Wait for actual readiness before using the spectrum/IQ. Changing profile reinitializes the radio and may take more than 20 seconds.

Set center frequency with the frequency control. Shared-LO channels must use compatible center frequencies. Retuning interrupts the sampled stream; treat each tuned segment separately when continuity matters.

## Record and export

The save icon exports the latest complete IQ block; it is not a whole-session recording. Use the recording control to record the incoming stream. Recording locks tuning, checks device overflow and complete file writes, and retains partial output on failure.

Each channel has a little-endian signed-16 interleaved I/Q file and `recording.json` metadata. Only a successfully completed recording should be treated as complete. Spectral plots alone cannot prove sample continuity.

## Sweep and transmit

Sweeps acquire frequency segments sequentially and include tuning gaps; they do not capture uninterrupted IQ across the entire displayed span. Display levels in dBFS are not calibrated RF power in dBm.

TX control uses explicitly prepared cyclic IQ for the supported GUI path, not unrestricted full-rate Ethernet TX streaming. Before transmission, connect suitable attenuation/loads and confirm the requested channel, frequency and output level. Stop TX and reception before disconnecting or switching applications.

## Troubleshooting

- Device unavailable: check IP, network and matching services. Do not enter a Linux password as a connection workaround.
- Device busy: stop and disconnect the other application before retrying.
- Unsupported profile/rate: select an installed profile within the aggregate 64 MB/s Ethernet IQ16 budget.
- Recording failure: keep partial data and inspect the error; do not rename partial files to mark them complete.

Release-specific hardware/RF limits and exact matching software are documented with the supplied package. Documentation preparation does not add new device qualification.
