from typing import List, Tuple
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QRadioButton, QButtonGroup,
    QLineEdit, QMessageBox, QSizePolicy
)
from PyQt5.QtCore import Qt, pyqtSignal
from database import DatabaseManager
from stock_management import InstrumentManager
from instrument_fetch_thread import InstrumentLoadThread
from volume_data import VolumeData

SYMBOL_COL_WIDTH = 120
INSTRUMENT_TYPE_COL_WIDTH = 100
EXPIRY_STRIKE_COL_WIDTH = 100
TBQ_TSQ_COL_WIDTH = 80
LTP_OHLC_COL_WIDTH = 90
TRADE_COL_WIDTH = 140


class QuotationWidget(QWidget):
    open_trading_dialog = pyqtSignal(dict)
    def __init__(self, db_manager: DatabaseManager, stock_manager: InstrumentManager,
                 futures_manager: InstrumentManager, options_manager: InstrumentManager):
        super().__init__()
        self.db_manager = db_manager
        self.stock_manager = stock_manager
        self.futures_manager = futures_manager
        self.options_manager = options_manager
        self.load_thread = None

        self.current_instrument_type = 'EQ'
        self.live_quotation_data = {}
        self.symbol_to_row_map = {}
        self.all_current_type_instruments: List[Tuple] = [] 

        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        type_selection_layout = QHBoxLayout()
        type_selection_layout.addWidget(QLabel("Select Instrument Type:"))

        self.instrument_type_group = QButtonGroup(self)
        self.stocks_radio = QRadioButton("Stocks")
        self.futures_radio = QRadioButton("Futures")
        self.nifty_options_radio = QRadioButton("NIFTY",)
        self.banknifty_options_radio = QRadioButton("BANKNIFTY")
        self.finnifty_options_radio = QRadioButton("FINNIFTY")
        self.midcpnifty_options_radio = QRadioButton("MIDCPNIFTY")
        self.stock_options_radio = QRadioButton("STOCK")

        self.instrument_type_group.addButton(self.stocks_radio)
        self.instrument_type_group.addButton(self.futures_radio)
        self.instrument_type_group.addButton(self.nifty_options_radio)
        self.instrument_type_group.addButton(self.banknifty_options_radio)
        self.instrument_type_group.addButton(self.finnifty_options_radio)
        self.instrument_type_group.addButton(self.midcpnifty_options_radio)
        self.instrument_type_group.addButton(self.stock_options_radio)

        type_selection_layout.addWidget(self.stocks_radio)
        type_selection_layout.addWidget(self.futures_radio)
        type_selection_layout.addWidget(self.nifty_options_radio)
        type_selection_layout.addWidget(self.banknifty_options_radio)
        type_selection_layout.addWidget(self.finnifty_options_radio)
        type_selection_layout.addWidget(self.midcpnifty_options_radio)
        type_selection_layout.addWidget(self.stock_options_radio)
        type_selection_layout.addStretch()

        layout.addLayout(type_selection_layout)

        self.stocks_radio.toggled.connect(lambda: self.on_instrument_type_changed('EQ'))
        self.futures_radio.toggled.connect(lambda: self.on_instrument_type_changed('FUT'))
        self.nifty_options_radio.toggled.connect(lambda: self.on_instrument_type_changed('NIFTY'))
        self.banknifty_options_radio.toggled.connect(lambda: self.on_instrument_type_changed('BANK'))
        self.finnifty_options_radio.toggled.connect(lambda: self.on_instrument_type_changed('FIN'))
        self.midcpnifty_options_radio.toggled.connect(lambda: self.on_instrument_type_changed('MIDCP'))
        self.stock_options_radio.toggled.connect(lambda: self.on_instrument_type_changed('STOCK'))

        self.stocks_radio.setChecked(True)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search Symbol...")
        self.search_input.textChanged.connect(self.filter_table) 
        layout.addWidget(self.search_input)

        self.quotation_table = QTableWidget()
        self.setup_quotation_table_headers()

        self.quotation_table.setAlternatingRowColors(True)
        self.quotation_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.quotation_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.quotation_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

        layout.addWidget(self.quotation_table)
        self.setLayout(layout)

    def setup_quotation_table_headers(self):
        headers = [
            "Symbol", "Instrument Type", "TBQ", "TSQ", "LTP",
            "Open", "High", "Low", "Close", "Trade"
        ]
        if self.current_instrument_type in ['FUT', 'OPT']:
            headers.insert(2, "Expiry Date")
            if self.current_instrument_type == 'OPT':
                headers.insert(3, "Strike Price")

        self.quotation_table.setColumnCount(len(headers))
        self.quotation_table.setHorizontalHeaderLabels(headers)
        col_offset = 0
        self.quotation_table.setColumnWidth(col_offset, SYMBOL_COL_WIDTH)
        col_offset += 1
        self.quotation_table.setColumnWidth(col_offset, INSTRUMENT_TYPE_COL_WIDTH)
        col_offset += 1

        if self.current_instrument_type in ['FUT', 'OPT']:
            self.quotation_table.setColumnWidth(col_offset, EXPIRY_STRIKE_COL_WIDTH)
            col_offset += 1
            self.quotation_table.setColumnWidth(col_offset, EXPIRY_STRIKE_COL_WIDTH)
            col_offset += 1

        self.quotation_table.setColumnWidth(col_offset, TBQ_TSQ_COL_WIDTH)
        col_offset += 1
        self.quotation_table.setColumnWidth(col_offset, TBQ_TSQ_COL_WIDTH)
        col_offset += 1
        self.quotation_table.setColumnWidth(col_offset, LTP_OHLC_COL_WIDTH)
        col_offset += 1
        self.quotation_table.setColumnWidth(col_offset, LTP_OHLC_COL_WIDTH)
        col_offset += 1
        self.quotation_table.setColumnWidth(col_offset, LTP_OHLC_COL_WIDTH)
        col_offset += 1
        self.quotation_table.setColumnWidth(col_offset, LTP_OHLC_COL_WIDTH)
        col_offset += 1
        self.quotation_table.setColumnWidth(col_offset, LTP_OHLC_COL_WIDTH)
        col_offset += 1
        self.quotation_table.setColumnWidth(col_offset, TRADE_COL_WIDTH)

        for i in range(self.quotation_table.columnCount()):
            self.quotation_table.horizontalHeader().setSectionResizeMode(i, QHeaderView.Stretch)


    def on_instrument_type_changed(self, instrument_type: str):
        if self.current_instrument_type != instrument_type:
            self.current_instrument_type = instrument_type
            self.live_quotation_data = {}
            self.symbol_to_row_map = {}
            self.setup_quotation_table_headers()
            self.search_input.clear()

            if self.current_instrument_type == 'EQ':
                self.all_current_type_instruments = self.stock_manager.get_all_tradable_instruments()
            elif self.current_instrument_type == 'FUT':
                self.all_current_type_instruments = self.futures_manager.get_all_tradable_instruments()
            elif self.current_instrument_type in ['NIFTY', 'BANK', 'FIN', 'MIDCP', 'STOCK']:
                self.all_current_type_instruments = self.options_manager.load_all_tradable_instruments_from_db(option_category=self.current_instrument_type, instrument_t='OPT')
            else:
                self.all_current_type_instruments = []

            if not self.all_current_type_instruments:
                QMessageBox.information(self, "No Instruments Found",
                                        f"No tradable instruments found for {self.current_instrument_type}. "
                                        "Please ensure your KiteConnect API is configured correctly and "
                                        "instruments have been fetched successfully in the Configuration tab.")
            
            self._refresh_table_display()

        manager = self._get_manager_for_type(instrument_type if instrument_type in ['EQ', 'FUT'] else 'OPT')
        
        if self.load_thread and self.load_thread.isRunning():
            self.load_thread.terminate()
            
        self.load_thread = InstrumentLoadThread(manager)
        self.load_thread.data_ready.connect(self.handle_instruments_loaded)
        self.load_thread.error_occurred.connect(self.show_error)
        self.load_thread.start()
    
    def _get_manager_for_type(self, instrument_type):
        if instrument_type == 'EQ': return self.stock_manager
        elif instrument_type == 'FUT': return self.futures_manager
        elif instrument_type == 'OPT': return self.options_manager
        return None

    def handle_instruments_loaded(self, instruments):
        self.all_current_type_instruments = instruments
        self._refresh_table_display()


    def populate_table(self):
        if self.current_instrument_type == 'EQ':
            self.all_current_type_instruments = self.stock_manager.get_all_tradable_instruments()
        elif self.current_instrument_type == 'FUT':
            self.all_current_type_instruments = self.futures_manager.get_all_tradable_instruments()
        elif self.current_instrument_type == 'OPT':
            self.all_current_type_instruments = self.options_manager.get_all_tradable_instruments()
        else:
            self.all_current_type_instruments = []

        self._refresh_table_display()
    
    def show_error(self, message):
        QMessageBox.critical(self, "Loading Error", message)
        self.quotation_table.setRowCount(0)

    def _refresh_table_display(self):
        self.quotation_table.setUpdatesEnabled(False)
        self.quotation_table.setSortingEnabled(False)

        self.quotation_table.setRowCount(0)
        self.symbol_to_row_map = {}

        search_text = self.search_input.text().lower()
        filtered_instruments = [
            inst for inst in self.all_current_type_instruments
            if search_text in inst[0].lower()
        ]

        if not filtered_instruments:
            self.quotation_table.setUpdatesEnabled(True)
            self.quotation_table.setSortingEnabled(True)
            return

        self.quotation_table.setRowCount(len(filtered_instruments))

        for row_idx, instrument_details in enumerate(filtered_instruments):
            if len(instrument_details) == 6:
                symbol, instrument_type, exchange, instrument_token, expiry_date, strike_price = instrument_details
            else:
                symbol, instrument_type, exchange, instrument_token = instrument_details
                expiry_date = None
                strike_price = None

            self.symbol_to_row_map[symbol] = row_idx

            tbq = "N/A"
            tsq = "N/A"
            ltp = "N/A"
            open_price = "N/A"
            high_price = "N/A"
            low_price = "N/A"
            close_price = "N/A"

            if symbol in self.live_quotation_data:
                data = self.live_quotation_data[symbol]
                tbq = f"{data.tbq:,}" if data.tbq is not None else "N/A"
                tsq = f"{data.tsq:,}" if data.tsq is not None else "N/A"
                ltp = f"₹{data.price:.2f}" if data.price is not None else "N/A"
                open_price = f"₹{data.open_price:.2f}" if data.open_price is not None else "N/A"
                high_price = f"₹{data.high_price:.2f}" if data.high_price is not None else "N/A"
                low_price = f"₹{data.low_price:.2f}" if data.low_price is not None else "N/A"
                close_price = f"₹{data.close_price:.2f}" if data.close_price is not None else "N/A"


            col_offset = 0
            item_symbol = QTableWidgetItem(symbol)
            item_symbol.setTextAlignment(Qt.AlignCenter)
            self.quotation_table.setItem(row_idx, col_offset, item_symbol)
            col_offset += 1

            item_inst_type = QTableWidgetItem(instrument_type)
            item_inst_type.setTextAlignment(Qt.AlignCenter)
            self.quotation_table.setItem(row_idx, col_offset, item_inst_type)
            col_offset += 1

            if self.current_instrument_type in ['FUT', 'OPT']:
                item_expiry = QTableWidgetItem(expiry_date if expiry_date is not None else "N/A")
                item_expiry.setTextAlignment(Qt.AlignCenter)
                self.quotation_table.setItem(row_idx, col_offset, item_expiry)
                col_offset += 1

                if self.current_instrument_type in ['OPT']:
                    item_strike = QTableWidgetItem(f"{strike_price:.2f}" if strike_price is not None else "N/A")
                    item_strike.setTextAlignment(Qt.AlignCenter)
                    self.quotation_table.setItem(row_idx, col_offset, item_strike)
                    col_offset += 1

            item_tbq = QTableWidgetItem(str(tbq))
            item_tbq.setTextAlignment(Qt.AlignCenter)
            self.quotation_table.setItem(row_idx, col_offset, item_tbq)
            col_offset += 1
            item_tsq = QTableWidgetItem(str(tsq))
            item_tsq.setTextAlignment(Qt.AlignCenter)
            self.quotation_table.setItem(row_idx, col_offset, item_tsq)
            col_offset += 1

            item_ltp = QTableWidgetItem(str(ltp))
            item_ltp.setTextAlignment(Qt.AlignCenter)
            self.quotation_table.setItem(row_idx, col_offset, item_ltp)
            col_offset += 1

            item_open = QTableWidgetItem(str(open_price))
            item_open.setTextAlignment(Qt.AlignCenter)
            self.quotation_table.setItem(row_idx, col_offset, item_open)
            col_offset += 1

            item_high = QTableWidgetItem(str(high_price))
            item_high.setTextAlignment(Qt.AlignCenter)
            self.quotation_table.setItem(row_idx, col_offset, item_high)
            col_offset += 1

            item_low = QTableWidgetItem(str(low_price))
            item_low.setTextAlignment(Qt.AlignCenter)
            self.quotation_table.setItem(row_idx, col_offset, item_low)
            col_offset += 1

            item_close = QTableWidgetItem(str(close_price))
            item_close.setTextAlignment(Qt.AlignCenter)
            self.quotation_table.setItem(row_idx, col_offset, item_close)
            col_offset += 1

            button_container = QWidget()
            button_layout = QHBoxLayout(button_container)
            button_layout.setContentsMargins(0, 0, 0, 0)
            button_layout.setSpacing(5)

            Buy_button = QPushButton("Buy")
            Buy_button.setStyleSheet("background-color: #28a745; color: white; border-radius: 5px; padding: 5px 10px;")
            Buy_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            Buy_button.clicked.connect(
                lambda checked, s=symbol, it=instrument_type, p=ltp, ed=expiry_date, sp=strike_price:
                self.on_Buy_Sell_clicked('Buy', s, it, p, ed, sp)
            )
            button_layout.addWidget(Buy_button)

            Sell_button = QPushButton("Sell")
            Sell_button.setStyleSheet("background-color: #dc3545; color: white; border-radius: 5px; padding: 5px 10px;")
            Sell_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            Sell_button.clicked.connect(
                lambda checked, s=symbol, it=instrument_type, p=ltp, ed=expiry_date, sp=strike_price:
                self.on_Buy_Sell_clicked('SELL', s, it, p, ed, sp)
            )
            button_layout.addWidget(Sell_button)

            self.quotation_table.setCellWidget(row_idx, col_offset, button_container)
            
        self.quotation_table.resizeColumnsToContents()
        num_cols = self.quotation_table.columnCount()
        if num_cols > 0:
            self.quotation_table.horizontalHeader().setSectionResizeMode(num_cols - 1, QHeaderView.Stretch)

        self.quotation_table.setUpdatesEnabled(True)
        self.quotation_table.setSortingEnabled(True)

    def on_Buy_Sell_clicked(self, transaction_type: str, symbol: str, instrument_type: str,
                           price: str, expiry_date: str = None, strike_price: float = None):
        dialog_data = {
            "symbol": symbol,
            "instrument_type": instrument_type,
            "transaction_type": transaction_type,
            "price": float(price.replace('₹', '')) if price != "N/A" else None
        }
        if expiry_date and expiry_date != "N/A":
            dialog_data["expiry_date"] = expiry_date
        if strike_price is not None:
            dialog_data["strike_price"] = float(strike_price)
        
        self.open_trading_dialog.emit(dialog_data)

    def update_quotation_data(self, data: VolumeData):
        symbol = data.symbol
        if not symbol:
            return
        self.live_quotation_data[symbol] = data

        updated_instrument_type = data.instrument_type
        if updated_instrument_type in ['CE', 'PE']:
            updated_instrument_type = 'OPT'

        if updated_instrument_type and updated_instrument_type == self.current_instrument_type:
            if symbol in self.symbol_to_row_map:
                row_idx = self.symbol_to_row_map[symbol]
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
                    pass
                
                if tbq_col != -1 and data.tbq is not None:
                    self.quotation_table.item(row_idx, tbq_col).setText(f"{data.tbq:,}")
                if tsq_col != -1 and data.tsq is not None:
                    self.quotation_table.item(row_idx, tsq_col).setText(f"{data.tsq:,}")
                if ltp_col != -1 and data.price is not None:
                    self.quotation_table.item(row_idx, ltp_col).setText(f"₹{data.price:.2f}")
                if open_col != -1 and data.open_price is not None:
                    self.quotation_table.item(row_idx, open_col).setText(f"₹{data.open_price:.2f}")
                if high_col != -1 and data.high_price is not None:
                    self.quotation_table.item(row_idx, high_col).setText(f"₹{data.high_price:.2f}")
                if low_col != -1 and data.low_price is not None:
                    self.quotation_table.item(row_idx, low_col).setText(f"₹{data.low_price:.2f}")
                if close_col != -1 and data.close_price is not None:
                    self.quotation_table.item(row_idx, close_col).setText(f"₹{data.close_price:.2f}")


    def filter_table(self):
        self._refresh_table_display()