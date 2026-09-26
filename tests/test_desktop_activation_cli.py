"""Black-box desktop activation tests; GI/AT-SPI and X11 are external fakes.

The real plugin CLI and focus helper run. No real desktop application, D-Bus
connection, or focus request is made.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FAKE_TOOL = r'''#!/usr/bin/python3
import json, os, re, sys
from pathlib import Path
state = json.loads(Path(os.environ["TEST_DESKTOP_STATE"]).read_text())
name, args = Path(sys.argv[0]).name, sys.argv[1:]
if name == "xdg-open":
    sys.exit(0)
if name == "xdg-mime":
    print("text/csv" if args[1] == "filetype" else state["desktop_id"])
elif name == "xdotool":
    if args[0] == "search":
        windows = state["windows"]
        if "--name" in args:
            windows = {k:v for k,v in windows.items() if re.search(args[-1], v)}
            if "--pid" not in args or args[args.index("--pid")+1] != "123":
                sys.exit(2)
        print("\n".join(windows))
    elif args[0] == "getwindowname":
        print(state["windows"][args[1]])
    elif args[0] == "windowactivate":
        Path(os.environ["TEST_ACTIVATION_LOG"]).write_text(json.dumps(args))
    else:
        sys.exit(2)
else:
    sys.exit(2)
'''
FAKE_GI = r'''
import json, os
from pathlib import Path
from types import SimpleNamespace
state = json.loads(Path(os.environ["TEST_DESKTOP_STATE"]).read_text())
class Node:
    def __init__(self, role, name, children=()):
        self.role, self.name, self.children = role, name, list(children)
    def get_name(self): return self.name
    def get_role_name(self): return self.role
    def get_process_id(self): return 123
    def get_child_count(self): return len(self.children)
    def get_child_at_index(self, i): return self.children[i]
frames = [Node("frame", f["title"], [Node("document spreadsheet", f["uri"] + " - LibreOffice Spreadsheets")]) for f in state["frames"]]
desktop = Node("desktop frame", "", [Node("application", "soffice", frames)])
def get_desktop(i):
    if state.get("a11y_error"): raise RuntimeError("Unavailable accessibility bus")
    return desktop
Atspi = SimpleNamespace(set_timeout=lambda *a: None, get_desktop=get_desktop)
class File:
    @staticmethod
    def new_for_path(path): return File()
    def query_info(self, *args): return SimpleNamespace(get_content_type=lambda: "text/csv")
Gio = SimpleNamespace(File=File, FileQueryInfoFlags=SimpleNamespace(NONE=0),
    AppInfo=SimpleNamespace(get_default_for_type=lambda *a: SimpleNamespace(get_id=lambda: state["desktop_id"])))
'''


@unittest.skipUnless(sys.platform.startswith("linux"), "Linux desktop adapter")
class DesktopActivationCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="desktop-activation-test-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.bin = self.directory / "bin"
        self.bin.mkdir()
        for name in ("xdg-open", "xdg-mime", "xdotool"):
            tool = self.bin / name
            tool.write_text(FAKE_TOOL)
            tool.chmod(0o700)
        # This desktop entry also reproduces the rejected title-only implementation.
        self.data = self.directory / "data"
        (self.data / "applications").mkdir(parents=True)
        (self.data / "applications/libreoffice-calc.desktop").write_text(
            "[Desktop Entry]\nName=LibreOffice Calc\nStartupWMClass=libreoffice-calc\n")
        gi_dir = self.directory / "modules/gi/repository"
        gi_dir.mkdir(parents=True)
        (gi_dir.parent / "__init__.py").write_text("def require_version(*args): pass\n")
        (gi_dir / "__init__.py").write_text(FAKE_GI)
        self.target = self.directory / "Prüfung 01.csv"
        self.target.write_text("document\n")
        self.other = self.directory / "other/Prüfung 01.csv"
        self.other.parent.mkdir()
        self.other.write_text("other document\n")
        self.title = self.target.name + " — LibreOffice Calc"
        self.state = self.directory / "state.json"
        self.log = self.directory / "activation.json"

    def run_open(self, frames=None, windows=None, overrides=None, desktop_id="libreoffice-calc.desktop", a11y_error=False):
        if frames is None:
            frames = [{"title": self.title, "uri": self.target.as_uri()}]
        if windows is None:
            windows = {"111": self.title}
        self.state.write_text(json.dumps({"windows": windows, "frames": frames,
                                         "desktop_id": desktop_id, "a11y_error": a11y_error}))
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("HERDR_", "LOCAL_PATH_ACTIONS_", "WSL_")) and k != "WAYLAND_DISPLAY"}
        env.update({"PATH": str(self.bin), "DISPLAY": ":test", "XDG_SESSION_TYPE": "x11",
                    "XDG_DATA_HOME": str(self.data), "XDG_DATA_DIRS": str(self.directory / "empty"),
                    "PYTHONPATH": str(self.directory / "modules"),
                    "HERDR_PLUGIN_CLICKED_URL": self.target.as_uri(), "HERDR_PLUGIN_CONTEXT_JSON": "{}",
                    "TEST_DESKTOP_STATE": str(self.state), "TEST_ACTIVATION_LOG": str(self.log)})
        env.update(overrides or {})
        result = subprocess.run([sys.executable, str(ROOT / "src/local_path_actions.py"), "open"],
                                cwd=ROOT, env=env, capture_output=True, text=True, timeout=10)
        return result

    def assert_no_activation(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.log.exists(), "Must not guess the document/window identity")

    def test_authoritative_document_uri_is_activated(self):
        result = self.run_open()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.log.exists(), result.stderr)
        self.assertEqual(json.loads(self.log.read_text()), ["windowactivate", "--sync", "111"])

    def test_same_basename_in_other_directory_is_not_activated(self):
        self.assert_no_activation(self.run_open(frames=[{"title": self.title, "uri": self.other.as_uri()}]))

    def test_filename_prefix_is_not_document_identity(self):
        wrong_title = self.target.name + " - backup.csv — LibreOffice Calc"
        self.assert_no_activation(self.run_open(frames=[{"title": wrong_title, "uri": self.other.as_uri()}],
                                               windows={"111": wrong_title}))

    def test_ambiguous_accessible_frames_are_not_activated(self):
        frames = [{"title": self.title, "uri": self.target.as_uri()}, {"title": self.title, "uri": self.other.as_uri()}]
        self.assert_no_activation(self.run_open(frames=frames))

    def test_ambiguous_native_windows_are_not_activated(self):
        self.assert_no_activation(self.run_open(windows={"111": self.title, "222": self.title}))

    def test_absent_authoritative_uri_is_not_activated(self):
        self.assert_no_activation(self.run_open(frames=[{"title": self.title, "uri": "unknown"}]))

    def test_unavailable_accessibility_bus_does_not_guess(self):
        self.assert_no_activation(self.run_open(a11y_error=True))

    def test_other_default_application_is_not_overridden(self):
        self.assert_no_activation(self.run_open(desktop_id="org.gnome.TextEditor.desktop"))

    def test_wayland_does_not_trigger_x11_activation(self):
        self.assert_no_activation(self.run_open(overrides={"XDG_SESSION_TYPE": "wayland", "WAYLAND_DISPLAY": "wayland-test"}))

    def test_wsl_does_not_trigger_native_x11_activation(self):
        self.assert_no_activation(self.run_open(overrides={"WSL_DISTRO_NAME": "fixture"}))

    def test_dry_run_does_not_trigger_window_activation(self):
        result = self.run_open(overrides={"LOCAL_PATH_ACTIONS_DRY_RUN": "1"})
        self.assert_no_activation(result)
        self.assertEqual(json.loads(result.stdout)["command"], ["xdg-open", str(self.target)])

    def test_missing_xdotool_preserves_plain_open_behavior(self):
        (self.bin / "xdotool").unlink()
        self.assert_no_activation(self.run_open())

    def test_executable_never_reaches_activation(self):
        self.target.chmod(0o700)
        result = self.run_open()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertFalse(self.log.exists())


if __name__ == "__main__":
    unittest.main()
