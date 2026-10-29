# DEVELOPED BY CARROTSTUDIO software house
"""Updating from a USB stick: only a newer version signed by CarrotStudio, checked where it
will run, applied whole or not at all. The tests sign with `cryptography`."""

import base64
import contextlib
import importlib.util
import io
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "campanile"))
import copying
import launch
import release
import signing
import update
from preparation import Preparation

CAN_SIGN = importlib.util.find_spec("cryptography") is not None


def write(root: Path, files: dict) -> None:
    for relative, text in files.items():
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        (root / relative).write_text(text, encoding="utf-8")


def program(root: Path, version: str) -> None:
    write(
        root,
        {
            "campanile/server.py": f'VERSION = "{version}"\n',
            "campanile/launch.py": "",
            "raspberry/install.sh": "echo installing\n",
            "README.md": "Campanile",
        },
    )


@unittest.skipUnless(CAN_SIGN, "signing in the tests needs the cryptography package")
class UpdateTestCase(unittest.TestCase):
    def setUp(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        self.key = Ed25519PrivateKey.generate()
        raw = self.key.public_key().public_bytes_raw()
        self.key_id = signing.key_id(raw)
        trusted = mock.patch.dict(release.KEYS, {self.key_id: base64.b64encode(raw).decode()})
        trusted.start()
        self.addCleanup(trusted.stop)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.tmp = Path(folder.name)
        self.installed = self.tmp / "Campanile"  # the laptop's Campanile, version 0.1.0
        program(self.installed, "0.1.0")
        write(
            self.installed,
            {"data/campanile.db": "posts", "data/maps/a.pmtiles": "map", "tools/k/kiwix-serve": ""},
        )
        self.stick = self.tmp / "stick"
        self.signed(self.stick / "Campanile", "0.2.0")

    def signed(self, folder: Path, version: str) -> None:
        program(folder, version)
        body = {"version": version, "files": release.manifest(folder)}
        signature = base64.b64encode(self.key.sign(release.message(body))).decode()
        signed = {"format": release.FORMAT, "release": body, "key": self.key_id}
        write(folder, {release.SIGNATURE: json.dumps({**signed, "signature": signature})})

    def stage(self, source=None):
        return update.stage(
            source or self.stick / "Campanile", self.installed / update.STAGING, "0.1.0"
        )


class TestTopNames(unittest.TestCase):
    # What 0.1.0 copies from a stick: names at the top of the folder, and everything under them.
    SHIPPED_0_1_0 = frozenset({
        "campanile", "raspberry", "scripts", "docs", "README.md", "README.it.md", "LICENSE",
        "SECURITY.md", "CONTRIBUTING.md", "ROADMAP.md", "pyproject.toml",
        "Avvia Campanile (Windows).bat", "Avvia Campanile (Mac).command",
    })  # fmt: skip

    def test_a_new_version_adds_or_renames_nothing_at_the_top(self):
        # A Campanile in the field copies an update with its own list: a new name would never
        # arrive, and the signature check would refuse the whole update.
        self.assertLessEqual(set(copying.PROGRAM), self.SHIPPED_0_1_0)


class TestStage(UpdateTestCase):
    def test_the_program_is_found_on_the_stick(self):
        self.assertEqual(update.find_program(self.stick), self.stick / "Campanile")
        unzipped = self.tmp / "other"
        self.signed(unzipped / "campanile-0.2.0", "0.2.0")
        self.assertEqual(update.find_program(unzipped), unzipped / "campanile-0.2.0")
        self.signed(unzipped / "campanile-0.3.0", "0.3.0")
        self.assertIsNone(update.find_program(unzipped))  # two: which one? none
        self.assertIsNone(update.find_program(self.tmp / "empty"))

    def test_a_newer_signed_version_is_copied_then_checked_where_it_will_run(self):
        folder, version = self.stage()
        self.assertEqual(version, "0.2.0")
        self.assertEqual(folder, self.installed / update.STAGING / copying.FOLDER)
        self.assertEqual(release.check(folder), "0.2.0")
        self.assertIn("0.2.0", (folder / copying.README).read_text(encoding="utf-8"))

    def test_unsigned_changed_or_older_is_refused_and_nothing_stays(self):
        (self.stick / "Campanile" / "README.md").write_text("changed", encoding="utf-8")
        with self.assertRaises(release.ReleaseError) as e:
            self.stage()
        self.assertEqual(e.exception.args[0], "release_files_differ")
        self.assertFalse((self.installed / update.STAGING / copying.FOLDER).exists())
        self.signed(self.stick / "Campanile", "0.1.0")
        with self.assertRaises(release.ReleaseError) as e:
            self.stage()
        self.assertEqual(e.exception.args[0], "release_not_newer")


class PowerCut(BaseException):
    """The power goes: nothing of ours may catch it."""


class TestApply(UpdateTestCase):
    def new(self) -> Path:
        return self.tmp / "Campanile 0.2.0"

    def assert_finished(self):
        new = self.new()
        self.assertEqual((new / "data" / "campanile.db").read_text(encoding="utf-8"), "posts")
        self.assertTrue((new / "tools" / "k" / "kiwix-serve").is_file())
        self.assertFalse((self.installed / "data").exists())
        self.assertFalse((self.installed / "tools").exists())
        self.assertFalse((self.installed / update.STAGING).exists())
        self.assertFalse((new / update.FROM).exists())
        self.assertEqual(release.check(new), "0.2.0")

    def test_data_and_tools_move_into_the_new_folder(self):
        self.stage()
        self.assertEqual(update.resume(self.installed, "0.1.0"), self.new())
        self.assert_finished()
        self.assertEqual(update.resume(self.installed, "0.1.0"), self.new())  # hands over again

    def test_a_power_cut_at_any_step_is_finished_at_the_next_start(self):
        steps = [("replace", update.FROM), ("replace", update.MOVED), ("rename", "Campanile 0.2.0")]
        steps += [("rename", name) for name in update.CARRIED]
        for kind, at in steps:
            with self.subTest(power_cut_at=at):
                self.setUp()
                self.stage()
                real = getattr(os if kind == "replace" else Path, kind)

                def cut(source, target, real=real, at=at):
                    if Path(target).name == at:
                        raise PowerCut()
                    return real(source, target)

                power = mock.patch.object(os if kind == "replace" else Path, kind, cut)
                with power, self.assertRaises(PowerCut):
                    update.resume(self.installed, "0.1.0")
                self.assertEqual(update.resume(self.installed, "0.1.0"), self.new())
                self.assert_finished()

    def test_the_new_folder_opened_first_finishes_the_move_itself(self):
        self.stage()
        rename = Path.rename

        def cut(source, target):
            if Path(target).name == "data":
                raise PowerCut()
            return rename(source, target)

        with mock.patch.object(Path, "rename", cut), self.assertRaises(PowerCut):
            update.resume(self.installed, "0.1.0")
        update.adopt(self.new())
        self.assert_finished()

    def test_a_folder_that_was_never_committed_takes_nothing(self):
        self.stage()
        orphan = self.tmp / "Campanile 9.9.9"
        program(orphan, "9.9.9")
        (orphan / update.FROM).write_text(self.installed.name, encoding="utf-8")
        with self.assertRaises(update.UpdateError) as e:
            update.adopt(orphan)
        self.assertEqual(e.exception.args, ("update_unfinished", self.installed.name))
        self.assertTrue((self.installed / "data" / "campanile.db").is_file())

    def test_never_starts_empty_when_the_new_folder_is_gone(self):
        self.stage()
        update.resume(self.installed, "0.1.0")
        shutil.rmtree(self.new())
        with self.assertRaises(update.UpdateError) as e:
            update.resume(self.installed, "0.1.0")
        self.assertEqual(e.exception.args, ("update_folder_missing", "Campanile 0.2.0"))

    def test_data_in_both_folders_is_never_merged(self):
        self.stage()
        update.resume(self.installed, "0.1.0")
        write(self.installed, {"data/campanile.db": "other posts"})
        with self.assertRaises(update.UpdateError) as e:
            update.resume(self.installed, "0.1.0")
        self.assertEqual(e.exception.args[0], "update_data_twice")
        self.assertEqual((self.new() / "data" / "campanile.db").read_text("utf-8"), "posts")

    def test_the_stick_changing_after_the_check_changes_nothing(self):
        self.stage()
        (self.stick / "Campanile" / "README.md").write_text("swapped later", encoding="utf-8")
        new = update.resume(self.installed, "0.1.0")
        self.assertEqual((new / "README.md").read_text(encoding="utf-8"), "Campanile")

    def test_a_prepared_copy_changed_before_the_start_is_refused(self):
        folder, _ = self.stage()
        (folder / "campanile" / "launch.py").write_text("steal()", encoding="utf-8")
        with self.assertRaises(release.ReleaseError):
            update.resume(self.installed, "0.1.0")
        self.assertTrue((self.installed / "data" / "campanile.db").is_file())

    def test_changed_after_the_point_of_no_return_is_undone_before_anything_moves(self):
        folder, _ = self.stage()
        replace = os.replace

        def cut(source, target):
            replace(source, target)
            if Path(target).name == update.MOVED:
                raise PowerCut()

        with mock.patch.object(os, "replace", cut), self.assertRaises(PowerCut):
            update.resume(self.installed, "0.1.0")
        (folder / "campanile" / "launch.py").write_text("steal()", encoding="utf-8")
        with self.assertRaises(release.ReleaseError):
            update.resume(self.installed, "0.1.0")
        self.assertFalse((self.installed / update.MOVED).exists())
        self.assertTrue((self.installed / "data" / "campanile.db").is_file())

    def test_the_note_names_only_a_folder_next_door(self):
        for name in ("", "..", "../elsewhere", "/etc"):
            (self.installed / update.MOVED).write_text(name, encoding="utf-8")
            self.assertIsNone(update.resume(self.installed, "0.1.0"), name)


class TestLaptopStart(UpdateTestCase):
    def setUp(self):
        super().setUp()
        italian = mock.patch.object(launch, "LANG", "it")  # the words checked below
        italian.start()
        self.addCleanup(italian.stop)

    def start(self):
        """launch.main() in the old folder, up to the hand-over or the refusal."""
        out = io.BytesIO()
        console = io.TextIOWrapper(out, encoding="utf-8")  # main() sets line buffering
        with contextlib.ExitStack() as stack:
            stack.enter_context(
                mock.patch.object(launch.server, "HERE", self.installed / "campanile")
            )
            call = stack.enter_context(mock.patch.object(launch.subprocess, "call", return_value=0))
            server = stack.enter_context(mock.patch.object(launch.server, "main"))
            stack.enter_context(contextlib.redirect_stdout(console))
            code = launch.main()
            console.flush()
        return code, call, server, out.getvalue().decode()

    def test_at_start_the_update_is_applied_and_handed_over(self):
        self.stage()
        code, call, server, _ = self.start()
        new_launcher = self.tmp / "Campanile 0.2.0" / "campanile" / "launch.py"
        self.assertEqual(code, 0)
        call.assert_called_once_with([sys.executable, str(new_launcher)])
        server.assert_not_called()

    def test_a_computer_set_to_the_united_states_or_canada_starts_with_911(self):
        for region, wanted in (("US", True), ("CA", True), ("IT", False), ("", False)):
            with mock.patch.object(launch.messages, "computer_region", return_value=region):
                args = " ".join(launch.server_args())
            self.assertEqual("--emergency-number 911" in args, wanted, region)

    def test_an_english_computer_reads_english(self):
        self.stage()
        with mock.patch.object(launch, "LANG", "en"):
            code, *_, said = self.start()
        self.assertEqual(code, 0)
        self.assertIn('Campanile updated: starting from the folder "Campanile 0.2.0"', said)

    def test_a_locked_file_stops_everything_and_the_next_start_finishes(self):
        self.stage()
        rename = Path.rename

        def locked(source, target):
            if Path(target).name == "tools":
                raise PermissionError("in use")
            return rename(source, target)

        with mock.patch.object(Path, "rename", locked):
            code, call, server, said = self.start()
        self.assertEqual(code, 1)
        self.assertIn("Niente e' perso", said)
        call.assert_not_called()
        server.assert_not_called()  # nothing started, so nothing started empty
        self.assertFalse((self.installed / "data").exists())
        code, call, _, _ = self.start()
        self.assertEqual(code, 0)
        self.assertTrue((self.tmp / "Campanile 0.2.0" / "tools" / "k" / "kiwix-serve").is_file())

    def test_the_new_folder_gone_stops_and_says_where_the_data_is(self):
        self.stage()
        self.start()
        shutil.rmtree(self.tmp / "Campanile 0.2.0")
        code, _, server, said = self.start()
        self.assertEqual(code, 1)
        self.assertIn('"Campanile 0.2.0"', said)
        server.assert_not_called()
        self.assertFalse((self.installed / "data").exists())  # no empty database here

    def test_every_refusal_has_its_words(self):
        source = Path(update.__file__).read_text(encoding="utf-8")
        raised = set(re.findall(r'UpdateError\(\s*"(\w+)"', source))
        self.assertEqual(raised - {"update_folder_exists"}, set(launch.STOPPED))
        for key in raised:  # and words for the window, or it would crash just when it matters
            self.assertIn(key, launch.messages.WINDOW, key)

    def test_a_tampered_prepared_copy_is_thrown_away_and_the_old_version_starts(self):
        folder, _ = self.stage()
        (folder / "README.md").write_text("changed", encoding="utf-8")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertIsNone(launch.updated(self.installed))
        self.assertIn("scartato", out.getvalue())
        self.assertFalse((self.installed / update.STAGING).exists())
        self.assertTrue((self.installed / "data" / "campanile.db").is_file())


class TestSetupPage(UpdateTestCase):
    def test_the_setup_job_prepares_the_update(self):
        prep = Preparation(self.installed / "data", self.installed / "tools", version="0.1.0")
        self.assertTrue(prep.start_update(copying.Drive(str(self.stick), "S", "exfat")))
        prep.wait(30)
        job = prep.state()["job"]
        self.assertEqual(
            (job["error"], job["step"], job["detail"]), (None, "update_ready", "0.2.0")
        )

    def test_the_setup_job_names_the_refusal(self):
        self.signed(self.stick / "Campanile", "0.1.0")
        prep = Preparation(self.installed / "data", self.installed / "tools", version="0.1.0")
        prep.start_update(copying.Drive(str(self.stick), "S", "exfat"))
        prep.wait(30)
        self.assertEqual(prep.state()["job"]["error"], "release_not_newer")
        prep.start_update(copying.Drive(str(self.tmp / "empty"), "E", "exfat"))
        prep.wait(30)
        self.assertEqual(prep.state()["job"]["error"], "update_no_program")


class TestRaspberry(UpdateTestCase):
    def run_update(self, stick):
        place = self.tmp / "opt"
        place.mkdir(exist_ok=True)
        ran = []

        def installer(args):
            ran.append((args, Path(args[1]).read_text(encoding="utf-8")))
            return 0

        options = self.tmp / "install-options"
        options.write_text("--ssid\nCampanile Piazza\n--country\nIT\n--no-hotspot\n", "utf-8")
        with contextlib.ExitStack() as stack:
            stack.enter_context(
                mock.patch.object(update.os, "geteuid", return_value=0, create=True)
            )
            stack.enter_context(mock.patch.object(update, "INSTALL_OPTIONS", options))
            stack.enter_context(mock.patch.object(update, "PLACE", place))
            stack.enter_context(mock.patch.object(update.subprocess, "call", installer))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            code = update.main([str(stick)])
        return code, ran

    def test_the_signed_installer_runs_with_last_time_choices(self):
        code, ran = self.run_update(self.stick)
        self.assertEqual(code, 0)
        [(args, script)] = ran
        self.assertEqual(args[0], "bash")
        self.assertEqual(
            args[2:], ["--ssid", "Campanile Piazza", "--country", "IT", "--no-hotspot"]
        )
        self.assertEqual(script, "echo installing\n")  # the checked copy, not the stick

    def test_an_unsigned_stick_installs_nothing(self):
        (self.stick / "Campanile" / "raspberry" / "install.sh").write_text("evil", "utf-8")
        code, ran = self.run_update(self.stick)
        self.assertEqual((code, ran), (1, []))


if __name__ == "__main__":
    unittest.main()
