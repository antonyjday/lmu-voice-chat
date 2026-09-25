"""Settings, recording, Whisper and typing: everything except the user interface."""
import collections
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
import tomlkit

import inject
import lmu_data
import ptt

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

SAMPLE_RATE = 16000
PREROLL_SECONDS = 0.3  # audio kept from just before the press, so the first word isn't clipped
DEFAULTS_FILE = Path(__file__).with_name("config.default.toml")  # shipped; never edited by users
DEFAULT_CONFIG = Path(__file__).with_name("config.toml")  # the user's own settings
PROFANITY_FILE = Path(__file__).with_name("profanity.txt")  # shipped word list
MERGED_TABLES = ("chat", "speech", "profanity")  # user settings override defaults key by key; other tables replace
BETWEEN_MESSAGES_SECONDS = 0.3  # lets the chat box close before a split message's next part


def ensure_config(path: Path) -> bool:
    """Creates the user's config from the defaults. True if it was just created."""
    if path.exists():
        return False
    shutil.copyfile(DEFAULTS_FILE, path)
    print(f"Created {path.name} from {DEFAULTS_FILE.name}. Edit {path.name} to change settings.")
    return True


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


def save_setting(path: Path, key: str, value, table: str | None = None):
    """Writes one setting into the user's config, keeping its comments and layout."""
    ensure_config(path)
    doc = tomlkit.parse(path.read_text(encoding="utf-8"))
    target = doc
    if table:
        if table not in doc:
            doc.add(table, tomlkit.table())
        target = doc[table]
    target[key] = value
    path.write_text(tomlkit.dumps(doc), encoding="utf-8")


def save_binding(path: Path, binding: ptt.Binding):
    save_setting(path, "ptt_button", str(binding))


def input_devices() -> list[str]:
    """Microphone names, once each. Windows lists every microphone once per audio API,
    so only those of the default input device's API are returned (for MME, the
    default, names are cut to 31 characters; find_microphone still matches them)."""
    try:
        api = sd.query_devices(kind="input")["hostapi"]
    except sd.PortAudioError:
        return []
    names = (d["name"] for d in sd.query_devices() if d["max_input_channels"] > 0 and d["hostapi"] == api)
    # "Sound Mapper" is Windows' alias for the default device, which is listed separately.
    return list(dict.fromkeys(n for n in names if "sound mapper" not in n.lower()))


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
    raise ValueError(f'No microphone matching "{setting}". See --list-mics.')


class ProfanityFilter:
    """Masks listed words with asterisks. Whole words only, any case; a * at either end
    of a listed word matches any ending or beginning (see profanity.txt)."""

    def __init__(self, words: list[str], allow: list[str]):
        self.allow = {w.strip().lower() for w in allow}
        parts = []
        for word in words:
            word = word.strip().lower()
            if not word.strip("*"):
                continue
            core = re.escape(word.strip("*"))
            parts.append((r"\w*" if word.startswith("*") else "") + core + (r"\w*" if word.endswith("*") else ""))
        self.pattern = re.compile(r"\b(?:" + "|".join(parts) + r")\b", re.IGNORECASE) if parts else None

    @classmethod
    def from_config(cls, settings: dict) -> "ProfanityFilter":
        lines = PROFANITY_FILE.read_text(encoding="utf-8").splitlines()
        words = [line for line in lines if line.strip() and not line.lstrip().startswith("#")]
        return cls(words + list(settings["add"]), settings["allow"])

    def apply(self, text: str) -> tuple[str, int]:
        """The text with listed words masked, and how many were masked."""
        if not self.pattern:
            return text, 0
        masked = 0

        def mask(match):
            nonlocal masked
            if match.group().lower() in self.allow:
                return match.group()
            masked += 1
            return "*" * len(match.group())

        return self.pattern.sub(mask, text), masked


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

    def close(self):
        self._stream.stop()
        self._stream.close()


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


