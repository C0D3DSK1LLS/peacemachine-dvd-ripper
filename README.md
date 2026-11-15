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

## Copy and paste (published release)

**Arch, Omarchy, Manjaro, EndeavourOS**

```
sudo pacman -S handbrake-cli ffmpeg libdvdcss
sudo pacman -U https://github.com/C0D3DSK1LLS/peacemachine-dvd-ripper/releases/download/v1.0.0/peacemachine-dvd-ripper-1.0.0-1-any.pkg.tar.zst
```

**Debian, Ubuntu, Kali, Mint**

```
sudo apt install handbrake-cli ffmpeg libdvd-pkg && sudo dpkg-reconfigure libdvd-pkg
curl -LO https://github.com/C0D3DSK1LLS/peacemachine-dvd-ripper/releases/download/v1.0.0/peacemachine-dvd-ripper_1.0.0_all.deb
sudo apt install ./peacemachine-dvd-ripper_1.0.0_all.deb
```

**Fedora**

```
sudo dnf install https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-$(rpm -E %fedora).noarch.rpm
sudo dnf install rpmfusion-free-release-tainted HandBrake ffmpeg libdvdcss
sudo dnf install https://github.com/C0D3DSK1LLS/peacemachine-dvd-ripper/releases/download/v1.0.0/peacemachine-dvd-ripper-1.0.0-1.noarch.rpm
```

**openSUSE Tumbleweed**

```
sudo zypper addrepo -f https://ftp.gwdg.de/pub/linux/misc/packman/suse/openSUSE_Tumbleweed/ packman
sudo zypper in handbrake-cli ffmpeg libdvdcss
sudo zypper in https://github.com/C0D3DSK1LLS/peacemachine-dvd-ripper/releases/download/v1.0.0/peacemachine-dvd-ripper-1.0.0-1.noarch.rpm
```

## Installing from a package

Packages install the program to `/usr/share/peacemachine-dvd-ripper`, a launcher
to `/usr/bin/peacemachine-dvd-ripper`, and the menu entry. Your settings go to
`~/.local/state/peacemachine-dvd-ripper`.

The app needs HandBrake and ffmpeg, and **every commercial DVD is encrypted**, so
you also need libdvdcss. How you get it depends on your distribution:

**Arch, Omarchy, Manjaro, EndeavourOS** — both are in `extra`:

```
sudo pacman -S handbrake-cli ffmpeg libdvdcss
```

**Debian, Ubuntu, Kali, Mint** — HandBrake is in the normal repositories; libdvdcss
is not, so Debian ships a helper that builds it on your machine:

```
sudo apt install handbrake-cli ffmpeg libdvd-pkg && sudo dpkg-reconfigure libdvd-pkg
```

**Fedora, RHEL, Alma, Rocky** — HandBrake lives in RPM Fusion because of codec
patents, and libdvdcss only in its tainted section:

```
sudo dnf install https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-$(rpm -E %fedora).noarch.rpm && sudo dnf install rpmfusion-free-release-tainted HandBrake ffmpeg libdvdcss
```

**openSUSE** — Packman carries all three:

```
sudo zypper addrepo -f https://ftp.gwdg.de/pub/linux/misc/packman/suse/openSUSE_Tumbleweed/ packman && sudo zypper in handbrake-cli ffmpeg libdvdcss
```

Building the packages yourself: see `packaging/README.md`.
