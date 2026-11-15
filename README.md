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

| Distribution | GTK | Verified at | What was proven |
| --- | --- | --- | --- |
| Debian 13 | 4.18 | 1.0.26 | install, drive detection, scan, Find, Start, Stop, rip |
| Ubuntu 24.04 LTS | 4.14 | 1.0.37 | install, drive detection, scan, rip |
| Ubuntu 26.04 | 4.20 | 1.0.26 | install, drive detection, scan, rip, Stop |
| Fedora 45 | 4.20 | 1.0.26 | install (RPM Fusion + `--allowerasing ffmpeg`), scan, rip |
| AlmaLinux 10 | 4.18 | 1.0.37 | install, Flatpak HandBrake, scan, rip, Stop |
| openSUSE Leap 16 | 4.18 | 1.0.37 | install, Flatpak HandBrake, scan, rip |
| Kali, Mint, Pop!_OS | - | - | same apt path as the Ubuntu builds above |
| Arch / Omarchy | 4.20 | 1.0.37 | package installs clean; the author runs the same code |

**1.0.37 is the current build for every distribution**, and is what the install
blocks below fetch. The table records the version each distribution was actually
tested at; 1.0.37 adds the 15-minute extras filter, the popover fix and the
window-button fix on top of those builds - display rules rather than changes to
scanning, ripping or encoding.

## Install

**Run one command at a time.** Paste a single line, let it finish, then the next -
several at once is how you end up wondering which one failed.

Everything below installs **PeaceMachine DVD Ripper 1.0.37**. The application is the
same on every distribution; only the package names differ.

### Arch, Omarchy, Manjaro, EndeavourOS, CachyOS

1. The tools HandBrake needs:
```
sudo pacman -S handbrake-cli ffmpeg libdvdcss
```
2. The ripper:
```
sudo pacman -U https://github.com/C0D3DSK1LLS/peacemachine-dvd-ripper/releases/download/v1.0.37/peacemachine-dvd-ripper-1.0.37-1-any.pkg.tar.zst
```

### Debian

1. HandBrake and ffmpeg:
```
sudo apt install -y handbrake-cli ffmpeg curl
```
2. `libdvdcss`, which Debian will not ship - `libdvd-pkg` builds it locally, and it
   lives in the **contrib** section:
```
sudo sed -i 's/ main$/ main contrib/' /etc/apt/sources.list
```
```
sudo apt update
```
```
sudo apt install -y libdvd-pkg
```
```
sudo dpkg-reconfigure libdvd-pkg
```
3. The ripper:
```
curl -LO https://github.com/C0D3DSK1LLS/peacemachine-dvd-ripper/releases/download/v1.0.37/peacemachine-dvd-ripper_1.0.37_all.deb
```
```
sudo apt install ./peacemachine-dvd-ripper_1.0.37_all.deb
```

### Ubuntu, Mint, Pop!_OS, Kali

1. HandBrake and ffmpeg:
```
sudo apt install -y handbrake-cli ffmpeg curl
```
2. `libdvdcss` for encrypted discs - on Ubuntu it is `libdvd-pkg` from **multiverse**:
```
sudo add-apt-repository -y multiverse
```
```
sudo apt update
```
```
sudo apt install -y libdvd-pkg
```
```
sudo dpkg-reconfigure libdvd-pkg
```
3. The ripper:
```
curl -LO https://github.com/C0D3DSK1LLS/peacemachine-dvd-ripper/releases/download/v1.0.37/peacemachine-dvd-ripper_1.0.37_all.deb
```
```
sudo apt install ./peacemachine-dvd-ripper_1.0.37_all.deb
```

### Fedora

Order matters: HandBrake, libdvdcss and the full ffmpeg all live in RPM Fusion, and
Fedora's own `ffmpeg-free` conflicts with it.

1. RPM Fusion, free half:
```
sudo dnf install https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-$(rpm -E %fedora).noarch.rpm
```
2. RPM Fusion, non-free half:
```
sudo dnf install https://mirrors.rpmfusion.org/nonfree/fedora/rpmfusion-nonfree-release-$(rpm -E %fedora).noarch.rpm
```
3. The full ffmpeg, replacing Fedora's `ffmpeg-free`:
```
sudo dnf install --allowerasing ffmpeg
```
4. HandBrake (this is the CLI package) and libdvdcss:
```
sudo dnf install rpmfusion-free-release-tainted HandBrake libdvdcss
```
5. The ripper:
```
sudo dnf install https://github.com/C0D3DSK1LLS/peacemachine-dvd-ripper/releases/download/v1.0.37/peacemachine-dvd-ripper-1.0.37-1.noarch.rpm
```

