# Packaging and release

One source tree, one install layout (`install-files.sh`), four package formats.

| Directory | Produces | For |
| --- | --- | --- |
| `arch/PKGBUILD` | `.pkg.tar.zst` | Arch, **Omarchy**, Manjaro, EndeavourOS, CachyOS |
| `debian/` | source package (needs `dpkg-buildpackage`) | Debian, Ubuntu, Kali, Mint |
| `build-deb.py` | `.deb` with no dpkg tooling | quick builds anywhere, including Arch |
| `rpm/*.spec` | `.rpm` | Fedora, RHEL/Alma/Rocky, openSUSE |

## What gets installed

```
/usr/bin/peacemachine-dvd-ripper
/usr/share/applications/org.jimmy.DvdRipper.desktop
/usr/share/peacemachine-dvd-ripper/{app,ripper,names}.py, LICENSE, README.md
/usr/share/peacemachine-dvd-ripper/gtk-4.0/*.css + settings.ini
/usr/share/peacemachine-dvd-ripper/asr/transcribe.py     (optional helper)
```

The launcher builds a **private GTK config home** in
`~/.local/share/peacemachine-dvd-ripper/config`, links the shipped skins into it,
symlinks the real `dconf` and `mimeapps.list`, and keeps settings in
`~/.local/state/peacemachine-dvd-ripper`. Nothing collides with the user's own
`~/.config/gtk-4.0`.

`theme/gtk-4.0/` in the repo is the packaged copy of the skins. Its `settings.ini`
is deliberately neutral (no custom font, no icon theme) because those are
specific to C0D3D's desktop; the app sets its icon theme itself.

## Building

```bash
cd packaging && sh make-tarball.sh          # dist/peacemachine-dvd-ripper-<ver>.tar.gz
```

Arch:

```bash
cd packaging/arch && cp ../../dist/*.tar.gz . && makepkg -f
```

Debian/Ubuntu, no tooling needed:

```bash
python3 packaging/build-deb.py              # dist/peacemachine-dvd-ripper_<ver>_all.deb
```

From a Debian machine, the proper source build:

```bash
cd <source tree> && dpkg-buildpackage -us -uc -b
```

Fedora / openSUSE (from a machine with `rpmbuild`):

```bash
mkdir -p ~/rpmbuild/{SOURCES,SPECS} && cp dist/*.tar.gz ~/rpmbuild/SOURCES/
cp packaging/rpm/*.spec ~/rpmbuild/SPECS/ && rpmbuild -ba ~/rpmbuild/SPECS/*.spec
```

## Dependencies, per family

| | GTK + bindings | ripper engine | DVD decryption |
| --- | --- | --- | --- |
| Arch / Omarchy | `gtk4 python-gobject` | `handbrake-cli ffmpeg` | `libdvdcss` (in `extra`) |
| Debian / Ubuntu / Kali | `python3-gi gir1.2-gtk-4.0` | `handbrake-cli ffmpeg` | `libdvd-pkg`, then `dpkg-reconfigure libdvd-pkg` |
| Fedora / RHEL | `python3-gobject gtk4` | `HandBrake ffmpeg` (RPM Fusion) | `rpmfusion-free-release-tainted` |
| openSUSE | `python3-gobject gtk4` | `handbrake-cli ffmpeg` (Packman) | Packman |

Stock Debian, Ubuntu, Fedora and openSUSE cannot read a commercial encrypted DVD
until libdvdcss is added — that is a legal restriction in those distributions, not
a bug here, and the README tells users the one command per family.

## Version bumps

1. `APP_VERSION` in `app.py`
2. `pkgver` in `arch/PKGBUILD`, then `makepkg --printsrcinfo > .SRCINFO`
3. top entry in `debian/changelog` (`dch -v <ver>-1` on Debian)
4. `Version:` and the `%changelog` entry in `rpm/*.spec`
5. re-run `make-tarball.sh`, rebuild, attach to the release
