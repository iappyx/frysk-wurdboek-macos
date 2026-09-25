#!/usr/bin/env python3
"""
make_frysk_hanwurdboek_mac.py

Builds a native macOS app of the Fryske Akademy's "Frysk Hanwurdboek" from
the official 2016 Linux download (Python 2.7 + wxPython 2.8/3.0).

This script contains NO code or data from the dictionary software. It:
  1. downloads the original Linux archive from the Fryske Akademy website,
  2. decompiles the original Python 2.7 bytecode with uncompyle6,
  3. applies only *generic* Python 2 -> 3 conversions to that output,
  4. adds a small compatibility layer (written for this script) that gives
     Python 2 string semantics and the old wxPython "Classic" names on top of
     Python 3 + wxPython 4,
  5. packages everything as "Frysk Hanwurdboek.app" with PyInstaller.

Usage (Terminal):
    python3 make_frysk_hanwurdboek_mac.py            # build the .app
    python3 make_frysk_hanwurdboek_mac.py --no-app   # only prepare & test the source
    python3 make_frysk_hanwurdboek_mac.py --archive ~/Downloads/fhwb.tar.gz

Everything happens inside a folder "fhwb-build" next to this script; the
finished app ends up in "fhwb-build/dist". The dictionary remains
(c) Fryske Akademy; use it according to their terms.
"""
import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request

URL = "https://beheer.frysker.nl/wp-content/uploads/2021/08/fhwb.tar.gz"
KNOWN_SHA256 = "faff7c526d71bdb6de665ab5c37116d82f2d7da37a04a468ab2d9108edf36479"
APP_NAME = "Frysk Hanwurdboek"
BUNDLE_ID = "nl.personal.fryskhanwurdboek"
PIP_PACKAGES = ["wxPython>=4.2", "uncompyle6==3.9.3", "xdis==6.1.7", "pyinstaller"]

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "fhwb-build")
VENV = os.path.join(WORK, "venv")
SRC = os.path.join(WORK, "src")


def say(msg):
    print("\n==> " + msg, flush=True)


# xdis 6.1.7 is the newest release that uncompyle6 3.9.3 accepts and that
# installs on every Python from 3.10 up to 3.14 (6.1.8 is limited to < 3.13).

# ---------------------------------------------------------------------------
# Stage 0: private virtual environment (avoids "externally-managed-environment")
# ---------------------------------------------------------------------------
def ensure_venv():
    if os.path.realpath(sys.prefix) == os.path.realpath(VENV):
        return
    if sys.version_info < (3, 10):
        sys.exit("Python 3.10 or newer is needed (you have %d.%d). Install one from "
                 "https://www.python.org/downloads/macos/ and run this script with it." % sys.version_info[:2])
    py = os.path.join(VENV, "bin", "python")
    marker = os.path.join(VENV, ".packages-installed")
    if not os.path.exists(marker):
        say("Creating a private Python environment in fhwb-build/venv")
        os.makedirs(WORK, exist_ok=True)
        if not os.path.exists(py):
            subprocess.check_call([sys.executable, "-m", "venv", VENV])
        subprocess.check_call([py, "-m", "pip", "install", "--upgrade", "pip"])
        say("Installing wxPython, uncompyle6 and PyInstaller (a few minutes)")
        try:
            subprocess.check_call([py, "-m", "pip", "install"] + PIP_PACKAGES)
        except subprocess.CalledProcessError:
            shutil.rmtree(VENV, ignore_errors=True)   # start clean next time
            sys.exit("\nInstalling the required packages failed (see the messages above).")
        open(marker, "w").close()
    os.execv(py, [py, os.path.abspath(__file__)] + sys.argv[1:])


# ---------------------------------------------------------------------------
# Stage 1: download
# ---------------------------------------------------------------------------
def get_archive(path):
    if path:
        return os.path.abspath(os.path.expanduser(path))
    dest = os.path.join(WORK, "fhwb.tar.gz")
    if not os.path.exists(dest):
        say("Downloading the original Linux edition from the Fryske Akademy")
        if shutil.which("curl"):               # uses the Mac's own certificate store
            subprocess.check_call(["curl", "-fL", "--retry", "3", "-o", dest + ".part", URL])
        else:
            req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req) as r, open(dest + ".part", "wb") as f:
                shutil.copyfileobj(r, f)
        os.replace(dest + ".part", dest)
    return dest


