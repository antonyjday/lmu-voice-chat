"""Push-to-talk voice chat for Le Mans Ultimate.

Hold the push-to-talk button, speak, release: the speech is transcribed locally
with Whisper and typed into LMU's chat box. Runs in the system tray; right-click
the icon for settings. The options below are one-off commands for the console.
"""
import argparse
import ctypes
import sys
import threading
import time
from pathlib import Path

import sounddevice as sd

import engine
import lmu_data
import ptt

LOG_FILE = Path(__file__).with_name("lmu_chat.log")
LENGTH_TEST_CHARS = 300  # well past rFactor 2's rumoured 128
ERROR_ALREADY_EXISTS = 183


class Tee:
    """Writes to the console (if there is one) and the log file, with a time on each line."""

    def __init__(self, console, log):
        self.console, self.log = console, log
        self.line_start = True

    def write(self, text: str):
        if self.console:
            self.console.write(text)
            self.console.flush()
        for line in text.splitlines(keepends=True):
            if self.line_start:
                self.log.write(time.strftime("%H:%M:%S "))
            self.log.write(line)
            self.line_start = line.endswith("\n")
        self.log.flush()

    def flush(self):
        pass


def start_log():
    log = open(LOG_FILE, "w", encoding="utf-8")
    sys.stdout = Tee(sys.stdout, log)  # sys.stdout is None under pythonw.exe
    sys.stderr = Tee(sys.stderr, log)


_instance_mutex = None


def already_running() -> bool:
    """True if another copy is running: two would type every message twice."""
    global _instance_mutex
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _instance_mutex = kernel32.CreateMutexW(None, False, "Local\\LMUVoiceChat")
    return ctypes.get_last_error() == ERROR_ALREADY_EXISTS


def message_box(text: str):
    ctypes.windll.user32.MessageBoxW(None, text, "LMU Voice Chat", 0x40)  # MB_ICONINFORMATION


def length_ruler(length: int) -> str:
    """Dots with a count every 10 characters: the number ending at position n is n."""
    return "".join(str(n).rjust(10, ".") for n in range(10, length + 1, 10))


def run_length_test(config: dict, binding: ptt.Binding, any_window: bool):
    # Runs once: a second press would tap open_key, which is often Enter and would send the ruler.
    ruler = length_ruler(LENGTH_TEST_CHARS)
    released = threading.Event()
    ptt.PushToTalk(lambda: None, released.set).set_binding(binding)
    print(f"Chat length test. Switch to LMU, then press and release {binding}. It types a")
    print(f"{len(ruler)}-character ruler into chat WITHOUT sending it. The last number showing,")
    print("plus any dots after it, is the limit. Afterwards delete the text before closing")
    print("the chat box, or Enter will send it. Ctrl+C to quit.")
    try:
        while not released.wait(0.5):  # short waits so Ctrl+C works
            pass
    except KeyboardInterrupt:
        return
    if engine.type_into_chat(config["chat"], ruler, any_window, submit=False):
        print("Typed the ruler. Delete it from the chat box before closing it.")


def list_drivers():
    try:
        session = lmu_data.read_session()
    except lmu_data.LayoutMismatch as e:
        print(f"LMU's shared memory doesn't match the expected layout ({e}).")
        print("A game update may have changed it; lmu_data.py needs updating.")
        return
    if session is None:
        print("LMU's shared memory isn't available. Is the game running?")
        return
    print(f"{session.track or '(no track loaded)'}: {len(session.drivers)} drivers")
    for d in session.drivers:
        if d.is_player:
            print(f"  you: {d.name}")
    for name in lmu_data.names_nearest_first(session):
        print(f"  {name}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, default=engine.DEFAULT_CONFIG)
    parser.add_argument("--console", action="store_true", help="run the app with this console showing the log")
    parser.add_argument("--any-window", action="store_true", help="type into any window (for testing in Notepad)")
    parser.add_argument("--bind", action="store_true", help="press a key or wheel button to set push-to-talk")
    parser.add_argument("--list-mics", action="store_true", help="list microphones")
    parser.add_argument("--list-controllers", action="store_true", help="list wheels, button boxes and joysticks")
    parser.add_argument("--list-drivers", action="store_true", help="show the driver names read from LMU, nearest first")
    parser.add_argument("--length-test", action="store_true", help="type a numbered ruler into chat to find its length limit")
    args = parser.parse_args()

    if args.list_drivers:
        list_drivers()
        return
    if args.list_mics:
        for i, dev in enumerate(sd.query_devices()):
            if dev["max_input_channels"] > 0:
                print(f"{i:3}  {dev['name']}")
        return
    if args.list_controllers:
        controllers = ptt.list_controllers()
        for name, buttons in controllers:
            print(f"{name}  ({buttons} buttons)")
        if not controllers:
            print("No controllers found.")
        return
    if args.bind:
        print("Press the key or wheel button to use for push-to-talk (30 s, Esc cancels)...")
        time.sleep(0.5)  # let go of Enter from launching the command
        binding = ptt.PushToTalk(lambda: None, lambda: None).capture()
        if binding is None:
            print("Nothing pressed; binding unchanged.")
            return
        engine.save_binding(args.config, binding)
        print(f'Saved ptt_button = "{binding}" to {args.config}')
        return
    if args.length_test:
        config = engine.load_config(args.config)
        run_length_test(config, ptt.parse_binding(config["ptt_button"]), args.any_window)
        return

    if already_running():
        message_box("LMU Voice Chat is already running. Look for its icon in the system tray.")
        return
    start_log()
    import tray  # loads pystray and Pillow only when needed
    tray.Tray(args.config, args.any_window, LOG_FILE).run()


if __name__ == "__main__":
    main()
