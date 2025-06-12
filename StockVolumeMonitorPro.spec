# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['src\\main.py'],
    pathex=[],
    binaries=[],
    datas=[('.env', '.'), ('assets/alert.wav', '.'), ('assets/icon.jpg', '.'), ('src/config.py', '.'), ('src/database.py', '.'), ('src/instrument_fetch_thread.py', '.'), ('src/logs.py', '.'), ('src/monitoring.py', '.'), ('src/quotation_widget.py', '.'), ('src/stock_management.py', '.'), ('src/volume_data.py', '.'), ('src/trading_dialog.py', '.'), ('src/ui_elements.py', '.'), ('src/utils.py', '.'), ('C:\\Users\\anshv\\AppData\\Local\\Programs\\Python\\Python312\\Lib\\site-packages\\certifi\\cacert.pem', '.')],
    hiddenimports=['kiteconnect', 'kiteconnect.exceptions', 'kiteconnect.utils', 'requests', 'urllib3', 'certifi', 'requests.packages.urllib3.contrib.pyopenssl', 'idna.idnadata', 'openpyxl.workbook.workbook', 'openpyxl.styles.colors', 'openpyxl.styles.fills', 'openpyxl.styles.borders', 'openpyxl.styles.alignment', 'openpyxl.cell.cell', 'openpyxl.worksheet.worksheet'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='StockVolumeMonitorPro',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
