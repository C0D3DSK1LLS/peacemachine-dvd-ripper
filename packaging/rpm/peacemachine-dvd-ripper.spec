Name:           peacemachine-dvd-ripper
Version:        1.0.51
Release:        1%{?dist}
Summary:        Rip DVDs and video files into files your PC can play
License:        MIT
URL:            https://peacemachinestudios.com
Source0:        %{name}-%{version}.tar.gz
BuildArch:      noarch

Requires:       python3
Requires:       python3-gobject
Requires:       python3-cairo
Requires:       gtk4
# Fedora ships ffmpeg-free, RPM Fusion ships the full ffmpeg. Either is fine -
# demanding only one of them made dnf refuse to install while the other was
# present (C0D3D, 2026-11-15).
Requires:       (ffmpeg or ffmpeg-free)

# HandBrake lives in RPM Fusion on Fedora, and is absent from RPM Fusion's EL
# branch for Alma/RHEL 10, where a hard requirement failed the entire install.
# The app now says plainly when HandBrakeCLI is missing.
%if 0%{?suse_version}
Requires:       python3-gobject-cairo
Recommends:     handbrake-cli
Recommends:     libdvdcss
%else
Recommends:     HandBrake
Recommends:     libdvdcss
%endif

%description
PeaceMachine DVD Ripper drives HandBrake from a GTK4 window: it scans a disc,
lists every title with resolution, duration and a size estimate, and names
per-episode files from a TV show's episode list.

Split modes cover whole titles, chapter ranges and timestamps, with a lossless
copy split for existing video files. It ships the Matrix, light and dark skins.

%prep
%setup -q

%build

%install
sh packaging/install-files.sh . %{buildroot} %{_prefix}

