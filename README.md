# SQL Splitter

Cross-platform SQL splitting tool. The recommended desktop app is now the Tauri
version, which bundles a Rust backend and does not require end users to install
Python.

## Tauri Desktop App

Development mode:

```bash
npm install
npm run tauri:dev
```

Build a macOS app on macOS:

```bash
npm run tauri:build:mac
```

or:

```bash
./build_macos.sh
```

Build a portable Windows executable on Windows:

```bash
npm run tauri:build:windows
```

or:

```bat
build_windows.bat
```

The portable executable is created at:

```text
src-tauri/target/release/sql_splitter_tauri.exe
```

`build_windows.bat` also copies it to:

```text
SQL拆分工具.exe
```

If you need a Windows installer instead, run:

```bash
npm run tauri:build:windows:installer
```

Build artifacts are OS-specific. Build on macOS for macOS users and on Windows
for Windows users. The generic `npm run tauri:build` currently builds the macOS
`.app` bundle.

This repository also includes `.github/workflows/build-desktop.yml`. After pushing
the project to GitHub, run the workflow manually or push a `v*` tag to build macOS
`.app` and Windows portable `.exe` artifacts on native runners.

The Rust backend splits at SQL statement boundaries and writes balanced output
parts without loading the whole SQL file into memory.

## Python Fallback

## Run the GUI

This source-code mode requires Python:

```bash
python3 sql_split_gui.py
```

On Windows, use:

```bat
python sql_split_gui.py
```

## Command Line

Split one SQL file into 5 balanced parts:

```bash
python3 sql_splitter.py lsjmcs0429_backup_202605131538.sql --parts 5
```

Choose the output folder:

```bash
python3 sql_splitter.py lsjmcs0429_backup_202605131538.sql --parts 5 --output-dir output_sql
```

## Behavior

- Splits at SQL statement boundaries, not arbitrary lines.
- Keeps semicolons inside quoted strings and SQL comments intact.
- Balances output files by statement byte size.
- Uses only Python standard library modules, so no install step is required.

## Python Packaging Fallback

End users do not need Python if you package the app first. The packaging machine needs
Python and PyInstaller, then it creates a native executable that includes the Python
runtime.

Build the Python fallback on macOS:

```bash
python3 -m pip install -r requirements-build.txt
python3 build_app.py
```

The macOS app will be created under `dist/SQL-Splitter.app`.

Build the Python fallback on Windows:

```bat
python -m pip install -r requirements-build.txt
python build_app.py --onefile
```

The Windows executable will be created under `dist`.

Build artifacts are OS-specific. Build on macOS for macOS users and on Windows for
Windows users.
