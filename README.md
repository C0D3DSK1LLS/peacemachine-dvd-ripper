# PeaceMachine DVD Ripper

![PeaceMachine DVD Ripper main window](docs/screenshot.png)

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

## Verified builds

Each distribution below is pinned to the version that was actually installed and
run on it, not simply the newest upload.

| Distribution | Build | What was verified |
| --- | --- | --- |
| Debian 13 | **1.0.26** | install, drive detection, scan, Find, Start, Stop, rip |
| Ubuntu 26.04 | **1.0.26** | install, drive detection, scan, rip, Stop |
| Fedora 45 | **1.0.26** | install (RPM Fusion + `--allowerasing ffmpeg`), scan, rip |
| AlmaLinux 10 | 1.0.29 verified | install, Flatpak HandBrake, scan, rip, Stop |
| openSUSE Leap 16 | 1.0.35 verified | install, Flatpak HandBrake, scan, rip |
| Kali, Mint, Pop!_OS | 1.0.26 | same apt path as Debian |
| Arch / Omarchy | 1.0.26 | package installs clean; the author runs the same code |

**1.0.36 is the current build for every distribution**, and is what the install
blocks above fetch. The table records the version each distribution was actually
tested at; 1.0.36 adds the 15-minute extras filter on top of those builds, which
is a display rule rather than a change to scanning, ripping or encoding.

## Install — copy and paste

Everything below installs **PeaceMachine DVD Ripper 1.0.19**. The app is the same on
every distribution; only the package names differ.

### Arch, Omarchy, Manjaro, EndeavourOS, CachyOS

```
sudo pacman -S handbrake-cli ffmpeg libdvdcss
sudo pacman -U https://github.com/C0D3DSK1LLS/peacemachine-dvd-ripper/releases/download/v1.0.36/peacemachine-dvd-ripper-1.0.36-1-any.pkg.tar.zst
```

### Debian, Ubuntu, Mint, Pop!_OS, Kali

```
sudo apt install -y handbrake-cli ffmpeg curl
curl -LO https://github.com/C0D3DSK1LLS/peacemachine-dvd-ripper/releases/download/v1.0.36/peacemachine-dvd-ripper_1.0.36_all.deb
sudo apt install ./peacemachine-dvd-ripper_1.0.36_all.deb
```

Reading an encrypted (commercial) disc needs libdvdcss, which Debian will not ship.
`libdvd-pkg` lives in **contrib**, and it builds libdvdcss on your machine:

```
sudo sed -i 's/ main$/ main contrib/' /etc/apt/sources.list
sudo apt update
sudo apt install -y libdvd-pkg && sudo dpkg-reconfigure libdvd-pkg
```

### Fedora

Order matters. HandBrake, libdvdcss and the full ffmpeg all live in RPM Fusion,
and Fedora's own `ffmpeg-free` conflicts with it, so the swap comes before
anything else:

```
# 1 - RPM Fusion, both halves
sudo dnf install https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-$(rpm -E %fedora).noarch.rpm
sudo dnf install https://mirrors.rpmfusion.org/nonfree/fedora/rpmfusion-nonfree-release-$(rpm -E %fedora).noarch.rpm

# 2 - the full ffmpeg, replacing Fedora's ffmpeg-free
sudo dnf install --allowerasing ffmpeg

# 3 - HandBrake (this is the CLI package) and libdvdcss from the tainted section
sudo dnf install rpmfusion-free-release-tainted HandBrake libdvdcss

# 4 - the ripper itself
sudo dnf install https://github.com/C0D3DSK1LLS/peacemachine-dvd-ripper/releases/download/v1.0.36/peacemachine-dvd-ripper-1.0.36-1.noarch.rpm
```

If step 4 complains about the signature, add `--nogpgcheck` - the package is not
signed yet.

### RHEL, AlmaLinux, Rocky Linux

RPM Fusion's **EL** branch gives you ffmpeg and libdvdcss. It has **no HandBrake at
all**, so the ripper cannot scan or rip until you supply one — use the Flatpak:

