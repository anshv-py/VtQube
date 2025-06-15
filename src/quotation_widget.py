import datetime
import traceback
from typing import List, Dict, Any, Tuple, Optional
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QLineEdit,
    QMessageBox, QApplication, QGroupBox, QGridLayout, QComboBox, QSpinBox,
    QAbstractItemView, QCompleter
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer, QObject, QThread, QStringListModel
from PyQt5.QtGui import QColor, QFont, QPalette

from database import DatabaseManager
from stock_management import InstrumentManager
from volume_data import VolumeData
from kiteconnect import KiteConnect

class AccountInfoWorker(QObject):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, kite_instance: KiteConnect):
        super().__init__()
        self.kite = kite_instance

    def run(self):
        try:
            if not self.kite:
                self.error.emit("KiteConnect instance not available for fetching account info.")
                return

            user_profile = self.kite.profile()
            balance_data = self.kite.margins()

            equity_margin = 0
            commodity_margin = 0
            if 'equity' in balance_data and 'net' in balance_data['equity']:
                equity_margin = balance_data['equity']['net']
            if 'commodity' in balance_data and 'net' in balance_data['commodity']:
                commodity_margin = balance_data['commodity']['net']

            positions = self.kite.positions()
            net_positions = positions.get('net', [])
            day_positions = positions.get('day', [])

            realized_pnl = 0.0
            unrealized_pnl = 0.0

            for position in net_positions:
                realized_pnl += position.get('realised_pnl', 0.0)
                unrealized_pnl += position.get('unrealised_pnl', 0.0)
            
            # Day positions might also have P&L that adds to the current day's figures
            for position in day_positions:
                realized_pnl += position.get('realised_pnl', 0.0)
                unrealized_pnl += position.get('unrealised_pnl', 0.0)

            total_balance = equity_margin + commodity_margin # Sum of Equity + Commodity margins

            account_info = {
                "total_balance": total_balance,
                "equity_margin": equity_margin,
                "commodity_margin": commodity_margin,
                "realized_pnl": realized_pnl,
                "unrealized_pnl": unrealized_pnl
            }
            self.finished.emit(account_info)

        except Exception as e:
            self.error.emit(f"Error fetching account info: {str(e)}\n{traceback.format_exc()}")