class VoiceChat:
    """Push-to-talk, recording, Whisper and typing. apply() takes new settings while running.

    on_change is called whenever state, last_text or ptt_status changes, and
    on_alert with messages the user should see even without the log open.
    """

    def __init__(self, any_window: bool, on_change=lambda: None, on_alert=lambda message: None):
        self.any_window = any_window
        self.on_change = on_change
        self.on_alert = on_alert
        self.config = self.chat = self.speech = None
        self.corrections = []
        self.profanity = None  # a ProfanityFilter when [profanity] filter is on
        self.model = None
        self.model_key = None
        self.model_ready = threading.Event()
        self.recorder = None
        self.mic_device = None
        self.recording = False
        self.pending = 0  # recordings queued or being transcribed
        self.last_text = ""
        self.ptt_status = ""
        self.names_problem = None  # last driver-names warning shown, so it isn't repeated
        self.prompt_limit = 0
        self.vocabulary_report = None  # last vocabulary size message, so reloads don't repeat it
        self.jobs = queue.Queue()
        self.ptt = ptt.PushToTalk(self.on_press, self.on_release, on_status=self.set_ptt_status)
        threading.Thread(target=self.worker, daemon=True).start()

    @property
    def state(self) -> str:
        """"paused", "recording", "loading", "working" or "ready"."""
        if self.ptt.paused:
            return "paused"
        if self.recording:
            return "recording"
        if not self.model_ready.is_set():
            return "loading"
        return "working" if self.pending else "ready"

    def alert(self, message: str):
        print(message)
        self.on_alert(message)

    def apply(self, config: dict):
        """Uses new settings. Rebinds push-to-talk, reopens the microphone or reloads the
        model only when those changed. Raises ValueError for a bad binding or microphone."""
        binding = ptt.parse_binding(config["ptt_button"])
        mic = find_microphone(config["speech"]["microphone"])
        self.config, self.chat, self.speech = config, config["chat"], config["speech"]
        # Whole words, any case: "Mac" = "Merc" fixes "mac" and "Mac's" but not "Macca".
        self.corrections = [
            (re.compile(rf"\b{re.escape(heard)}\b", re.IGNORECASE), meant)
            for heard, meant in config.get("corrections", {}).items()
        ]
        self.profanity = ProfanityFilter.from_config(config["profanity"]) if config["profanity"]["filter"] else None
        if str(binding) != str(self.ptt.binding):
            self.ptt.set_binding(binding)
        if self.recorder is None or mic != self.mic_device:
            old, self.recorder, self.mic_device = self.recorder, Recorder(mic), mic
            if old:
                old.close()
        key = (self.speech["model"], self.speech["device"], self.speech["compute_type"])
        if key != self.model_key:
            self.model_key = key
            threading.Thread(target=self.load_model, args=(key,), daemon=True).start()
        elif self.model:
            self.check_vocabulary()
        self.on_change()

    def load_model(self, key: tuple):
        from faster_whisper import WhisperModel  # slow import; only needed when running

        self.model_ready.clear()
        self.on_change()
        print(f"Loading speech model {key[0]} (first run downloads it)...")
        try:
            model = WhisperModel(key[0], device=key[1], compute_type=key[2])
        except Exception as e:
            self.alert(f"Couldn't load speech model {key[0]}: {e}")
            if self.model:
                self.model_ready.set()  # keep using the previous one
            self.on_change()
            return
        if key != self.model_key:
            return  # another model was chosen while this one loaded
        self.model = model
        self.check_vocabulary()
        self.model_ready.set()
        print(f"Speech model {key[0]} ready")
        self.on_change()

    def close(self):
        self.ptt.set_binding(None)
        if self.recorder:
            self.recorder.close()

    def set_ptt_status(self, message: str):
        print(message)
        self.ptt_status = message
        self.on_change()

    def prompt_tokens(self, prompt: str) -> int:
        return len(self.model.hf_tokenizer.encode(" " + prompt.strip(), add_special_tokens=False).ids)

    def check_vocabulary(self):
        # faster-whisper keeps only the last max_length // 2 - 1 prompt tokens.
        self.prompt_limit = self.model.max_length // 2 - 1
        used = self.prompt_tokens(self.speech["vocabulary"])
        report = (used, self.prompt_limit, self.speech["driver_names"])
        if report == self.vocabulary_report:
            return
        self.vocabulary_report = report
        if used > self.prompt_limit:
            self.alert(f"The vocabulary is {used} tokens; Whisper keeps the last {self.prompt_limit}"
                       " and ignores the start")
        elif self.speech["driver_names"]:
            print(f"  vocabulary uses {used} of {self.prompt_limit} prompt tokens; driver names get the rest")

    def warn_names(self, problem: Exception | None):
        """Reports a driver-names problem once, not on every message, and when it clears."""
        text = str(problem) if problem else None
        if text == self.names_problem:
            return
        if isinstance(problem, lmu_data.LayoutMismatch):
            self.alert(f"Skipping driver names: LMU's shared memory doesn't match the expected"
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
        self.recording = True
        if self.speech["beep"]:
            beep(880)
        self.on_change()

    def on_release(self):
        audio = self.recorder.stop()
        self.recording = False
        if self.speech["beep"]:
            beep(660)
        if len(audio) - PREROLL_SECONDS * SAMPLE_RATE >= self.speech["min_seconds"] * SAMPLE_RATE:
            self.pending += 1
            self.jobs.put(audio)
        self.on_change()

    def transcribe(self, audio: np.ndarray) -> tuple[str, int, int]:
        """The corrected, filtered text, how many driver names were in the prompt,
        and how many words the profanity filter masked."""
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
        masked = 0
        if self.profanity:  # last, so corrections can't bring a word back
            text, masked = self.profanity.apply(text)
        return text, names, masked

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
                self.model_ready.wait()  # recordings made while the model loads wait for it
                started = time.monotonic()
                text, names, masked = self.transcribe(audio)
                if not text:
                    print("  (heard nothing)")
                    continue
                notes = f"{time.monotonic() - started:.1f}s"
                if self.speech["driver_names"]:
                    notes += f", {names} driver names"
                if masked:
                    notes += f", {masked} masked"
                print(f"> {text}  [{notes}]")
                self.last_text = text
                self.send(text)
            except Exception as e:
                print(f"  error: {e!r}")
            finally:
                self.pending -= 1
                self.on_change()
