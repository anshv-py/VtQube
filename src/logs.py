import datetime
import pandas as pd
from typing import List, Dict, Any, Tuple, Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QTextEdit,
    QComboBox, QSizePolicy, QMenu, QAction, QMessageBox
)
from PyQt5.QtCore import Qt, pyqtSignal, QDateTime, QDate
from PyQt5.QtGui import QColor, QBrush, QFont

from database import DatabaseManager

class LogsWidget(QWidget):
    log_row_double_clicked = pyqtSignal(dict) # Signal to emit when a log row is double-clicked

    def __init__(self, db_manager: DatabaseManager):
        super().__init__()
        self.db_manager = db_manager
        # Initialize alerts_cache before calling refresh_logs
        self.alerts_cache: List[Dict[str, Any]] = [] # Cache for alerts to filter them
        self.init_ui()
        self.refresh_logs() # Load initial logs
        

    def init_ui(self):
        """Initializes the UI components for the logs tab."""
        self.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 2px solid #cccccc;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 15px;
                background-color: #ffffff;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
                color: #333;
            }
            QLabel {
                font-size: 18px;
            }
            QLineEdit, QSpinBox, QDoubleSpinBox, QTimeEdit, QComboBox, QTextEdit {
                padding: 8px;
                border: 1px solid #ccc;
                border-radius: 4px;
                font-size: 20px;
            }
            QPushButton {
                background-color: #007bff;
                color: white;
                border: none;
                padding: 10px 15px;
                font-size: 20px;
                font-weight: bold;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #0056b3;
            }
            QTableWidget {
                border: 1px solid #ccc;
                border-radius: 4px;
                gridline-color: #eee;
                font-size: 18px;
            }
            QHeaderView::section {
                background-color: #f0f0f0;
                padding: 8px;
                border: 1px solid #ddd;
                font-weight: bold;
                font-size: 18px;
            }
        """)

        main_layout = QVBoxLayout()

        # Filter and Control Row
        filter_layout = QHBoxLayout()

        filter_layout.addWidget(QLabel("Filter by Symbol:"))
        self.symbol_filter_combo = QComboBox()
        self.symbol_filter_combo.addItem("All Symbols")
        self.symbol_filter_combo.currentIndexChanged.connect(self.filter_alerts_and_logs)
        filter_layout.addWidget(self.symbol_filter_combo, 1)

        filter_layout.addWidget(QLabel("Filter by Type:"))
        self.type_filter_combo = QComboBox()
        # Updated filter options to match requested categories
        self.type_filter_combo.addItems(["All Types", "Alert", "Trade"]) 
        self.type_filter_combo.currentIndexChanged.connect(self.filter_alerts_and_logs)
        filter_layout.addWidget(self.type_filter_combo, 1)

        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh_logs)
        filter_layout.addWidget(self.refresh_button)

        self.export_button = QPushButton("Export to Excel")
        self.export_button.clicked.connect(self.export_logs_to_excel)
        filter_layout.addWidget(self.export_button)

        # Clear All Logs Button
        self.clear_logs_button = QPushButton("Clear All Logs")
        self.clear_logs_button.setStyleSheet("background-color: #dc3545;") # Red color for clear button
        self.clear_logs_button.clicked.connect(self.clear_all_logs_button_clicked)
        filter_layout.addWidget(self.clear_logs_button)


        main_layout.addLayout(filter_layout)

        # Alerts and Trades Table
        self.alerts_table = QTableWidget()
        # Updated columns as per request
        self.alerts_table.setColumnCount(13) 
        self.alerts_table.setHorizontalHeaderLabels([
            "Timestamp", "Symbol", "Type", "TBQ", "TBQ Chg %", "TSQ", 
            "TSQ Chg %", "Price", "Remark", "Open", "High", "Low", "Close"
        ])
        self.alerts_table.horizontalHeader().setStretchLastSection(True)
        self.alerts_table.setEditTriggers(QAbstractItemView.NoEditTriggers) # Make table read-only
        self.alerts_table.setSelectionBehavior(QAbstractItemView.SelectRows) # Select entire rows
        self.alerts_table.setAlternatingRowColors(True)

        # Enable context menu
        self.alerts_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.alerts_table.customContextMenuRequested.connect(self.show_context_menu)
        self.alerts_table.doubleClicked.connect(self.on_table_double_clicked) # Connect double click

        main_layout.addWidget(self.alerts_table, 2) # Give it a stretch factor

        self.setLayout(main_layout)

    def show_context_menu(self, pos):
        """Displays a context menu for the alerts table."""
        menu = QMenu(self)
        open_trade_action = QAction("Open Trade Dialog", self)
        open_trade_action.triggered.connect(self.open_trade_dialog_from_context)
        menu.addAction(open_trade_action)
        menu.exec_(self.alerts_table.mapToGlobal(pos))

    def on_table_double_clicked(self, index):
        """Handles double-click on a table row to emit a signal with log data."""
        row = index.row()
        if row < 0: # No valid row selected
            return

        selected_log_entry = self.alerts_cache[row] # Access the original cached data

        # Prepare data for the trading dialog (example fields)
        dialog_data = {
            "symbol": selected_log_entry.get("symbol", ""),
            "instrument_type": selected_log_entry.get("instrument_type", "EQ"),
            "price": selected_log_entry.get("price", 0.0), # Price is now a float
            "alert_id": selected_log_entry.get("log_id"), # Pass the log ID as alert_id
            "expiry_date": selected_log_entry.get("expiry_date"),
            "strike_price": selected_log_entry.get("strike_price")
        }
        self.log_row_double_clicked.emit(dialog_data) # Emit signal with the data

    def open_trade_dialog_from_context(self):
        """Opens the trade dialog based on the selected row's data from context menu."""
        selected_rows = self.alerts_table.selectionModel().selectedRows()
        if not selected_rows:
            return

        row = selected_rows[0].row()
        selected_log_entry = self.alerts_cache[row] # Access the original cached data

        dialog_data = {
            "symbol": selected_log_entry.get("symbol", ""),
            "instrument_type": selected_log_entry.get("instrument_type", "EQ"),
            "price": selected_log_entry.get("price", 0.0), # Price is now a float
            "alert_id": selected_log_entry.get("log_id"),
            "expiry_date": selected_log_entry.get("expiry_date"),
            "strike_price": selected_log_entry.get("strike_price")
        }
        self.log_row_double_clicked.emit(dialog_data)


    def refresh_logs(self):
        """
        Retrieves all relevant log entries (alerts, trades, volume data) from the database
        and populates the alerts table.
        """
        self.alerts_table.setRowCount(0)
        self.alerts_cache.clear()
        
        all_logs = []

        # Fetch Alerts
        alerts = self.db_manager.get_all_alerts()
        for alert in alerts:
            log_id, timestamp_str, symbol, message, alert_type, volume_log_id = alert
            
            # Default values for fields that might come from volume_data
            price = None
            instrument_type = "N/A"
            tbq = None
            tbq_change_percent = None
            tsq = None
            tsq_change_percent = None
            open_price = None
            high_price = None
            low_price = None
            close_price = None
            expiry_date = None
            strike_price = None
            is_baseline = False # New flag for coloring

            # Attempt to get associated volume data for detailed fields
            if log_id: 
                volume_data_entry = self.db_manager.get_volume_data_by_alert_id(log_id) 
                if volume_data_entry:
                    price = volume_data_entry.get('price')
                    instrument_type = volume_data_entry.get('instrument_type')
                    tbq = volume_data_entry.get('tbq')
                    tbq_change_percent = volume_data_entry.get('tbq_change_percent')
                    tsq = volume_data_entry.get('tsq')
                    tsq_change_percent = volume_data_entry.get('tsq_change_percent')
                    open_price = volume_data_entry.get('open')
                    high_price = volume_data_entry.get('high')
                    low_price = volume_data_entry.get('low')
                    close_price = volume_data_entry.get('close')
                    expiry_date = volume_data_entry.get('expiry_date')
                    strike_price = volume_data_entry.get('strike_price')
                    # Check for baseline flags from VolumeData
                    is_baseline = volume_data_entry.get('is_tbq_baseline', False) or \
                                  volume_data_entry.get('is_tsq_baseline', False)


            all_logs.append({
                "log_id": log_id, # This is the alert's ID
                "timestamp": timestamp_str,
                "symbol": symbol,
                "instrument_type": instrument_type,
                "tbq": tbq,
                "tbq_change_percent": tbq_change_percent,
                "tsq": tsq,
                "tsq_change_percent": tsq_change_percent,
                "price": price, # This is LTP
                "remark": message, # The original alert message
                "open_price": open_price,
                "high_price": high_price,
                "low_price": low_price,
                "close_price": close_price,
                "type_filter_category": "Alert", # For filtering combo box
                "expiry_date": expiry_date,
                "strike_price": strike_price,
                "is_baseline": is_baseline # Add baseline flag
            })

        # Fetch Trades
        trades = self.db_manager.get_all_trades()
        for trade in trades:
            (trade_id, timestamp_str, symbol, instrument_type, transaction_type,
             quantity, price, order_type, product_type, status, message, order_id, alert_id) = trade
            
            # Create a descriptive remark for trades
            trade_remark = f"Order: {transaction_type} {quantity} @ ₹{price:.2f} ({product_type}, {order_type}) Status: {status}"
            if message and message != trade_remark: # Append original message if different
                trade_remark += f" (Msg: {message})"

            all_logs.append({
                "log_id": trade_id, # This is the trade's ID
                "timestamp": timestamp_str,
                "symbol": symbol,
                "instrument_type": instrument_type, # Instrument type of the trade
                "tbq": None, # N/A for trades
                "tbq_change_percent": None, # N/A for trades
                "tsq": None, # N/A for trades
                "tsq_change_percent": None, # N/A for trades
                "price": price, # The traded price
                "remark": trade_remark,
                "open_price": None, # N/A for trades
                "high_price": None, # N/A for trades
                "low_price": None, # N/A for trades
                "close_price": None, # N/A for trades
                "type_filter_category": "Trade", # For filtering combo box
                "expiry_date": None, # Not directly in trade logs, would need lookup
                "strike_price": None, # Not directly in trade logs, would need lookup
                "is_baseline": False # Trades are not baselines
            })

        # Sort logs by timestamp (newest first)
        all_logs.sort(key=lambda x: datetime.datetime.strptime(x['timestamp'], "%Y-%m-%d %H:%M:%S"), reverse=True)
        self.alerts_cache = all_logs # Cache the full sorted data

        self.populate_symbol_filter_combo()
        self.filter_alerts_and_logs() # Apply filters after refreshing data

    def populate_symbol_filter_combo(self):
        """Populates the symbol filter combo box with unique symbols from cached alerts."""
        self.symbol_filter_combo.blockSignals(True) # Block signals to prevent unnecessary calls
        self.symbol_filter_combo.clear()
        self.symbol_filter_combo.addItem("All Symbols") # Add default option

        unique_symbols = sorted(list(set(entry['symbol'] for entry in self.alerts_cache if 'symbol' in entry)))
        self.symbol_filter_combo.addItems(unique_symbols)
        self.symbol_filter_combo.blockSignals(False) # Re-enable signals

    def filter_alerts_and_logs(self):
        """Filters the alerts and logs table based on selected criteria."""
        self.alerts_table.setRowCount(0) # Clear current table content

        selected_symbol = self.symbol_filter_combo.currentText()
        selected_type_filter_category = self.type_filter_combo.currentText() # Renamed from selected_type

        filtered_data = []
        for entry in self.alerts_cache:
            match_symbol = (selected_symbol == "All Symbols" or entry.get("symbol") == selected_symbol)
            # Match against the new 'type_filter_category'
            match_type = (selected_type_filter_category == "All Types" or entry.get("type_filter_category") == selected_type_filter_category)

            if match_symbol and match_type:
                filtered_data.append(entry)

        self.alerts_table.setRowCount(len(filtered_data))
        for row_idx, entry in enumerate(filtered_data):
            self.add_log_entry_to_table(row_idx, entry)

        self.alerts_table.resizeColumnsToContents()
        self.alerts_table.resizeRowsToContents()

    def add_log_entry_to_table(self, row_idx: int, entry: Dict[str, Any]):
        """Adds a single log entry to the alerts table based on the new column order."""
        try:
            dt_object = datetime.datetime.strptime(entry['timestamp'], "%Y-%m-%d %H:%M:%S")
            formatted_timestamp = dt_object.strftime("%d/%m/%Y %I:%M:%S %p")
        except ValueError:
            formatted_timestamp = entry['timestamp'] # Fallback if parsing fails

        # Define column indices as per the requested order (0-12)
        COL_TIMESTAMP = 0
        COL_SYMBOL = 1
        COL_TYPE = 2 # Instrument Type
        COL_TBQ = 3
        COL_TBQ_CHG_PERCENT = 4
        COL_TSQ = 5
        COL_TSQ_CHG_PERCENT = 6
        COL_PRICE = 7 # LTP for alerts, Traded Price for trades
        COL_REMARK = 8
        COL_OPEN = 9
        COL_HIGH = 10
        COL_LOW = 11
        COL_CLOSE = 12

        self.alerts_table.setItem(row_idx, COL_TIMESTAMP, QTableWidgetItem(formatted_timestamp))
        self.alerts_table.setItem(row_idx, COL_SYMBOL, QTableWidgetItem(entry.get("symbol", "N/A")))
        self.alerts_table.setItem(row_idx, COL_TYPE, QTableWidgetItem(entry.get("instrument_type", "N/A")))
        
        self.alerts_table.setItem(row_idx, COL_TBQ, QTableWidgetItem(f"{entry['tbq']:,}" if entry.get('tbq') is not None else "N/A"))
        self.alerts_table.setItem(row_idx, COL_TBQ_CHG_PERCENT, QTableWidgetItem(f"{entry['tbq_change_percent']:.2%}" if entry.get('tbq_change_percent') is not None else "N/A"))
        self.alerts_table.setItem(row_idx, COL_TSQ, QTableWidgetItem(f"{entry['tsq']:,}" if entry.get('tsq') is not None else "N/A"))
        self.alerts_table.setItem(row_idx, COL_TSQ_CHG_PERCENT, QTableWidgetItem(f"{entry['tsq_change_percent']:.2%}" if entry.get('tsq_change_percent') is not None else "N/A"))
        self.alerts_table.setItem(row_idx, COL_PRICE, QTableWidgetItem(f"₹{entry['price']:.2f}" if entry.get('price') is not None else "N/A"))
        self.alerts_table.setItem(row_idx, COL_REMARK, QTableWidgetItem(entry.get("remark", "N/A"))) # Remark column
        self.alerts_table.setItem(row_idx, COL_OPEN, QTableWidgetItem(f"₹{entry['open_price']:.2f}" if entry.get('open_price') is not None else "N/A"))
        self.alerts_table.setItem(row_idx, COL_HIGH, QTableWidgetItem(f"₹{entry['high_price']:.2f}" if entry.get('high_price') is not None else "N/A"))
        self.alerts_table.setItem(row_idx, COL_LOW, QTableWidgetItem(f"₹{entry['low_price']:.2f}" if entry.get('low_price') is not None else "N/A"))
        self.alerts_table.setItem(row_idx, COL_CLOSE, QTableWidgetItem(f"₹{entry['close_price']:.2f}" if entry.get('close_price') is not None else "N/A"))
        
        # Apply color based on log type and baseline status
        base_bg_color = QColor(Qt.white) # Default white

        if entry.get("is_baseline", False):
            base_bg_color = QColor(173, 216, 230) # Light blue for baseline
        elif entry.get("type_filter_category") == "Alert":
            base_bg_color = QColor("#FFDDC1") # Light orange for alerts
        elif entry.get("type_filter_category") == "Trade":
            base_bg_color = QColor("#D4EDDA") # Light green for trades
        else:
            # Alternating grey/white for general rows not covered by above, if any.
            # This part handles alternating colors for rows that are neither baseline, alert nor trade.
            if row_idx % 2 == 0:
                base_bg_color = QColor(Qt.white)
            else:
                base_bg_color = QColor(240, 240, 240) # Light grey

        # Apply the determined background color to all columns of the row
        for col in range(self.alerts_table.columnCount()):
            # The remark column's background is not dynamically calculated here based on "rise/fall"
            # as it's a historical log, so it takes the row's base background color.
            self.alerts_table.item(row_idx, col).setBackground(base_bg_color)


    def export_logs_to_excel(self):
        """Exports the currently displayed logs to an Excel file."""
        if not self.alerts_cache:
            QMessageBox.information(self, "Export", "No data to export.")
            return

        try:
            # Create a DataFrame from the filtered data
            # Use a copy to avoid modifying the cached data when dropping columns
            df = pd.DataFrame(self.alerts_cache).copy() 

            # Define the order of columns for export based on display order in UI
            export_columns_order = [
                "timestamp", "symbol", "instrument_type", "tbq", "tbq_change_percent",
                "tsq", "tsq_change_percent", "price", "remark",
                "open_price", "high_price", "low_price", "close_price"
            ]
            
            # Rename columns for clarity in Excel to match UI headers
            df = df.rename(columns={
                "instrument_type": "Type", # Changed to "Type" from "Inst. Type"
                "tbq_change_percent": "TBQ Chg %",
                "tsq_change_percent": "TSQ Chg %",
                "price": "Price", # Changed to "Price" from "LTP"
                "open_price": "Open",
                "high_price": "High",
                "low_price": "Low",
                "close_price": "Close",
                "remark": "Remark" # Ensure 'remark' is explicitly mapped if needed
            })
            
            # Select and reorder columns, fill missing with empty string for cleaner export
            df = df.reindex(columns=[
                "timestamp", "symbol", "Type", "TBQ", "TBQ Chg %", "TSQ", 
                "TSQ Chg %", "Price", "Remark", "Open", "High", "Low", "Close"
            ]).fillna('') # Fill NaN values with empty string for Excel

            # Convert 'timestamp' column to datetime objects using the correct format for DB
            df['timestamp'] = pd.to_datetime(df['timestamp'], format="%Y-%m-%d %H:%M:%S")
            # Now format them for display in Excel
            df['timestamp'] = df['timestamp'].dt.strftime("%d/%m/%Y %I:%M:%S %p")


            # Define the file name with a timestamp
            file_name = f"alerts_trades_log_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            
            # Export to Excel
            df.to_excel(file_name, index=False)
            QMessageBox.information(self, "Export Successful", f"Logs exported to {file_name}")
        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"Failed to export logs: {str(e)}")

    def clear_all_logs_button_clicked(self):
        """Clears all volume logs, alerts, and trades from the database after confirmation."""
        reply = QMessageBox.question(
            self, "Confirm Clear",
            "Are you sure you want to clear ALL volume logs, alerts, and trades from the database?\nThis action cannot be undone.",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            try:
                self.db_manager.clear_all_logs()
                self.refresh_logs() # Refresh the UI to show cleared state
                self.populate_symbol_filter_combo() # Repopulate symbol filter
                QMessageBox.information(self, "Success", "All logs cleared successfully!")

            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to clear logs: {str(e)}")