class TradingWidget(QWidget):
    open_trading_dialog = pyqtSignal(dict)
    request_live_data_for_symbol = pyqtSignal(str) 
    stop_live_data_for_symbol = pyqtSignal(str)


    def __init__(self, db_manager: DatabaseManager, stock_manager: InstrumentManager,
                 futures_manager: InstrumentManager, options_manager: InstrumentManager,
                 kite_instance: KiteConnect):
        super().__init__()
        self.db_manager = db_manager
        self.stock_manager = stock_manager
        self.futures_manager = futures_manager
        self.options_manager = options_manager
        self.kite = kite_instance # Store KiteConnect instance
        
        self.current_selected_instrument: Optional[Tuple] = None # Stores (symbol, inst_type, exchange, token, expiry, strike)
        self.live_quotation_data: Dict[str, VolumeData] = {} # Stores live data for the *single* displayed symbol
        self.instrument_list: List[Tuple] = [] # List of all tradable instruments for search

        # Timer for periodically refreshing account balance and P&L
        self.account_info_timer = QTimer(self)
        self.account_info_timer.timeout.connect(self.fetch_and_display_account_info)
        self.account_info_timer.start(30000) # Update every 30 seconds

        self.init_ui()
        self.load_all_tradable_instruments() # Load all instruments once for search functionality
        self.fetch_and_display_account_info() # Initial fetch of account details

    def init_ui(self):
        main_layout = QVBoxLayout()
        self.setLayout(main_layout)
        afps = QApplication.instance().font().pointSize() if QApplication.instance() else 10
        # Apply basic styling
        self.setStyleSheet(f"""
            QGroupBox {{
                font-weight: bold;
                border: 2px solid #cccccc;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 15px;
                background-color: #f8f8f8;
                font-size: {afps * 1.2}pt;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
                color: #333;
            }}
            QLabel {{
                font-size: {afps * 1.2}pt;
            }}
            QLineEdit {{
                padding: 8px;
                border: 1px solid #ccc;
                border-radius: 4px;
                font-size: {afps * 1.2}pt;
            }}
            QPushButton {{
                background-color: #007bff;
                color: white;
                border: none;
                padding: 10px 15px;
                font-size: {afps * 1.2}pt;
                font-weight: bold;
                border-radius: 5px;
            }}
            QPushButton:hover {{
                background-color: #0056b3;
            }}
            QTableWidget {{
                border: 1px solid #ccc;
                border-radius: 4px;
                gridline-color: #eee;
                font-size: {afps * 1.2}pt;
            }}
            QHeaderView::section {{
                background-color: #e0e0e0;
                padding: 8px;
                border: 1px solid #ddd;
                font-weight: bold;
                font-size: {afps * 1.2}pt;
            }}
        """)

        top_section_layout = QHBoxLayout()
        instrument_panel_group = QGroupBox("Instrument Details")
        instrument_panel_layout = QVBoxLayout()
        instrument_panel_group.setLayout(instrument_panel_layout)

        # Search Bar
        search_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Enter Symbol (e.g., RELIANCE, NIFTY24AUGFUT)")
        self.search_input.returnPressed.connect(self.on_search_input_entered) # Trigger search on Enter key
        search_layout.addWidget(self.search_input)
        
        self.search_button = QPushButton("Search")
        self.search_button.clicked.connect(self.on_search_input_entered)
        search_layout.addWidget(self.search_button)
        instrument_panel_layout.addLayout(search_layout)

        self.completer_model = QStringListModel()
        self.completer = QCompleter(self.completer_model, self)
        self.completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.completer.setFilterMode(Qt.MatchContains)
        self.search_input.setCompleter(self.completer)

        # Instrument Details Display (Grid Layout)
        details_grid_layout = QGridLayout()
        self.detail_labels: Dict[str, QLabel] = {}
        details_fields = [
            "Symbol:", "Type:", "Exchange:", "Token:", "Expiry Date:", "Strike Price:", 
            "Last Traded Price (LTP):", "Open:", "High:", "Low:", "Close:",
            "Total Buy Quantity (TBQ):", "Total Sell Quantity (TSQ):", "Bid/Ask Ratio:", "Timestamp:"
        ]
        for i, field in enumerate(details_fields):
            grid_row = i // 2
            col_offset = (i % 2) * 2
            details_grid_layout.addWidget(QLabel(field), grid_row, col_offset)
            label = QLabel("N/A")
            label.setObjectName(f"detail_{field.lower().replace(':', '').replace(' ', '_')}")
            label.setFont(QFont("Arial", 10, QFont.Bold))
            details_grid_layout.addWidget(label, grid_row, col_offset + 1)
            self.detail_labels[field.lower().replace(':', '').replace(' ', '_')] = label
        instrument_panel_layout.addLayout(details_grid_layout)

        # Buy/Sell Buttons
        trade_buttons_layout = QHBoxLayout()
        self.buy_button = QPushButton("Buy")
        self.buy_button.setStyleSheet(f"background-color: #28a745; color: white; border-radius: 5px; padding: 10px 20px; font-size: {afps * 1.2}pt;")
        self.buy_button.setEnabled(False) # Disable until instrument is selected
        self.buy_button.clicked.connect(lambda: self.on_trade_button_clicked("BUY"))
        trade_buttons_layout.addWidget(self.buy_button)

        self.sell_button = QPushButton("Sell")
        self.sell_button.setStyleSheet(f"background-color: #dc3545; color: white; border-radius: 5px; padding: 10px 20px; font-size: {afps * 1.2}pt;")
        self.sell_button.setEnabled(False) # Disable until instrument is selected
        self.sell_button.clicked.connect(lambda: self.on_trade_button_clicked("SELL"))
        trade_buttons_layout.addWidget(self.sell_button)
        instrument_panel_layout.addLayout(trade_buttons_layout)

        top_section_layout.addWidget(instrument_panel_group, 2) # Takes 2/3 of space

        # Right Side: Account Summary
        account_summary_group = QGroupBox("Account Summary")
        account_summary_layout = QGridLayout()
        account_summary_group.setLayout(account_summary_layout)

        self.balance_label = QLabel("Total Balance: ₹ N/A")
        self.balance_label.setFont(QFont("Arial", int(afps * 1.2), QFont.Bold))
        self.realized_pnl_label = QLabel("Realized P&L: ₹ N/A")
        self.realized_pnl_label.setFont(QFont("Arial", int(afps * 1.2), QFont.Bold))
        self.unrealized_pnl_label = QLabel("Unrealized P&L: ₹ N/A")
        self.unrealized_pnl_label.setFont(QFont("Arial", int(afps * 1.2), QFont.Bold))

        account_summary_layout.addWidget(self.balance_label, 0, 0, 1, 2)
        account_summary_layout.addWidget(self.realized_pnl_label, 1, 0, 1, 2)
        account_summary_layout.addWidget(self.unrealized_pnl_label, 2, 0, 1, 2)
        
        top_section_layout.addWidget(account_summary_group, 1) # Takes 1/3 of space

        main_layout.addLayout(top_section_layout)

        # --- Bottom Section: Trade History ---
        trade_history_group = QGroupBox("Recent Trades")
        trade_history_layout = QVBoxLayout()
        trade_history_group.setLayout(trade_history_layout)

        self.trade_history_table = QTableWidget()
        self.trade_history_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.trade_history_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.trade_history_table.setAlternatingRowColors(True)
        self.setup_trade_history_table_headers()
        trade_history_layout.addWidget(self.trade_history_table)
        
        main_layout.addWidget(trade_history_group)

        self.trade_history_table.doubleClicked.connect(self.on_trade_history_double_clicked)
        self.refresh_trade_history_table() # Initial load of trade history

    def setup_trade_history_table_headers(self):
        """Sets up the column headers and initial widths for the trade history table."""
        headers = [
            "Timestamp", "Symbol", "Type", "Transaction", "Quantity",
            "Price", "Order Type", "Product Type", "Status", "Message", "Order ID"
        ]
        self.trade_history_table.setColumnCount(len(headers))
        self.trade_history_table.setHorizontalHeaderLabels(headers)
        self.trade_history_table.horizontalHeader().setStretchLastSection(True)
        # Set reasonable default widths
        self.trade_history_table.setColumnWidth(0, 150) # Timestamp
        self.trade_history_table.setColumnWidth(1, 100) # Symbol
        self.trade_history_table.setColumnWidth(2, 80)  # Type
        self.trade_history_table.setColumnWidth(3, 100) # Transaction
        self.trade_history_table.setColumnWidth(4, 70)  # Quantity
        self.trade_history_table.setColumnWidth(5, 80)  # Price
        self.trade_history_table.setColumnWidth(6, 90)  # Order Type
        self.trade_history_table.setColumnWidth(7, 100) # Product Type
        self.trade_history_table.setColumnWidth(8, 80)  # Status
        self.trade_history_table.setColumnWidth(9, 200) # Message
        self.trade_history_table.setColumnWidth(10, 150) # Order ID


    def load_all_tradable_instruments(self):
        """
        Loads all tradable instruments from all managers into a combined list for search.
        This list populates the QCompleter for the search input.
        """
        self.instrument_list = []
        # Fetch instruments from all managers
        self.instrument_list.extend(self.stock_manager.get_all_tradable_instruments())
        self.instrument_list.extend(self.futures_manager.get_all_tradable_instruments())
        self.instrument_list.extend(self.options_manager.get_all_tradable_instruments())
        
        # Sort for better search performance (if doing binary search, etc., though linear is fine for < 10k)
        self.instrument_list.sort(key=lambda x: x[0]) # Sort by symbol

        # Populate completer model
        symbol_list = [inst[0] for inst in self.instrument_list]
        # Use QStringListModel instead of QLineEdit for completer source
        # This requires importing QStringListModel from PyQt5.QtCore
        from PyQt5.QtCore import QStringListModel
        self.completer.setModel(QStringListModel(symbol_list))


    def on_search_input_entered(self):
        """
        Handles search input: finds the instrument, updates the details display,
        and requests live data for the selected symbol.
        """
        search_text = self.search_input.text().strip().upper()
        
        # Stop any previous live data requests
        if self.current_selected_instrument:
            self.stop_live_data_for_symbol.emit(self.current_selected_instrument[0])

        self.clear_instrument_details() # Clear old details regardless of search outcome
        self.current_selected_instrument = None
        self.buy_button.setEnabled(False)
        self.sell_button.setEnabled(False)

        if not search_text:
            QMessageBox.warning(self, "Search Error", "Please enter a symbol to search.")
            return

        found_instrument = None
        for inst in self.instrument_list:
            symbol = inst[0]
            if symbol == search_text:
                found_instrument = inst
                break
        
        if found_instrument:
            self.current_selected_instrument = found_instrument
            self.update_instrument_details_display(found_instrument)
            # Request MainWindow to start live data for this specific symbol
            self.request_live_data_for_symbol.emit(found_instrument[0]) 
            self.buy_button.setEnabled(True)
            self.sell_button.setEnabled(True)
        else:
            QMessageBox.warning(self, "Instrument Not Found",
                                f"No instrument found matching '{search_text}'. "
                                "Please ensure you have fetched instruments via the Configuration tab "
                                "and the symbol is correct (case-insensitive search).")


    def update_instrument_details_display(self, instrument_details: Tuple):
        """
        Updates the instrument details section with the selected instrument's static info.
        Live data will be updated separately by `update_quotation_data`.
        """
        symbol = instrument_details[0]
        instrument_type = instrument_details[1]
        exchange = instrument_details[2]
        instrument_token = instrument_details[3]
        expiry_date = instrument_details[4] if len(instrument_details) > 4 else "N/A"
        strike_price = instrument_details[5] if len(instrument_details) > 5 else "N/A"

        self.detail_labels["symbol"].setText(symbol)
        self.detail_labels["type"].setText(instrument_type)
        self.detail_labels["exchange"].setText(exchange)
        self.detail_labels["token"].setText(str(instrument_token)) # Display token for debugging/info
        self.detail_labels["expiry_date"].setText(expiry_date if expiry_date else "N/A")
        self.detail_labels["strike_price"].setText(f"₹{strike_price:.2f}" if isinstance(strike_price, (int, float)) else "N/A")
        
        self.detail_labels["last_traded_price_(ltp)"].setText("Fetching...")
        self.detail_labels["open"].setText("N/A")
        self.detail_labels["high"].setText("N/A")
        self.detail_labels["low"].setText("N/A")
        self.detail_labels["close"].setText("N/A")
        self.detail_labels["total_buy_quantity_(tbq)"].setText("N/A")
        self.detail_labels["total_sell_quantity_(tsq)"].setText("N/A")
        self.detail_labels["bid/ask_ratio"].setText("N/A")
        self.detail_labels["timestamp"].setText("N/A")
        self.detail_labels["last_traded_price_(ltp)"].setStyleSheet("color: black;") # Reset color


    def clear_instrument_details(self):
        """Clears all instrument detail labels to their default 'N/A' state."""
        for label_key in self.detail_labels:
            if label_key == "last_traded_price_(ltp)":
                self.detail_labels[label_key].setText("N/A")
                self.detail_labels[label_key].setStyleSheet("color: black;")
            else:
                self.detail_labels[label_key].setText("N/A")


    def update_quotation_data(self, data: VolumeData):
        if self.current_selected_instrument and data.symbol == self.current_selected_instrument[0]:
            self.live_quotation_data[data.symbol] = data

            current_ltp_label = self.detail_labels["last_traded_price_(ltp)"]
            prev_price = self.live_quotation_data[data.symbol].price

            if data.price is not None:
                current_ltp_label.setText(f"₹{data.price:.2f}")
                if prev_price is not None:
                    if data.price > prev_price:
                        current_ltp_label.setStyleSheet("color: green;")
                    elif data.price < prev_price:
                        current_ltp_label.setStyleSheet("color: red;")
                    else:
                        current_ltp_label.setStyleSheet("color: black;")
                else:
                    current_ltp_label.setStyleSheet("color: black;")
            else:
                current_ltp_label.setText("N/A")
                current_ltp_label.setStyleSheet("color: black;")

            self.detail_labels["open"].setText(f"₹{data.open_price:.2f}" if data.open_price is not None else "N/A")
            self.detail_labels["high"].setText(f"₹{data.high_price:.2f}" if data.high_price is not None else "N/A")
            self.detail_labels["low"].setText(f"₹{data.low_price:.2f}" if data.low_price is not None else "N/A")
            self.detail_labels["close"].setText(f"₹{data.close_price:.2f}" if data.close_price is not None else "N/A")
            self.detail_labels["total_buy_quantity_(tbq)"].setText(f"{data.tbq:,}" if data.tbq is not None else "N/A")
            self.detail_labels["total_sell_quantity_(tsq)"].setText(f"{data.tsq:,}" if data.tsq is not None else "N/A")
            self.detail_labels["bid/ask_ratio"].setText(f"{data.ratio:.2f}" if data.ratio is not None else "N/A")
            self.detail_labels["timestamp"].setText(data.timestamp.split(' ')[1] if data.timestamp else "N/A")


    def on_trade_button_clicked(self, transaction_type: str):
        if not self.current_selected_instrument:
            QMessageBox.warning(self, "Trade Error", "Please select an instrument first by searching for it.")
            return

        # Get the latest live data for the selected instrument
        current_live_data = self.live_quotation_data.get(self.current_selected_instrument[0])
        if not current_live_data or current_live_data.price is None:
            QMessageBox.warning(self, "Trade Error", "Live price data not available for the selected instrument. Please wait for an update.")
            return

        dialog_data = {
            "symbol": self.current_selected_instrument[0],
            "instrument_type": self.current_selected_instrument[1],
            "transaction_type": transaction_type,
            "price": current_live_data.price,
            "expiry_date": self.current_selected_instrument[4] if len(self.current_selected_instrument) > 4 else None,
            "strike_price": self.current_selected_instrument[5] if len(self.current_selected_instrument) > 5 else None
        }
        self.open_trading_dialog.emit(dialog_data)


    def refresh_trade_history_table(self):
        """Fetches and displays the user's trade history."""
        trades = self.db_manager.get_all_trades()
        self.trade_history_table.setRowCount(0) # Clear existing rows
        self.trade_history_table.setColumnCount(11) # Ensure correct number of columns
        
        headers = [
            "Timestamp", "Symbol", "Type", "Transaction", "Quantity",
            "Price", "Order Type", "Product Type", "Status", "Message", "Order ID"
        ]
        self.trade_history_table.setHorizontalHeaderLabels(headers)

        self.trade_history_table.setRowCount(len(trades))
        for row_idx, trade in enumerate(trades):
            (trade_id, timestamp_str, symbol, instrument_type, transaction_type,
             quantity, price, order_type, product_type, status, message, order_id, alert_id) = trade

            # Format timestamp for display
            formatted_timestamp = datetime.datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%d %H:%M:%S")

            items = [
                QTableWidgetItem(formatted_timestamp),
                QTableWidgetItem(symbol),
                QTableWidgetItem(instrument_type),
                QTableWidgetItem(transaction_type),
                QTableWidgetItem(str(quantity)),
                QTableWidgetItem(f"₹{price:.2f}" if price is not None else "N/A"),
                QTableWidgetItem(order_type),
                QTableWidgetItem(product_type),
                QTableWidgetItem(status),
                QTableWidgetItem(message),
                QTableWidgetItem(str(order_id) if order_id else "N/A")
            ]
            
            # Set row background colors based on transaction type or status
            row_color = QColor(255, 255, 255) # Default white
            if transaction_type == "BUY":
                row_color = QColor(220, 255, 220) # Light Green
            elif transaction_type == "SELL":
                row_color = QColor(255, 220, 220) # Light Red

            if status == "REJECTED":
                row_color = QColor(255, 180, 180) # Darker Red for rejected

            for col_idx, item in enumerate(items):
                item.setTextAlignment(Qt.AlignCenter)
                item.setBackground(row_color)
                self.trade_history_table.setItem(row_idx, col_idx, item)

        self.trade_history_table.resizeColumnsToContents()
        self.trade_history_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch) # Stretch last section

    def on_trade_history_double_clicked(self, index):
        """
        Handles double-click on trade history row to potentially show more details.
        """
        row = index.row()
        # Example: show order ID if it exists
        order_id_item = self.trade_history_table.item(row, 10) # Order ID is in column 10
        if order_id_item:
            QMessageBox.information(self, "Trade Details", f"Double-clicked Trade with Order ID: {order_id_item.text()}")
            # In a real app, you might fetch full details from DB using trade_id or order_id
            # and display them in a more detailed dialog.


    def fetch_and_display_account_info(self):
        """
        Fetches account balance and P&L asynchronously using AccountInfoWorker
        and updates the display labels.
        """
        if not self.kite:
            self.balance_label.setText("Total Balance: ₹ N/A (KiteConnect not initialized)")
            self.realized_pnl_label.setText("Realized P&L: ₹ N/A")
            self.unrealized_pnl_label.setText("Unrealized P&L: ₹ N/A")
            return
        
        # Create and start a new thread for fetching account info
        self.account_worker = AccountInfoWorker(self.kite)
        self.account_thread = QThread()
        self.account_worker.moveToThread(self.account_thread)

        self.account_thread.started.connect(self.account_worker.run)
        self.account_worker.finished.connect(self._on_account_info_received)
        self.account_worker.error.connect(self._on_account_info_error)
        
        # Connect finished signals for proper thread cleanup
        self.account_worker.finished.connect(self.account_thread.quit)
        self.account_worker.finished.connect(self.account_worker.deleteLater)
        self.account_thread.finished.connect(self.account_thread.deleteLater)

        self.account_thread.start()

    def _on_account_info_received(self, info: Dict[str, Any]):
        """Slot to receive account information from worker and update UI."""
        self.balance_label.setText(f"Total Balance: ₹{info.get('total_balance', 0.0):,.2f}")
        
        realized_pnl = info.get('realized_pnl', 0.0)
        unrealized_pnl = info.get('unrealized_pnl', 0.0)

        # Set colors for P&L labels based on value
        realized_color = "green" if realized_pnl >= 0 else "red"
        unrealized_color = "green" if unrealized_pnl >= 0 else "red"

        self.realized_pnl_label.setText(f"Realized P&L: ₹{realized_pnl:,.2f}")
        self.realized_pnl_label.setStyleSheet(f"color: {realized_color}; font-weight: bold;")
        
        self.unrealized_pnl_label.setText(f"Unrealized P&L: ₹{unrealized_pnl:,.2f}")
        self.unrealized_pnl_label.setStyleSheet(f"color: {unrealized_color}; font-weight: bold;")

    def _on_account_info_error(self, message: str):
        """Slot to handle errors during account info fetching."""
        QMessageBox.warning(self, "Account Info Error", message)
        self.balance_label.setText("Total Balance: ₹ N/A (Error)")
        self.realized_pnl_label.setText("Realized P&L: ₹ N/A")
        self.unrealized_pnl_label.setText("Unrealized P&L: ₹ N/A")
    
    def stop_account_info_timer(self):
        """Stops the account info refresh timer."""
        self.account_info_timer.stop()
        # No explicit thread stop needed as worker cleans up on finish