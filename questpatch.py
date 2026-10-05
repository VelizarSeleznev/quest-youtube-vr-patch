#!/usr/bin/env python3
"""GPL-3.0-only. Build an experimental native YouTube VR ad patch on your computer."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import urllib.request

from build import build_apk, discover_tools, file_hash, inspect_apk, run
from patch import ORIGINAL_PACKAGE, PATCH_PACKAGE, patch_decoded

VERSION = "0.1.0"
APKTOOL_VERSION = "3.0.3"
APKTOOL_SHA256 = "dbf930b076c6b9be08d57c449cacefc3bdd6b71ebd59b3066fc0e1f5b14f9423"
APKTOOL_URL = ("https://github.com/iBotPeaches/Apktool/releases/download/v3.0.3/"
               "apktool_3.0.3.jar")


def publish_file(source, destination):
    """Atomically publish complete bytes without replacing an existing file."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as stream:
            temporary = Path(stream.name)
            with Path(source).open("rb") as input_stream:
                shutil.copyfileobj(input_stream, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def apktool_jar(cache, supplied=None):
    jar = Path(supplied).resolve() if supplied else Path(cache) / ("apktool-" + APKTOOL_VERSION + ".jar")
    if supplied and not jar.is_file():
        raise SystemExit("Specified Apktool jar does not exist.")
    if not jar.exists():
        jar.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=jar.parent, delete=False) as output:
                temporary = Path(output.name)
                print("Downloading pinned Apktool from its official GitHub release...")
                with urllib.request.urlopen(APKTOOL_URL, timeout=60) as response:
                    shutil.copyfileobj(response, output)
            if file_hash(temporary) != APKTOOL_SHA256:
                raise SystemExit("Downloaded Apktool checksum mismatch.")
            temporary.replace(jar)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    if file_hash(jar) != APKTOOL_SHA256:
        raise SystemExit("Apktool checksum mismatch. Use the official 3.0.3 jar.")
    return jar


def quest_device(tools, serial=None):
    if tools.adb is None:
        raise SystemExit("ADB not found. Install Android SDK Platform-Tools.")
    devices = []
    for line in run([tools.adb, "devices", "-l"], capture=True).splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            devices.append(parts[0])
    if serial:
        if serial not in devices:
            raise SystemExit("Requested device is not connected and authorized.")
    elif len(devices) == 1:
        serial = devices[0]
    else:
        raise SystemExit("Connect and authorize one Quest, or select it with --serial SERIAL.")
    command = [tools.adb, "-s", serial]
    model = run(command + ["shell", "getprop", "ro.product.model"], capture=True).strip()
    if "quest" not in model.lower():
        raise SystemExit("Selected device is not a Meta Quest: " + model)
    print("Selected headset:", model)
    return command


def pull_original(command, destination):
    lines = run(command + ["shell", "pm", "path", ORIGINAL_PACKAGE], capture=True).splitlines()
    paths = [line.removeprefix("package:").strip() for line in lines if line.startswith("package:")]
    if len(paths) != 1:
        raise SystemExit("Install the official YouTube VR app first. Split APK installations are unsupported.")
    run(command + ["pull", paths[0], destination])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=VERSION)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--from-device", action="store_true", help="Pull official APK from a connected Quest")
    source.add_argument("--apk", type=Path, help="Use your own original Google-signed Quest APK")
    parser.add_argument("--install", action="store_true", help="Install and launch the separate patched app")
    parser.add_argument("--serial", help="Explicit ADB device serial when multiple devices are connected")
    parser.add_argument("--output", type=Path, default=Path("out/YouTubeVR-AdPatch.apk"))
    parser.add_argument("--sdk", type=Path, help="Android SDK directory")
    parser.add_argument("--java-home", type=Path, help="JDK 17+ directory")
    parser.add_argument("--cache", type=Path, default=Path.home() / ".quest-youtube-vr-patch")
    parser.add_argument("--keys", type=Path, help="Private signing-key directory; retain for updates")
    parser.add_argument("--apktool", type=Path, help="Offline official Apktool 3.0.3 jar")
    parser.add_argument("--experimental", action="store_true", help="Attempt an untested original APK version")
    parser.add_argument("--keep-work", action="store_true", help="Keep local decoded files for debugging")
    parser.add_argument("--mode", choices=("r1", "control"), default="r1",
                        help="control builds a clone without the ad hook for comparison")
    args = parser.parse_args()
    output = args.output.resolve()
    report_path = output.with_suffix(".report.json")
    if output.exists() or report_path.exists():
        raise SystemExit("Output already exists. Choose another --output path to preserve that build.")
    if args.apk and not args.apk.is_file():
        raise SystemExit("Input APK does not exist.")
    tools = discover_tools(args.sdk, args.java_home)
    command = quest_device(tools, args.serial) if args.from_device or args.install else None
    cache = args.cache.resolve()
    cache.mkdir(parents=True, exist_ok=True)
    jar = apktool_jar(cache, args.apktool)
    work = Path(tempfile.mkdtemp(prefix="build-", dir=cache))
    try:
        original = work / "original.apk"
        if args.from_device:
            pull_original(command, original)
        else:
            shutil.copyfile(args.apk, original)
        metadata = inspect_apk(original, tools, args.experimental)
        print("Verified input:", metadata["version_name"], metadata["sha256"])
        decoded = work / "decoded"
        run([tools.java, "-jar", jar, "d", "-f", original, "-o", decoded])
        patch_report = patch_decoded(decoded, args.mode)
        # Stage the complete build before publishing the output file.
        staged = work / "YouTubeVR-AdPatch.apk"
        result = build_apk(decoded, original, jar, staged, args.keys or cache / "keys", tools)
        badging = run([tools.aapt, "dump", "badging", staged], capture=True)
        if "package: name='" + PATCH_PACKAGE + "'" not in badging:
            raise SystemExit("Built APK is not the separate patched package.")
        if "application-debuggable" in badging:
            raise SystemExit("Built APK unexpectedly has debugging enabled.")
        output.parent.mkdir(parents=True, exist_ok=True)
        report = {"tool_version": VERSION, "input": metadata, "patch": patch_report, "output": result}
        staged_report = work / "report.json"
        staged_report.write_text(json.dumps(report, indent=2) + "\n")
        publish_file(staged, output)
        try:
            publish_file(staged_report, report_path)
        except OSError:
            output.unlink()
            raise
        print("Built and verified:", output)
        if args.install:
            run(command + ["install", "--no-incremental", "-r", output])
            run(command + ["shell", "am", "start", "-n", PATCH_PACKAGE + "/" +
                           "com.google.android.apps.youtube.vr.activities.YouTubeVrActivity"])
            print("Launched YouTube VR AdPatch. Sign in inside the headset if requested.")
    finally:
        if args.keep_work:
            print("Local debugging files:", work)
        else:
            shutil.rmtree(work)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as error:
        if error.stdout:
            print(error.stdout)
        raise SystemExit("Tool failed with exit code " + str(error.returncode)) from error
