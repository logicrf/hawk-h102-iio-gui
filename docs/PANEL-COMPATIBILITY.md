# Panel status and firmware compatibility

GUI 0.8.1 supports the reviewed H102 panel bitstream in addition to the previous D81 and EFA revisions. Use the device-control service supplied with the matching firmware. Normal connections require only the device IP address; an administrator prepares firmware once.

S0 flashes once per second while the FPGA is running. S1 flashes during host IQ activity and turns off after activity stops. These indicators do not measure RF signal level, establish GNSS lock or confirm recording integrity. Use acquisition status and recording verification for those checks.

Use the integrated Kuiper 1.2.1 image (internal build 1.2.1-rc2) for a newly provisioned card. The matching device API is included, so the older 1.2.0 board-service add-on is not required. Exact first-unit card/cold/warm boot, asset/identity checks, representative IIO/USB and Linux ADI Oscilloscope checks passed. Those system checks do not extend RF, all-profile endurance, absolute UTC or second-unit qualification. The earlier panel1 incremental installation retains its original separate scope.

The application starts in English and supports Simplified Chinese from the language selector. A saved language choice remains in effect.