%files
%license LICENSE
%{_bindir}/peacemachine-dvd-ripper
%{_datadir}/applications/org.jimmy.DvdRipper.desktop
%{_datadir}/icons/hicolor/*/apps/org.jimmy.DvdRipper.png
%{_docdir}/%{name}
%{_datadir}/%{name}

%changelog
* Sun Nov 15 2026 William James Sova (C0D3D) <william@peacemachinestudios.com> - 1.0.40-1
- Older GTK uses the plain file chooser, not the portal-backed one

* Sun Nov 15 2026 William James Sova (C0D3D) <william@peacemachinestudios.com> - 1.0.39-1
- File and folder choosers work on GTK older than 4.10

* Sun Nov 15 2026 William James Sova (C0D3D) <william@peacemachinestudios.com> - 1.0.38-1
- No duplicate window buttons on Hyprland, About included

* Sun Nov 15 2026 William James Sova (C0D3D) <william@peacemachinestudios.com> - 1.0.37-1
- Popovers lose the black band around them

* Sun Nov 15 2026 William James Sova (C0D3D) <william@peacemachinestudios.com> - 1.0.36-1
- Extras threshold is 15 minutes, so only episodes and the main feature list

* Sun Nov 15 2026 William James Sova (C0D3D) <william@peacemachinestudios.com> - 1.0.35-1
- Alma candidate: set gtk-decoration-layout on the live Gtk.Settings, because the
  settings.ini copy alone did not add the minimise/maximise buttons

* Sun Nov 15 2026 William James Sova (C0D3D) <william@peacemachinestudios.com> - 1.0.34-1
- Alma candidate: queue buttons packed tight and centred, all three window
  buttons via gtk-decoration-layout

* Sun Nov 15 2026 William James Sova (C0D3D) <william@peacemachinestudios.com> - 1.0.33-1
- Queue buttons packed with no gaps

* Sun Nov 15 2026 William James Sova (C0D3D) <william@peacemachinestudios.com> - 1.0.32-1
- Queue buttons on one row with small gaps

* Sun Nov 15 2026 William James Sova (C0D3D) <william@peacemachinestudios.com> - 1.0.31-1
- Queue buttons packed tight

* Sun Nov 15 2026 William James Sova (C0D3D) <william@peacemachinestudios.com> - 1.0.30-1
- All three window buttons, even on a close-only desktop

* Sun Nov 15 2026 William James Sova (C0D3D) <william@peacemachinestudios.com> - 1.0.29-1
- Stop kills the Flatpak HandBrake; queue buttons stay in one row

* Sun Nov 15 2026 William James Sova (C0D3D) <william@peacemachinestudios.com> - 1.0.28-1
- Fall back to the Flatpak HandBrake when no native binary exists

* Sun Nov 15 2026 William James Sova (C0D3D) <william@peacemachinestudios.com> - 1.0.27-1
- ffmpeg or ffmpeg-free; HandBrake is a Recommends now

* Sun Nov 15 2026 William James Sova (C0D3D) <william@peacemachinestudios.com> - 1.0.26-1
- Two skins only: Matrix and Basic (dark)

* Sun Nov 15 2026 William James Sova (C0D3D) <william@peacemachinestudios.com> - 1.0.25-1
- Red dropdown text, x264 default, NVENC label warns about VMs

* Sun Nov 15 2026 William James Sova (C0D3D) <william@peacemachinestudios.com> - 1.0.24-1
- Every popup label white, whatever the desktop accent

* Sun Nov 15 2026 William James Sova (C0D3D) <william@peacemachinestudios.com> - 1.0.23-1
- Green/white hover in dropdowns and popups

* Sun Nov 15 2026 William James Sova (C0D3D) <william@peacemachinestudios.com> - 1.0.22-1
- White popup text, x264 default quality, NVENC/VM note

* Sun Nov 15 2026 William James Sova (C0D3D) <william@peacemachinestudios.com> - 1.0.21-1
- Fall back to x264 when there is no NVIDIA card; explain NVENC failures

* Sun Nov 15 2026 William James Sova (C0D3D) <william@peacemachinestudios.com> - 1.0.20-1
- All UI updates via timeouts; encodes run unwrapped so Stop works

* Sun Nov 15 2026 William James Sova (C0D3D) <william@peacemachinestudios.com> - 1.0.19-1
- Start from a timeout; idle callbacks were never dispatched on the test VM

* Sun Nov 15 2026 William James Sova (C0D3D) <william@peacemachinestudios.com> - 1.0.18-1
- Scan disc resolves an empty or stale source to a live drive

* Sun Nov 15 2026 William James Sova (C0D3D) <william@peacemachinestudios.com> - 1.0.16-1
- Use lsblk for disc type and label; blkid is not always installed

* Sun Nov 15 2026 William James Sova (C0D3D) <william@peacemachinestudios.com> - 1.0.15-1
- Hand the scan result over with a timer, not an idle callback

* Sun Nov 15 2026 William James Sova (C0D3D) <william@peacemachinestudios.com> - 1.0.14-1
- Fix the missing subprocess import

* Sun Nov 15 2026 William James Sova (C0D3D) <william@peacemachinestudios.com> - 1.0.13-1
- Auto-detect the drive, never auto-scan

* Sun Nov 15 2026 William James Sova (C0D3D) <william@peacemachinestudios.com> - 1.0.12-1
- Prefer a udf DVD-Video disc over a plain data ISO

* Sun Nov 15 2026 William James Sova (C0D3D) <william@peacemachinestudios.com> - 1.0.10-1
- Read the scan with communicate() so it can never wedge

* Sun Nov 15 2026 William James Sova (C0D3D) <william@peacemachinestudios.com> - 1.0.9-1
- Scan HandBrake directly; the systemd-run wrapper deadlocked the pipe reader

* Sun Nov 15 2026 William James Sova (C0D3D) <william@peacemachinestudios.com> - 1.0.8-1
- Automatic scan tries every drive until one has titles

* Sun Nov 15 2026 William James Sova (C0D3D) <william@peacemachinestudios.com> - 1.0.7-1
- Scan a disc that is already in the drive automatically

* Sun Nov 15 2026 William James Sova (C0D3D) <william@peacemachinestudios.com> - 1.0.6-1
- Prefer the optical drive that actually has media

* Sun Nov 15 2026 William James Sova (C0D3D) <william@peacemachinestudios.com> - 1.0.5-1
- Fix the cairo bridge detection from 1.0.4

* Sun Nov 15 2026 William James Sova (C0D3D) <william@peacemachinestudios.com> - 1.0.4-1
- Require the PyGObject cairo bridge (python3-gobject-cairo on SUSE)

* Sun Nov 15 2026 William James Sova (C0D3D) <william@peacemachinestudios.com> - 1.0.3-1
- Window controls as the house discs

* Sun Nov 15 2026 William James Sova (C0D3D) <william@peacemachinestudios.com> - 1.0.2-1
- Ship the rain tiles and resolve them at runtime (they were absolute home paths)
- Require python3-cairo for the spinner

* Sun Nov 15 2026 William James Sova (C0D3D) <william@peacemachinestudios.com> - 1.0.1-1
- Headerbar clearance for the Hyprland hyprbars discs is Hyprland-only now;
  other desktops get the app's own window buttons at the edge

* Sun Nov 15 2026 William James Sova (C0D3D) <william@peacemachinestudios.com> - 1.0.0-1
- Initial package
