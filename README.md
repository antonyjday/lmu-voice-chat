# LMU Voice Chat

Hold a push-to-talk button, speak, let go: your words are transcribed on your own
PC (Whisper, no cloud) and typed into Le Mans Ultimate's chat.

- Push-to-talk on a keyboard key or a wheel / button box button.
- Knows sim racing words, every make in LMU and their nicknames (Porker, Lambo, Vette...).
- Adds the names of the drivers in your session, nearest on track first.
- Opens chat with the key you've bound in LMU, and splits messages longer than
  LMU's 119-character limit.
- Masks swear words and slurs with asterisks (on by default; the list is
  `profanity.txt`, and `[profanity]` in config.toml adds or allows words).

Windows only.

## Install

1. Download `LMU-Voice-Chat-<version>.zip` from the latest release on the
   [Releases page](../../releases) and extract it (right-click > Extract All).
2. Double-click **Install LMU Voice Chat.bat**. If Windows asks whether to run
   it, choose Run. The installer sets everything up for your Windows account
   (no admin rights needed): it installs Python 3.12 if you don't have it,
   downloads the speech model (about 250 MB), adds **LMU Voice Chat** to the
   Start Menu and desktop, and starts the app. The first install takes a few
   minutes. The extracted folder isn't needed afterwards.
3. The app runs in the system tray (on Windows 11, new tray icons start in the
   overflow behind the `^` arrow; drag it onto the taskbar to keep it visible).
   Right-click the icon > **Set push-to-talk button...** and press the key or
   wheel button you want. It's F9 until you do.

The app is installed in `%LOCALAPPDATA%\Programs\LMU Voice Chat`.

**Updating:** download the new release and run its installer. Your settings are kept.

**Uninstalling:** Settings > Apps > Installed apps > LMU Voice Chat > Uninstall.
This also deletes your settings; it asks before deleting the speech models.

Leave it running while you race. The icon shows what it's doing: green ready,
red recording, amber transcribing, grey loading, crossed out paused.

## Settings

Right-click the tray icon for push-to-talk, pause, sending messages
automatically, driver names, beeps, the profanity filter, microphone, speech model, chat key and
starting with Windows. Changes apply straight away.

Everything else is in `config.toml` (**Edit settings file** in the menu), created
on first start. Saved edits apply straight away. `config.default.toml` holds the
defaults; don't edit that one. **Open log** shows what the app heard and typed.

## Commands

For troubleshooting, in a command prompt in the app's folder
(`cd /d "%LOCALAPPDATA%\Programs\LMU Voice Chat"`):

```
run.bat                      start in the tray (same as the shortcut)
run.bat --console            start, with a console showing the log
run.bat --any-window         start, typing into any window (to test in Notepad)
run.bat --bind               set the push-to-talk key or wheel button
run.bat --list-mics          microphones, for `microphone` in config.toml
run.bat --list-controllers   connected wheels and button boxes
run.bat --list-drivers       driver names read from LMU (the game must be running)
run.bat --length-test        type a numbered ruler into chat (unsent) to measure its limit
run.bat --version            show the installed version
```

For development, work in a git clone and run `powershell -ExecutionPolicy Bypass -File install.ps1 -Here` there: it sets
up that folder (and points the shortcuts at it) instead of copying it. Build a
release zip with `release.ps1`.

## Troubleshooting

- **Chat doesn't open:** the app presses LMU's "Realtime Chat" key, read from your
  LMU controls. If that's bound to a wheel button rather than a key, bind a
  keyboard key to it too, or set `open_key` in config.toml.
- **First letters missing:** raise `open_delay_ms`.
- **Chat opens but stays empty:** set `text_mode = "scancode"`.
- **Nothing happens in game:** run LMU and this app the same way (both normally,
  or both as administrator).
- **A word keeps coming out wrong:** add it under `[corrections]`, e.g.
  `"Mac" = "Merc"`. Or try `model = "medium.en"` (more accurate, slower).

## Anti-cheat

The app doesn't touch the game's process or memory. It types with standard
Windows key presses, like a macro keyboard, and reads driver names from
`LMU_Data`, the shared memory LMU publishes for tools like this. It has been
used in online lobbies with Easy Anti-Cheat running.

## Credits and licences

LMU Voice Chat is released under the [MIT licence](LICENSE).

This app builds on:

- [OpenAI Whisper](https://github.com/openai/whisper) speech recognition (MIT),
  run with [faster-whisper](https://github.com/SYSTRAN/faster-whisper) and
  [CTranslate2](https://github.com/OpenNMT/CTranslate2) (MIT), using the
  [Systran/faster-whisper-small.en](https://huggingface.co/Systran/faster-whisper-small.en)
  model conversion (MIT)
- [Silero VAD](https://github.com/snakers4/silero-vad) to skip silence (MIT)
- [sounddevice](https://github.com/spatialaudio/python-sounddevice) (MIT),
  [keyboard](https://github.com/boppreh/keyboard) (MIT),
  [pygame](https://www.pygame.org) (LGPL 2.1),
  [pystray](https://github.com/moses-palmer/pystray) (LGPLv3),
  [Pillow](https://python-pillow.org) (MIT-CMU),
  [tomlkit](https://github.com/python-poetry/tomlkit) (MIT) and
  [NumPy](https://numpy.org) (BSD)

None of these are included in this repository: the installer downloads them from
PyPI, and the speech model from Hugging Face. Each is
covered by its own licence.

Not affiliated with or endorsed by Studio 397 or Motorsport Games. Le Mans
Ultimate is their product.
