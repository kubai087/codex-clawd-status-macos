# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_all

root = Path(SPECPATH).parent
bleak_data, bleak_bins, bleak_hidden = collect_all("bleak")
serial_data, serial_bins, serial_hidden = collect_all("serial")

a = Analysis(
    [str(root / "packaging/entrypoint.py")],
    pathex=[str(root / "src"), str(root / "vendor/codex-status-LED/scripts")],
    binaries=bleak_bins + serial_bins,
    datas=bleak_data + serial_data,
    hiddenimports=[
        "clawd_status_hub",
        "codex_session_watch",
        "codex_clawd_hook",
        "buddy_clawd_hook",
        "status_arbiter",
        *bleak_hidden,
        *serial_hidden,
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="clawd-status",
    debug=False,
    strip=False,
    upx=False,
    console=True,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="clawd-status",
)
