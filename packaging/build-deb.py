#!/usr/bin/env python3
"""Build a .deb for PeaceMachine DVD Ripper without any dpkg tooling.

A .deb is an `ar` archive holding three members in this order:

    debian-binary      "2.0\\n"
    control.tar.gz     ./control, ./md5sums
    data.tar.gz        ./usr/...

That is the whole format, so this script writes it directly and works on Arch,
which is where the project is developed. Debian and Ubuntu users can also build
it with `dpkg-buildpackage -us -uc` from the `debian/` directory.

    usage: build-deb.py [--out DIR] [--version V]
"""

import argparse
import gzip
import hashlib
import io
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time

NAME = "peacemachine-dvd-ripper"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def project_version():
    with open(os.path.join(ROOT, "app.py"), encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("APP_VERSION = "):
                return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit("APP_VERSION not found in app.py")


def package_stanza():
    """The Package: block from debian/control, minus the ${...} placeholders."""
    paragraph = []
    with open(os.path.join(HERE, "debian", "control"), encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("Source:") or not line.strip():
                continue
            paragraph.append(line.rstrip("\n"))
    return "\n".join(paragraph) + "\n"


def write_tar_gz(path, files, base):
    """files: list of (absolute path, arcname). uid/gid 0, root ownership."""
    with gzip.GzipFile(path, "wb", mtime=0) as gz:
        with tarfile.open(fileobj=gz, mode="w", format=tarfile.GNU_FORMAT) as tar:
            for absolute, arcname in files:
                info = tar.gettarinfo(absolute, arcname)
                info.uid = info.gid = 0
                info.uname = info.gname = "root"
                info.mtime = int(time.time())
                if info.isreg():
                    with open(absolute, "rb") as handle:
                        tar.addfile(info, handle)
                else:
                    tar.addfile(info)


def walk(base):
    """Every path under base as (absolute, "./relative") with dirs first."""
    entries = []
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames.sort()
        rel = os.path.relpath(dirpath, base)
        arc = "." if rel == "." else "./" + rel
        if rel != ".":
            entries.append((dirpath, arc))
        for name in sorted(filenames):
            entries.append((os.path.join(dirpath, name), "./" + os.path.join(rel, name)))
    return entries


def write_ar(path, members):
    """members: list of (name, bytes). Names get a trailing slash, as dpkg does."""
    with open(path, "wb") as out:
        out.write(b"!<arch>\n")
        for name, blob in members:
            header = "%-16s%-12d%-6d%-6d%-8s%-10d`\n" % (
                name + "/", int(time.time()), 0, 0, "100644", len(blob))
            out.write(header.encode("ascii"))
            out.write(blob)
            if len(blob) % 2:
                out.write(b"\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=os.path.join(ROOT, "dist"))
    parser.add_argument("--version", default=None)
    args = parser.parse_args()

    version = args.version or project_version()
    os.makedirs(args.out, exist_ok=True)

    work = tempfile.mkdtemp(prefix="pmdvd-deb-")
    try:
        destdir = os.path.join(work, "data")
        os.makedirs(destdir)
        subprocess.run(["sh", os.path.join(HERE, "install-files.sh"), ROOT, destdir, "/usr"],
                       check=True)

        data_tree = walk(destdir)
        data_tar = os.path.join(work, "data.tar.gz")
        write_tar_gz(data_tar, data_tree, destdir)

        # md5sums, control side
        md5_lines = []
        for absolute, arcname in data_tree:
            if not os.path.isfile(absolute):
                continue
            with open(absolute, "rb") as handle:
                digest = hashlib.md5(handle.read()).hexdigest()
            md5_lines.append("%s  %s\n" % (digest, arcname[2:]))

        installed_size = 0
        for absolute, _ in data_tree:
            if os.path.isfile(absolute):
                installed_size += os.path.getsize(absolute)
        installed_size = max(1, (installed_size + 1023) // 1024)

        control = package_stanza()
        control = control.replace("${misc:Depends}", "")
        control = control.replace("Architecture: all", "Architecture: all")
        control += "Installed-Size: %d\n" % installed_size
        control += "Homepage: https://peacemachinestudios.com\n"
        if "Version:" not in control:
            control += "\n"  # the version lives in the file name for a binary-only deb

        control_work = os.path.join(work, "control")
        os.makedirs(control_work)
        with open(os.path.join(control_work, "control"), "w", encoding="utf-8") as handle:
            handle.write(control)
        with open(os.path.join(control_work, "md5sums"), "w", encoding="utf-8") as handle:
            handle.writelines(md5_lines)

        control_tar = os.path.join(work, "control.tar.gz")
        write_tar_gz(control_tar, walk(control_work), control_work)

        deb = os.path.join(args.out, "%s_%s_all.deb" % (NAME, version))
        with open(os.path.join(work, "debian-binary"), "w", encoding="utf-8") as handle:
            handle.write("2.0\n")
        write_ar(deb, [
            ("debian-binary", b"2.0\n"),
            ("control.tar.gz", open(control_tar, "rb").read()),
            ("data.tar.gz", open(data_tar, "rb").read()),
        ])
        print(deb)
        print("%d files, %d KiB installed" % (
            sum(1 for a, _ in data_tree if os.path.isfile(a)), installed_size))
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
