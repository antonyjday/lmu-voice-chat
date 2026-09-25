"""The tray icon and its right-click menu."""
import subprocess
import sys
import threading
import time
import winreg
from pathlib import Path

import pystray
from PIL import Image, ImageDraw
from pystray import Menu, MenuItem as Item

import engine

APP_NAME = "LMU Voice Chat"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
SCRIPT = Path(__file__).with_name("lmu_chat.py")

STATE_COLOURS = {
    "loading": (128, 128, 128),
    "ready": (46, 125, 50),
    "recording": (211, 47, 47),
    "working": (245, 166, 35),
    "paused": (90, 90, 90),
    "error": (40, 40, 40),
}
STATE_TEXT = {
    "loading": "Loading speech model...",
    "ready": "Ready: hold {binding} to talk",
    "recording": "Recording...",
    "working": "Transcribing...",
    "paused": "Paused",
    "error": "Not working: {problem}",
}
MODELS = [("tiny.en", "Tiny (fastest)"), ("base.en", "Base"), ("small.en", "Small (recommended)"),
          ("medium.en", "Medium (most accurate, slowest)")]
CHAT_KEYS = [("auto", "LMU's chat key (automatic)"), ("enter", "Enter"), ("t", "T"),
             ("", "None: I open chat myself")]


def icon_image(state: str) -> Image.Image:
    """A coloured disc with a white microphone; the colour shows the state."""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((0, 0, 63, 63), fill=STATE_COLOURS[state])
    white = (255, 255, 255)
    if state == "error":  # an exclamation mark instead of the microphone
        d.rounded_rectangle((27, 10, 37, 40), radius=4, fill=(255, 193, 7))
        d.ellipse((27, 45, 37, 55), fill=(255, 193, 7))
        return img
    d.rounded_rectangle((24, 10, 40, 38), radius=8, fill=white)  # capsule
    d.arc((17, 20, 47, 46), start=0, end=180, fill=white, width=4)  # holder
    d.line((32, 46, 32, 53), fill=white, width=4)  # stand
    d.line((23, 54, 41, 54), fill=white, width=4)  # base
    if state == "paused":
        d.line((12, 12, 52, 52), fill=white, width=5)
    return img


def shorten(text: str, width: int = 60) -> str:
    return text if len(text) <= width else text[:width - 3].rstrip() + "..."


def autostart_command() -> str:
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    return f'"{pythonw if pythonw.exists() else sys.executable}" "{SCRIPT}"'


def autostart_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            return winreg.QueryValueEx(key, APP_NAME)[0] == autostart_command()
    except OSError:
        return False


def set_autostart(enabled: bool):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, autostart_command())
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass


class Tray:
    def __init__(self, config_path: Path, any_window: bool, log_file: Path):
        self.config_path = config_path
        self.log_file = log_file
        self.created_config = engine.ensure_config(config_path)
        self.config_mtime = None
        self.settings_error = None  # why config.toml couldn't be applied
        self.reload_lock = threading.Lock()  # reloads come from the menu, the watcher and capture
        self.refresh_lock = threading.Lock()
        self.shown = None  # what the icon and menu last showed, to skip redundant updates
        self.capturing = False
        self.mics = engine.input_devices()
        self.app = engine.VoiceChat(any_window, on_change=self.refresh, on_alert=self.notify)
        self.icon = pystray.Icon(APP_NAME, icon_image("loading"), APP_NAME, menu=self.menu())

    def run(self):
        self.icon.run(setup=self.start)

    def start(self, icon):
        icon.visible = True
        self.reload()
        threading.Thread(target=self.watch_config, daemon=True).start()
        if self.created_config:
            self.notify(f"{APP_NAME} is running. Right-click this icon to set your push-to-talk"
                        f" button ({self.binding_text()} for now).")

    # ---- state shown in the icon and menu ---------------------------------------

    def binding_text(self) -> str:
        binding = self.app.ptt.binding
        return binding.describe() if binding else "nothing"

    def status_text(self) -> str:
        problem = self.settings_error or self.app.model_error or "see the log"
        return STATE_TEXT[self.app.state].format(binding=self.binding_text(), problem=problem)

    def refresh(self):
        icon = getattr(self, "icon", None)
        if icon is None:  # the engine reported something before the icon exists
            return
        with self.refresh_lock:  # called from the push-to-talk, worker and menu threads
            state, status = self.app.state, self.status_text()
            shown = (state, status, self.settings_error, self.app.ptt_status, self.app.last_text, id(self.app.config),
                     autostart_enabled())
            if shown == self.shown:
                return
            if self.shown is None or state != self.shown[0]:
                icon.icon = icon_image(state)
            icon.title = f"{APP_NAME}: {status}"[:127]
            icon.update_menu()  # rebuilds the whole menu, so only when something in it changed
            self.shown = shown

    def notify(self, message: str):
        print(message)
        try:
            self.icon.remove_notification()
            self.icon.notify(message, APP_NAME)
        except Exception as e:  # the icon may not be visible yet
            print(f"  (couldn't show notification: {e!r})")

    # ---- settings ---------------------------------------------------------------

    def reload(self, only_if_changed: bool = False):
        """Loads config.toml and applies it. A problem is shown, never raised: this runs
        on the menu, watcher and capture threads, and an exception would end them."""
        with self.reload_lock:
            try:
                mtime = self.config_path.stat().st_mtime
                if only_if_changed and mtime == self.config_mtime:
                    return
                self.config_mtime = mtime
                self.app.apply(engine.load_config(self.config_path))
                self.settings_error = None
            except Exception as e:
                self.settings_error = str(e)
                self.notify(f"Settings problem: {e}")
        self.refresh()

    def watch_config(self):
        """Applies edits made to config.toml in a text editor."""
        while True:
            time.sleep(1)
            try:
                mtime = self.config_path.stat().st_mtime
            except OSError:
                continue
            if mtime != self.config_mtime:
                self.reload(only_if_changed=True)  # re-checked under the lock: a menu change may have just reloaded

    def set_option(self, key: str, value, table: str | None = None):
        engine.save_setting(self.config_path, key, value, table)
        self.reload()

    def option(self, table: str, key: str):
        return (self.app.config or {}).get(table, {}).get(key)

    def toggle(self, table: str, key: str):
        return lambda: self.set_option(key, not self.option(table, key), table)

    def checked(self, table: str, key: str, value=True):
        return lambda item: self.option(table, key) == value

    def radio(self, table: str, key: str, choices: list[tuple[str, str]]) -> list[Item]:
        current = self.option(table, key)
        if current is not None and current not in [value for value, _ in choices]:
            choices = [(current, f"{current} (from settings)")] + choices
        return [Item(label, (lambda v=value: self.set_option(key, v, table)),
                     checked=self.checked(table, key, value), radio=True)
                for value, label in choices]

    # ---- menu actions -----------------------------------------------------------

    def set_ptt(self):
        if not self.capturing:  # a second click while waiting would start a competing capture
            self.capturing = True
            threading.Thread(target=self._capture_ptt, daemon=True).start()

    def _capture_ptt(self):
        self.notify("Press the key or wheel button to use for push-to-talk (Esc cancels).")
        try:
            binding = self.app.ptt.capture(timeout=30)
        finally:
            self.capturing = False
        if binding is None:
            self.notify(f"Push-to-talk unchanged: {self.binding_text()}.")
            return
        engine.save_binding(self.config_path, binding)
        self.reload()
        self.notify(f"Push-to-talk set to {binding.describe()}.")

    def toggle_pause(self):
        self.app.ptt.paused = not self.app.ptt.paused
        self.refresh()

    def toggle_autostart(self):
        set_autostart(not autostart_enabled())
        self.refresh()

    def edit_settings(self):
        subprocess.Popen(["notepad.exe", str(self.config_path)])

    def open_log(self):
        subprocess.Popen(["notepad.exe", str(self.log_file)])

    def quit(self):
        self.app.close()
        self.icon.stop()

    def menu(self) -> Menu:
        def mic_items():  # the list is read at startup: the audio library doesn't see later changes
            return self.radio("speech", "microphone", [("", "Windows default")] + [(m, m) for m in self.mics])

        return Menu(
            Item(lambda item: self.status_text(), None, enabled=False),
            Item(lambda item: "Settings problem: " + shorten(self.settings_error or ""), None, enabled=False,
                 visible=lambda item: bool(self.settings_error)),
            Item(lambda item: self.app.ptt_status, None, enabled=False,
                 visible=lambda item: bool(self.app.ptt_status)),
            Item(lambda item: "Last: " + shorten(self.app.last_text), None, enabled=False,
                 visible=lambda item: bool(self.app.last_text)),
            Menu.SEPARATOR,
            Item("Set push-to-talk button...", self.set_ptt),
            Item("Pause", self.toggle_pause, checked=lambda item: self.app.ptt.paused),
            Menu.SEPARATOR,
            Item("Send messages automatically", self.toggle("chat", "auto_send"),
                 checked=self.checked("chat", "auto_send")),
            Item("Add driver names to vocabulary", self.toggle("speech", "driver_names"),
                 checked=self.checked("speech", "driver_names")),
            Item("Beep when recording", self.toggle("speech", "beep"), checked=self.checked("speech", "beep")),
            Item("Filter profanity", self.toggle("profanity", "filter"), checked=self.checked("profanity", "filter")),
            Item("Microphone", Menu(mic_items)),
            Item("Speech model", Menu(lambda: self.radio("speech", "model", MODELS))),
            Item("Chat key", Menu(lambda: self.radio("chat", "open_key", CHAT_KEYS))),
            Menu.SEPARATOR,
            Item("Start with Windows", self.toggle_autostart, checked=lambda item: autostart_enabled()),
            Item("Edit settings file", self.edit_settings),
            Item("Open log", self.open_log),
            Menu.SEPARATOR,
            Item("Quit", self.quit),
        )
