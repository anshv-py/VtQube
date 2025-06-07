import PyInstaller.__main__
import os
import shutil
import certifi # Import certifi to get its path

# Define the name of your executable
APP_NAME = "StockVolumeMonitorPro"

# Define the main script file
MAIN_SCRIPT = "src/main.py"

# Define additional data files to include (e.g., .env, alert.wav, other Python modules)
# Paths are relative to the script being run (setup.py)
ADDITIONAL_DATA_FILES = [
    ('.env', '.'),  # Include .env file in the root of the executable directory
    ('assets/alert.wav', '.'), # Include alert.wav in the root
    ('assets/icon.jpg', '.'), # Include icon.jpg in the root
    
    # Include all Python source files from the 'src' directory
    ('src/config.py', '.'),
    ('src/database.py', '.'),
    ('src/instrument_fetch_thread.py', '.'),
    ('src/logs.py', '.'),
    ('src/monitoring.py', '.'),
    ('src/quotation_widget.py', '.'),
    ('src/stock_management.py', '.'),
    ('src/stock_volume_monitor.py', '.'),
    ('src/trading_dialog.py', '.'),
    ('src/ui_elements.py', '.'),
    ('src/utils.py', '.'),
    # Conditionally include auto_trade_widget.py if it exists (as per main.py's try-except)
    ('src/auto_trade_widget.py', '.') if os.path.exists('src/auto_trade_widget.py') else None,

    # Explicitly include the certifi CA bundle for SSL verification (important for requests/kiteconnect)
    (certifi.where(), '.'),
]

# Filter out None entries in case conditional files don't exist
ADDITIONAL_DATA_FILES = [f for f in ADDITIONAL_DATA_FILES if f]

# Clean up previous build directories
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

    # Construct the PyInstaller command arguments
    pyinstaller_args = [
        MAIN_SCRIPT,
        '--name', APP_NAME,
        '--onefile',  # Create a single executable file
        '--windowed', # Hide the console window (for GUI apps)
        '--clean',    # Clean PyInstaller cache and remove temporary files

        # Add explicit hidden imports for potentially problematic libraries
        '--hidden-import', 'kiteconnect',
        '--hidden-import', 'kiteconnect.exceptions',
        '--hidden-import', 'kiteconnect.utils',
        '--hidden-import', 'requests',
        '--hidden-import', 'urllib3',
        '--hidden-import', 'certifi',
        '--hidden-import', 'requests.packages.urllib3.contrib.pyopenssl',
        '--hidden-import', 'idna.idnadata',

        # openpyxl: Ensure necessary submodules for Excel export are included
        '--hidden-import', 'openpyxl.workbook.workbook',
        '--hidden-import', 'openpyxl.styles.colors',
        '--hidden-import', 'openpyxl.styles.fills',
        '--hidden-import', 'openpyxl.styles.borders',
        '--hidden-import', 'openpyxl.styles.alignment',
        '--hidden-import', 'openpyxl.cell.cell',
        '--hidden-import', 'openpyxl.worksheet.worksheet',
    ]

    # Add all data files defined in ADDITIONAL_DATA_FILES
    for src, dest in ADDITIONAL_DATA_FILES:
        # PyInstaller expects source;destination_in_bundle
        pyinstaller_args.extend(['--add-data', f'{src}{os.pathsep}{dest}'])

    PyInstaller.__main__.run(pyinstaller_args)

    print(f"Build process finished. Executable can be found in the 'dist' directory.")

if __name__ == "__main__":
    clean_build()
    run_pyinstaller()