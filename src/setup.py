import PyInstaller.__main__
import os
import shutil

# Define the name of your executable
APP_NAME = "StockVolumeMonitorPro"

# Define the main script file
MAIN_SCRIPT = "main.py"

# Define additional files to include (e.g., .env, alert.wav)
# These paths are relative to the script being run (setup.py)
ADDITIONAL_FILES = [
    ('.env', '.'),  # Include .env file in the root of the executable directory
    ('alert.wav', '.'), # Include alert.wav in the root
    ('stock_management.py', '.'),
    ('config.py', '.'),
    ('database.py', '.'),
    ('monitoring.py', '.'),
    ('ui_elements.py', '.'),
    ('utils.py', '.'),
    ('logs.py', '.'),
    ('instrument_fetch_thread.py', '.'), # Added
    ('quotation_widget.py', '.'),      # Added
    ('trading_dialog.py', '.'),        # Added
]

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
        '--add-data', f'.env{os.pathsep}.', # Add .env file to the root of the bundle
        '--add-data', f'alert.wav{os.pathsep}.', # Add alert.wav file to the root of the bundle
        '--add-data', f'stock_management.py{os.pathsep}.',
        '--add-data', f'config.py{os.pathsep}.',
        '--add-data', f'database.py{os.pathsep}.',
        '--add-data', f'monitoring.py{os.pathsep}.',
        '--add-data', f'ui_elements.py{os.pathsep}.',
        '--add-data', f'utils.py{os.pathsep}.',
        '--add-data', f'logs.py{os.pathsep}.',
        '--add-data', f'instrument_fetch_thread.py{os.pathsep}.', # Added
        '--add-data', f'quotation_widget.py{os.pathsep}.',      # Added
        '--add-data', f'trading_dialog.py{os.pathsep}.',        # Added
        '--hidden-import', 'openpyxl.workbook.workbook', # Ensure openpyxl is included
        '--hidden-import', 'openpyxl.styles.colors',
        '--hidden-import', 'openpyxl.styles.fills',
        '--hidden-import', 'openpyxl.styles.borders',
        '--hidden-import', 'openpyxl.styles.alignment',
        '--hidden-import', 'openpyxl.cell.cell',
        '--hidden-import', 'openpyxl.worksheet.worksheet',
    ]

    # Add other additional files
    for src, dest in ADDITIONAL_FILES:
        # PyInstaller expects source;destination_in_bundle
        pyinstaller_args.extend(['--add-data', f'{src}{os.pathsep}{dest}'])

    PyInstaller.__main__.run(pyinstaller_args)

    print(f"Build process finished. Executable can be found in the 'dist' directory.")

if __name__ == "__main__":
    clean_build()
    run_pyinstaller()