If step 5 complains about the signature, add `--nogpgcheck` - the package is not
signed yet.

### RHEL, AlmaLinux, Rocky Linux

RPM Fusion's **EL** branch has ffmpeg and libdvdcss but **no HandBrake at all**, so
the ripper needs the Flatpak version of HandBrake. The app finds it automatically.

1. RPM Fusion for EL:
```
sudo dnf install --nogpgcheck https://mirrors.rpmfusion.org/free/el/rpmfusion-free-release-$(rpm -E %rhel).noarch.rpm
```
2. ffmpeg and libdvdcss:
```
sudo dnf install rpmfusion-free-release-tainted ffmpeg libdvdcss
```
3. The ripper (it installs fine and will say HandBrake is missing - that is next):
```
sudo dnf install https://github.com/C0D3DSK1LLS/peacemachine-dvd-ripper/releases/download/v1.0.37/peacemachine-dvd-ripper-1.0.37-1.noarch.rpm
```
4. Flatpak itself:
```
sudo dnf install -y flatpak
```
5. **Reboot, or log out and back in**, so the Flatpak services start. Nothing else
   on this list works until you do.
6. Flathub:
```
sudo flatpak remote-add --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo
```
7. HandBrake:
```
sudo flatpak install -y flathub fr.handbrake.ghb
```
8. Let the sandbox see the DVD drive, or HandBrake cannot read the disc:
```
sudo flatpak override --device=all fr.handbrake.ghb
```
9. Check it - this should print a version number:
```
flatpak run --command=HandBrakeCLI fr.handbrake.ghb --version
```

### openSUSE Leap and Tumbleweed

HandBrake and ffmpeg come from **Packman**; libdvdcss from **VideoLAN's** repo,
because Packman does not carry it for Leap 16. Both need their signing keys
accepted, or zypper skips the repo entirely.

1. Packman:
```
sudo zypper addrepo -f https://ftp.gwdg.de/pub/linux/misc/packman/suse/openSUSE_Leap_16.0/ packman
```
2. VideoLAN:
```
sudo zypper addrepo -f https://download.videolan.org/pub/videolan/vlc/SuSE/16.0/ videolan
```
3. Import both keys without being prompted - answering `r` at that prompt **rejects**
   the key, and the repo is then skipped:
```
sudo zypper --gpg-auto-import-keys refresh
```
4. The tools. openSUSE calls libdvdcss **`libdvdcss2`** - `rpm -q libdvdcss` will
   always claim it is missing:
```
sudo zypper in -y handbrake-cli ffmpeg libdvdcss2
```
5. The ripper:
```
curl -LO https://github.com/C0D3DSK1LLS/peacemachine-dvd-ripper/releases/download/v1.0.37/peacemachine-dvd-ripper-1.0.37-1.noarch.rpm
```
```
sudo zypper in -y --allow-unsigned-rpm ./peacemachine-dvd-ripper-1.0.37-1.noarch.rpm
```

On **Tumbleweed**, use `openSUSE_Tumbleweed` in the Packman path.

If Packman's HandBrake will not install, use the Flatpak instead - the app finds it
on its own:

1. Flatpak:
```
sudo zypper in -y flatpak
```
2. Reboot, or log out and back in.
3. Flathub:
```
sudo flatpak remote-add --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo
```
4. HandBrake:
```
sudo flatpak install -y flathub fr.handbrake.ghb
```
5. Drive access:
```
sudo flatpak override --device=all fr.handbrake.ghb
```
6. Check it:
```
flatpak run --command=HandBrakeCLI fr.handbrake.ghb --version
```

### From source, on anything

The only requirements are Python 3, GTK 4 with PyGObject, PyGObject's cairo
bridge, HandBrake and ffmpeg:

```
curl -LO https://github.com/C0D3DSK1LLS/peacemachine-dvd-ripper/releases/download/v1.0.37/peacemachine-dvd-ripper-1.0.37.tar.gz
tar -xzf peacemachine-dvd-ripper-1.0.37.tar.gz
cd peacemachine-dvd-ripper-1.0.37
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
