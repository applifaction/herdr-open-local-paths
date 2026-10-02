"""Black-box desktop activation tests; GI/AT-SPI, procfs and X11 are faked.

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
sys.path.insert(0, str(ROOT / "src"))
import libreoffice_focus as lof

FAKE_TOOL = r'''#!/usr/bin/python3
import json, os, re, sys
from pathlib import Path
state_path = Path(os.environ["TEST_DESKTOP_STATE"])
state = json.loads(state_path.read_text())
name, args = Path(sys.argv[0]).name, sys.argv[1:]
if name == "xdg-open":
    if "open_target_after" in state:
        state["open_target"] = state["open_target_after"]
    if "windows_after" in state:
        state["windows"] = state["windows_after"]
    state["after_open"] = True
    state_path.write_text(json.dumps(state))
    sys.exit(0)
if name == "xdg-mime":
    print("text/csv" if args[1] == "filetype" else state["desktop_id"])
elif name == "xdotool":
    if args[0] == "search":
        if state.get("search_error_before") and not state.get("after_open"):
            sys.exit(2)
        windows = state["windows"]
        if "--pid" in args and args[args.index("--pid")+1] != str(os.getppid()):
            sys.exit(2)
        if "--name" in args:
            pattern = args[args.index("--name")+1]
            windows = {k:v for k,v in windows.items() if re.search(pattern, v)}
        print("\n".join(windows))
    elif args[0] == "getwindowname":
        print(state["windows"][args[1]])
    elif args[0] == "getwindowpid":
        if args[1] not in state["windows"]: sys.exit(2)
        print(os.getppid())
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
_target_handle = open(state["target"], "rb") if state.get("open_target", True) else None
class Node:
    def __init__(self, role, name, children=()):
        self.role, self.name, self.children = role, name, list(children)
    def get_name(self): return self.name
    def get_role_name(self): return self.role
    def get_process_id(self): return os.getpid()
    def get_child_count(self): return len(self.children)
    def get_child_at_index(self, i): return self.children[i]
frames = [Node("frame", f["title"], [
    Node("document spreadsheet", uri + " - LibreOffice Spreadsheets")
    for uri in f.get("uris", [f.get("uri", "unknown")])
]) for f in state["frames"]]
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
        self.plugin_state = self.directory / "plugin-state"
        self.plugin_state.mkdir()

    def remember_target_window(self, window_id="111"):
        cache = self.plugin_state / "libreoffice-window-map.json"
        cache.write_text(json.dumps({
            "version": 1, "entries": {str(self.target.resolve()): window_id}
        }))

    def run_open(self, frames=None, windows=None, overrides=None, desktop_id="libreoffice-calc.desktop",
                 a11y_error=False, open_target=True, open_target_after=None, windows_after=None,
                 search_error_before=False):
        if frames is None:
            frames = [{"title": self.title, "uri": self.target.as_uri()}]
        if windows is None:
            windows = {"111": self.title}
        state = {"windows": windows, "frames": frames, "desktop_id": desktop_id,
                 "a11y_error": a11y_error, "target": str(self.target),
                 "open_target": open_target, "search_error_before": search_error_before}
        if open_target_after is not None:
            state["open_target_after"] = open_target_after
        if windows_after is not None:
            state["windows_after"] = windows_after
        self.state.write_text(json.dumps(state))
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("HERDR_", "LOCAL_PATH_ACTIONS_", "WSL_")) and k != "WAYLAND_DISPLAY"}
        env.update({"PATH": str(self.bin), "DISPLAY": ":test", "XDG_SESSION_TYPE": "x11",
                    "XDG_DATA_HOME": str(self.data), "XDG_DATA_DIRS": str(self.directory / "empty"),
                    "PYTHONPATH": str(self.directory / "modules"),
                    "HERDR_PLUGIN_CLICKED_URL": self.target.as_uri(), "HERDR_PLUGIN_CONTEXT_JSON": "{}",
                    "HERDR_PLUGIN_STATE_DIR": str(self.plugin_state),
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

    def test_conflicting_document_uris_fail_closed(self):
        self.assert_no_activation(self.run_open(frames=[{
            "title": self.title, "uris": [self.target.as_uri(), self.other.as_uri()]
        }]))

    def test_invalid_file_uri_does_not_fall_back_to_process_evidence(self):
        self.assert_no_activation(self.run_open(frames=[{
            "title": self.title, "uri": "file://remote.invalid/report.csv"
        }]))

    def test_malformed_percent_escapes_are_not_authoritative_paths(self):
        literal = self.directory / "bad%ZZ.csv"
        literal.write_text("document\n")
        malformed = literal.as_uri().replace("%25ZZ", "%ZZ") + " - LibreOffice Spreadsheets"
        self.assertIsNone(lof.document_path(malformed))
        self.assertIsNone(lof.document_path("file:///tmp/bad%FF.csv - LibreOffice Spreadsheets"))

    def test_filename_prefix_is_not_document_identity(self):
        wrong_title = self.target.name + " - backup.csv — LibreOffice Calc"
        self.assert_no_activation(self.run_open(frames=[{"title": wrong_title, "uri": self.other.as_uri()}],
                                               windows={"111": wrong_title}))

    def test_ambiguous_accessible_frames_are_not_activated(self):
        frames = [{"title": self.title, "uri": self.target.as_uri()}, {"title": self.title, "uri": self.other.as_uri()}]
        self.assert_no_activation(self.run_open(frames=frames))

    def test_uri_absent_fallback_rejects_another_modified_same_basename_frame(self):
        frames = [
            {"title": self.title, "uri": "unknown"},
            {"title": self.target.name + " * — LibreOffice Calc", "uri": "unknown"},
        ]
        self.assert_no_activation(self.run_open(frames=frames))

    def test_ambiguous_native_windows_are_not_activated(self):
        self.assert_no_activation(self.run_open(windows={"111": self.title, "222": self.title}))

    def test_cached_window_fallback_activates_when_document_uri_is_absent(self):
        self.remember_target_window()
        result = self.run_open(frames=[{"title": self.title, "uri": "unknown"}])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.log.exists(), result.stderr)
        self.assertEqual(json.loads(self.log.read_text()), ["windowactivate", "--sync", "111"])

    def test_uri_absent_without_exact_open_file_does_not_activate(self):
        self.remember_target_window()
        self.assert_no_activation(self.run_open(
            frames=[{"title": self.title, "uri": "unknown"}], open_target=False))

    def test_stale_cached_window_does_not_authorize_another_same_title_window(self):
        self.remember_target_window("222")
        self.assert_no_activation(self.run_open(
            frames=[{"title": self.title, "uri": "unknown"}], windows={"111": self.title}))

    def test_new_open_does_not_reuse_preexisting_same_title_window(self):
        self.assert_no_activation(self.run_open(
            frames=[{"title": self.title, "uri": "unknown"}],
            windows={"111": self.title}, open_target=False, open_target_after=True))

    def test_incomplete_pre_open_snapshot_disables_fallback(self):
        self.assert_no_activation(self.run_open(
            frames=[{"title": self.title, "uri": "unknown"}],
            open_target=True, search_error_before=True))

    def test_incomplete_snapshot_still_allows_authoritative_uri(self):
        result = self.run_open(search_error_before=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(self.log.read_text()), ["windowactivate", "--sync", "111"])

    def test_new_open_activates_only_the_new_same_title_window(self):
        result = self.run_open(
            frames=[{"title": self.title, "uri": "unknown"}],
            windows={"111": self.title}, open_target=False, open_target_after=True,
            windows_after={"111": self.title, "222": self.title})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(self.log.read_text()), ["windowactivate", "--sync", "222"])
        cache = json.loads((self.plugin_state / "libreoffice-window-map.json").read_text())
        self.assertEqual(cache["entries"][str(self.target.resolve())], "222")

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
