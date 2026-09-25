"""Push-to-talk voice chat for Le Mans Ultimate.

Hold the push-to-talk button, speak, release: the speech is transcribed locally
with Whisper and typed into LMU's chat box.
"""
import argparse
import collections
import json
import os
import queue
import re
import shutil
import textwrap
import threading
import time
import tomllib
import winsound
from pathlib import Path

import numpy as np
import sounddevice as sd

import lmu_data
import inject
import ptt

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

SAMPLE_RATE = 16000
PREROLL_SECONDS = 0.3  # audio kept from just before the press, so the first word isn't clipped
DEFAULTS_FILE = Path(__file__).with_name("config.default.toml")  # shipped; never edited by users
DEFAULT_CONFIG = Path(__file__).with_name("config.toml")  # the user's own settings
MERGED_TABLES = ("chat", "speech")  # user settings override defaults key by key; other tables replace
LENGTH_TEST_CHARS = 300  # well past rFactor 2's rumoured 128
BETWEEN_MESSAGES_SECONDS = 0.3  # lets the chat box close before a split message's next part


def ensure_config(path: Path):
    if not path.exists():
        shutil.copyfile(DEFAULTS_FILE, path)
        print(f"Created {path.name} from {DEFAULTS_FILE.name}. Edit {path.name} to change settings.")


def load_config(path: Path) -> dict:
    """The defaults, overridden by the user's file, so settings added in later versions still work."""
    ensure_config(path)
    with open(DEFAULTS_FILE, "rb") as f:
        config = tomllib.load(f)
    with open(path, "rb") as f:
        user = tomllib.load(f)
    for key, value in user.items():
        config[key] = {**config.get(key, {}), **value} if key in MERGED_TABLES else value
    return config


def save_binding(path: Path, binding: ptt.Binding):
    ensure_config(path)
    text = path.read_text(encoding="utf-8")
    line = f"ptt_button = {json.dumps(str(binding))}"
    text, count = re.subn(r"(?m)^ptt_button\s*=.*$", lambda _: line, text)
    if not count:
        text = line + "\n" + text
    path.write_text(text, encoding="utf-8")


def find_microphone(setting: str):
    """Returns a device index for a number or name fragment, or None for the Windows default.

    Windows lists each microphone once per audio API, so take the first match.
    """
    if not setting:
        return None
    if setting.isdigit():
        return int(setting)
    for i, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] > 0 and setting.lower() in dev["name"].lower():
            return i
    raise SystemExit(f'No microphone matching "{setting}". See --list-mics.')


def beep(freq: int):
    threading.Thread(target=winsound.Beep, args=(freq, 60), daemon=True).start()


class Recorder:
    """Keeps the microphone open and collects audio between start() and stop()."""

    def __init__(self, device):
        self._lock = threading.Lock()
        self._chunks = []
        self._preroll = collections.deque()
        self._preroll_frames = 0
        self._recording = False
        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE, channels=1, dtype="float32", device=device, callback=self._callback
        )
        self._stream.start()

    def _callback(self, indata, frames, time_info, status):
        chunk = indata[:, 0].copy()
        with self._lock:
            if self._recording:
                self._chunks.append(chunk)
                return
            self._preroll.append(chunk)
            self._preroll_frames += len(chunk)
            while self._preroll_frames - len(self._preroll[0]) >= PREROLL_SECONDS * SAMPLE_RATE:
                self._preroll_frames -= len(self._preroll.popleft())

    def start(self):
        with self._lock:
            self._chunks = list(self._preroll)
            self._recording = True

    def stop(self) -> np.ndarray:
        with self._lock:
            self._recording = False
            chunks, self._chunks = self._chunks, []
        return np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)


def open_chat(chat: dict, any_window: bool) -> bool:
    """Presses the chat key: open_key, or LMU's own binding when it's "auto"."""
    key = chat["open_key"]
    if not key:
        return True
    if key.lower() == "auto":
        found = lmu_data.chat_key_scan()
        if found is None:
            if any_window:  # testing in Notepad: there's no chat box to open
                return True
            print('  not sent: couldn\'t read LMU\'s chat key. Bind "Realtime Chat" to a keyboard key'
                  " in LMU (Settings > Controls), or set open_key in config.toml")
            return False
        inject.tap_scan(*found, hold_ms=chat["key_hold_ms"])
    else:
        inject.tap(key, chat["key_hold_ms"])
    time.sleep(chat["open_delay_ms"] / 1000)
    return True


