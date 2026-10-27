## Panel firmware compatibility

GUI 0.8.1 adds support for the matching panel firmware. See [firmware requirements and indicators](docs/PANEL-COMPATIBILITY.md). Bilingual operation and the English first-launch default are retained.

# LogicRF Hawk H102 IIO GUI

A Linux desktop application for configuring Hawk H102 radios, receiving IQ over Gigabit Ethernet, viewing spectrum/waterfall/time-domain plots, recording IQ and controlling supported cyclic TX.

The interface starts in English and supports live switching to Simplified Chinese. Your saved language choice is retained. Ordinary operation uses the device IP only; no Linux username or SSH password is requested.

## Get started

1. Install the [host prerequisites](docs/INSTALL.md).
2. Use the matching device-control service: it is included in Kuiper 1.2.1 (internal build 1.2.1-rc2), or supplied by the reviewed panel1 incremental installation. The unmodified 1.2.0 SD image needs its separate service update.
3. Run `bash ./launch.sh --host DEVICE_IP`, then connect and read back the active configuration.
4. Start with 8 MSPS / 4 MHz and RX1. Apply the profile before starting acquisition.

Read the [user guide](docs/USER-GUIDE.md) for recording, tuning, sweep and TX controls.

## Package scope

This repository contains the reviewed English GUI source and its client-side helpers, with the panel compatibility update from development revision `1c5951e59396a389763e2c3256bbeac3021c446e`. Chinese UI text is confined to the explicit locale resource. It does not contain an SD image, FPGA build, vendor SDK or the device service installer.

- [Installation](docs/INSTALL.md)
- [User guide](docs/USER-GUIDE.md)
- [Validation and compatibility](docs/VALIDATION.md)
- [Source and licensing](LICENSE.md)
- [Delivery maintenance](docs/MAINTAINING.md)

This private source delivery does not grant a new open-source license or extend existing hardware/RF qualification.