def check_archive(path):
    h = hashlib.sha256(open(path, "rb").read()).hexdigest()
    if h != KNOWN_SHA256:
        print("    NOTE: the archive differs from the version this script was tested with.\n"
              "          Continuing; the self-test below will tell whether it worked.")


# ---------------------------------------------------------------------------
# Stage 2: extract + decompile + generic Python 2 -> 3 conversion
# ---------------------------------------------------------------------------
# Standard-library modules whose str/bytes behaviour changed; imports of these
# are redirected to the compatibility layer.
COMPAT_MODULES = {"array", "zlib", "re"}


def normalise_constants(co):
    """Python 2 'str' constants were byte strings. Represent them as Python 3
    str with one character per byte (latin-1), so indexing, slicing, offsets
    and regular expressions behave exactly as in Python 2. Python 2 'unicode'
    constants become ordinary str."""
    from xdis.cross_types import UnicodeForPython3
    new = []
    for c in co.co_consts:
        if isinstance(c, UnicodeForPython3):
            c = c.value.decode("utf-8")
        elif isinstance(c, bytes):
            c = c.decode("latin-1")
        elif isinstance(c, str):
            c = c.encode("utf-8").decode("latin-1")
        elif hasattr(c, "co_consts"):
            normalise_constants(c)
        elif isinstance(c, tuple):
            c = tuple(x.value.decode("utf-8") if isinstance(x, UnicodeForPython3)
                      else x.decode("latin-1") if isinstance(x, bytes)
                      else x.encode("utf-8").decode("latin-1") if isinstance(x, str)
                      else x for x in c)
        new.append(c)
    co.co_consts = tuple(new)


def decompile(pyc, out_py):
    from xdis.load import load_module
    from uncompyle6.main import decompile as uncompyle
    from uncompyle6.scanners import scanner2
    # uncompyle6 3.9 prints constant *indexes* instead of values for long
    # constant lists from Python 2 bytecode; turn that shortcut off.
    scanner2.Scanner2.bound_collection_from_tokens = lambda self, *a, **k: None
    version, _ts, magic, co = load_module(pyc)[:4]
    normalise_constants(co)
    with open(out_py + ".raw", "w", encoding="utf-8") as out:
        uncompyle(co, version, out, magic_int=magic)
    return open(out_py + ".raw", encoding="utf-8").read()


def py2to3(src):
    """Generic, mechanical Python 2 -> 3 rewrites (no knowledge of the program)."""
    lines = []
    for line in src.split("\n"):
        if line.strip() == "return" and not line.startswith(" "):
            continue                                   # decompiler artefact at module level
        m = re.match(r"^(\s*)import ([\w., ]+)$", line)
        if m:
            names = [n.strip() for n in m.group(2).split(",")]
            compat = [n for n in names if n in COMPAT_MODULES]
            rest = [n for n in names if n not in COMPAT_MODULES]
            parts = []
            if rest:
                parts.append(m.group(1) + "import " + ", ".join(rest))
            if compat:
                parts.append(m.group(1) + "from py2compat import " + ", ".join(compat))
            line = "\n".join(parts)
        # it.next()  ->  next(it)
        line = re.sub(r"\b([A-Za-z_][\w.]*)\.next\(\)", r"next(\1)", line)
        # byte strings are latin-1 str here: keep encode/decode round trips consistent
        line = re.sub(r"\.decode\((['\"])utf-?8\1\)", ".encode('latin-1').decode('utf-8')", line)
        line = re.sub(r"\.encode\((['\"])utf-?8\1\)", ".encode('utf-8').decode('latin-1')", line)
        lines.append(line)
    return "from py2compat import *  # noqa: F401,F403  (added by converter)\n" + "\n".join(lines)