def type_into_chat(chat: dict, text: str, any_window: bool, submit: bool) -> bool:
    """Opens the chat box, types `text` and optionally sends it. False if the game isn't focused."""
    if chat["only_when_focused"] and not any_window:
        title = inject.foreground_title()
        if chat["window_title"].lower() not in title.lower():
            print(f'  not sent: focused window is "{title}", not "{chat["window_title"]}"')
            return False
    if not open_chat(chat, any_window):
        return False
    if chat["text_mode"] == "scancode":
        inject.type_scancode(text, chat["char_delay_ms"], chat["key_hold_ms"])
    else:
        inject.type_unicode(text, chat["char_delay_ms"])
    if submit:
        time.sleep(chat["char_delay_ms"] / 1000)
        inject.tap(chat["send_key"], chat["key_hold_ms"])
    return True


def length_ruler(length: int) -> str:
    """Dots with a count every 10 characters: the number ending at position n is n."""
    return "".join(str(n).rjust(10, ".") for n in range(10, length + 1, 10))


def run_length_test(config: dict, binding: ptt.Binding, any_window: bool):
    # Runs once: a second press would tap open_key, which is often Enter and would send the ruler.
    ruler = length_ruler(LENGTH_TEST_CHARS)
    released = threading.Event()
    ptt.PushToTalk(binding, lambda: None, released.set).start()
    print(f"Chat length test. Switch to LMU, then press and release {binding}. It types a")
    print(f"{len(ruler)}-character ruler into chat WITHOUT sending it. The last number showing,")
    print("plus any dots after it, is the limit. Afterwards delete the text before closing")
    print("the chat box, or Enter will send it. Ctrl+C to quit.")
    try:
        while not released.wait(0.5):  # short waits so Ctrl+C works
            pass
    except KeyboardInterrupt:
        return
    if type_into_chat(config["chat"], ruler, any_window, submit=False):
        print("Typed the ruler. Delete it from the chat box before closing it.")


