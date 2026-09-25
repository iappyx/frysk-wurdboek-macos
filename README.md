# Use Frysk Hânwurdboek on macOS

This script turns the Fryske Akademy's free Linux edition of the *Ientalich
Frysk Hânwurdboek* (2016) into a native Mac app. It runs on Apple Silicon and
Intel Macs.

The script contains no code or text from the dictionary itself. It downloads
the original from the Fryske Akademy and converts it on your own Mac.

## Requirements

- macOS
- Python 3.10 – 3.14 (from [python.org](https://www.python.org/downloads/macos/) or Homebrew)
- An internet connection

## Usage

Put `make_frysk_hanwurdboek_mac.py` in an empty folder, open Terminal in that
folder, and run:

```
python3 make_frysk_hanwurdboek_mac.py
```

The first run takes a few minutes. When it finishes, drag
`fhwb-build/dist/Frysk Hanwurdboek.app` into your Applications folder. You can
delete the `fhwb-build` folder afterwards.

### Options

| Option | What it does |
|---|---|
| `--archive path/to/fhwb.tar.gz` | Use a copy you already downloaded instead of downloading it |
| `--no-app` | Only convert and test; run the result with `fhwb-build/venv/bin/python fhwb-build/src/Wurdboek.py` |

## What the script does

1. Creates a private Python environment in `fhwb-build/venv`, so nothing is
   installed system-wide.
2. Installs wxPython, uncompyle6 and PyInstaller into that environment.
3. Downloads `fhwb.tar.gz` from the Fryske Akademy website.
4. Decompiles the original Python 2 program and converts it to Python 3.
5. Checks every dictionary entry before building anything.
6. Builds and signs `Frysk Hanwurdboek.app` for your own Mac.

## If something goes wrong

Run the script again; a failed installation cleans up after itself. If it
still fails, the last lines of the Terminal output explain why.

## License

Made by **iappyx**.

- **The script** is © 2026 iappyx, released under the [MIT License](LICENSE).
- **The dictionary** is © Fryske Akademy and is not covered by that license.
  This script only automates converting your own download of their free Linux
  edition. Use the result according to the Fryske Akademy's terms.

This project is not affiliated with or endorsed by the Fryske Akademy.