def convert(archive):
    say("Unpacking and converting the original program")
    if os.path.exists(SRC):
        shutil.rmtree(SRC)
    orig = os.path.join(WORK, "original")
    if os.path.exists(orig):
        shutil.rmtree(orig)
    os.makedirs(orig)
    with tarfile.open(archive) as tf:
        try:
            tf.extractall(orig, filter="data")
        except TypeError:                              # Python < 3.12
            tf.extractall(orig)
    top = os.path.join(orig, next(d for d in os.listdir(orig)
                                  if os.path.isdir(os.path.join(orig, d))))
    os.makedirs(SRC)
    for name in sorted(os.listdir(top)):
        p = os.path.join(top, name)
        if name.endswith(".pyc"):
            mod = name[:-4]
            print("    decompiling " + name + (" (large, takes a while)" if os.path.getsize(p) > 10**6 else ""),
                  flush=True)
            out = os.path.join(SRC, mod + ".py")
            code = py2to3(decompile(p, out))
            compile(code, out, "exec")                 # fail early on syntax problems
            with open(out, "w", encoding="utf-8") as f:
                f.write(code)
            os.remove(out + ".raw")
        elif name.endswith(".py"):
            continue                                   # original launcher; replaced below
        elif os.path.isdir(p):
            shutil.copytree(p, os.path.join(SRC, name))
        else:
            shutil.copy2(p, SRC)
    for fname, text in SUPPORT_FILES.items():
        with open(os.path.join(SRC, fname), "w", encoding="utf-8") as f:
            f.write(text)


# ---------------------------------------------------------------------------
# Support files written by this script (not part of the original software)
# ---------------------------------------------------------------------------
PY2COMPAT = r'''
"""Python 2 semantics for code decompiled from Python 2.7 (written by the
build script). Python 2 byte strings are represented as latin-1 str."""
import array as _array
import builtins as _b
import io as _io
import re as _re
import types as _types
import zlib as _zlib
from functools import reduce

basestring = str
unicode = str
long = int
unichr = chr
xrange = _b.range


def map(*a):
    return list(_b.map(*a))


def filter(*a):
    return list(_b.filter(*a))


def zip(*a):
    return list(_b.zip(*a))


def range(*a):
    return list(_b.range(*a))


__all__ = ["basestring", "unicode", "long", "unichr", "xrange", "reduce",
           "map", "filter", "zip", "range"]


def _bytes(s):
    return s.encode("latin-1") if isinstance(s, str) else s


# --- re: Python 2 re.escape (escapes every non-alphanumeric character) ---
_ALNUM = frozenset("_abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")


def _escape(pattern):
    return "".join(c if c in _ALNUM else ("\\000" if c == "\000" else "\\" + c) for c in pattern)


re = _types.ModuleType("re")
re.__dict__.update({k: v for k, v in vars(_re).items() if not k.startswith("__")})
re.escape = _escape


# --- array: accept/return latin-1 str where Python 2 used byte strings ---
class _Array(_array.array):
    def __new__(cls, typecode, init=None):
        if init is None:
            return _array.array.__new__(cls, typecode)
        return _array.array.__new__(cls, typecode, _bytes(init))

    def tostring(self):
        return self.tobytes().decode("latin-1")

    def fromstring(self, s):
        self.frombytes(_bytes(s))


array = _types.ModuleType("array")
array.__dict__.update({k: v for k, v in vars(_array).items() if not k.startswith("__")})
array.array = _Array

# --- zlib ---
zlib = _types.ModuleType("zlib")
zlib.__dict__.update({k: v for k, v in vars(_zlib).items() if not k.startswith("__")})
zlib.decompress = lambda s, *a: _zlib.decompress(_bytes(s), *a).decode("latin-1")
zlib.compress = lambda s, *a: _zlib.compress(_bytes(s), *a).decode("latin-1")


def repair_tag_collisions(data, tag_chars):
    """Some UTF-8 characters in the text contain a byte that is also used as a
    structure code, which breaks parsing. Replace such a character with an
    ASCII look-alike and pad with spaces at the end of the same text run, so
    no other offset in the data moves."""
    lookalike = {"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"'}
    tags = set(tag_chars)
    out = list(data)
    for m in _re.finditer("[\xc2-\xf4][\x80-\xbf]+", data):
        seq = m.group()
        try:
            ch = seq.encode("latin-1").decode("utf-8")
        except UnicodeDecodeError:
            continue
        if not any(c in tags for c in seq[1:]):
            continue
        rep = lookalike.get(ch, "?")
        start, end = m.span()
        run_end = end
        while run_end < len(data) and data[run_end] not in tags:
            run_end += 1
        # shift the rest of the run left, then pad with spaces
        run = rep + data[end:run_end]
        run += " " * (run_end - start - len(run))
        out[start:run_end] = list(run)
    return "".join(out)
'''

