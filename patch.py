#!/usr/bin/env python3
"""GPL-3.0-only. Patch a locally decoded native YouTube VR APK."""
import argparse
import json
import re
from pathlib import Path
import xml.etree.ElementTree as ET

ORIGINAL_PACKAGE = "com.google.android.apps.youtube.vr.oculus"
PATCH_PACKAGE = "app.questpatch.youtube.vr.oculus"
FINGERPRINTS = (
    "TriggerBundle doesn't have the required metadata specified by the trigger ",
    "Ping migration no associated ping bindings for activated trigger: ",
)
ANDROID = "{http://schemas.android.com/apk/res/android}"
PREFIX = '''
    # QUEST_YOUTUBE_PATCH_R1_BEGIN
    const-string v0, "QuestYouTubePatch"
    const-string v1, "r1: suppressed ads trigger bundle"
    invoke-static {v0, v1}, Landroid/util/Log;->w(Ljava/lang/String;Ljava/lang/String;)I
    return-void
    # QUEST_YOUTUBE_PATCH_R1_END
'''


def patch_decoded(root, mode="r1"):
    if mode not in ("control", "r1"):
        raise ValueError("Unknown patch mode")
    root = Path(root).resolve()
    matches = []
    for path in root.glob("smali*/**/*.smali"):
        text = path.read_text()
        if not all(word in text.replace("\\'", "'") for word in FINGERPRINTS):
            continue
        for method in re.finditer(r"(?ms)^\.method[^\n]*\n.*?^\.end method", text):
            if all(word in method.group().replace("\\'", "'") for word in FINGERPRINTS):
                matches.append((path, text, method))
    if len(matches) != 1:
        raise SystemExit(f"Expected one ads method, found {len(matches)}; refusing to patch")
    path, text, match = matches[0]
    method = match.group()
    header = method.splitlines()[0]
    if not header.endswith("(Ljava/util/List;)V"):
        raise SystemExit(f"Unexpected method signature: {header}")
    locals_match = re.search(r"(?m)^    \.locals (\d+)\s*$", method)
    if not locals_match or int(locals_match.group(1)) < 2:
        raise SystemExit("Expected at least two local registers")
    method = re.sub(r"\n    # QUEST_YOUTUBE_PATCH_R1_BEGIN.*?# QUEST_YOUTUBE_PATCH_R1_END\n", "\n", method, flags=re.S)
    if mode == "r1":
        method = re.sub(r"(?m)^(    \.locals \d+)\s*$", lambda m: m.group(1) + "\n" + PREFIX, method, count=1)
    patched_smali = text[:match.start()] + method + text[match.end():]

    ET.register_namespace("android", ANDROID[1:-1])
    ET.register_namespace("horizonos", "http://schemas.horizonos/sdk")
    manifest_path = root / "AndroidManifest.xml"
    tree = ET.parse(manifest_path)
    manifest = tree.getroot()
    if manifest.get("package") not in (ORIGINAL_PACKAGE, PATCH_PACKAGE):
        raise SystemExit("Unexpected input package")
    is_clone = manifest.get("package") == PATCH_PACKAGE
    manifest.set("package", PATCH_PACKAGE)
    application = manifest.find("application")
    if application is None:
        raise SystemExit("Missing application")
    application.set(ANDROID + "label", "YouTube VR AdPatch" if mode == "r1" else "YouTube VR Control")
    for element in manifest.iter():
        for key, value in list(element.attrib.items()):
            if element.tag in ("permission", "uses-permission") or key == ANDROID + "authorities":
                element.set(key, value.replace(ORIGINAL_PACKAGE, PATCH_PACKAGE))
            if key == ANDROID + "taskAffinity" and value.startswith("com.google.android.apps.youtube.vr."):
                element.set(key, "app.questpatch." + value)
    # Give the clone a distinct launcher entry while keeping its original VR activity.
    activity = next((e for e in application.findall("activity") if e.get(ANDROID + "name") == "com.google.android.apps.youtube.vr.activities.YouTubeVrActivity"), None)
    if activity is None:
        raise SystemExit("Missing native YouTube VR activity")
    main_filter = next((e for e in activity.findall("intent-filter") if any(a.get(ANDROID + "name") == "android.intent.action.MAIN" for a in e.findall("action"))), None)
    if main_filter is None:
        raise SystemExit("Missing VR launch intent")
    if not any(c.get(ANDROID + "name") == "android.intent.category.LAUNCHER" for c in main_filter.findall("category")):
        ET.SubElement(main_filter, "category", {ANDROID + "name": "android.intent.category.LAUNCHER"})
    strings_path = root / "res/values/strings.xml"
    strings = strings_path.read_text().replace("com.google.android.vr.inputmethod.fileprovider.youtube", "app.questpatch.youtube.vr.fileprovider")
    if "app.questpatch.youtube.vr.fileprovider" not in strings:
        raise SystemExit("Expected file-provider resource not found")
    config_path = root / "apktool.yml"
    config = config_path.read_text()
    version = re.search(r"(?m)^  versionCode: (\d+)$", config)
    if version is None:
        raise SystemExit("Missing numeric APK version code")
    if not is_clone and mode == "r1":
        config = config[:version.start(1)] + str(int(version.group(1)) + 1) + config[version.end(1):]
    # Validate everything before modifying any source file.
    path.write_text(patched_smali)
    tree.write(manifest_path, encoding="utf-8", xml_declaration=True)
    strings_path.write_text(strings)
    config_path.write_text(config)
    return {"mode": mode, "package": PATCH_PACKAGE, "method": header, "file": path.relative_to(root).as_posix(), "fingerprints": list(FINGERPRINTS)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("decoded", type=Path)
    parser.add_argument("--mode", choices=("control", "r1"), default="r1")
    args = parser.parse_args()
    report = patch_decoded(args.decoded, args.mode)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
