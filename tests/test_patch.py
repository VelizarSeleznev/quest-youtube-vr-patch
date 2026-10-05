"""Synthetic source-only tests. Contains no Google app source."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from build import Tools, signing_key
from patch import ANDROID, FINGERPRINTS, ORIGINAL_PACKAGE, PATCH_PACKAGE, patch_decoded
from questpatch import apktool_jar, publish_file, quest_device


def fixture(root, package=ORIGINAL_PACKAGE):
    smali = root / "smali_classes3" / "synthetic.smali"
    smali.parent.mkdir()
    smali.write_text('.class public Lsynthetic;\n.method public m(Ljava/util/List;)V\n'
                     '    .locals 2\n'
                     + ''.join('    const-string v0, "' + text + '"\n' for text in FINGERPRINTS)
                     + '    return-void\n.end method\n')
    (root / "AndroidManifest.xml").write_text(
        '<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="' + package + '">'
        '<permission android:name="' + ORIGINAL_PACKAGE + '.LOCAL"/>'
        '<application android:label="Original">'
        '<provider android:name="OriginalProvider" android:authorities="' + ORIGINAL_PACKAGE + '.provider"/>'
        '<activity android:name="com.google.android.apps.youtube.vr.activities.YouTubeVrActivity" '
        'android:taskAffinity="com.google.android.apps.youtube.vr.task">'
        '<intent-filter><action android:name="android.intent.action.MAIN"/></intent-filter>'
        '</activity></application></manifest>')
    strings = root / "res/values/strings.xml"
    strings.parent.mkdir(parents=True)
    strings.write_text('<resources><string name="provider">com.google.android.vr.inputmethod.fileprovider.youtube</string></resources>')
    (root / "apktool.yml").write_text('versionInfo:\n  versionCode: 18810000\n')
    return smali


class PatchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.smali = fixture(self.root)

    def snapshot(self):
        return {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}

    def test_idempotent_patch_and_clone(self):
        report = patch_decoded(self.root)
        once = self.snapshot()
        self.assertEqual(once, (patch_decoded(self.root), self.snapshot())[1])
        self.assertEqual(report["package"], PATCH_PACKAGE)
        self.assertEqual(self.smali.read_text().count("# QUEST_YOUTUBE_PATCH_R1_BEGIN"), 1)
        self.assertIn("versionCode: 18810001", (self.root / "apktool.yml").read_text())
        self.assertIn("android.intent.category.LAUNCHER", (self.root / "AndroidManifest.xml").read_text())
        self.assertIn("com.google.android.apps.youtube.vr.activities.YouTubeVrActivity",
                      (self.root / "AndroidManifest.xml").read_text())

    def test_control_removes_hook(self):
        patch_decoded(self.root)
        patch_decoded(self.root, "control")
        self.assertNotIn("QUEST_YOUTUBE_PATCH_R1_BEGIN", self.smali.read_text())

    def test_wrong_package_leaves_every_file_unchanged(self):
        manifest = self.root / "AndroidManifest.xml"
        manifest.write_text(manifest.read_text().replace('package="' + ORIGINAL_PACKAGE + '"', 'package="other.app"'))
        before = self.snapshot()
        with self.assertRaises(SystemExit):
            patch_decoded(self.root)
        self.assertEqual(before, self.snapshot())

    def test_ambiguous_fingerprint_refused_without_changes(self):
        self.smali.with_name("duplicate.smali").write_text(self.smali.read_text())
        before = self.snapshot()
        with self.assertRaises(SystemExit):
            patch_decoded(self.root)
        self.assertEqual(before, self.snapshot())

    def test_missing_vr_activity_refused_without_changes(self):
        manifest = self.root / "AndroidManifest.xml"
        manifest.write_text(manifest.read_text().replace("activities.YouTubeVrActivity", "activities.Other"))
        before = self.snapshot()
        with self.assertRaises(SystemExit):
            patch_decoded(self.root)
        self.assertEqual(before, self.snapshot())

    def test_missing_provider_refused_without_changes(self):
        (self.root / "res/values/strings.xml").write_text("<resources/>")
        before = self.snapshot()
        with self.assertRaises(SystemExit):
            patch_decoded(self.root)
        self.assertEqual(before, self.snapshot())


class ToolTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        placeholder = Path("unused")
        self.tools = Tools(placeholder, placeholder, placeholder, placeholder, placeholder, Path("adb"))

    def test_apktool_checksum_refused(self):
        jar = self.root / "bad.jar"
        jar.write_bytes(b"not apktool")
        with self.assertRaises(SystemExit):
            apktool_jar(self.root, jar)

    def test_existing_key_without_password_is_preserved(self):
        keystore = self.root / "quest-youtube-patch.jks"
        keystore.write_bytes(b"private key placeholder")
        with self.assertRaises(SystemExit):
            signing_key(self.root, self.tools)
        self.assertFalse((self.root / "password.txt").exists())
        self.assertEqual(keystore.read_bytes(), b"private key placeholder")

    def test_existing_key_and_password_reused(self):
        (self.root / "quest-youtube-patch.jks").write_bytes(b"key")
        (self.root / "password.txt").write_text("private test fixture")
        with patch("build.run") as run:
            key, password = signing_key(self.root, self.tools)
            run.assert_not_called()
        self.assertEqual(password.read_text(), "private test fixture")

    def test_multiple_devices_require_selection(self):
        with patch("questpatch.run", return_value="List of devices attached\na device\nb device\n"):
            with self.assertRaises(SystemExit):
                quest_device(self.tools)

    def test_pixel_refused(self):
        with patch("questpatch.run", side_effect=["List of devices attached\na device\n", "Pixel 10"]):
            with self.assertRaises(SystemExit):
                quest_device(self.tools)

    def test_explicit_quest_selected(self):
        with patch("questpatch.run", side_effect=["List of devices attached\na device\nb device\n", "Quest_3"]):
            command = quest_device(self.tools, "b")
        self.assertEqual(command, [Path("adb"), "-s", "b"])

    def test_complete_output_published_without_overwrite(self):
        source, destination = self.root / "source", self.root / "output"
        source.write_bytes(b"complete bytes")
        publish_file(source, destination)
        self.assertEqual(destination.read_bytes(), b"complete bytes")
        source.write_bytes(b"other build")
        with self.assertRaises(FileExistsError):
            publish_file(source, destination)
        self.assertEqual(destination.read_bytes(), b"complete bytes")
        self.assertEqual({p.name for p in self.root.iterdir()}, {"source", "output"})


if __name__ == "__main__":
    unittest.main()
