"""Presses keys and types text into the focused window with Win32 SendInput."""
import ctypes
import time
from ctypes import wintypes

import keyboard

user32 = ctypes.WinDLL("user32", use_last_error=True)

INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_SCANCODE = 0x0008
MAPVK_VK_TO_VSC = 0

SCAN_SHIFT, SCAN_CTRL, SCAN_ALT = 0x2A, 0x1D, 0x38

# Keys whose scan code needs the E0 "extended" prefix.
EXTENDED_KEYS = {
    "right ctrl", "right alt", "insert", "delete", "home", "end", "page up",
    "page down", "up", "down", "left", "right", "num lock", "divide",
}

ULONG_PTR = wintypes.WPARAM


class KEYBDINPUT(ctypes.Structure):
    _fields_ = (("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR))


class MOUSEINPUT(ctypes.Structure):
    _fields_ = (("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR))


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = (("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD))


class _INPUTUNION(ctypes.Union):
    _fields_ = (("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT))


class INPUT(ctypes.Structure):
    _fields_ = (("type", wintypes.DWORD), ("u", _INPUTUNION))


user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
user32.SendInput.restype = wintypes.UINT
user32.VkKeyScanW.argtypes = (wintypes.WCHAR,)
user32.VkKeyScanW.restype = ctypes.c_short
user32.MapVirtualKeyW.argtypes = (wintypes.UINT, wintypes.UINT)
user32.MapVirtualKeyW.restype = wintypes.UINT
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowTextLengthW.argtypes = (wintypes.HWND,)
user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)


def _send(*inputs: INPUT):
    array = (INPUT * len(inputs))(*inputs)
    if user32.SendInput(len(inputs), array, ctypes.sizeof(INPUT)) != len(inputs):
        raise ctypes.WinError(ctypes.get_last_error())


def _key_input(scan: int, flags: int) -> INPUT:
    return INPUT(type=INPUT_KEYBOARD, u=_INPUTUNION(ki=KEYBDINPUT(0, scan, flags, 0, 0)))


def _press(scan: int, up: bool, extended: bool = False):
    flags = KEYEVENTF_SCANCODE | (KEYEVENTF_KEYUP if up else 0) | (KEYEVENTF_EXTENDEDKEY if extended else 0)
    _send(_key_input(scan, flags))


def tap(name: str, hold_ms: int = 30):
    """Presses and releases a key by name ("t", "enter", "f9", ...) as a real scan code."""
    name = name.lower()
    tap_scan(keyboard.key_to_scan_codes(name)[0], name in EXTENDED_KEYS, hold_ms)


def tap_scan(scan: int, extended: bool = False, hold_ms: int = 30):
    _press(scan, up=False, extended=extended)
    time.sleep(hold_ms / 1000)
    _press(scan, up=True, extended=extended)


def type_unicode(text: str, char_delay_ms: int = 5):
    data = text.encode("utf-16-le")
    for i in range(0, len(data), 2):
        unit = int.from_bytes(data[i:i + 2], "little")
        _send(_key_input(unit, KEYEVENTF_UNICODE), _key_input(unit, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))
        time.sleep(char_delay_ms / 1000)


def type_scancode(text: str, char_delay_ms: int = 5, hold_ms: int = 10):
    """Types with real key presses. Characters the keyboard layout can't produce are skipped."""
    for ch in text:
        result = user32.VkKeyScanW(ch)
        if result == -1:
            continue
        vk, shift_state = result & 0xFF, (result >> 8) & 0xFF
        scan = user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)
        modifiers = [m for bit, m in ((1, SCAN_SHIFT), (2, SCAN_CTRL), (4, SCAN_ALT)) if shift_state & bit]
        for m in modifiers:
            _press(m, up=False)
        _press(scan, up=False)
        time.sleep(hold_ms / 1000)
        _press(scan, up=True)
        for m in reversed(modifiers):
            _press(m, up=True)
        time.sleep(char_delay_ms / 1000)


def foreground_title() -> str:
    hwnd = user32.GetForegroundWindow()
    length = user32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value