CSTRINGIO = r'''
"""Python 2 cStringIO: StringIO() is a text buffer, StringIO(s) an input stream
of bytes (written by the build script)."""
import io


def StringIO(initial=None):
    if initial is None:
        return io.StringIO()
    if isinstance(initial, str):
        initial = initial.encode("latin-1")
    return io.BytesIO(initial)
'''

WXVERSION = r'''
"""Stand-in for the old wxversion selector (written by the build script)."""
def checkInstalled(*a, **k):
    return False


def select(*a, **k):
    pass
'''

WXCOMPAT = r'''
"""Old wxPython 'Classic' names and behaviour on top of wxPython 4
(written by the build script)."""
import pathlib
import warnings

import wx
import wx.adv
import wx.html

warnings.simplefilter("ignore", getattr(wx, "wxPyDeprecationWarning", DeprecationWarning))


class HtmlListBox(wx.html.HtmlListBox):
    def ScrollToLine(self, line):
        if line is not None and line >= 0:
            return self.ScrollToRow(line)


wx.HtmlListBox = HtmlListBox

wx.SplashScreen = wx.adv.SplashScreen
for _n in dir(wx.adv):
    if _n.startswith("SPLASH_"):
        setattr(wx, _n, getattr(wx.adv, _n))


_HtmlWindow = wx.html.HtmlWindow


class HtmlWindow(_HtmlWindow):
    """Adds HasAnchor() and routes link clicks to OnLinkClicked()."""
    def __init__(self, *a, **k):
        _HtmlWindow.__init__(self, *a, **k)
        self._page = ""
        self.Bind(wx.html.EVT_HTML_LINK_CLICKED, lambda e: self.OnLinkClicked(e.GetLinkInfo()))

    def SetPage(self, source):
        self._page = source
        return _HtmlWindow.SetPage(self, source)

    def HasAnchor(self, name):
        return ('name="%s"' % name) in self._page


wx.html.HtmlWindow = HtmlWindow

_menu_append = wx.Menu.Append


def _Append(self, *a, **k):
    if "help" in k:
        k["helpString"] = k.pop("help")
    return _menu_append(self, *a, **k)


wx.Menu.Append = _Append

_AccelTable = wx.AcceleratorTable


class AcceleratorTable(_AccelTable):
    def __init__(self, entries=None):
        if entries is None:
            _AccelTable.__init__(self)
        else:
            _AccelTable.__init__(self, [e if isinstance(e, wx.AcceleratorEntry)
                                        else wx.AcceleratorEntry(*e) for e in entries])


wx.AcceleratorTable = AcceleratorTable

_browser = wx.LaunchDefaultBrowser


def LaunchDefaultBrowser(url, *a):
    if url.startswith("file://"):
        url = pathlib.Path(url[len("file://"):]).resolve().as_uri()
    return _browser(url, *a)


wx.LaunchDefaultBrowser = LaunchDefaultBrowser

# toolbar spacer tools with odd bitmap sizes: use the control-based fallback
try:
    del wx.EmptyBitmapRGBA
except AttributeError:
    pass


class App(wx.App):
    def OnInit(self):
        # the program's colours are made for the light appearance
        if hasattr(self, "SetAppearance") and hasattr(wx.PyApp, "Light"):
            try:
                self.SetAppearance(wx.PyApp.Light)
            except Exception:
                pass
        return True


wx.App = App
'''

LAUNCHER = r'''#!/usr/bin/env python3
"""Starts the converted dictionary (written by the build script)."""
import os
import sys

HERE = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)          # the program reads its resource folder from sys.path[0]
os.chdir(HERE)

import py2compat                  # noqa: E402
import datamodule                 # noqa: E402

datamodule.data = py2compat.repair_tag_collisions(datamodule.data, datamodule.tags)

if os.environ.get("FHWB_NO_GUI") != "1":
    import wxcompat               # noqa: E402,F401
    import app                    # noqa: E402,F401  (the program runs on import)
'''

