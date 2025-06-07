import sqlite3
import pandas as pd
from typing import List, Dict, Any, Optional, Tuple
import re
import traceback

from PyQt5.QtCore import Qt, QStringListModel, pyqtSignal, QObject
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QComboBox, QCompleter,
    QAbstractItemView, QGroupBox
)
from PyQt5.QtGui import QKeyEvent

# Assuming KiteConnect is available in the environment
try:
    from kiteconnect import KiteConnect
except ImportError:
    KiteConnect = None # Set to None if not available

from database import DatabaseManager # Ensure this import is correct

# Define a curated list of approximately top 400 Indian large-cap and prominent mid-cap stocks.
# This list is based on general market knowledge and includes companies across various sectors.
# It is not dynamically generated based on real-time market capitalization or volume.
DEFAULT_TOP_INDIAN_STOCKS = [
    # Nifty 50 components (representative list)
    "RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY", "HINDUNILVR", "ITC", "LT",
    "SBIN", "BHARTIARTL", "KOTAKBANK", "AXISBANK", "MARUTI", "ASIANPAINT",
    "BAJFINANCE", "NESTLEIND", "SUNPHARMA", "ULTRACEMCO", "TITAN", "GRASIM",
    "TECHM", "INDUSINDBK", "HCLTECH", "WIPRO", "DRREDDY", "CIPLA", "ADANIPORTS",
    "POWERGRID", "NTPC", "JSWSTEEL", "HINDALCO", "BPCL", "IOC", "ONGC",
    "GAIL", "SHREECEM", "UPL", "EICHERMOT", "TATAMOTORS", "HEROMOTOCO", "BAJAJ-AUTO",
    "COALINDIA", "DIVISLAB", "APOLLOHOSP", "SBILIFE", "HDFCLIFE", "BRITANNIA",
    "GODREJCP", "DABUR", "PIDILITIND", "SIEMENS", "BOSCHLTD", "M&M", "IRCTC", "DMART",
    "PIDILITIND", "BERGEPAINT", "PIIND", "NAUKRI", "GLAND", "MUTHOOTFIN", "COLPAL",
    "PGHH", "GILLETTE", "ATGL", "ADANIENSOL", "ADANIGREEN", "ADANITRANS",
    # Additional prominent large & mid-cap stocks
    "LICI", "PATANJALI", "HAL", "BEL", "BHEL", "COFORGE", "PERSISTENT", "MPHASIS",
    "LTIM", "POLYCAB", "DIXON", "TVSMOTOR", "ASHOKLEY", "AMBUJACEM", "ACC", "IDBI",
    "CANBK", "PNB", "BANKBARODA", "UNIONBANK", "FEDERALBNK", "INDIGO", "SPICEJET",
    "ZEEL", "SUNTV", "RAINBOW", "MAXHEALTH", "FORTIS", "METROPOLIS", "LALPATHLAB",
    "CDSL", "MCX", "INDIAMART", "JUSTDIAL", "NYKAA", "PAYTM", "ZOMATO", "DELHIVERY",
    "POLICYBZR", "MINDTREE", "LAURUSLABS", "GRANULES", "IPCALAB", "ALKEM", "TORRENTPHARM",
    "BIOCON", "AUROPHARMA", "CADILAHC", "NATCOPHARM", "SUZLON", "YESBANK", "IDFCFIRSTB",
    "RECLTD", "PFC", "HDFC", "ICICI_PRU", "SBI_LIFE", "BANDHANBNK", "AUBANK",
    "CUB", "DCBBANK", "RBLBANK", "IIFLWAM", "ANGELONE", "MOTILALOFS", "BLUEDART",
    "CONCOR", "IDFC", "NHPC", "NBCC", "IRB", "GMRINFRA", "WELSPUNIND", "JKCEMENT",
    "RAMCOCEM", "DALMIABARAT", "ULTRACEMCO", "ATS", "OBEROIRLTY", "PRESTIGE",
    "GODREJPROP", "PHOENIXLTD", "SOBHA", "DLF", "IGL", "GUJGASLTD", "MGL",
    "PETRONET", "GSPL", "AIAENG", "GRAPHITE", "HEG", "GRINDWELL", "SKFINDIA",
    "TIMKEN", "CUMMINSIND", "WABCOINDIA", "BHARATFORG", "SONACOMS", "ENDURANCE",
    "AMARAJABAT", "EXIDEIND", "CEATLTD", "MRF", "APOLLOTYRE", "JKTYRE", "BALKRISIND",
    "ESCORTS", "CIEAUTOMOT", "GNAAXLES", "MAHINDCIE", "SUNDRMFAST", "TVSSUPER",
    "MOTHERSON", "BOSCHLTD", "SUPRAJIT", "JBMAUTO", "TATACHEM", "UPL", "SUMICHEM",
    "COROMANDEL", "DEEPAKFERT", "GUJFLUORO", "NAVINFLUOR", "GODREJAGRO", "VENKEYS",
    "AVANTIFEED", "CCL", "TATACOFFEE", "MCDOWELL-N", "UNITEDBREW", "RADICO", "VBL",
    "JUBILANTFG", "WESTLIFE", "DEVYANI", "BURGERKING", "INDIANHOTEL", "ECLERX",
    "TATAELXSI", "KPITTECH", "TATACOMM", "RAILTEL", "ROUTE", "AFFLE", "INDIACEM",
    "JKLAKSHMI", "BIRLACORPN", "STARCEMENT", "RAMCOIND", "JKPAPER", "BALAMINES",
    "FINEORG", "AETHER", "TATAMETALI", "RATNAMANI", "APLAPOLLO", "JINDALSTEL",
    "SAIL", "JSPL", "NMDC", "MOIL", "KIOCL", "ADANIENT", "ADANIPOWER", "JUBLPHARMA",
    "GRANULES", "NATCOPHARM", "IPCALAB", "DREAMFOLKS", "LATENTVIEW", "MAPMYINDIA",
    "PBFINTECH", "FRESHWORKS", "DELHIVERY", "TRACXN", "KAYNES", "SYRMA", "ELIN",
    "NETWEB", "IDEA", "VODAFONE", "INDUS_TOWR", "OBEROIRLTY", "BRIGADE", "DLF",
    "PRESTIGE", "GODREJPROP", "MACROTECH", "SOBHA", "SFL", "SUNDRAMFIN", "CHOLAFIN",
    "L&TFH", "IDFCFIRSTB", "PERSISTENT", "ANGELONE", "MCX", "CDSL", "CAMS", "NSDL"
]


