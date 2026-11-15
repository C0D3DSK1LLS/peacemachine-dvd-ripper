# PeaceMachine DVD Ripper

Rips a DVD — or any video file — into files your PC can play, with optional
per-episode naming in the style of FileBot.

- Launcher: `~/.local/bin/c0d3d-dvd-ripper`
- Menu entry: `org.jimmy.DvdRipper.desktop` ("PeaceMachine DVD Ripper")
- Skin: `~/.local/share/c0d3d/dvd-ripper-config/gtk-4.0/` (Matrix / light / dark)
- State: `state.json` (settings), `episode-cache.json` (TVmaze lookups)

It scans a disc, lists every title with resolution, duration and an estimate,
then queues encodes through HandBrake. Split modes cover whole titles, chapter
ranges and timestamps; there is also a lossless `-c copy` split for existing
video files, and an optional speech-to-text pass.

## Licence and credits

PeaceMachine DVD Ripper is **MIT licensed** — see `LICENSE`.
© 2026 William James Sova (C0D3D) — PeaceMachineStudios.

The ripper is original code. It uses:

| Component | Licence | How it is used |
| --- | --- | --- |
| GTK 4 | LGPL-2.1-or-later | UI toolkit, dynamically linked |
| PyGObject | LGPL-2.1-or-later | GTK bindings |
| HandBrakeCLI | GPL-2.0-only | **external program**, run as a separate process |
| ffmpeg / ffprobe | GPL-3.0-only as built on Arch | **external programs**, run as separate processes |
| libdvdcss (optional) | GPL-2.0-only | **external library**, loaded by HandBrake to read encrypted discs |
| TVmaze API | n/a | episode titles and numbering, fetched over HTTPS |

The optional speech-to-text pass uses **faster-whisper** (MIT), **CTranslate2**
(MIT) and **ONNX Runtime** (MIT), installed separately into `asr/venv/` — that
folder and its models are not part of this source tree.

Nothing GPL is linked into this program and nothing GPL is redistributed with it:
HandBrake, ffmpeg and libdvdcss are called as separate programs and installed by
you from your distribution. That is why the MIT licence above holds.

If you ever ship an installer that *includes* HandBrake, ffmpeg or libdvdcss,
that combined distribution is GPL and must also offer their source.

Note: ripping a disc you own for your own use is legal in many places, but the
rules differ by country — check your own.