SELFTEST = r'''
"""Checks the converted search engine and renderer without opening a window."""
import os, sys
os.environ["FHWB_NO_GUI"] = "1"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import Wurdboek  # noqa: F401  (loads and repairs the data)
import search, render
n = search.setFilter(None, ignorecase=True, dia=True)
assert n > 50000, n
errors = 0
for i in range(n):
    try:
        render.art2html(i)
    except Exception:
        errors += 1
first = search.getLemma(search.lemmaByPrefix("a"))
hit = search.fullTextSearch("a", True, True, False, False, False, True, None, False)
print("    self-test: %d entries, %d render errors, first entry %r, full-text search %s"
      % (n, errors, first, "ok" if hit is not None else "FAILED"))
sys.exit(1 if errors or hit is None else 0)
'''

SUPPORT_FILES = {
    "py2compat.py": PY2COMPAT,
    "cStringIO.py": CSTRINGIO,
    "wxversion.py": WXVERSION,
    "wxcompat.py": WXCOMPAT,
    "Wurdboek.py": LAUNCHER,
    "selftest.py": SELFTEST,
}


# ---------------------------------------------------------------------------
# Stage 3: test, Stage 4: package
# ---------------------------------------------------------------------------
def selftest():
    say("Testing the converted dictionary (all entries)")
    subprocess.check_call([sys.executable, os.path.join(SRC, "selftest.py")])


def make_icon():
    ico = os.path.join(SRC, "dictionary.ico")
    icns = os.path.join(WORK, "Wurdboek.icns")
    if not os.path.exists(ico) or sys.platform != "darwin":
        return None
    iconset = os.path.join(WORK, "Wurdboek.iconset")
    shutil.rmtree(iconset, ignore_errors=True)
    os.makedirs(iconset)
    png = os.path.join(WORK, "icon.png")
    subprocess.check_call(["sips", "-s", "format", "png", ico, "--out", png], stdout=subprocess.DEVNULL)
    for size in (16, 32, 64, 128, 256, 512):
        for scale in (1, 2):
            px = size * scale
            name = "icon_%dx%d%s.png" % (size, size, "@2x" if scale == 2 else "")
            subprocess.check_call(["sips", "-z", str(px), str(px), png, "--out", os.path.join(iconset, name)],
                                  stdout=subprocess.DEVNULL)
    subprocess.check_call(["iconutil", "-c", "icns", iconset, "-o", icns])
    return icns


def build_app():
    say("Building %s.app with PyInstaller (a few minutes)" % APP_NAME)
    datas = []
    for name in os.listdir(SRC):
        p = os.path.join(SRC, name)
        if os.path.isdir(p) and name not in ("__pycache__",):
            datas += ["--add-data", "%s:%s" % (p, name)]
        elif name.lower().endswith((".png", ".ico", ".html")):
            datas += ["--add-data", "%s:." % p]
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
           "--name", APP_NAME, "--osx-bundle-identifier", BUNDLE_ID,
           "--paths", SRC, "--hidden-import", "wxcompat", "--hidden-import", "app",
           "--distpath", os.path.join(WORK, "dist"), "--workpath", os.path.join(WORK, "pyi-build"),
           "--specpath", WORK] + datas
    try:
        icns = make_icon()
    except Exception:
        icns = None                            # the app just gets the default icon
    if icns:
        cmd += ["--icon", icns]
    subprocess.check_call(cmd + [os.path.join(SRC, "Wurdboek.py")])
    app = os.path.join(WORK, "dist", APP_NAME + ".app")
    if sys.platform == "darwin" and os.path.isdir(app):
        plist = os.path.join(app, "Contents", "Info.plist")
        subprocess.check_call(["plutil", "-replace", "NSRequiresAquaSystemAppearance", "-bool", "YES", plist])
        subprocess.check_call(["codesign", "--force", "--deep", "--sign", "-", app])
    return app


def main():
    ap = argparse.ArgumentParser(description="Build a macOS app of the Frysk Hanwurdboek from the original Linux edition.")
    ap.add_argument("--archive", help="use an already downloaded fhwb.tar.gz instead of downloading")
    ap.add_argument("--no-app", action="store_true", help="only convert and test; run with fhwb-build/src/Wurdboek.py")
    args = ap.parse_args()

    ensure_venv()
    archive = get_archive(args.archive)
    check_archive(archive)
    convert(archive)
    selftest()
    if args.no_app:
        say("Done. Start it with:\n    %s %s" % (os.path.join(VENV, "bin", "python"), os.path.join(SRC, "Wurdboek.py")))
        return
    app = build_app()
    say("Done: %s\n    Drag it into your Applications folder." % app)


if __name__ == "__main__":
    main()
