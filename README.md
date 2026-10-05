# Native YouTube VR ad patch for Meta Quest

An experimental, open-source patcher for the **native YouTube VR app on Quest**. Build a separate “YouTube VR AdPatch” app from the official APK already installed on your own headset.

This keeps the original native VR player and installs alongside the official app. It is a small adaptation of [ReVanced’s video-ad hook](https://gitlab.com/ReVanced/revanced-patches/-/tree/015fe10a23ea5b919a3fda6e7da2c176517ae75d/patches/src/main/kotlin/app/revanced/patches/youtube/ad/video), with local rebuilding and signing.

**Tested:** Quest 3, YouTube VR **1.88.10**. The owner confirmed Google sign-in and video playback in the headset. The hook was observed executing; a controlled before/after test against a known served ad is still outstanding. This release does not claim to block every ad. Dedicated VR180/360 regression tests are also outstanding.

## Quick start

You need:
- Python **3.10+** and a **JDK 17+**.
- Android SDK **Build-Tools 35+** and **Platform-Tools** (ADB). Android Studio includes a JDK; install the SDK tools through its SDK Manager.
- A Quest with developer mode enabled, USB debugging authorized, and the official YouTube VR app installed.

Download this repository or clone it:

```sh
git clone https://github.com/VelizarSeleznev/quest-youtube-vr-patch.git
cd quest-youtube-vr-patch
python3 questpatch.py --from-device --install
```

On Windows, use `py -3` instead of `python3`.

The tool pulls your original APK, verifies its hash and Google signing certificate, downloads checksum-pinned Apktool, decodes a fresh copy, checks the ad-method fingerprint, rebuilds and signs locally, and verifies that every native library is unchanged. It then installs and launches the separate app. Sign in inside the headset if YouTube asks.

If several Android devices are connected, select your Quest with `--serial SERIAL` (find it with `adb devices -l`). The tool refuses to install on a device whose model is not a Quest.

If automatic tool discovery fails:

```sh
python3 questpatch.py --from-device --install --sdk /path/to/Android/sdk --java-home /path/to/jdk
```

To build without connecting a headset:

```sh
python3 questpatch.py --apk /path/to/your/original.apk
```

Output defaults to `out/YouTubeVR-AdPatch.apk`, with a JSON verification report beside it. Existing output files are preserved: choose a new `--output` path for another build.

## Updates and compatibility

Keep the private signing key and password in `~/.quest-youtube-vr-patch/keys/`. Future builds reuse them so Android can update your patched app. Back them up privately; never attach them to an issue. `--keys PATH` selects an existing key directory.

The original app stays installed. Removing the patched app is enough to stop using this patch. A clone signed by someone else cannot be updated with your local key; removing that clone also removes its app data.

Only this original APK is currently supported by default:

```text
YouTube VR: 1.88.10
SHA-256: 023d8348c6e42bab74ca7b18f5aa5f7ff2aacf38b2ed342d652a655a1aeb3762
```

`--experimental` attempts another Google-signed version but still requires an unambiguous matching method and the expected native VR layout. A successful build does not establish playback or ad-blocking compatibility.

Apktool **3.0.3** comes from its [official release](https://github.com/iBotPeaches/Apktool/releases/tag/v3.0.3), pinned to SHA-256 `dbf930b076c6b9be08d57c449cacefc3bdd6b71ebd59b3066fc0e1f5b14f9423`. For offline use, download that jar first and pass `--apktool PATH`.

## What the patch changes

The patch identifies the same pair of strings used by ReVanced’s video-ad fingerprint, then inserts an early return in the matching trigger-bundle method. It uses an existing Android logging reference because the tested DEX is already at its method-reference limit.

The package, provider identifiers, task affinity and launcher label are adjusted for side-by-side installation. Native libraries are compared byte for byte against the original APK. No Google APK, decompiled Google source, signing key or account data is included in this repository.

See [verification notes](docs/verification.md) for observed results and remaining checks. `--mode control` creates a clone without the ad hook for developer comparisons; use a separate output path.

## Contributing

Run the source-only checks:

```sh
python3 -m unittest discover -s tests -v
```

Useful contributions: controlled pre-roll/mid-roll comparisons, VR180/360 playback and seeking checks, and compatibility reports for newer official APKs. Include your headset model, original app version, tool version, and exact steps. Do not upload APKs, decoded app files, account details, login codes or private keys.

Built by [Velizar Seleznev](https://github.com/VelizarSeleznev). Released under [GPL-3.0](LICENSE); upstream attribution and pinned sources are in [NOTICE](NOTICE).
