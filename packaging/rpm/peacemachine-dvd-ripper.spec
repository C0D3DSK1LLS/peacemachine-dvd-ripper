Name:           peacemachine-dvd-ripper
Version:        1.0.0
Release:        1%{?dist}
Summary:        Rip DVDs and video files into files your PC can play
License:        MIT
URL:            https://peacemachinestudios.com
Source0:        %{name}-%{version}.tar.gz
BuildArch:      noarch

Requires:       python3
Requires:       python3-gobject
Requires:       gtk4
Requires:       ffmpeg

# Fedora/RHEL ship HandBrake in RPM Fusion as "HandBrake" (which provides the
# HandBrakeCLI binary); openSUSE ships it in Packman as "handbrake-cli".
%if 0%{?suse_version}
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
%doc README.md
%{_bindir}/peacemachine-dvd-ripper
%{_datadir}/applications/org.jimmy.DvdRipper.desktop
%{_datadir}/%{name}

%changelog
* Sat Nov 15 2026 William James Sova (C0D3D) <william@peacemachinestudios.com> - 1.0.0-1
- Initial package
