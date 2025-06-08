from PyQt5.QtCore import QThread, pyqtSignal
from kiteconnect import KiteConnect
from typing import List, Any
import pandas as pd
import traceback

class InstrumentLoadThread(QThread):
    data_ready = pyqtSignal(list)
    error_occurred = pyqtSignal(str)

    def __init__(self, manager):
        super().__init__()
        self.manager = manager

    def run(self):
        try:
            instruments = self.manager.get_all_tradable_instruments()
            self.data_ready.emit(instruments)
        except Exception as e:
            self.error_emit(f"Error loading instruments: {str(e)}")
class InstrumentFetchThread(QThread):
    fetch_started = pyqtSignal(str)
    fetch_finished = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    all_fetches_complete = pyqtSignal()

    def __init__(self, instrument_managers: List[Any], db_path: str, api_key: str, access_token: str):
        super().__init__()
        self.instrument_managers = instrument_managers
        self.db_path = db_path
        self.api_key = api_key
        self.access_token = access_token
        self.kite = None

    def run(self):
        try:
            self.fetch_started.emit("Connecting to KiteConnect for instrument fetch...")
            
            self.kite = KiteConnect(api_key=self.api_key)
            self.kite.set_access_token(self.access_token)
            raw_instruments = self.kite.instruments()
            df = pd.DataFrame(raw_instruments)

            if df.empty:
                self.error_occurred.emit("No instruments fetched from KiteConnect. Check API credentials or market status.")
                return

            for manager in self.instrument_managers:
                manager.set_kite_instance(self.kite)

                manager.fetch_all_tradable_instruments(raw_instruments_df=df)
                pass


            self.fetch_finished.emit("All tradable instruments fetched and saved.")
            self.all_fetches_complete.emit()

        except Exception as e:
            error_msg = f"Error fetching instruments: {traceback.format_exc()}"
            self.error_occurred.emit(error_msg)