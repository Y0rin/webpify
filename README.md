# WebPify

Batch-converts a folder of `.png` images to `.webp` (quality 82, transparency kept).
It trims empty transparent edges and works out the right size on its own.

## Quick start (no install)

Download **`WebPify.exe`** from the
[latest release](https://github.com/Y0rin/webpify/releases/latest) and double-click it.
No Python needed.

Windows may show "Windows protected your PC" the first time, because the app isn't
code-signed. Click **More info → Run anyway**.

## Install from source

0. Get the files: on GitHub click **Code → Download ZIP** and unzip it, or run
   ```
   git clone https://github.com/Y0rin/webpify.git
   ```
1. Install Python 3 (skip if `python --version` works):
   ```
   winget install Python.Python.3.12
   ```
   Open a new terminal afterwards so `python` is on your PATH.
2. Install Pillow and the window theme:
   ```
   python -m pip install -r requirements.txt
   ```
   (The theme, `sv-ttk`, is optional. Without it the window still works, just with the plain look.)

## Canva workflow

Export from Canva with fixed canvas sizes:

| Canva canvas | Treated as | Scale factor | Example |
|---|---|---|---|
| 600 × 600 (anything under 1000 px wide) | object (eyes, nose, ears…) | 300 ÷ 600 = **0.5** | visible ear 300×450 → 150×225 |
| 1200 × 1200 (1000 px wide or more) | background (face, large drop areas) | 960 ÷ 1200 = **0.8** | visible face 1000×800 → 800×640 |

For each PNG the converter:

1. reads the full canvas width and picks the scale factor (never above 1.0, so nothing is enlarged),
2. trims the transparent edges,
3. resizes the **trimmed** image by that factor.

The factor comes from the full canvas, not the trimmed part, so every part keeps its
drawn size relative to the others. A brow that took a thin strip of its 600 page stays
smaller than an ear that filled most of it.

Then the whole job is: pick the folder, press Convert.

## Use the window (easiest)

Double-click **`Open WebPify.bat`**. In the window:

1. **Convert:** choose **Folder** (every PNG in a folder) or **Image(s)** (pick one or
   more PNGs), then click Browse.
2. **Save to:** pick where the .webp files should go.
3. **Size:** *Auto* (default, see above) or *Exact width* (e.g. 560 for covers).
   Exact width is applied after trimming.
4. **Name prefix:** e.g. `p_001_`. The grey preview shows what the names will look like.
5. **Trim transparent edges:** on by default. Images without transparency are never trimmed.
6. Tick **Overwrite** to redo files that already exist, then click **Convert**.

While converting, the bar shows progress and an estimated time left. The table shows,
for each file: original size, type (object / background / exact width), scale factor,
trimmed size, final size and KB before/after. **Open** opens the output folder in Explorer.

**⚙ Settings** (top right) opens a panel with:

- **Night mode:** dark or light theme.
- **Text size:** 80–200%. 100% matches your Windows display scaling. The size stays
  fixed when you resize or maximise the window. Shortcuts: `Ctrl +`, `Ctrl −`, `Ctrl 0`.

Press `Esc` or click outside the panel to close it. Your last folders, options, theme,
text size and window size (including maximised) are remembered in `settings.json`.

## Build the .exe yourself

Double-click **`build_exe.bat`**. It installs PyInstaller and creates `dist\WebPify.exe`.
The .exe stores its settings in `%APPDATA%\WebPify\settings.json`.

## Run from the command line

```
python convert.py SOURCE_FOLDER_OR_PNG OUTPUT_FOLDER [--width N] [--prefix TEXT] [--no-trim] [--force]
```

| Option | What it does |
|---|---|
| *(default)* | Auto size + trim, as described above. |
| `--width N` | Resizes the (trimmed) image to exactly N px wide instead of Auto. |
| `--prefix TEXT` | Adds TEXT to the start of every output name. |
| `--no-trim` | Keeps the transparent edges. |
| `--force` | Overwrites files that already exist in the output folder (normally they are skipped). |

The output folder is created if it doesn't exist.

### Output names

Prefix + original name, lowercased, spaces and dashes turned into underscores,
other special characters removed:

`Left Ear-2.png` with `--prefix p_001_` → `p_001_left_ear_2.webp`

## Examples

Worksheet parts and backgrounds, with a page prefix:
```
python convert.py "C:\Users\me\Downloads\parts" "C:\output" --prefix p_001_
```

A cover image at exactly 560 px wide:
```
python convert.py "C:\Users\me\Downloads\cover" "C:\output" --width 560
```

Re-convert everything, replacing existing files:
```
python convert.py "C:\Users\me\Downloads\parts" "C:\output" --prefix p_001_ --force
```

## Output

```
OK    Ears.png -> p_001_ears.webp  600x600 object x0.50  trimmed 300x450 -> 150x225  2.4 KB -> 0.2 KB
OK    Face BG.png -> p_001_face_bg.webp  1200x1200 background x0.80  trimmed 1000x800 -> 800x640  7.4 KB -> 1.0 KB
SKIP  Nose.png -> p_001_nose.webp (exists, use --force)

Converted 2, skipped 1, failed 0.
Total: 9.8 KB -> 1.2 KB
```
