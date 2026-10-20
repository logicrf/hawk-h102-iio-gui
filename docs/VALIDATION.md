# Validation and compatibility

## English source checkpoint

The source export is based on GUI revision `637a80cd2b9daec21741dd47d051067ce0ad8806`. This delivery changes source explanations, customer documentation and UI localization, makes English the first-launch default, removes a development-host IP and launcher fallback, and separates reviewed host hashes from installed device-helper requirements.

Offline checks on Linux passed:

- 127 application tests, including real Qt widgets with controlled RX/TX sessions, tuning/recording models and nine language-switch tests.
- Two additional exact-helper identity/client-lock tests; the catalog test was rerun after final resource cleanup.
- English and Simplified Chinese offscreen window previews at 1280 x 900, with no horizontal sidebar scroll.
- Matching placeholder fields/formats in both locale catalogs; user paths and diagnostic arguments remain literal.
- Structural comparison of 28 original Python modules: 25 retain executable AST structure after string normalization. The three explicit code changes are locale lookup/default/capture, the native language-selector label, and the reviewed helper-hash adapter. String normalization is a review aid, not a full behavioral proof.

The first combined test run exposed a model-session timeout: the fake worker expired while a loaded Qt suite was switching languages. Its fail-safe was extended to keep the model alive until the explicit stop action. The final full run passed; no production timing guarantee follows from that test adjustment.

## Device compatibility

Five exact translated host payload hashes map to their original installed-helper hashes. Unknown or edited source hashes are not mapped. The device still checks its installed bytes independently. These original helper identities match the reviewed gr-logicrf English delivery pins.

Ordinary operation uses the fixed device-control API and libiio 0.x. It does not upload translated scripts, run remote shell commands or request a Linux password. Device API services must already be installed; the base Kuiper 1.2.0 SD image and later service add-ons are separate deliveries.

## Scope

No device, RF, USB, SD-card, cold-boot or long-duration acceptance was run for this English packaging checkpoint. Existing hardware results keep their original versions and test windows. The internal hardware campaign validator and its receipt-scope test are outside the standalone source package.

The aggregate application admission budget is 64 MB/s for Ethernet IQ16. Device reconfiguration may exceed 20 seconds. Ordinary IQ plots do not prove exact lost-sample count; strict recording checks device overflow and full file writes for the actual window. Refer to the matching firmware release for RF and timing limits.


## Source packaging revision r2

The original r1 source checker treated a locally installed root `.venv` as package
content, so the documented post-install source check failed on a virtual-environment
symlink. Revision r2 excludes that one local dependency directory. Packaged source
hashes, unlisted source files and symlinks outside it are still checked. Dependency
consistency is a separate `pip check`. Application files, protocol identities and
device requirements are unchanged. This correction does not add hardware qualification.
