# LMU Voice Chat

Hold a push-to-talk button, speak, let go: your words are transcribed on your own
PC (Whisper, no cloud) and typed into Le Mans Ultimate's chat.

- Push-to-talk on a keyboard key or a wheel / button box button.
- Knows sim racing words, every make in LMU and their nicknames (Porker, Lambo, Vette...).
- Adds the names of the drivers in your session, nearest on track first.
- Opens chat with the key you've bound in LMU, and splits messages longer than
  LMU's 119-character limit.

Windows only.

## Setup

1. Install Python 3.12 if you don't have it: `winget install Python.Python.3.12`
   (or from [python.org](https://www.python.org/downloads/), with the "py launcher" ticked).
2. Run `setup.bat`.
3. Run `run.bat --bind` and press the key or wheel button you want for push-to-talk.
4. Start LMU, then `run.bat`. Leave it running while you race. The first start
   downloads the speech model (about 250 MB).

Your settings are in `config.toml`, created on first start. Edit it and restart
the app. `config.default.toml` holds the defaults; don't edit that one.

## Commands

```
run.bat                      start
run.bat --bind               set the push-to-talk key or wheel button
run.bat --any-window         test by talking into Notepad
run.bat --list-mics          microphones, for `microphone` in config.toml
run.bat --list-controllers   connected wheels and button boxes
run.bat --list-drivers       driver names read from LMU (the game must be running)
run.bat --length-test        type a numbered ruler into chat (unsent) to measure its limit
```

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