```
# 1 - RPM Fusion for EL (ffmpeg, libdvdcss)
sudo dnf install --nogpgcheck https://mirrors.rpmfusion.org/free/el/rpmfusion-free-release-$(rpm -E %rhel).noarch.rpm
sudo dnf install rpmfusion-free-release-tainted ffmpeg libdvdcss

# 2 - the ripper itself (installs fine; it will say HandBrake is missing)
sudo dnf install https://github.com/C0D3DSK1LLS/peacemachine-dvd-ripper/releases/download/v1.0.29/peacemachine-dvd-ripper-1.0.29-1.noarch.rpm

# 3 - HandBrake, as a Flatpak, because EL has no package for it
sudo dnf install -y flatpak
# reboot or log out and back in after this one, so the Flatpak services start
sudo flatpak remote-add --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo
sudo flatpak install -y flathub fr.handbrake.ghb

# 4 - let the sandbox see the DVD drive, or HandBrake cannot read the disc
sudo flatpak override --device=all fr.handbrake.ghb

# 5 - check it is reachable (prints a version number)
flatpak run --command=HandBrakeCLI fr.handbrake.ghb --version
```

The ripper looks for a native `HandBrakeCLI` first and falls back to
`fr.handbrake.ghb` on its own — no setting to change.

### openSUSE Leap and Tumbleweed

HandBrake and ffmpeg come from **Packman**; libdvdcss comes from **VideoLAN's**
repo, because Packman does not carry it for Leap 16. Accept the signing keys or
zypper skips both repos:

```
# 1 - Packman (HandBrake, ffmpeg)
sudo zypper addrepo -f https://ftp.gwdg.de/pub/linux/misc/packman/suse/openSUSE_Leap_16.0/ packman
# 2 - VideoLAN (libdvdcss, needed for encrypted discs)
sudo zypper addrepo -f https://download.videolan.org/pub/videolan/vlc/SuSE/16.0/ videolan
# 3 - import both keys in one go (answering "r" at the prompt rejects them)
sudo zypper --gpg-auto-import-keys refresh

# 4 - the tools.  openSUSE calls libdvdcss "libdvdcss2"
sudo zypper in -y handbrake-cli ffmpeg libdvdcss2

# 5 - the ripper
curl -O https://github.com/C0D3DSK1LLS/peacemachine-dvd-ripper/releases/download/v1.0.36/peacemachine-dvd-ripper-1.0.36-1.noarch.rpm
sudo zypper in -y --allow-unsigned-rpm ./peacemachine-dvd-ripper-1.0.36-1.noarch.rpm
```

On **Tumbleweed**, swap both repo paths for `openSUSE_Tumbleweed` and `SuSE/16.0`
keeps working for VideoLAN; on **Leap** use the `16.0` paths above.

If Packman's HandBrake does not install, use the Flatpak instead - the app finds
it automatically:

```
sudo zypper in -y flatpak        # then reboot or log out and back in
sudo flatpak remote-add --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo
sudo flatpak install -y flathub fr.handbrake.ghb
sudo flatpak override --device=all fr.handbrake.ghb
flatpak run --command=HandBrakeCLI fr.handbrake.ghb --version
```

### From source, on anything

The only requirements are Python 3, GTK 4 with PyGObject, PyGObject's cairo
bridge, HandBrake and ffmpeg:

```
curl -LO https://github.com/C0D3DSK1LLS/peacemachine-dvd-ripper/releases/download/v1.0.36/peacemachine-dvd-ripper-1.0.36.tar.gz
tar -xzf peacemachine-dvd-ripper-1.0.36.tar.gz
cd peacemachine-dvd-ripper-1.0.36
sudo sh packaging/install-files.sh . /usr /usr
```

### If the window works but the spinner and rain are missing

That is the PyGObject cairo bridge. It is declared as a dependency in every
package, but if you installed with `dpkg -i` or `rpm -U` instead of through the
package manager, nothing pulls it in:

```
# Debian, Ubuntu, Kali
sudo apt install -y python3-gi-cairo python3-cairo
# openSUSE
sudo zypper in python3-gobject-cairo
# Fedora bundles it inside python3-gobject - reinstall that if it is missing
sudo dnf reinstall python3-gobject
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
