# Verification

Release candidate v0.1.0, 2026-10-05.

## Observed on the initial working build

- Physical Quest 3; Android API 34; official YouTube VR 1.88.10.
- Separate patched package installed and native VR activity launched.
- Original official app remained installed.
- All 40 native shared libraries matched the original APK byte for byte.
- APK signature verified; release app had no debuggable flag.
- Runtime logs showed the injected ad-trigger hook executing.
- Native player decoded thousands of video frames.
- Headset owner reported that playback worked, then confirmed sign-in and playback after signing in.

The hook log can fire for empty trigger lists. A log line alone is not proof that
an actual served ad was blocked. The owner’s positive report establishes usability
of the tested build; a controlled known-ad comparison is still needed to quantify
ad suppression.

## Portable release tool

The release tool owns a fresh decode of a signature- and hash-verified original.
It validates a unique fingerprint and native VR manifest before writes, signs
with a persistent local key, verifies alignment/signature, and compares the
complete native-library inventory and bytes before output/install.

Source-only unit tests cover refusal paths, idempotence, control-hook removal,
key preservation, checksum validation and device selection. The portable CLI was
also used to rebuild the pinned real APK locally on macOS. Its release APK was
not substituted for the already accepted headset build.

## Remaining work

- Repeated controlled before/after checks against known served pre-rolls and mid-rolls.
- Seeking around known ad points, live streams and long sessions.
- Dedicated VR180/360, resolution and controller regression checks.
- End-to-end installation/build on Windows and Linux (CI checks Python logic).
- Other Quest models and newer official app versions.

Please distinguish a successful build, observed playback and controlled
ad-blocking evidence in your reports.
