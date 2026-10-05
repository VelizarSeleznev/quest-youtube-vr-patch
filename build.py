#!/usr/bin/env python3
"""GPL-3.0-only. Portable Android tool discovery and local APK rebuilding."""
import hashlib
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
from dataclasses import dataclass
import zipfile

TESTED_SHA256 = "023d8348c6e42bab74ca7b18f5aa5f7ff2aacf38b2ed342d652a655a1aeb3762"
GOOGLE_SIGNER_SHA256 = "8027b7a6ab434237c401541aa1b9dfc99a8fcadc7e5e3a27402a318825b34754"


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run(command, capture=False):
    command = [str(arg) for arg in command]
    result = subprocess.run(command, check=True, text=True,
                            stdout=subprocess.PIPE if capture else None,
                            stderr=subprocess.STDOUT if capture else None)
    return result.stdout if capture else None


@dataclass
class Tools:
    java: Path
    keytool: Path
    aapt: Path
    zipalign: Path
    apksigner: Path
    adb: Path | None


def discover_tools(sdk=None, java_home=None):
    suffix = ".exe" if os.name == "nt" else ""
    explicit_java = java_home or os.environ.get("JAVA_HOME")
    homes = [Path(explicit_java)] if explicit_java else [
        Path("/Applications/Android Studio.app/Contents/jbr/Contents/Home"),
        Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Android/Android Studio/jbr",
        Path("/opt/android-studio/jbr"),
    ]
    if not explicit_java and shutil.which("java"):
        homes.append(Path(shutil.which("java")).resolve().parent.parent)
    java_root = next((home for home in homes if
                      (home / ("bin/java" + suffix)).is_file() and
                      (home / ("bin/keytool" + suffix)).is_file()), None)
    if java_root is None:
        raise SystemExit("JDK 17+ not found. Install it or pass --java-home PATH.")
    java = java_root / ("bin/java" + suffix)
    version = run([java, "-version"], capture=True)
    match = re.search(r'version "(\d+)', version)
    if not match or int(match.group(1)) < 17:
        raise SystemExit("JDK 17 or newer is required.")
    explicit_sdk = sdk or os.environ.get("ANDROID_SDK_ROOT") or os.environ.get("ANDROID_HOME")
    roots = [Path(explicit_sdk)] if explicit_sdk else [
        Path.home() / "Library/Android/sdk", Path.home() / "Android/Sdk",
        Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local"))) / "Android/Sdk",
    ]
    candidates = []
    for root in roots:
        for directory in (root / "build-tools").glob("*"):
            numbers = tuple(int(n) for n in re.findall(r"\d+", directory.name))
            required = [directory / ("aapt" + suffix), directory / ("zipalign" + suffix),
                        directory / "lib/apksigner.jar"]
            if numbers and numbers[0] >= 35 and all(path.is_file() for path in required):
                candidates.append((numbers, root, directory))
    if not candidates:
        raise SystemExit("Android SDK Build-Tools 35+ not found. Install them or pass --sdk PATH.")
    _, sdk_root, directory = max(candidates, key=lambda item: item[0])
    adb = sdk_root / ("platform-tools/adb" + suffix)
    if not adb.is_file():
        adb = Path(shutil.which("adb")) if shutil.which("adb") else None
    return Tools(java, java_root / ("bin/keytool" + suffix), directory / ("aapt" + suffix),
                 directory / ("zipalign" + suffix), directory / "lib/apksigner.jar", adb)


def inspect_apk(apk, tools, experimental=False):
    from patch import ORIGINAL_PACKAGE
    badging = run([tools.aapt, "dump", "badging", apk], capture=True)
    match = re.search(r"package: name='([^']+)' versionCode='(\d+)' versionName='([^']*)'", badging)
    if not match or match.group(1) != ORIGINAL_PACKAGE:
        raise SystemExit("Input must be the original native YouTube VR app for Quest.")
    digest = file_hash(apk)
    if digest != TESTED_SHA256 and not experimental:
        raise SystemExit("Untested APK. Only 1.88.10 with the documented SHA-256 is supported. "
                         "Use --experimental to attempt another Google-signed version.")
    verification = run([tools.java, "-jar", tools.apksigner, "verify", "--print-certs", apk], capture=True)
    signers = re.findall(r"(?m)^Signer #\d+ certificate SHA-256 digest: ([a-fA-F0-9]+)$", verification)
    if [value.lower() for value in signers] != [GOOGLE_SIGNER_SHA256]:
        raise SystemExit("APK signature does not match the inspected Google signing certificate.")
    with zipfile.ZipFile(apk) as archive:
        if "lib/arm64-v8a/libyoutubevrjni.so" not in archive.namelist():
            raise SystemExit("Input does not contain the expected native arm64 VR library.")
    return {"package": match.group(1), "version_code": int(match.group(2)),
            "version_name": match.group(3), "sha256": digest,
            "signer_sha256": signers[0].lower(), "tested_input": digest == TESTED_SHA256}


def signing_key(keys, tools):
    keys = Path(keys)
    keys.mkdir(parents=True, exist_ok=True)
    keys.chmod(0o700)
    password = keys / "password.txt"
    keystore = keys / "quest-youtube-patch.jks"
    if keystore.exists() and not password.exists():
        raise SystemExit("Existing signing key has no password file. Restore your original password.txt.")
    if not password.exists():
        descriptor = os.open(password, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            stream.write(secrets.token_urlsafe(32) + "\n")
    if not keystore.exists():
        run([tools.keytool, "-genkeypair", "-keystore", keystore,
             "-storepass:file", password, "-keypass:file", password,
             "-alias", "questpatch", "-keyalg", "RSA", "-keysize", "3072",
             "-validity", "3650", "-dname", "CN=Local Quest YouTube Patch", "-storetype", "JKS"])
        keystore.chmod(0o600)
    return keystore, password


def build_apk(decoded, original, apktool, output, keys, tools):
    output = Path(output)
    keystore, password = signing_key(keys, tools)
    output.parent.mkdir(parents=True, exist_ok=True)
    unsigned = Path(decoded).parent / "unsigned.apk"
    aligned = Path(decoded).parent / "aligned.apk"
    run([tools.java, "-jar", apktool, "b", decoded, "-o", unsigned])
    run([tools.zipalign, "-P", "16", "-f", "4", unsigned, aligned])
    run([tools.java, "-jar", tools.apksigner, "sign", "--ks", keystore,
         "--ks-key-alias", "questpatch", "--ks-pass", "file:" + str(password),
         "--out", output, aligned])
    run([tools.java, "-jar", tools.apksigner, "verify", output])
    run([tools.zipalign, "-c", "-P", "16", "4", output])
    with zipfile.ZipFile(original) as source, zipfile.ZipFile(output) as patched:
        libraries = {n for n in source.namelist() if n.startswith("lib/") and n.endswith(".so")}
        built_libraries = {n for n in patched.namelist() if n.startswith("lib/") and n.endswith(".so")}
        if not libraries or libraries != built_libraries:
            raise SystemExit("Native library inventory changed.")
        for name in libraries:
            if source.read(name) != patched.read(name):
                raise SystemExit("Native library changed: " + name)
    return {"sha256": file_hash(output), "identical_native_libraries": len(libraries)}
