# Panel status and firmware compatibility

GUI 0.8.1 supports the reviewed H102 panel bitstream in addition to the previous D81 and EFA revisions. Use the device-control service supplied with the matching firmware. Normal connections require only the device IP address; an administrator prepares firmware once.

S0 flashes once per second while the FPGA is running. S1 flashes during host IQ activity and turns off after activity stops. These indicators do not measure RF signal level, establish GNSS lock or confirm recording integrity. Use acquisition status and recording verification for those checks.

Kuiper 1.2.1-rc1 integrates the panel firmware and device-control service into a complete SD image. It is a release candidate: verification of an SD card written from that exact image is pending. The earlier panel1 incremental installation has passed representative digital/data checks. This does not extend the existing RF, timing or throughput specifications.

The application starts in English and supports Simplified Chinese from the language selector. A saved language choice remains in effect.