class InstrumentManager(QObject):
    user_instruments_changed = pyqtSignal() # Signal emitted when user instruments are added/removed

    def __init__(self, db_manager: DatabaseManager, instrument_type: str, user_table_name: str):
        super().__init__()
        self.db_manager = db_manager
        self.instrument_type = instrument_type
        self.user_table_name = user_table_name
        self.kite = None
        
        self.exchange = self._get_default_exchange(instrument_type)
    
        # all_tradable_symbols will store a list of tuples: (tradingsymbol, instrument_type, exchange, instrument_token, expiry, strike)
        self.all_tradable_symbols: List[Tuple[str, str, str, int, Optional[str], Optional[float]]] = []
        self.load_all_tradable_instruments_from_db() # Initial load from DB at startup

        self.user_selected_symbols: List[str] = []
        self.load_user_instruments()

        print(f"DEBUG: InstrumentManager ({self.instrument_type}) initialized. User table: {self.user_table_name}, Exchange: {self.exchange}")


    def _get_default_exchange(self, instrument_type: str) -> str:
        """Returns the default exchange for a given instrument type."""
        if instrument_type == 'EQ':
            return 'NSE'
        elif instrument_type in ['FUT', 'OPT']:
            return 'NFO'
        return ''


    def set_kite_instance(self, kite_instance: KiteConnect):
        """Sets the KiteConnect instance for fetching instruments."""
        self.kite = kite_instance
        print(f"DEBUG: InstrumentManager ({self.instrument_type}) - set_kite_instance called. Kite instance: {self.kite is not None}")

    def fetch_all_tradable_instruments(self, raw_instruments_df: pd.DataFrame):
        """
        Filters and saves tradable instruments from a raw DataFrame to the database.
        This method is intended to be called from a separate thread (e.g., InstrumentFetchThread).
        """
        if self.kite is None:
            print(f"ERROR: InstrumentManager ({self.instrument_type}) - KiteConnect instance is None. Cannot fetch tradable instruments.")
            return

        # Create a new DB connection for this thread to ensure thread safety
        thread_db_manager = DatabaseManager(self.db_manager.db_path)
        
        try:
            print(f"DEBUG: InstrumentManager ({self.instrument_type}) - Created thread-local DatabaseManager for saving.")

            # Filter the raw DataFrame based on this manager's instrument type and exchange
            filtered_df = self.filter_instruments(raw_instruments_df)
            print(f"DEBUG: InstrumentManager ({self.instrument_type}) - Filtered raw DataFrame. Count: {len(filtered_df)}.")
            
            # Convert filtered DataFrame to list of tuples for bulk saving
            # Ensure the order and content match the bulk_save_tradable_instruments expectation
            instruments_to_save = [
                (row['tradingsymbol'], row['instrument_type'], row['exchange'],
                 row['instrument_token'], row['expiry'], row['strike']) # expiry and strike might be None
                for index, row in filtered_df.iterrows()
            ]
            
            print(f"DEBUG: InstrumentManager ({self.instrument_type}) - Prepared {len(instruments_to_save)} instruments for saving to DB.")
            if instruments_to_save:
                print(f"DEBUG: InstrumentManager ({self.instrument_type}) - First 5 instruments to save: {instruments_to_save[:5]}")

            print(f"DEBUG: InstrumentManager ({self.instrument_type}) - Cleared existing tradable instruments of type '{self.instrument_type}' from DB.")

            # Bulk save to database
            if instruments_to_save:
                thread_db_manager.bulk_save_tradable_instruments(instruments_to_save)
                print(f"DEBUG: InstrumentManager ({self.instrument_type}) - Successfully bulk saved {len(instruments_to_save)} instruments to DB.")
            else:
                print(f"WARNING: InstrumentManager ({self.instrument_type}) - No instruments to save after filtering for type '{self.instrument_type}'.")

        except Exception as e:
            # Emit error to main thread for UI notification
            print(f"ERROR: InstrumentManager ({self.instrument_type}) - Error during instrument fetch and save: {traceback.format_exc()}")
            # Consider emitting an error signal here if needed for UI feedback
        finally:
            thread_db_manager.close() # Ensure DB connection is closed
            print(f"DEBUG: InstrumentManager ({self.instrument_type}) - Closed thread-local DatabaseManager connection.")


    def filter_instruments(self, raw_instruments_df: pd.DataFrame) -> pd.DataFrame:
        """
        Filters the raw DataFrame of instruments based on this manager's
        instrument_type and exchange. Handles variations for options (CE/PE).
        Ensures necessary columns exist before filtering.
        """
        # Ensure all necessary columns are present, adding them with None/default if missing
        for col in ['instrument_type', 'exchange', 'tradingsymbol', 'instrument_token', 'name', 'expiry', 'strike']:
            if col not in raw_instruments_df.columns:
                raw_instruments_df[col] = None
                print(f"WARNING: Missing column '{col}' in raw_instruments_df. Added with None values.")

        filtered_df = pd.DataFrame() # Initialize empty DataFrame

        # Standardize casing for comparison
        raw_instruments_df['instrument_type_upper'] = raw_instruments_df['instrument_type'].str.upper()
        raw_instruments_df['exchange_upper'] = raw_instruments_df['exchange'].str.upper()
        
        if self.instrument_type == 'EQ':
            filtered_df = raw_instruments_df[
                (raw_instruments_df['instrument_type_upper'] == 'EQ') &
                (raw_instruments_df['exchange_upper'] == self.exchange.upper())
            ].copy()
        elif self.instrument_type == 'FUT':
            filtered_df = raw_instruments_df[
                (raw_instruments_df['instrument_type_upper'] == 'FUT') &
                (raw_instruments_df['exchange_upper'] == self.exchange.upper())
            ].copy()
        elif self.instrument_type == 'OPT':
            # For options, instrument_type can be 'CE' or 'PE'
            filtered_df = raw_instruments_df[
                (raw_instruments_df['instrument_type_upper'].isin(['CE', 'PE'])) &
                (raw_instruments_df['exchange_upper'] == self.exchange.upper())
            ].copy()
        else:
            print(f"WARNING: InstrumentManager ({self.instrument_type}) - Unknown instrument_type '{self.instrument_type}' for filtering.")
            return pd.DataFrame() # Return empty if type is unknown

        # Drop the temporary upper-cased columns
        if 'instrument_type_upper' in filtered_df.columns:
            filtered_df = filtered_df.drop(columns=['instrument_type_upper'])
        if 'exchange_upper' in filtered_df.columns:
            filtered_df = filtered_df.drop(columns=['exchange_upper'])

        print(f"DEBUG: InstrumentManager ({self.instrument_type}) - filter_instruments returning {len(filtered_df)} rows.")
        return filtered_df


    def load_all_tradable_instruments_from_db(self):
        """
        Loads all tradable instruments of this manager's type from the database into the in-memory cache.
        This is called at initialization and after a successful instrument fetch.
        """
        self.all_tradable_symbols = self.db_manager.get_all_tradable_instruments(
            instrument_type=self.instrument_type,
            exchange=self.exchange
        )
        print(f"DEBUG: InstrumentManager ({self.instrument_type}) - Loaded {len(self.all_tradable_symbols)} tradable symbols from DB into main thread cache. ID of cache: {id(self.all_tradable_symbols)}")
        if self.all_tradable_symbols:
            print(f"DEBUG: InstrumentManager ({self.instrument_type}) - First 5 loaded tradable symbols: {self.all_tradable_symbols[:min(5, len(self.all_tradable_symbols))]}")


    def get_all_tradable_instruments(self) -> List[Tuple[str, str, str, int, Optional[str], Optional[float]]]:
        """Returns the cached list of all tradable instruments."""
        # This method directly returns the in-memory cache, which is loaded/reloaded from DB
        print(f"DEBUG: InstrumentManager ({self.instrument_type}) - get_all_tradable_instruments called. Returning {len(self.all_tradable_symbols)} instruments from cache. ID of cache: {id(self.all_tradable_symbols)}")
        return self.all_tradable_symbols


    def load_user_instruments(self):
        """Loads user-selected instruments for this manager's type from the database."""
        self.user_selected_symbols = self.db_manager.load_user_instruments(self.user_table_name)
        print(f"DEBUG: InstrumentManager ({self.instrument_type}) - Loaded {len(self.user_selected_symbols)} user instruments from DB.")


    def get_user_selected_symbols(self) -> List[str]:
        """Returns the list of user-selected symbols."""
        return self.user_selected_symbols

    def add_user_instrument(self, symbol: str):
        """Adds a symbol to the user's monitored list and saves to DB."""
        if symbol not in self.user_selected_symbols:
            # Validate if the symbol exists in tradable instruments before adding
            # Need to search through the cached tuples for the symbol
            if not any(inst[0] == symbol for inst in self.all_tradable_symbols):
                QMessageBox.warning(None, "Invalid Symbol", f"'{symbol}' is not a valid tradable {self.instrument_type} symbol. Please select from the available list.")
                return False

            self.db_manager.save_user_instrument(self.user_table_name, symbol)
            self.user_selected_symbols.append(symbol)
            self.user_selected_symbols.sort() # Keep sorted
            self.user_instruments_changed.emit() # Emit signal
            print(f"DEBUG: InstrumentManager ({self.instrument_type}) - Added '{symbol}' to user list.")
            return True
        return False


    def remove_user_instrument(self, symbol: str):
        """Removes a symbol from the user's monitored list and from DB."""
        if symbol in self.user_selected_symbols:
            self.db_manager.remove_user_instrument(self.user_table_name, symbol)
            self.user_selected_symbols.remove(symbol)
            self.user_instruments_changed.emit() # Emit signal
            print(f"DEBUG: InstrumentManager ({self.instrument_type}) - Removed '{symbol}' from user list.")
            return True
        return False

    def set_default_monitored_stocks_if_empty(self, limit: int = 400):
        """
        Sets a default list of top Indian stocks as monitored if the user's list is empty.
        Only applies to 'EQ' instrument type.
        """
        if self.instrument_type == 'EQ' and not self.user_selected_symbols:
            print("DEBUG: InstrumentManager (EQ) - User stocks list is empty. Attempting to set default stocks.")
            
            # Ensure all_tradable_symbols is populated
            if not self.all_tradable_symbols:
                print("DEBUG: InstrumentManager (EQ) - all_tradable_symbols is empty. Attempting to load from DB for default setting.")
                self.load_all_tradable_instruments_from_db()

            if self.all_tradable_symbols:
                # Filter DEFAULT_TOP_INDIAN_STOCKS to only include those present in all_tradable_symbols
                available_default_stocks = []
                # tradable_symbols_set will contain just the trading symbols for quick lookup
                tradable_symbols_set = {inst[0] for inst in self.all_tradable_symbols} 
                
                for default_symbol in DEFAULT_TOP_INDIAN_STOCKS:
                    if default_symbol in tradable_symbols_set:
                        available_default_stocks.append(default_symbol)
                    if len(available_default_stocks) >= limit:
                        break # Stop after reaching the limit

                # Add these symbols to the user's monitored list
                for symbol in available_default_stocks:
                    # Use self.db_manager.save_user_instrument
                    self.db_manager.save_user_instrument(self.user_table_name, symbol)
                    if symbol not in self.user_selected_symbols: # Add to in-memory cache if not already there
                        self.user_selected_symbols.append(symbol)

                self.user_selected_symbols.sort() # Keep sorted
                self.user_instruments_changed.emit() # Notify UI
                print(f"DEBUG: InstrumentManager (EQ) - Set {len(available_default_stocks)} default stocks.")
            else:
                print("DEBUG: InstrumentManager (EQ) - No tradable instruments found in DB after attempting to load for default setting.")
        else:
            print(f"DEBUG: InstrumentManager ({self.instrument_type}) - Not setting default stocks. Either not EQ type or user already has stocks.")


    def get_tradable_instrument_details(self, symbol: str) -> Optional[Tuple[str, str, str, int, Optional[str], Optional[float]]]:
        """
        Retrieves full details for a given trading symbol from the cached tradable instruments.
        Returns None if not found.
        """
        for instrument in self.all_tradable_symbols:
            if instrument[0] == symbol: # instrument[0] is the tradingsymbol
                return instrument
        return None


