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


def _find_controller(device: str):
    for i in range(pygame.joystick.get_count()):
        joy = pygame.joystick.Joystick(i)
        if device.lower() in joy.get_name().lower():
            return joy
    return None


class PushToTalk:
    """Calls on_press when the bound button goes down and on_release when it comes up."""

    def __init__(self, binding: Binding, on_press, on_release):
        self.binding = binding
        self._on_press = on_press
        self._on_release = on_release
        self._held = False

    def start(self):
        if self.binding.kind == "key":
            keyboard.hook_key(self.binding.key, self._on_key)
        else:
            threading.Thread(target=self._poll_controller, daemon=True).start()

    def _set_held(self, held: bool):
        if held == self._held:
            return
        self._held = held
        (self._on_press if held else self._on_release)()

    def _on_key(self, event):
        # Auto-repeat sends many "down" events while held; _set_held ignores them.
        self._set_held(event.event_type == keyboard.KEY_DOWN)

    def _poll_controller(self):
        _init_controllers()
        joy = None
        warned = False
        while True:
            for event in pygame.event.get():
                if event.type in (pygame.JOYDEVICEADDED, pygame.JOYDEVICEREMOVED):
                    joy = None
            if joy is None:
                self._set_held(False)
                joy = _find_controller(self.binding.device)
                if joy is None:
                    if not warned:
                        print(f'Waiting for controller matching "{self.binding.device}"...')
                        warned = True
                    time.sleep(1)
                    continue
                if self.binding.button >= joy.get_numbuttons():
                    raise SystemExit(
                        f"{joy.get_name()} has {joy.get_numbuttons()} buttons; "
                        f"button {self.binding.button} does not exist. Run --bind."
                    )
                print(f"Push-to-talk: {joy.get_name()}, button {self.binding.button}")
                warned = False
            try:
                self._set_held(bool(joy.get_button(self.binding.button)))
            except pygame.error:
                joy = None
            time.sleep(0.01)


def capture_binding(timeout: float = 30) -> Binding | None:
    """Waits for the next key or controller button press and returns it as a binding."""
    _init_controllers()
    controllers = {}
    captured = []

    def on_key(event):
        if event.event_type == keyboard.KEY_DOWN and not captured:
            captured.append(Binding("key", key=event.name.lower()))

    hook = keyboard.hook(on_key)
    try:
        deadline = time.monotonic() + timeout
        while not captured and time.monotonic() < deadline:
            for event in pygame.event.get():
                if event.type == pygame.JOYDEVICEADDED:
                    joy = pygame.joystick.Joystick(event.device_index)
                    controllers[joy.get_instance_id()] = joy
                elif event.type == pygame.JOYBUTTONDOWN and not captured:
                    joy = controllers[event.instance_id]
                    captured.append(Binding("joy", device=joy.get_name(), button=event.button))
            time.sleep(0.01)
    finally:
        keyboard.unhook(hook)
    return captured[0] if captured else None
