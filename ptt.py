"""Push-to-talk bindings: a keyboard key or a wheel/joystick button."""
import os
import threading
import time
from dataclasses import dataclass

# Must be set before pygame loads: read controllers while LMU has focus, and
# run without opening a window.
os.environ.setdefault("SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", "1")
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import keyboard  # noqa: E402
import pygame  # noqa: E402

CANCEL_KEY = "esc"  # cancels capture()


@dataclass
class Binding:
    kind: str  # "key" or "joy"
    key: str = ""
    device: str = ""
    button: int = 0

    def __str__(self):
        if self.kind == "key":
            return f"key:{self.key}"
        return f"joy:{self.device}:{self.button}"

    def describe(self) -> str:
        if self.kind == "key":
            return self.key.upper() if len(self.key) <= 3 else self.key.title()
        return f"{self.device or 'controller'} button {self.button}"


def parse_binding(text: str) -> Binding:
    kind, _, rest = text.partition(":")
    kind = kind.strip().lower()
    if kind == "key" and rest.strip():
        return Binding("key", key=rest.strip().lower())
    if kind == "joy":
        device, sep, button = rest.rpartition(":")
        if sep and button.strip().isdigit():
            return Binding("joy", device=device.strip(), button=int(button))
    raise ValueError(
        f'ptt_button "{text}" is not valid. Use "key:<name>" or '
        '"joy:<device>:<button>", or run with --bind.'
    )


def _init_controllers():
    if not pygame.display.get_init():
        pygame.display.init()
    pygame.joystick.init()


def list_controllers():
    _init_controllers()
    pygame.event.pump()
    return [
        (j.get_name(), j.get_numbuttons())
        for j in (pygame.joystick.Joystick(i) for i in range(pygame.joystick.get_count()))
    ]


class PushToTalk:
    """Calls on_press when the bound button goes down and on_release when it comes up.

    The binding can be changed while running, and capture() records a new one.
    All pygame work happens on one thread: SDL only reports controllers to the
    thread that initialised it, so polling and capturing must share it.
    """

    def __init__(self, on_press, on_release, on_status=print):
        self._on_press = on_press
        self._on_release = on_release
        self._on_status = on_status
        self._lock = threading.RLock()
        self._binding: Binding | None = None
        self._remove_key_hook = None
        self._paused = False
        self._held = False
        self._capture: tuple[threading.Event, list] | None = None
        self._last_status = None
        threading.Thread(target=self._controller_loop, daemon=True).start()

    @property
    def binding(self) -> Binding | None:
        return self._binding

    def set_binding(self, binding: Binding | None):
        with self._lock:
            self._set_held(False)
            if self._remove_key_hook:
                self._remove_key_hook()
                self._remove_key_hook = None
            self._binding = binding
            self._last_status = None
            if binding and binding.kind == "key":
                self._remove_key_hook = keyboard.hook_key(binding.key, self._on_key)

    @property
    def paused(self) -> bool:
        return self._paused

    @paused.setter
    def paused(self, value: bool):
        with self._lock:
            self._paused = value
            self._set_held(False)

    def capture(self, timeout: float = 30) -> Binding | None:
        """Waits for the next key or controller button press and returns it as a binding.
        Push-to-talk is ignored meanwhile. None on timeout or when Escape is pressed."""
        done, result = threading.Event(), []

        def on_key(event):
            if event.event_type == keyboard.KEY_DOWN and not done.is_set():
                if event.name.lower() != CANCEL_KEY:
                    result.append(Binding("key", key=event.name.lower()))
                done.set()

        with self._lock:
            self._set_held(False)
            self._capture = (done, result)
        hook = keyboard.hook(on_key)
        try:
            done.wait(timeout)
        finally:
            keyboard.unhook(hook)
            with self._lock:
                self._capture = None
        return result[0] if result else None

    def _status(self, message: str):
        if message != self._last_status:
            self._last_status = message
            self._on_status(message)

    def _set_held(self, held: bool):
        with self._lock:
            if held and (self._paused or self._capture):
                return
            if held == self._held:
                return
            self._held = held
            (self._on_press if held else self._on_release)()

    def _on_key(self, event):
        # Auto-repeat sends many "down" events while held; _set_held ignores them.
        self._set_held(event.event_type == keyboard.KEY_DOWN)

    def _controller_loop(self):
        _init_controllers()
        joysticks = {}  # instance id -> Joystick; SDL announces existing ones at startup
        while True:
            for event in pygame.event.get():
                if event.type == pygame.JOYDEVICEADDED:
                    joy = pygame.joystick.Joystick(event.device_index)
                    joysticks[joy.get_instance_id()] = joy
                elif event.type == pygame.JOYDEVICEREMOVED:
                    joysticks.pop(event.instance_id, None)
                elif event.type == pygame.JOYBUTTONDOWN:
                    capture, joy = self._capture, joysticks.get(event.instance_id)
                    if capture and joy and not capture[0].is_set():
                        capture[1].append(Binding("joy", device=joy.get_name(), button=event.button))
                        capture[0].set()
            binding = self._binding
            if binding and binding.kind == "joy":
                self._poll(binding, joysticks.values())
            time.sleep(0.01)

    def _poll(self, binding: Binding, joysticks):
        joy = next((j for j in joysticks if binding.device.lower() in j.get_name().lower()), None)
        if joy is None:
            self._set_held(False)
            self._status(f'Waiting for controller matching "{binding.device}"')
        elif binding.button >= joy.get_numbuttons():
            self._set_held(False)
            self._status(f"{joy.get_name()} has no button {binding.button}; set push-to-talk again")
        else:
            self._status(f"Push-to-talk: {joy.get_name()}, button {binding.button}")
            try:
                self._set_held(bool(joy.get_button(binding.button)))
            except pygame.error:
                self._set_held(False)
