#!/usr/bin/env python3
"""Build a .deb for PeaceMachine DVD Ripper without any dpkg tooling.

A .deb is an `ar` archive holding three members in this order:

    debian-binary      "2.0\\n"
    control.tar.xz     ./control, ./md5sums, ./postinst
    data.tar.xz        ./usr/...

That is the whole format, so this script writes it directly and works on Arch,
which is where the project is developed. Debian and Ubuntu users can also build
it with `dpkg-buildpackage -us -uc` from the `debian/` directory.

Two details matter, both measured on Debian 13 (2026-11-15):

  * ar member names carry NO trailing slash. GNU `ar` writes one, dpkg-deb does
    not, and libapt's reader segfaults on the slash form when you run
    `apt install ./file.deb`.
  * xz-compressed members, matching dpkg-deb.

    usage: build-deb.py [--out DIR] [--version V]
"""

import argparse
import hashlib
import lzma
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

# Fields that belong in the *source* control file, not the binary one.
SOURCE_ONLY = {"Source", "Build-Depends", "Build-Depends-Indep", "Standards-Version",
               "Rules-Requires-Root", "Testsuite", "Vcs-Browser", "Vcs-Git"}
BINARY_ORDER = ["Package", "Version", "Section", "Priority", "Architecture",
                "Maintainer", "Installed-Size", "Depends", "Recommends", "Suggests",
                "Homepage", "Description"]


def project_version():
    with open(os.path.join(ROOT, "app.py"), encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("APP_VERSION = "):
                return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit("APP_VERSION not found in app.py")


def package_fields():
    """The binary stanza from debian/control, as a dict of name -> value.

    Continuation lines (the long Description) stay attached to their field.
    """
    fields = {}
    current = None
    with open(os.path.join(HERE, "debian", "control"), encoding="utf-8") as handle:
        for line in handle:
            line = line.rstrip("\n")
            if not line.strip():
                current = None
                continue
            if line.startswith((" ", "\t")):
                if current:
                    fields[current] += "\n" + line
                continue
            name, _, value = line.partition(":")
            current = name.strip()
            fields[current] = value.strip()
    return {name: value for name, value in fields.items() if name not in SOURCE_ONLY}


def build_control(version, installed_size):
    fields = package_fields()
    fields["Version"] = version
    fields["Installed-Size"] = str(installed_size)
    fields.setdefault("Homepage", "https://peacemachinestudios.com")
    # ${misc:Depends} is substituted by debhelper; here it resolves to nothing.
    for name in ("Depends", "Recommends", "Suggests"):
        if name in fields:
            parts = [part.strip() for part in fields[name].split(",")]
            fields[name] = ", ".join(part for part in parts if part and not part.startswith("${"))
    order = [name for name in BINARY_ORDER if name in fields]
    order += [name for name in fields if name not in BINARY_ORDER]
    return "".join("%s: %s\n" % (name, fields[name]) for name in order)


def write_tar_xz(path, files):
    """files: list of (absolute path, arcname). uid/gid 0, root ownership."""
    with open(path, "wb") as raw:
        with lzma.LZMAFile(raw, "wb", preset=6, format=lzma.FORMAT_XZ) as packed:
            with tarfile.open(fileobj=packed, mode="w", format=tarfile.GNU_FORMAT) as tar:
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
    """Every path under base as (absolute, "./relative"), directories included."""
    entries = []
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames.sort()
        rel = os.path.relpath(dirpath, base)
        if rel != ".":
            entries.append((dirpath, "./" + rel))
        for name in sorted(filenames):
            entries.append((os.path.join(dirpath, name),
                            "./" + os.path.normpath(os.path.join(rel, name))))
    return entries


def write_ar(path, members):
    """members: list of (name, bytes). Names carry NO trailing slash — libapt
    segfaults on the GNU-ar form when handed a local .deb."""
    with open(path, "wb") as out:
        out.write(b"!<arch>\n")
        for name, blob in members:
            header = "%-16s%-12d%-6d%-6d%-8s%-10d`\n" % (
                name, int(time.time()), 0, 0, "100644", len(blob))
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
        data_tar = os.path.join(work, "data.tar.xz")
        write_tar_xz(data_tar, data_tree)

        md5_lines = []
        installed_size = 0
        for absolute, arcname in data_tree:
            if not os.path.isfile(absolute):
                continue
            installed_size += os.path.getsize(absolute)
            with open(absolute, "rb") as handle:
                digest = hashlib.md5(handle.read()).hexdigest()
            md5_lines.append("%s  %s\n" % (digest, arcname[2:]))
        installed_size = max(1, (installed_size + 1023) // 1024)

        control_work = os.path.join(work, "control")
        os.makedirs(control_work)
        with open(os.path.join(control_work, "control"), "w", encoding="utf-8") as handle:
            handle.write(build_control(version, installed_size))
        with open(os.path.join(control_work, "md5sums"), "w", encoding="utf-8") as handle:
            handle.writelines(md5_lines)
        # Keep the menu in step without debhelper around to do it for us.
        postinst = os.path.join(control_work, "postinst")
        with open(postinst, "w", encoding="utf-8") as handle:
            handle.write("#!/bin/sh\nset -e\n"
                         "command -v update-desktop-database >/dev/null && "
                         "update-desktop-database -q || true\nexit 0\n")
        os.chmod(postinst, 0o755)

        control_tar = os.path.join(work, "control.tar.xz")
        write_tar_xz(control_tar, walk(control_work))

        deb = os.path.join(args.out, "%s_%s_all.deb" % (NAME, version))
        with open(control_tar, "rb") as c_handle, open(data_tar, "rb") as d_handle:
            write_ar(deb, [
                ("debian-binary", b"2.0\n"),
                ("control.tar.xz", c_handle.read()),
                ("data.tar.xz", d_handle.read()),
            ])
        print(deb)
        print("%d files, %d KiB installed" % (
            sum(1 for a, _ in data_tree if os.path.isfile(a)), installed_size))
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