class VoiceChat:
    def __init__(self, config: dict, any_window: bool):
        self.chat = config["chat"]
        self.speech = config["speech"]
        self.any_window = any_window
        self.names_problem = None  # last driver-names warning shown, so it isn't repeated
        self.jobs = queue.Queue()
        # Whole words, any case: "Mac" = "Merc" fixes "mac" and "Mac's" but not "Macca".
        self.corrections = [
            (re.compile(rf"\b{re.escape(heard)}\b", re.IGNORECASE), meant)
            for heard, meant in config.get("corrections", {}).items()
        ]

        from faster_whisper import WhisperModel  # slow import; only needed when running

        print(f"Loading speech model {self.speech['model']} (first run downloads it)...")
        self.model = WhisperModel(
            self.speech["model"], device=self.speech["device"], compute_type=self.speech["compute_type"]
        )
        self.check_vocabulary()
        self.recorder = Recorder(find_microphone(self.speech["microphone"]))

    def prompt_tokens(self, prompt: str) -> int:
        return len(self.model.hf_tokenizer.encode(" " + prompt.strip(), add_special_tokens=False).ids)

    def check_vocabulary(self):
        # faster-whisper keeps only the last max_length // 2 - 1 prompt tokens.
        self.prompt_limit = self.model.max_length // 2 - 1
        used = self.prompt_tokens(self.speech["vocabulary"])
        if used > self.prompt_limit:
            print(f"  warning: vocabulary is {used} tokens, Whisper keeps the last {self.prompt_limit}; the start is ignored")
        elif self.speech["driver_names"]:
            print(f"  vocabulary uses {used} of {self.prompt_limit} prompt tokens; driver names get the rest")

    def warn_names(self, problem: Exception | None):
        """Reports a driver-names problem once, not on every message, and when it clears."""
        text = str(problem) if problem else None
        if text == self.names_problem:
            return
        if isinstance(problem, lmu_data.LayoutMismatch):
            print(f"  warning: skipping driver names; LMU's shared memory doesn't match the expected"
                  f" layout ({problem}). A game update may have changed it.")
        elif problem:
            print(f"  warning: skipping driver names: {problem!r}")
        else:
            print("  driver names are readable again")
        self.names_problem = text

    def build_prompt(self) -> tuple[str, int]:
        """The vocabulary plus as many driver names as fit, nearest on track first."""
        vocab = self.speech["vocabulary"].strip()
        if not self.speech["driver_names"]:
            return vocab, 0
        try:
            session = lmu_data.read_session()
        except Exception as e:  # never lose a message over this
            self.warn_names(e)
            return vocab, 0
        self.warn_names(None)
        prompt, used = vocab, 0
        for name in lmu_data.names_nearest_first(session) if session else []:
            candidate = f"{prompt}, {name}" if used else f"{vocab} Drivers: {name}".strip()
            if self.prompt_tokens(candidate) > self.prompt_limit:
                break
            prompt, used = candidate, used + 1
        return prompt, used

    def on_press(self):
        self.recorder.start()
        if self.speech["beep"]:
            beep(880)

    def on_release(self):
        audio = self.recorder.stop()
        if self.speech["beep"]:
            beep(660)
        if len(audio) - PREROLL_SECONDS * SAMPLE_RATE < self.speech["min_seconds"] * SAMPLE_RATE:
            return
        self.jobs.put(audio)

    def transcribe(self, audio: np.ndarray) -> tuple[str, int]:
        """The corrected text, and how many driver names were in the prompt."""
        prompt, names = self.build_prompt()
        segments, _ = self.model.transcribe(
            audio,
            language=self.speech["language"] or None,
            initial_prompt=prompt or None,
            vad_filter=True,
            condition_on_previous_text=False,
        )
        text = " ".join(s.text.strip() for s in segments).strip()
        for pattern, meant in self.corrections:
            text = pattern.sub(lambda _: meant, text)
        return text, names

    def send(self, text: str):
        parts = textwrap.wrap(text, self.chat["max_length"], break_on_hyphens=False)
        if not self.chat["auto_send"] and len(parts) > 1:
            # Only one unsent message fits in the chat box.
            print(f"  too long for one message; not typed: {' '.join(parts[1:])}")
            parts = parts[:1]
        for i, part in enumerate(parts):
            if i:
                time.sleep(BETWEEN_MESSAGES_SECONDS)
            if not type_into_chat(self.chat, part, self.any_window, self.chat["auto_send"]):
                return

    def worker(self):
        while True:
            audio = self.jobs.get()
            try:
                started = time.monotonic()
                text, names = self.transcribe(audio)
                if not text:
                    print("  (heard nothing)")
                    continue
                name_note = f", {names} driver names" if self.speech["driver_names"] else ""
                print(f"> {text}  [{time.monotonic() - started:.1f}s{name_note}]")
                self.send(text)
            except Exception as e:
                print(f"  error: {e!r}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--bind", action="store_true", help="press a key or wheel button to set push-to-talk")
    parser.add_argument("--list-mics", action="store_true", help="list microphones")
    parser.add_argument("--list-controllers", action="store_true", help="list wheels, button boxes and joysticks")
    parser.add_argument("--any-window", action="store_true", help="type into any window (for testing in Notepad)")
    parser.add_argument("--length-test", action="store_true", help="type a numbered ruler into chat to find its length limit")
    parser.add_argument("--list-drivers", action="store_true", help="show the driver names read from LMU, nearest first")
    args = parser.parse_args()

    if args.list_drivers:
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
        print("Press the key or wheel button to use for push-to-talk (30 s)...")
        time.sleep(0.5)  # let go of Enter from launching the command
        binding = ptt.capture_binding()
        if binding is None:
            print("Nothing pressed; binding unchanged.")
            return
        save_binding(args.config, binding)
        print(f'Saved ptt_button = "{binding}" to {args.config}')
        return

    config = load_config(args.config)
    binding = ptt.parse_binding(config["ptt_button"])
    if args.length_test:
        run_length_test(config, binding, args.any_window)
        return
    app = VoiceChat(config, args.any_window)
    threading.Thread(target=app.worker, daemon=True).start()
    ptt.PushToTalk(binding, app.on_press, app.on_release).start()
    print(f"Ready. Hold {binding} to talk. Ctrl+C to quit.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