class InstrumentSelectionWidget(QWidget):
    """
    A reusable widget for managing user-selected instruments (stocks, futures, options).
    Provides search, add, remove functionality, and displays monitored instruments.
    """
    def __init__(self, instrument_manager: InstrumentManager, display_name: str):
        super().__init__()
        self.instrument_manager = instrument_manager
        self.display_name = display_name # e.g., "Stocks", "Futures", "Options"
        
        # Initialize UI components
        self.instrument_search_input = QLineEdit()
        self.add_instrument_button = QPushButton(f"Add {self.display_name}")
        self.completer_model = QStringListModel()
        self.completer = QCompleter(self.completer_model, self)
        self.monitored_instruments_list = QListWidget()

        self.init_ui()

        # Connect signals
        self.instrument_manager.user_instruments_changed.connect(self.update_monitored_list)
        self.instrument_manager.user_instruments_changed.connect(self.populate_all_symbols)


    def populate_all_symbols(self):
        """Populates the autocompleter with all tradable symbols for this manager's type."""
        tradable_symbols = [inst[0] for inst in self.instrument_manager.get_all_tradable_instruments()]
        self.completer_model.setStringList(tradable_symbols)
        print(f"DEBUG: InstrumentSelectionWidget ({self.display_name}) - populate_all_symbols called with {len(tradable_symbols)} symbols.")

    def update_monitored_list(self):
        """Updates the QListWidget with the current user-selected instruments."""
        self.monitored_instruments_list.clear()
        for symbol in self.instrument_manager.get_user_selected_symbols():
            self.monitored_instruments_list.addItem(symbol)
        print(f"DEBUG: InstrumentSelectionWidget ({self.display_name}) - Monitored list updated with {len(self.instrument_manager.get_user_selected_symbols())} symbols.")


    def add_instrument(self):
        """Adds the symbol from the search input to the monitored list."""
        symbol = self.instrument_search_input.text().upper().strip()
        if not symbol:
            QMessageBox.warning(self, "Input Error", "Please enter a symbol to add.")
            return

        # Use the InstrumentManager's add_user_instrument for validation and saving
        if not self.instrument_manager.add_user_instrument(symbol):
            # The add_user_instrument method now shows its own QMessageBox
            return

        self.instrument_search_input.clear()
        QMessageBox.information(self, "Success", f"'{symbol}' added to monitored {self.display_name}.")


    def remove_selected_instruments(self):
        """Removes selected instruments from the monitored list."""
        selected_items = self.monitored_instruments_list.selectedItems()
        if not selected_items:
            QMessageBox.information(self, "No Selection", f"Please select one or more {self.display_name.lower()}s to remove.")
            return

        reply = QMessageBox.question(
            self, "Confirm Removal",
            f"Are you sure you want to remove {len(selected_items)} selected {self.display_name.lower()}(s)?",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            symbols_to_remove = [item.text() for item in selected_items]
            
            for symbol in symbols_to_remove:
                self.instrument_manager.remove_user_instrument(symbol)
            
            QMessageBox.information(self, "Success", f"{len(symbols_to_remove)} {self.display_name.lower()}(s) removed.")

    def init_ui(self):
        """Initializes the UI elements for the instrument selection widget."""
        layout = QVBoxLayout()
        self.setLayout(layout)

        # Search and Add Section
        search_group = QGroupBox(f"Add {self.display_name}")
        search_layout = QHBoxLayout()

        self.instrument_search_input.setPlaceholderText(f"Search for {self.display_name} symbol...")
        search_layout.addWidget(self.instrument_search_input)

        self.instrument_search_input.returnPressed.connect(self.add_instrument)

        search_group.setLayout(search_layout)
        layout.addWidget(search_group)

        # Autocompletion setup
        self.completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.completer.setFilterMode(Qt.MatchContains)
        self.instrument_search_input.setCompleter(self.completer)
        self.populate_all_symbols() # Initial population of completer

        # Monitored Instruments List
        monitored_group = QGroupBox(f"Monitored {self.display_name}")
        monitored_layout = QVBoxLayout()

        self.monitored_instruments_list.setSelectionMode(QAbstractItemView.ExtendedSelection) # Allow multi-selection
        monitored_layout.addWidget(self.monitored_instruments_list)

        monitored_group.setLayout(monitored_layout)
        layout.addWidget(monitored_group)

        self.update_monitored_list()
    
    def keyPressEvent(self, event: QKeyEvent):
        """Handle key press events for the widget, specifically for Delete key."""
        # Check if the event source is the monitored_instruments_list and the key is Delete
        if event.key() == Qt.Key_Delete and self.monitored_instruments_list.hasFocus():
            self.remove_selected_instruments()
            event.accept() # Accept the event to prevent propagation
            return
        super().keyPressEvent(event)