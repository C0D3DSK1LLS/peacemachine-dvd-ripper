Name:           peacemachine-dvd-ripper
Version:        1.0.5
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
Requires:       ffmpeg

# Fedora/RHEL ship HandBrake in RPM Fusion as "HandBrake" (which provides the
# HandBrakeCLI binary); openSUSE ships it in Packman as "handbrake-cli".
%if 0%{?suse_version}
Requires:       python3-gobject-cairo
Requires:       handbrake-cli
Recommends:     libdvdcss
%else
Requires:       HandBrake
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
%{_docdir}/%{name}
%{_datadir}/%{name}

%changelog
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
