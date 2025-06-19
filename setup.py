import PyInstaller.__main__
import os
import shutil
import certifi
APP_NAME = "VtQube-v1.0.5"
MAIN_SCRIPT = "src/main.py"

ADDITIONAL_DATA_FILES = [
    ('.env', '.'), 
    ('assets/alert.wav', '.'),
    ('assets/icon.jpg', '.'),

    ('src/config.py', '.'),
    ('src/database.py', '.'),
    ('src/instrument_fetch_thread.py', '.'),
    ('src/logs.py', '.'),
    ('src/monitoring.py', '.'),
    ('src/quotation_widget.py', '.'),
    ('src/stock_management.py', '.'),
    ('src/volume_data.py', '.'),
    ('src/trading_dialog.py', '.'),
    ('src/ui_elements.py', '.'),
    ('src/utils.py', '.'),

    (certifi.where(), '.'),
]

ADDITIONAL_DATA_FILES = [f for f in ADDITIONAL_DATA_FILES if f]

def clean_build():
    print("Cleaning up previous build directories...")
    if os.path.exists('build'):
        shutil.rmtree('build')
    if os.path.exists('dist'):
        shutil.rmtree('dist')
    if os.path.exists(f'{APP_NAME}.spec'):
        os.remove(f'{APP_NAME}.spec')
    print("Cleanup complete.")

def run_pyinstaller():
    print(f"Building {APP_NAME} with PyInstaller...")

    pyinstaller_args = [
        MAIN_SCRIPT,
        '--name', APP_NAME,
        '--onefile',
        '--windowed',
        '--clean',
        '--hidden-import', 'kiteconnect',
        '--hidden-import', 'kiteconnect.exceptions',
        '--hidden-import', 'kiteconnect.utils',
        '--hidden-import', 'requests',
        '--hidden-import', 'urllib3',
        '--hidden-import', 'certifi',
        '--hidden-import', 'requests.packages.urllib3.contrib.pyopenssl',
        '--hidden-import', 'idna.idnadata',

        '--hidden-import', 'openpyxl.workbook.workbook',
        '--hidden-import', 'openpyxl.styles.colors',
        '--hidden-import', 'openpyxl.styles.fills',
        '--hidden-import', 'openpyxl.styles.borders',
        '--hidden-import', 'openpyxl.styles.alignment',
        '--hidden-import', 'openpyxl.cell.cell',
        '--hidden-import', 'openpyxl.worksheet.worksheet',
    ]

    for src, dest in ADDITIONAL_DATA_FILES:
        pyinstaller_args.extend(['--add-data', f'{src}{os.pathsep}{dest}'])
    PyInstaller.__main__.run(pyinstaller_args)
    print(f"Build process finished. Executable can be found in the 'dist' directory.")

if __name__ == "__main__":
    clean_build()
    run_pyinstaller()