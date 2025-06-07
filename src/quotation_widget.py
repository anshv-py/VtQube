import sqlite3
import pandas as pd
from typing import List, Dict, Any, Optional, Tuple
import re

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QRadioButton, QButtonGroup,
    QComboBox, QFrame, QLineEdit, QMessageBox, QSizePolicy
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor

from database import DatabaseManager
from stock_management import InstrumentManager
from trading_dialog import TradingDialog

SYMBOL_COL_WIDTH = 120
INSTRUMENT_TYPE_COL_WIDTH = 100
EXPIRY_STRIKE_COL_WIDTH = 100
TBQ_TSQ_COL_WIDTH = 80
LTP_OHLC_COL_WIDTH = 90
TRADE_COL_WIDTH = 140


class QuotationWidget(QWidget):
    """
    Widget for displaying live market quotations (Stocks, Futures, Options)
    and enabling direct trading actions (Buy/Sell).
    """
    # Signal to emit when a Buy/Sell button is clicked or a log entry is double-clicked
    open_trading_dialog = pyqtSignal(dict)

    def __init__(self, db_manager: DatabaseManager, stock_manager: InstrumentManager,
                 futures_manager: InstrumentManager, options_manager: InstrumentManager):
        super().__init__()
        self.db_manager = db_manager
        self.stock_manager = stock_manager
        self.futures_manager = futures_manager
        self.options_manager = options_manager
        print(f"DEBUG: QuotationWidget.__init__ - ID of self.stock_manager: {id(self.stock_manager)}")
        print(f"DEBUG: QuotationWidget.__init__ - ID of self.futures_manager: {id(self.futures_manager)}")
        print(f"DEBUG: QuotationWidget.__init__ - ID of self.options_manager: {id(self.options_manager)}")


        self.current_instrument_type = 'EQ' # Default to Stocks
        self.live_quotation_data = {} # Cache for live data updates for the table (e.g., LTP, TBQ, TSQ)
        self.symbol_to_row_map = {} # Map symbol to row index for efficient updates of live data

        # New: Cache for all instruments of the currently selected type (unfiltered)
        self.all_current_type_instruments: List[Tuple] = [] 

        self.init_ui()
        # Initial population will happen in on_instrument_type_changed via setChecked(True)
        # populate_table() is now called from main.py after instruments are loaded
        # to ensure data is available.

    def init_ui(self):
        """Initializes the UI elements for the Quotation tab."""
        layout = QVBoxLayout()

        # Instrument Type Selection
        type_selection_layout = QHBoxLayout()
        type_selection_layout.addWidget(QLabel("Select Instrument Type:"))

        self.instrument_type_group = QButtonGroup(self)
        self.stocks_radio = QRadioButton("Stocks")
        self.futures_radio = QRadioButton("Futures")
        self.options_radio = QRadioButton("Options")

        self.instrument_type_group.addButton(self.stocks_radio)
        self.instrument_type_group.addButton(self.futures_radio)
        self.instrument_type_group.addButton(self.options_radio)

        type_selection_layout.addWidget(self.stocks_radio)
        type_selection_layout.addWidget(self.futures_radio)
        type_selection_layout.addWidget(self.options_radio)
        type_selection_layout.addStretch() # Push radio buttons to left

        layout.addLayout(type_selection_layout)

        # Connect radio button signals
        self.stocks_radio.toggled.connect(lambda: self.on_instrument_type_changed('EQ'))
        self.futures_radio.toggled.connect(lambda: self.on_instrument_type_changed('FUT'))
        self.options_radio.toggled.connect(lambda: self.on_instrument_type_changed('OPT'))

        self.stocks_radio.setChecked(True) # Set Stocks as default selected, triggers initial population

        # Search Box
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search Symbol...")
        # Connecting to filter_table which now calls _refresh_table_display
        self.search_input.textChanged.connect(self.filter_table) 
        layout.addWidget(self.search_input)

        # Quotation Table
        self.quotation_table = QTableWidget()
        self.setup_quotation_table_headers() # Set up headers dynamically based on type

        self.quotation_table.setAlternatingRowColors(True)
        self.quotation_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.quotation_table.setEditTriggers(QTableWidget.NoEditTriggers) # Make table read-only
        self.quotation_table.horizontalHeader().setStretchLastSection(True) # Stretch last column

        layout.addWidget(self.quotation_table)

        self.setLayout(layout)

    def setup_quotation_table_headers(self):
        """Sets up the headers for the quotation table based on the current instrument type."""
        headers = [
            "Symbol", "Instrument Type", "TBQ", "TSQ", "LTP",
            "Open", "High", "Low", "Close", "Trade"
        ]
        if self.current_instrument_type in ['FUT', 'OPT']:
            headers.insert(2, "Expiry Date") # Insert at index 2 (after Instrument Type)
            headers.insert(3, "Strike Price") # Insert at index 3 (after Expiry Date)

        self.quotation_table.setColumnCount(len(headers))
        self.quotation_table.setHorizontalHeaderLabels(headers)
        
        # Apply fixed widths to columns
        col_offset = 0
        self.quotation_table.setColumnWidth(col_offset, SYMBOL_COL_WIDTH) # Symbol
        col_offset += 1
        self.quotation_table.setColumnWidth(col_offset, INSTRUMENT_TYPE_COL_WIDTH) # Instrument Type
        col_offset += 1

        if self.current_instrument_type in ['FUT', 'OPT']:
            self.quotation_table.setColumnWidth(col_offset, EXPIRY_STRIKE_COL_WIDTH) # Expiry Date
            col_offset += 1
            self.quotation_table.setColumnWidth(col_offset, EXPIRY_STRIKE_COL_WIDTH) # Strike Price
            col_offset += 1

        self.quotation_table.setColumnWidth(col_offset, TBQ_TSQ_COL_WIDTH) # TBQ
        col_offset += 1
        self.quotation_table.setColumnWidth(col_offset, TBQ_TSQ_COL_WIDTH) # TSQ
        col_offset += 1
        self.quotation_table.setColumnWidth(col_offset, LTP_OHLC_COL_WIDTH) # LTP
        col_offset += 1
        self.quotation_table.setColumnWidth(col_offset, LTP_OHLC_COL_WIDTH) # Open
        col_offset += 1
        self.quotation_table.setColumnWidth(col_offset, LTP_OHLC_COL_WIDTH) # High
        col_offset += 1
        self.quotation_table.setColumnWidth(col_offset, LTP_OHLC_COL_WIDTH) # Low
        col_offset += 1
        self.quotation_table.setColumnWidth(col_offset, LTP_OHLC_COL_WIDTH) # Close
        col_offset += 1
        self.quotation_table.setColumnWidth(col_offset, TRADE_COL_WIDTH) # Trade button column

        # Remove header stretch mode which conflicts with fixed widths
        for i in range(self.quotation_table.columnCount()):
            self.quotation_table.horizontalHeader().setSectionResizeMode(i, QHeaderView.Fixed)


    def on_instrument_type_changed(self, instrument_type: str):
        """Handles changes in instrument type selection and loads instruments into cache."""
        if self.current_instrument_type != instrument_type:
            self.current_instrument_type = instrument_type
            self.live_quotation_data = {} # Clear live data cache when type changes
            self.symbol_to_row_map = {} # Clear row map
            self.setup_quotation_table_headers()
            self.search_input.clear() # Clear search when tab changes

            # Load all instruments for the selected type into our internal cache
            if self.current_instrument_type == 'EQ':
                self.all_current_type_instruments = self.stock_manager.get_all_tradable_instruments()
            elif self.current_instrument_type == 'FUT':
                self.all_current_type_instruments = self.futures_manager.get_all_tradable_instruments()
            elif self.current_instrument_type == 'OPT':
                self.all_current_type_instruments = self.options_manager.get_all_tradable_instruments()
            else:
                self.all_current_type_instruments = [] # Should not happen

            print(f"DEBUG: QuotationWidget - Loaded {len(self.all_current_type_instruments)} instruments into cache for type: {self.current_instrument_type}.")

            # Now, refresh the table display with this newly cached data
            self._refresh_table_display()

            if not self.all_current_type_instruments:
                QMessageBox.information(self, "No Instruments Found",
                                        f"No tradable instruments found for {self.current_instrument_type}. "
                                        "Please ensure your KiteConnect API is configured correctly and "
                                        "instruments have been fetched successfully in the Configuration tab.")


    def populate_table(self):
        """
        Public method to trigger a full refresh.
        This is called externally (e.g., from MainWindow) when instruments are fetched.
        It re-loads the current type's instruments into cache and refreshes the display.
        """
        # This will trigger on_instrument_type_changed if the type is different,
        # or just refresh the existing type if it's the same.
        # Calling setChecked on the currently checked radio button will not
        # trigger the toggled signal if it's already checked.
        # So we explicitly re-load cache and refresh display here.
        if self.current_instrument_type == 'EQ':
            self.all_current_type_instruments = self.stock_manager.get_all_tradable_instruments()
        elif self.current_instrument_type == 'FUT':
            self.all_current_type_instruments = self.futures_manager.get_all_tradable_instruments()
        elif self.current_instrument_type == 'OPT':
            self.all_current_type_instruments = self.options_manager.get_all_tradable_instruments()
        else:
            self.all_current_type_instruments = []

        print(f"DEBUG: QuotationWidget.populate_table (external call) - Re-loaded {len(self.all_current_type_instruments)} instruments into cache for type: {self.current_instrument_type}.")
        self._refresh_table_display()


    def _refresh_table_display(self):
        """
        Filters the cached instruments based on search input and populates the table
        only with the filtered results.
        """
        self.quotation_table.setUpdatesEnabled(False) # Disable updates for performance
        self.quotation_table.setSortingEnabled(False) # Disable sorting during population

        self.quotation_table.setRowCount(0) # Clear existing rows
        self.symbol_to_row_map = {} # Reset row map

        search_text = self.search_input.text().lower()
        
        # Filter instruments from the in-memory cache
        filtered_instruments = [
            inst for inst in self.all_current_type_instruments
            if search_text in inst[0].lower() # Assuming inst[0] is the symbol
        ]

        if not filtered_instruments:
            # No need for QMessageBox here, as it will be empty if no results.
            # The on_instrument_type_changed already shows a message if initial load is empty.
            self.quotation_table.setUpdatesEnabled(True)
            self.quotation_table.setSortingEnabled(True)
            return

        self.quotation_table.setRowCount(len(filtered_instruments))

        for row_idx, instrument_details in enumerate(filtered_instruments):
            # Unpack the tuple based on its length (6 for F&O, 4 for EQ)
            if len(instrument_details) == 6:
                symbol, instrument_type, exchange, instrument_token, expiry_date, strike_price = instrument_details
            else: # Assuming EQ with 4 elements
                symbol, instrument_type, exchange, instrument_token = instrument_details
                expiry_date = None
                strike_price = None

            self.symbol_to_row_map[symbol] = row_idx # Store symbol to row mapping for live updates

            # Initial values for live data fields (will be updated by update_quotation_data)
            tbq = "N/A"
            tsq = "N/A"
            ltp = "N/A"
            open_price = "N/A"
            high_price = "N/A"
            low_price = "N/A"
            close_price = "N/A"

            # Check if live data exists for this symbol and update placeholders
            if symbol in self.live_quotation_data:
                data = self.live_quotation_data[symbol]
                tbq = f"{data.get('tbq'):,}" if data.get('tbq') is not None else "N/A"
                tsq = f"{data.get('tsq'):,}" if data.get('tsq') is not None else "N/A"
                ltp = f"₹{data.get('price'):.2f}" if data.get('price') is not None else "N/A"
                open_price = f"₹{data.get('open_price'):.2f}" if data.get('open_price') is not None else "N/A"
                high_price = f"₹{data.get('high_price'):.2f}" if data.get('high_price') is not None else "N/A"
                low_price = f"₹{data.get('low_price'):.2f}" if data.get('low_price') is not None else "N/A"
                close_price = f"₹{data.get('close_price'):.2f}" if data.get('close_price') is not None else "N/A"


            col_offset = 0 # Offset for columns due to optional F&O fields

            # Symbol
            item_symbol = QTableWidgetItem(symbol)
            item_symbol.setTextAlignment(Qt.AlignCenter)
            self.quotation_table.setItem(row_idx, col_offset, item_symbol)
            col_offset += 1

            # Instrument Type
            item_inst_type = QTableWidgetItem(instrument_type)
            item_inst_type.setTextAlignment(Qt.AlignCenter)
            self.quotation_table.setItem(row_idx, col_offset, item_inst_type)
            col_offset += 1

            # Expiry Date (F&O only)
            if self.current_instrument_type in ['FUT', 'OPT']:
                item_expiry = QTableWidgetItem(expiry_date if expiry_date is not None else "N/A")
                item_expiry.setTextAlignment(Qt.AlignCenter)
                self.quotation_table.setItem(row_idx, col_offset, item_expiry)
                col_offset += 1

                # Strike Price (F&O only)
                item_strike = QTableWidgetItem(f"{strike_price:.2f}" if strike_price is not None else "N/A")
                item_strike.setTextAlignment(Qt.AlignCenter)
                self.quotation_table.setItem(row_idx, col_offset, item_strike)
                col_offset += 1

            # TBQ
            item_tbq = QTableWidgetItem(str(tbq))
            item_tbq.setTextAlignment(Qt.AlignCenter)
            self.quotation_table.setItem(row_idx, col_offset, item_tbq)
            col_offset += 1

            # TSQ
            item_tsq = QTableWidgetItem(str(tsq))
            item_tsq.setTextAlignment(Qt.AlignCenter)
            self.quotation_table.setItem(row_idx, col_offset, item_tsq)
            col_offset += 1

            # LTP
            item_ltp = QTableWidgetItem(str(ltp))
            item_ltp.setTextAlignment(Qt.AlignCenter)
            self.quotation_table.setItem(row_idx, col_offset, item_ltp)
            col_offset += 1

            # Open
            item_open = QTableWidgetItem(str(open_price))
            item_open.setTextAlignment(Qt.AlignCenter)
            self.quotation_table.setItem(row_idx, col_offset, item_open)
            col_offset += 1

            # High
            item_high = QTableWidgetItem(str(high_price))
            item_high.setTextAlignment(Qt.AlignCenter)
            self.quotation_table.setItem(row_idx, col_offset, item_high)
            col_offset += 1

            # Low
            item_low = QTableWidgetItem(str(low_price))
            item_low.setTextAlignment(Qt.AlignCenter)
            self.quotation_table.setItem(row_idx, col_offset, item_low)
            col_offset += 1

            # Close
            item_close = QTableWidgetItem(str(close_price))
            item_close.setTextAlignment(Qt.AlignCenter)
            self.quotation_table.setItem(row_idx, col_offset, item_close)
            col_offset += 1

            # Buy/Sell Buttons (within a container widget for layout control)
            button_container = QWidget()
            button_layout = QHBoxLayout(button_container)
            button_layout.setContentsMargins(0, 0, 0, 0) # Remove margins for tight fit
            button_layout.setSpacing(5) # Small spacing between buttons

            Buy_button = QPushButton("Buy")
            Buy_button.setStyleSheet("background-color: #28a745; color: white; border-radius: 5px; padding: 5px 10px;")
            Buy_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred) # Make button expand
            Buy_button.clicked.connect(
                lambda checked, s=symbol, it=instrument_type, p=ltp, ed=expiry_date, sp=strike_price:
                self.on_Buy_Sell_clicked('Buy', s, it, p, ed, sp)
            )
            button_layout.addWidget(Buy_button)

            Sell_button = QPushButton("Sell")
            Sell_button.setStyleSheet("background-color: #dc3545; color: white; border-radius: 5px; padding: 5px 10px;")
            Sell_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred) # Make button expand
            Sell_button.clicked.connect(
                lambda checked, s=symbol, it=instrument_type, p=ltp, ed=expiry_date, sp=strike_price:
                self.on_Buy_Sell_clicked('SELL', s, it, p, ed, sp)
            )
            button_layout.addWidget(Sell_button)

            self.quotation_table.setCellWidget(row_idx, col_offset, button_container)
            
        self.quotation_table.resizeColumnsToContents()
        # Set the last column (which now contains the button container) to stretch
        num_cols = self.quotation_table.columnCount()
        if num_cols > 0:
            self.quotation_table.horizontalHeader().setSectionResizeMode(num_cols - 1, QHeaderView.Stretch)


        self.quotation_table.setUpdatesEnabled(True) # Re-enable updates
        self.quotation_table.setSortingEnabled(True) # Re-enable sorting


    def on_Buy_Sell_clicked(self, transaction_type: str, symbol: str, instrument_type: str,
                           price: str, expiry_date: str = None, strike_price: float = None):
        dialog_data = {
            "symbol": symbol,
            "instrument_type": instrument_type,
            "transaction_type": transaction_type, # 'Buy' or 'SELL'
            "price": float(price.replace('₹', '')) if price != "N/A" else None # Convert price string to float
        }
        if expiry_date and expiry_date != "N/A":
            dialog_data["expiry_date"] = expiry_date
        if strike_price is not None: # Check for None, as 0.0 is a valid strike
            dialog_data["strike_price"] = float(strike_price) # Ensure it's a float
        
        self.open_trading_dialog.emit(dialog_data)
        print(f"DEBUG: Buy/Sell clicked - Type: {transaction_type}, Symbol: {symbol}, Price: {price}")

    def update_quotation_data(self, data: dict):
        symbol = data.get('symbol')
        if not symbol:
            return

        # Store the full data object for later retrieval if needed by trading dialog
        self.live_quotation_data[symbol] = data

        # Check if the updated symbol's instrument type matches the currently displayed type
        updated_instrument_type = data.get('instrument_type')
        # Handle 'CE'/'PE' for options by mapping them to 'OPT' for display filtering
        if updated_instrument_type in ['CE', 'PE']:
            updated_instrument_type = 'OPT'

        if updated_instrument_type and updated_instrument_type == self.current_instrument_type:
            # Update specific row if symbol is currently in the table
            if symbol in self.symbol_to_row_map:
                row_idx = self.symbol_to_row_map[symbol]
                
                # Correct way to get horizontal header labels
                headers = [self.quotation_table.horizontalHeaderItem(col).text() for col in range(self.quotation_table.columnCount())]
                
                tbq_col = -1
                tsq_col = -1
                ltp_col = -1
                open_col = -1
                high_col = -1
                low_col = -1
                close_col = -1

                try:
                    tbq_col = headers.index("TBQ")
                    tsq_col = headers.index("TSQ")
                    ltp_col = headers.index("LTP")
                    open_col = headers.index("Open")
                    high_col = headers.index("High")
                    low_col = headers.index("Low")
                    close_col = headers.index("Close")
                except ValueError as e:
                    print(f"WARNING: Header column not found in quotation table: {e}. Skipping update for some fields.")

                
                # Only update if data is not None and column exists
                if tbq_col != -1 and data.get('tbq') is not None:
                    self.quotation_table.item(row_idx, tbq_col).setText(f"{data['tbq']:,}")
                if tsq_col != -1 and data.get('tsq') is not None:
                    self.quotation_table.item(row_idx, tsq_col).setText(f"{data['tsq']:,}")
                if ltp_col != -1 and data.get('price') is not None:
                    self.quotation_table.item(row_idx, ltp_col).setText(f"₹{data['price']:.2f}")
                if open_col != -1 and data.get('open_price') is not None:
                    self.quotation_table.item(row_idx, open_col).setText(f"₹{data['open_price']:.2f}")
                if high_col != -1 and data.get('high_price') is not None:
                    self.quotation_table.item(row_idx, high_col).setText(f"₹{data['high_price']:.2f}")
                if low_col != -1 and data.get('low_price') is not None:
                    self.quotation_table.item(row_idx, low_col).setText(f"₹{data['low_price']:.2f}")
                if close_col != -1 and data.get('close_price') is not None:
                    self.quotation_table.item(row_idx, close_col).setText(f"₹{data['close_price']:.2f}")


    def filter_table(self):
        self._refresh_table_display()