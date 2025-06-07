from PyQt5.QtCore import QThread, pyqtSignal
import sqlite3
from database import DatabaseManager
from kiteconnect import KiteConnect # Assuming this is correctly imported or handled
from typing import List, Any
import pandas as pd # Import pandas for DataFrame operations
import re
import traceback

# Import InstrumentManager to use its type hints, but don't create instances here
# from stock_management import InstrumentManager # This import is not needed for object creation here

class InstrumentFetchThread(QThread):
    fetch_started = pyqtSignal(str)
    fetch_finished = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    all_fetches_complete = pyqtSignal()

    # Modified __init__ to accept actual InstrumentManager instances
    def __init__(self, instrument_managers: List[Any], db_path: str, api_key: str, access_token: str):
        super().__init__()
        self.instrument_managers = instrument_managers # List of InstrumentManager objects
        self.db_path = db_path
        self.api_key = api_key
        self.access_token = access_token
        self.kite = None

    def run(self):
        try:
            self.fetch_started.emit("Connecting to KiteConnect for instrument fetch...")
            
            # Initialize KiteConnect in the thread
            self.kite = KiteConnect(api_key=self.api_key)
            self.kite.set_access_token(self.access_token)
            raw_instruments = self.kite.instruments() # This is the call that fetches from Kite
            df = pd.DataFrame(raw_instruments) # Convert to DataFrame
            print(f"DEBUG: InstrumentFetchThread - Fetched {len(df)} raw instruments from KiteConnect.")

            if df.empty:
                print("WARNING: InstrumentFetchThread - No raw instruments fetched from KiteConnect. Check API credentials or market status.")
                self.error_occurred.emit("No instruments fetched from KiteConnect. Check API credentials or market status.")
                return

            for manager in self.instrument_managers:
                print(f"DEBUG: InstrumentFetchThread - Processing instruments for manager type: {manager.instrument_type}")
                manager.set_kite_instance(self.kite) # Ensure manager has the kite instance for its own internal calls if any

                manager.fetch_all_tradable_instruments(raw_instruments_df=df)
                pass


            self.fetch_finished.emit("All tradable instruments fetched and saved.")
            self.all_fetches_complete.emit()

        except Exception as e:
            error_msg = f"Error fetching instruments: {traceback.format_exc()}"
            self.error_occurred.emit(error_msg)
            print(error_msg) # Print to console for debugging
        finally:
            print(f"DEBUG: InstrumentFetchThread - Thread finished.")