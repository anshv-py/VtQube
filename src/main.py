import sys
import time
import datetime
from typing import Dict, Any, Optional, Tuple
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QHeaderView,
    QLabel, QPushButton, QTabWidget, QFrame, QStatusBar, QMessageBox,
    QLineEdit, QGroupBox, QTableWidget, QTableWidgetItem, QCompleter,
    QAbstractItemView
)
from pyqtspinner import WaitingSpinner
from PyQt5.QtCore import QTimer, Qt, QStringListModel, QThread, QObject, pyqtSignal
from PyQt5.QtGui import QColor, QIcon, QKeyEvent
from config import ConfigWidget, AlertConfig
from database import DatabaseManager
from monitoring import MonitoringThread, VolumeData
from logs import LogsWidget
from ui_elements import create_stat_card
from stock_management import InstrumentManager, InstrumentSelectionWidget
from utils import send_telegram_message, RequestTokenServer
from instrument_fetch_thread import InstrumentFetchThread
from quotation_widget import TradingWidget
from trading_dialog import TradingDialog
from kiteconnect import KiteConnect
import traceback

class QuotationFetcherWorker(QObject):
    """
    A worker thread for fetching live quotation data for a SINGLE specified instrument
    from KiteConnect API and emitting it to the UI.
    """
    live_data_update = pyqtSignal(VolumeData)
    error_occurred = pyqtSignal(str)
    finished = pyqtSignal() # Signal to indicate worker has stopped

    def __init__(self, kite: KiteConnect, db_path: str):
        super().__init__()
        self.kite = kite
        self.db_path = db_path
        self.symbol: Optional[str] = None # The trading symbol (e.g., RELIANCE)
        self.instrument_token: Optional[int] = None
        self.instrument_type: Optional[str] = None # EQ, FUT, CE, PE
        self.exchange: Optional[str] = None # NSE, NFO etc.
        self.expiry_date: Optional[str] = None
        self.strike_price: Optional[float] = None
        self._running = False # Control flag for the run loop
        self.refresh_interval = 2 # seconds, for live quotes fetch
        self.db_manager: Optional[DatabaseManager] = None # To be initialized in run()

    def set_instrument_details(self, symbol: str, instrument_token: int, instrument_type: str, exchange: str, expiry_date: Optional[str], strike_price: Optional[float]):
        """Sets the details of the instrument to fetch quotes for."""
        self.symbol = symbol
        self.instrument_token = instrument_token
        self.instrument_type = instrument_type
        self.exchange = exchange
        self.expiry_date = expiry_date
        self.strike_price = strike_price
        self._running = True # Set running flag to True when details are set
        print(f"DEBUG: QuotationFetcherWorker - Set instrument details: {symbol}, {instrument_type}, {exchange}, {instrument_token}")


    def stop(self):
        """Stops the quotation fetching loop gracefully."""
        self._running = False

    def run(self):
        """Main loop for fetching live data for the single instrument."""
        # Initialize DBManager here in the thread's context
        self.db_manager = DatabaseManager(self.db_path)

        if not self.kite:
            self.error_occurred.emit("KiteConnect instance not available. Cannot fetch live quotes.")
            self.finished.emit()
            return

        if not self.symbol or not self.instrument_token or not self.exchange:
            self.error_occurred.emit("Instrument details not fully set for live quotation fetch.")
            self.finished.emit()
            return

        # Construct the full trading symbol key (e.g., "NSE:RELIANCE", "NFO:NIFTY24AUGFUT")
        full_symbol_key = f"{self.exchange}:{self.symbol}"
        print(f"DEBUG: QuotationFetcherWorker - Starting live fetch for: {full_symbol_key}")

        while self._running:
            try:
                # kite.quote takes a list of trading symbol strings
                quote_data = self.kite.quote([full_symbol_key])
                # print(f"DEBUG: QuotationFetcherWorker - Raw quote data for {full_symbol_key}: {quote_data}")

                if quote_data and full_symbol_key in quote_data:
                    tick = quote_data[full_symbol_key] # Use 'tick' as in previous logic
                    current_timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                    last_price = tick.get('last_price')
                    ohlc = tick.get('ohlc', {})

                    if last_price is None:
                        print(f"WARNING: No last_price for {self.symbol}. Skipping update for this tick.")
                        # Do not continue and sleep here, let the main sleep handle it
                    else:
                        buy_quantity = tick.get('buy_quantity', 0)
                        sell_quantity = tick.get('sell_quantity', 0)

                        ratio = buy_quantity / sell_quantity if sell_quantity else (buy_quantity / 0.0001 if buy_quantity else 0)

                        # Create VolumeData object with available details
                        data = VolumeData(
                            timestamp=current_timestamp,
                            symbol=self.symbol,
                            instrument_type=self.instrument_type,
                            price=last_price,
                            tbq=buy_quantity,
                            tsq=sell_quantity,
                            ratio=ratio,
                            open_price=ohlc.get('open'),
                            high_price=ohlc.get('high'),
                            low_price=ohlc.get('low'),
                            close_price=ohlc.get('close'),
                            expiry_date=self.expiry_date,
                            strike_price=self.strike_price,
                            tbq_change_percent=0.0,
                            tsq_change_percent=0.0,
                            day_high_tbq=None,
                            day_low_tbq=None,
                            day_high_tsq=None,
                            day_low_tsq=None
                        )
                        self.live_data_update.emit(data)
                else:
                    print(f"WARNING: QuotationFetcherWorker - No live quote data found for {self.symbol} in response or invalid response structure. Quote data: {quote_data}")

            except Exception as e:
                error_msg = f"Error fetching live quote for {self.symbol}: {traceback.format_exc()}"
                self.error_occurred.emit(error_msg)
            
            time.sleep(self.refresh_interval)
        if self.db_manager:
            self.db_manager.close()
        self.finished.emit()
class DraggableTableWidget(QTableWidget):
    enterPressed = pyqtSignal()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.viewport().setAcceptDrops(True)


    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter:
            self.enterPressed.emit()
            event.accept()
        else:
            super().keyPressEvent(event)

class VolumeLoggerWorker(QObject):
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, db_path: str, data: VolumeData, remark: str = ""):
        super().__init__()
        self.db_path = db_path
        self.data = data
        self.remark = remark

    def run(self):
        try:
            db = DatabaseManager(self.db_path)
            db.log_volume_data(self.data, self.remark)
            db.close()
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))
class MainWindow(QMainWindow):
    init_success = pyqtSignal()
    def __init__(self):
        super().__init__()
        self.db_manager = DatabaseManager()

        self.stock_manager = InstrumentManager(self.db_manager, instrument_type='EQ', user_table_name='user_stocks')
        self.futures_manager = InstrumentManager(self.db_manager, instrument_type='FUT', user_table_name='user_futures')
        self.options_manager = InstrumentManager(self.db_manager, instrument_type='OPT', user_table_name='user_options')

        self.config = AlertConfig(
            tbq_tsq_threshold=0.0, stability_threshold=0.0, stability_duration=0,
            start_time=None, end_time=None,
            budget_cap=0.0, trade_ltp_percentage=0.0, trade_on_tbq_tsq_alert=True
        )
        self.config.load_settings_from_db(self.db_manager)
        self.config_widget = ConfigWidget(self.db_manager)

        self.kite = None
        self.monitoring_thread: Optional[MonitoringThread] = None
        self.request_token_server: Optional[RequestTokenServer] = None
        self.instrument_fetch_thread: Optional[InstrumentFetchThread] = None

        self.current_live_data: Dict[str, VolumeData] = {}
        self.specific_monitored_symbol: Optional[str] = None

        self.end_of_day_timer = QTimer(self)
        self.end_of_day_timer.setSingleShot(True)
        self.logger_threads = []
        QApplication.processEvents()

        self.init_ui()
        self.load_settings()
        self._initialize_kite_from_db_settings()

        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self.update_status_bar)
        self.status_timer.start(1000)

    def init_ui(self):
        self.setWindowTitle("VtQube v1.0.3")
        screen_rect = QApplication.desktop().availableGeometry(self)
        self.setGeometry(screen_rect)
        self.showMaximized()
        self.setWindowIcon(QIcon('assets/icon.jpg'))
        afps = QApplication.instance().font().pointSize() if QApplication.instance() else 10

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout()
        central_widget.setLayout(main_layout)

        self.tab_widget = QTabWidget()
        main_layout.addWidget(self.tab_widget)

        self.spinner = WaitingSpinner(
                            self,
                            roundness=100.0,
                            fade=80.0,
                            radius=30,
                            lines=29,
                            line_length=15,
                            line_width=8,
                            speed=1.5707963267948966,
                            color=QColor(0, 0, 255)
                        )
        self.spinner.start()

        self.tab_widget.addTab(self.config_widget, "Configuration")
        self.config_widget.api_keys_saved.connect(self.on_api_keys_saved)
        self.config_widget.login_success.connect(self.on_login_success)

        instruments_main_tab = QWidget()
        instruments_main_layout = QVBoxLayout()
        instruments_main_tab.setLayout(instruments_main_layout)
        self.tab_widget.addTab(instruments_main_tab, "Instruments")

        self.instrument_sub_tab_widget = QTabWidget()
        instruments_main_layout.addWidget(self.instrument_sub_tab_widget)

        self.stock_selection_widget = InstrumentSelectionWidget(self.stock_manager, "Stocks")
        self.futures_selection_widget = InstrumentSelectionWidget(self.futures_manager, "Futures")
        self.options_selection_widget = InstrumentSelectionWidget(self.options_manager, "Options")

        self.instrument_sub_tab_widget.addTab(self.stock_selection_widget, "Stocks")
        self.instrument_sub_tab_widget.addTab(self.futures_selection_widget, "Futures")
        self.instrument_sub_tab_widget.addTab(self.options_selection_widget, "Options")

        monitoring_tab = QWidget()
        monitoring_layout = QVBoxLayout()
        monitoring_tab.setLayout(monitoring_layout)
        self.tab_widget.addTab(monitoring_tab, "Monitoring")

        control_frame = QFrame()
        control_layout = QHBoxLayout()
        control_frame.setLayout(control_layout)

        self.start_monitor_btn = QPushButton("Start Monitoring")
        self.start_monitor_btn.clicked.connect(self.start_monitoring)
        self.start_monitor_btn.setEnabled(False)
        control_layout.addWidget(self.start_monitor_btn)

        self.toggle_pause_resume_btn = QPushButton("Pause Monitoring")
        self.toggle_pause_resume_btn.setStyleSheet("background-color: #f0ad4e;")
        self.toggle_pause_resume_btn.clicked.connect(self.toggle_monitoring_state)
        self.toggle_pause_resume_btn.setEnabled(False)
        control_layout.addWidget(self.toggle_pause_resume_btn)

        self.stop_monitor_btn = QPushButton("Stop Monitoring")
        self.stop_monitor_btn.clicked.connect(self.stop_monitoring)
        self.stop_monitor_btn.setEnabled(False)
        control_layout.addWidget(self.stop_monitor_btn)

        specific_monitor_group = QGroupBox("Monitor Specific Instrument (Optional)")
        specific_monitor_layout = QHBoxLayout()
        specific_monitor_group.setLayout(specific_monitor_layout)

        specific_monitor_layout.addWidget(QLabel("Symbol:"))
        self.specific_symbol_input = QLineEdit()
        self.specific_symbol_input.setPlaceholderText("Enter symbol (e.g., RELIANCE) and press Enter")
        
        self.completer_model = QStringListModel()
        self.completer = QCompleter(self.completer_model, self)
        self.completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.specific_symbol_input.setCompleter(self.completer)
        self.specific_symbol_input.returnPressed.connect(self.set_specific_monitored_symbol)

        specific_monitor_layout.addWidget(self.specific_symbol_input)

        monitoring_layout.addWidget(control_frame)
        monitoring_layout.addWidget(specific_monitor_group)

        self.live_data_table = DraggableTableWidget()
        self.live_data_table.setColumnCount(13)
        self.live_data_table.setHorizontalHeaderLabels([
            "Timestamp", "Symbol", "Type", "TBQ", "TBQ Chg %", "TSQ", "TSQ Chg %",
            "Remark", "LTP", "Open", "High", "Low", "Close",
        ])
        self.live_data_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        monitoring_layout.addWidget(self.live_data_table)
        self.live_data_table.doubleClicked.connect(self.on_monitoring_table_double_clicked)
        self.live_data_table.enterPressed.connect(self.apply_display_order_to_monitoring)

        self.live_data_table.setDragEnabled(True)
        self.live_data_table.setAcceptDrops(True)
        self.live_data_table.setDropIndicatorShown(True)
        self.live_data_table.setDragDropMode(QAbstractItemView.InternalMove)
        self.live_data_table.viewport().setAcceptDrops(True)

        self.stat_cards_layout = QHBoxLayout()
        monitoring_layout.addLayout(self.stat_cards_layout)
        self.init_stat_cards()

        self.logs_widget = LogsWidget(self.db_manager)
        self.tab_widget.addTab(self.logs_widget, "Logs")
        self.logs_widget.log_row_double_clicked.connect(self.open_trading_dialog_from_log)

        self.trading_widget = TradingWidget(
                                self.db_manager,
                                self.stock_manager,
                                self.futures_manager,
                                self.options_manager,
                                self.kite
                            )
        self.tab_widget.addTab(self.trading_widget, "Trading")
        self.trading_widget.request_live_data_for_symbol.connect(self._start_specific_symbol_quotation_fetch)
        self.trading_widget.stop_live_data_for_symbol.connect(self._stop_specific_symbol_quotation_fetch)
        self.trading_widget.open_trading_dialog.connect(self.open_trading_dialog)
        self.init_success.connect(self._on_kite_init_success)

        self.quotation_fetcher_thread: Optional[QThread] = None
        self.quotation_fetcher_worker: Optional[QuotationFetcherWorker] = None

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_label = QLabel("Status: Stopped")
        self.status_bar.addWidget(self.status_label)

    def init_stat_cards(self):
        self.stat_cards = {}
        card_data = [
            ("Total Alerts Today", "0", "#e74c3c"),
            ("Monitored Instruments", "0", "#f39c12"),
            ("Total TBQ", "0", "#3498db"),
            ("Total TSQ", "0", "#e67e22"),
            ("Avg TBQ Change %", "0.00%", "#27ae60"),
            ("Avg TSQ Change %", "0.00%", "#c0392b")
        ]
        for title, value, color in card_data:
            card = create_stat_card(title, value, color)
            self.stat_cards_layout.addWidget(card)
            self.stat_cards[title.lower().replace(' ', '_').replace('%', '')] = card

    def update_stat_card(self, title: str, value: str):
        key = title.lower().replace(' ', '_').replace('%', '')
        if key in self.stat_cards:
            value_label = self.stat_cards[key].findChild(QLabel, f"{key}_value")
            if value_label:
                value_label.setText(value)
            else:
                pass
        else:
            pass
    
    def _on_kite_init_success(self):
        self.trading_widget.kite = self.kite
        self.trading_widget.load_all_tradable_instruments()
        self.trading_widget.fetch_and_display_account_info()
    
    def _start_specific_symbol_quotation_fetch(self, symbol: str):
        self._stop_specific_symbol_quotation_fetch()

        if not self.kite:
            QMessageBox.warning(self, "KiteConnect Error", "KiteConnect is not initialized. Cannot fetch live quotes.")
            return

        instrument_details = (
            self.stock_manager.get_tradable_instrument_details(symbol) or
            self.futures_manager.get_tradable_instrument_details(symbol) or
            self.options_manager.get_tradable_instrument_details(symbol)
        )
        if not instrument_details:
            QMessageBox.warning(self, "Instrument Not Found", f"Could not find details for instrument: {symbol}. Cannot fetch live quotes.")
            return
        
        _symbol, _inst_type, _exchange, _token, _expiry, _strike = instrument_details
        self.quotation_fetcher_thread = QThread()
        self.quotation_fetcher_worker = QuotationFetcherWorker(self.kite, self.db_manager.db_path)
        
        self.quotation_fetcher_worker.set_instrument_details(
            symbol=_symbol,
            instrument_token=_token,
            instrument_type=_inst_type,
            exchange=_exchange,
            expiry_date=_expiry,
            strike_price=_strike
        )
        self.quotation_fetcher_worker.moveToThread(self.quotation_fetcher_thread)
        self.quotation_fetcher_thread.started.connect(self.quotation_fetcher_worker.run)
        self.quotation_fetcher_worker.live_data_update.connect(self.trading_widget.update_quotation_data)
        self.quotation_fetcher_worker.error_occurred.connect(lambda msg: QMessageBox.critical(self, "Live Data Error (Trading)", msg))
        
        self.quotation_fetcher_worker.finished.connect(self.quotation_fetcher_thread.quit)
        self.quotation_fetcher_worker.finished.connect(self.quotation_fetcher_worker.deleteLater)
        self.quotation_fetcher_thread.finished.connect(self.quotation_fetcher_thread.deleteLater)

        self.quotation_fetcher_thread.start()

    def _stop_specific_symbol_quotation_fetch(self, symbol: str = None):
        if self.quotation_fetcher_worker and self.quotation_fetcher_thread and self.quotation_fetcher_thread.isRunning():
            if symbol is None or self.quotation_fetcher_worker.symbol == symbol:
                self.quotation_fetcher_worker.stop()
                self.quotation_fetcher_thread.quit()
                if not self.quotation_fetcher_thread.wait(5000):
                    print(f"WARNING: Quotation fetcher thread for {self.quotation_fetcher_worker.symbol} did not terminate gracefully within timeout.")
                
                # Clear references only after attempting to terminate the thread
                self.quotation_fetcher_thread = None
                self.quotation_fetcher_worker = None
            else:
                print(f"DEBUG: MainWindow - Not stopping quotation fetcher for {self.quotation_fetcher_worker.symbol} as requested symbol was {symbol}.")

    def update_monitoring_stat_cards(self):
        total_monitored = len(self.current_live_data)
        self.update_stat_card("Monitored Instruments", str(total_monitored))

        if total_monitored == 0:
            self.update_stat_card("Total TBQ", "0")
            self.update_stat_card("Total TSQ", "0")
            self.update_stat_card("Avg TBQ Change %", "0.00%")
            self.update_stat_card("Avg TSQ Change %", "0.00%")
            return

        total_tbq = sum(data.tbq for data in self.current_live_data.values() if data.tbq is not None)
        total_tsq = sum(data.tsq for data in self.current_live_data.values() if data.tsq is not None)

        avg_tbq_change_percent = 0.0
        avg_tsq_change_percent = 0.0
        
        valid_tbq_changes = [data.tbq_change_percent for data in self.current_live_data.values() if data.tbq_change_percent is not None]
        valid_tsq_changes = [data.tsq_change_percent for data in self.current_live_data.values() if data.tsq_change_percent is not None]

        if valid_tbq_changes:
            avg_tbq_change_percent = sum(valid_tbq_changes) / len(valid_tbq_changes) * 100
        if valid_tsq_changes:
            avg_tsq_change_percent = sum(valid_tsq_changes) / len(valid_tsq_changes) * 100

        self.update_stat_card("Total TBQ", f"{total_tbq:,}")
        self.update_stat_card("Total TSQ", f"{total_tsq:,}")
        self.update_stat_card("Avg TBQ Change %", f"{avg_tbq_change_percent:.2f}%")
        self.update_stat_card("Avg TSQ Change %", f"{avg_tsq_change_percent:.2f}%")

    def load_settings(self):
        self.config_widget.load_settings()
    
    def apply_display_order_to_monitoring(self):
        new_monitored_order = []
        for row in range(self.live_data_table.rowCount()):
            symbol_item = self.live_data_table.item(row, 1) # Symbol is in column 1 (index 1)
            if symbol_item:
                new_monitored_order.append(symbol_item.text())

        if not new_monitored_order:
            QMessageBox.warning(self, "No Instruments", "No instruments displayed in the table to reorder.")
            return

        self._current_monitoring_order = new_monitored_order # Store the new order

        QMessageBox.information(self, "Order Applied", "Display order saved. Restart monitoring to apply the new order.")

        if self.monitoring_thread and self.monitoring_thread.isRunning():
            reply = QMessageBox.question(
                self, "Restart Monitoring?",
                "Monitoring is currently running. Do you want to restart monitoring to apply the new order?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self.stop_monitoring()
                self.start_monitoring() # This will now use the new self._current_monitoring_order
        else:
            QMessageBox.information(self, "Ready to Monitor", "New display order applied. Click 'Start Monitoring' to begin.")

    def on_api_keys_saved(self):
        api_key = self.db_manager.get_setting("api_key")
        api_secret = self.db_manager.get_setting("api_secret")
        
        if api_key and api_secret:
            if KiteConnect is None:
                QMessageBox.critical(self, "Error", "KiteConnect library not found. Please install it (`pip install kiteconnect`).")
                return

            self.kite = KiteConnect(api_key=api_key)
        else:
            QMessageBox.warning(self, "Missing API Keys", "Please provide Kite API Key and API Secret.")
            self.start_monitor_btn.setEnabled(False)

    def on_login_success(self, access_token: str):
        if self.kite:
            self.kite.set_access_token(access_token)
            QMessageBox.information(self, "Login Success", "KiteConnect login successful!")
            self.db_manager.save_setting("access_token", access_token)
            self.config.access_token = access_token
            self.fetch_all_tradable_instruments()
            self.start_monitor_btn.setEnabled(True)
            self._populate_completer_with_all_tradable_symbols()
            self._schedule_access_token_deletion()
        else:
            QMessageBox.critical(self, "Login Error", "KiteConnect instance not initialized. Please ensure API keys are saved.")
            self.start_monitor_btn.setEnabled(False)

    def _populate_completer_with_all_tradable_symbols(self):
        all_symbols = set()
        all_symbols.update(inst[0] for inst in self.stock_manager.all_tradable_symbols)
        all_symbols.update(inst[0] for inst in self.futures_manager.all_tradable_symbols)
        all_symbols.update(inst[0] for inst in self.options_manager.all_tradable_symbols)
        self.completer_model.setStringList(sorted(list(all_symbols)))

    def set_specific_monitored_symbol(self):
        symbol = self.specific_symbol_input.text().strip().upper()
        if symbol:
            is_valid_symbol = False
            if self.stock_manager.get_tradable_instrument_details(symbol) or \
               self.futures_manager.get_tradable_instrument_details(symbol) or \
               self.options_manager.get_tradable_instrument_details(symbol):
                is_valid_symbol = True

            if is_valid_symbol:
                self.specific_monitored_symbol = symbol
                QMessageBox.information(self, "Monitoring Selection", f"Monitoring set to: {symbol}")
                if self.monitoring_thread and self.monitoring_thread.isRunning():
                    self.stop_monitoring()
                    self.start_monitoring()
            else:
                QMessageBox.warning(self, "Invalid Symbol", f"'{symbol}' is not a valid tradable instrument.")
                self.specific_symbol_input.clear()
                self.specific_monitored_symbol = None
        else:
            self.specific_monitored_symbol = None
            QMessageBox.information(self, "Monitoring Selection", "Monitoring reverted to all user-selected instruments.")
            if self.monitoring_thread and self.monitoring_thread.isRunning():
                self.stop_monitoring()
                self.start_monitoring()
    
    def on_monitoring_table_double_clicked(self, index):
        row = index.row()
        if row < 0:
            return

        symbol_item = self.live_data_table.item(row, 1)
        if not symbol_item:
            return

        symbol = symbol_item.text()
        live_data_for_symbol = self.current_live_data.get(symbol)

        if live_data_for_symbol:
            dialog_data = {
                "symbol": live_data_for_symbol.symbol,
                "instrument_type": live_data_for_symbol.instrument_type,
                "transaction_type": "Buy",
                "price": live_data_for_symbol.price,
                "expiry_date": live_data_for_symbol.expiry_date,
                "strike_price": live_data_for_symbol.strike_price
            }
            self.open_trading_dialog(dialog_data)
        else:
            QMessageBox.warning(self, "Trade Error", f"Could not retrieve live data for {symbol} to open trading dialog.")
    
    def _initialize_kite_from_db_settings(self):
        api_key = self.db_manager.get_setting("api_key")
        api_secret = self.db_manager.get_setting("api_secret")
        access_token = self.db_manager.get_setting("access_token")

        if api_key and api_secret:
            try:
                self.kite = KiteConnect(api_key=api_key)
                if access_token:
                    self.kite.set_access_token(access_token)
                    self.config.access_token = access_token
                    self.start_monitor_btn.setEnabled(True)
                    QTimer.singleShot(100, self._safe_fetch)
                self.init_success.emit()
            except Exception as e:
                self.kite = None
                QMessageBox.critical(self, "KiteConnect Error", f"Failed to initialize KiteConnect from saved settings (possibly expired token): {e}\nPlease click 'Fetch Access Token' to re-login.")
                self.start_monitor_btn.setEnabled(False)

    def _safe_fetch(self):
        if self.kite:
            self.fetch_all_tradable_instruments()
            self._populate_completer_with_all_tradable_symbols()
            self._schedule_access_token_deletion()

    def fetch_all_tradable_instruments(self):
        if not self.kite:
            QMessageBox.warning(self, "KiteConnect Error", "Please log in to KiteConnect first.")
            return

        api_key = self.db_manager.get_setting("api_key")
        access_token = self.db_manager.get_setting("access_token")

        if not api_key or not access_token:
            QMessageBox.warning(self, "API Keys Missing", "API Key or Access Token not found. Please re-login.")
            return

        self.instrument_fetch_thread = InstrumentFetchThread(
            instrument_managers=[self.stock_manager, self.futures_manager, self.options_manager],
            db_path=self.db_manager.db_path,
            api_key=api_key,
            access_token=access_token
        )
        self.instrument_fetch_thread.fetch_started.connect(self.status_label.setText)
        self.instrument_fetch_thread.fetch_finished.connect(self.status_label.setText)
        self.instrument_fetch_thread.error_occurred.connect(lambda msg: QMessageBox.critical(self, "Instrument Fetch Error", msg))
        self.instrument_fetch_thread.all_fetches_complete.connect(self.on_all_fetches_complete)
        self.instrument_fetch_thread.start()
        self.status_label.setText("Fetching tradable instruments...")

    def on_all_fetches_complete(self):
        self.db_manager.reopen_connection()
        self.stock_manager.load_all_tradable_instruments_from_db()
        self.futures_manager.load_all_tradable_instruments_from_db()
        self.options_manager.load_all_tradable_instruments_from_db()

        self.stock_selection_widget.populate_all_symbols()
        self.futures_selection_widget.populate_all_symbols()
        self.options_selection_widget.populate_all_symbols()
        self._populate_completer_with_all_tradable_symbols()
        self.spinner.stop()
        QMessageBox.information(self, "Fetch Complete", "All tradable instruments fetched and saved.")

    def _delete_access_token_and_reschedule(self):
        self.db_manager.remove_setting("access_token")
        self.config.access_token = None
        self.kite = None
        self.start_monitor_btn.setEnabled(False)
        self.toggle_pause_resume_btn.setEnabled(False)
        self.stop_monitor_btn.setEnabled(False)

        QMessageBox.information(self, "Access Token Expired",
                                "Your KiteConnect access token has been automatically deleted as per market end time. "
                                "Please re-login to fetch a new token for the next trading session.")
        self._schedule_access_token_deletion()

    def _schedule_access_token_deletion(self):
        self.end_of_day_timer.stop()
        end_time_config = self.config.end_time
        if end_time_config is None:
            QMessageBox.warning(self, "End time not configured in settings. Cannot schedule access token deletion.")
            return

        now = datetime.datetime.now()
        end_time_today = datetime.datetime(now.year, now.month, now.day,
                                            end_time_config.hour, end_time_config.minute,
                                            end_time_config.second)

        delay_seconds = 0.0
        if now < end_time_today:
            delay_seconds = (end_time_today - now).total_seconds()
        else:
            end_time_tomorrow = end_time_today + datetime.timedelta(days=1)
            delay_seconds = (end_time_tomorrow - now).total_seconds()

        if delay_seconds > 0:
            self.end_of_day_timer.start(int(delay_seconds * 1000))
        else:
            QMessageBox.warning(self, "Calculated delay for token deletion is zero or negative. Deleting token immediately.")
            self._delete_access_token_and_reschedule()

    def start_monitoring(self):
        if not self.kite:
            QMessageBox.warning(self, "KiteConnect Error", "Please log in to KiteConnect first.")
            return

        if self.monitoring_thread and self.monitoring_thread.isRunning():
            QMessageBox.information(self, "Monitoring", "Stopping previous monitoring session...")
            self.stop_monitoring()
            
            QApplication.processEvents()

        self.config.load_settings_from_db(self.db_manager)

        if not self.config.is_valid():
            QMessageBox.critical(self, "Configuration Error", "Please complete all required fields in the Configuration tab.")
            return

        monitored_symbols_for_thread = []
        if self.specific_monitored_symbol:
            monitored_symbols_for_thread.append(self.specific_monitored_symbol)
        else:
            monitored_symbols_for_thread.extend(self.stock_manager.get_user_selected_symbols())
            monitored_symbols_for_thread.extend(self.futures_manager.get_user_selected_symbols())
            monitored_symbols_for_thread.extend(self.options_manager.get_user_selected_symbols())

        if not monitored_symbols_for_thread:
            QMessageBox.warning(self, "No Instruments Selected", "Please select instruments to monitor in the Instruments tab or specify one above.")
            return

        self.monitoring_thread = MonitoringThread(
            kite=self.kite,
            config=self.config,
            db_path=self.db_manager.db_path,
            stock_manager=self.stock_manager,
            futures_manager=self.futures_manager,
            options_manager=self.options_manager
        )
        self.monitoring_thread.set_monitored_symbols(monitored_symbols_for_thread)
        
        self.monitoring_thread.volume_update.connect(
            self.update_live_data_table, 
            Qt.QueuedConnection
        )
        self.monitoring_thread.alert_triggered.connect(
            self.on_alert_triggered,
            Qt.QueuedConnection
        )
        self.monitoring_thread.status_changed.connect(
            self.status_label.setText,
            Qt.DirectConnection
        )
        self.monitoring_thread.error_occurred.connect(
            lambda msg: QMessageBox.critical(self, "Monitoring Error", msg),
            Qt.DirectConnection
        )
        self.monitoring_thread.finished.connect(
            self.on_monitoring_thread_finished,
            Qt.DirectConnection
        )
        
        self.monitoring_thread.start()
        
        self.start_monitor_btn.setEnabled(False)
        self.toggle_pause_resume_btn.setEnabled(True)
        self.stop_monitor_btn.setEnabled(True)
        self.status_label.setText("Status: Starting...")

    def toggle_monitoring_state(self):
        if self.monitoring_thread and self.monitoring_thread.isRunning():
            if self.monitoring_thread.paused:
                self.monitoring_thread.resume_monitoring()
                self.toggle_pause_resume_btn.setText("Pause Monitoring")
                self.toggle_pause_resume_btn.setStyleSheet("background-color: #f0ad4e;")
                self.status_label.setText("Status: Running")
            else:
                self.monitoring_thread.pause_monitoring()
                self.toggle_pause_resume_btn.setText("Resume Monitoring")
                self.toggle_pause_resume_btn.setStyleSheet("background-color: #5bc0de;")
                self.status_label.setText("Status: Paused")
    def stop_monitoring(self):
        if self.monitoring_thread:
            try:
                self.monitoring_thread.volume_update.disconnect()
                self.monitoring_thread.alert_triggered.disconnect()
                self.monitoring_thread.status_changed.disconnect()
                self.monitoring_thread.error_occurred.disconnect()
            except:
                pass
            
            self.monitoring_thread.wait()
            self.monitoring_thread.deleteLater()
            self.monitoring_thread = None
            
            self._update_ui_after_stop()
    
    def _update_ui_after_stop(self):
        self.start_monitor_btn.setEnabled(True)
        self.toggle_pause_resume_btn.setEnabled(False)
        self.stop_monitor_btn.setEnabled(False)
        self.status_label.setText("Status: Stopped")
        
        self.live_data_table.setRowCount(0)
        self.current_live_data.clear()
        self.update_monitoring_stat_cards()

    def on_monitoring_thread_finished(self):
        print("Monitoring thread finished naturally")
        self._update_ui_after_stop()

    def update_live_data_table(self, data: VolumeData):
        row_idx = -1
        for i in range(self.live_data_table.rowCount()):
            if self.live_data_table.item(i, 1) and self.live_data_table.item(i, 1).text() == data.symbol:
                row_idx = i
                break

        if row_idx == -1:
            row_idx = self.live_data_table.rowCount()
            self.live_data_table.insertRow(row_idx)

        self.current_live_data[data.symbol] = data
        self.live_data_table.setItem(row_idx, 0, QTableWidgetItem(data.timestamp.split(' ')[1]))
        self.live_data_table.setItem(row_idx, 1, QTableWidgetItem(data.symbol))
        self.live_data_table.setItem(row_idx, 2, QTableWidgetItem(data.instrument_type if data.instrument_type else "N/A"))
        self.live_data_table.setItem(row_idx, 3, QTableWidgetItem(f"{data.tbq:,}"))
        self.live_data_table.setItem(row_idx, 4, QTableWidgetItem(f"{data.tbq_change_percent * 100:.2f}"))
        self.live_data_table.setItem(row_idx, 5, QTableWidgetItem(f"{data.tsq:,}"))
        self.live_data_table.setItem(row_idx, 6, QTableWidgetItem(f"{data.tsq_change_percent * 100:.2f}"))
        self.live_data_table.setItem(row_idx, 8, QTableWidgetItem(f"₹{data.price:.2f}"))
        self.live_data_table.setItem(row_idx, 9, QTableWidgetItem(f"₹{data.open_price:.2f}"))
        self.live_data_table.setItem(row_idx, 10, QTableWidgetItem(f"₹{data.high_price:.2f}"))
        self.live_data_table.setItem(row_idx, 11, QTableWidgetItem(f"₹{data.low_price:.2f}"))
        self.live_data_table.setItem(row_idx, 12, QTableWidgetItem(f"₹{data.close_price:.2f}"))
        
        remark_text = ""
        remark_color = QColor(255, 255, 255)

        tbq_threshold_percent = self.config.tbq_tsq_threshold
        
        tbq_changed = data.tbq_change_percent is not None and abs(data.tbq_change_percent) >= tbq_threshold_percent
        tsq_changed = data.tsq_change_percent is not None and abs(data.tsq_change_percent) >= tbq_threshold_percent


        if tbq_changed or tsq_changed:
            tbq_rise = data.tbq_change_percent > 0 if tbq_changed else False
            tsq_rise = data.tsq_change_percent > 0 if tsq_changed else False

            remark_text = ""
            if tbq_changed:
                remark_text += f"TBQ ({data.tbq_change_percent:.2%})"
            if tsq_changed:
                if remark_text:
                    remark_text += " || "
                remark_text += f"TSQ ({data.tsq_change_percent:.2%})"

            if tbq_rise or tsq_rise:
                remark_color = QColor(173, 216, 230)
            else:
                remark_color = QColor(255, 223, 186)
        else:
            remark_text = ""
            remark_color = QColor(255, 255, 255)


        remark_item = QTableWidgetItem(remark_text)
        remark_item.setBackground(remark_color)
        self.live_data_table.setItem(row_idx, 7, remark_item)
        
        thread = QThread()
        worker = VolumeLoggerWorker(self.db_manager.db_path, data, remark_text)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        self.logger_threads.append(thread)
        thread.finished.connect(lambda: self.logger_threads.remove(thread))

        worker.error.connect(lambda e: print(f"Volume logging error: {e}"))
        thread.start()
        self.logs_widget.refresh_logs()
        self.update_monitoring_stat_cards()

    def on_alert_triggered(self, symbol: str, combined_message_type_string: str, primary_alert_type: str, data: VolumeData):
        alerts_count = self.db_manager.get_alerts_count_today()
        self.update_stat_card("Total Alerts Today", str(alerts_count))

        telegram_enabled = self.db_manager.get_setting("enable_telegram_notifications", "False") == "True"
        telegram_bot_token = self.db_manager.get_setting("telegram_bot_token")
        telegram_chat_id = self.db_manager.get_setting("telegram_chat_id")

        if telegram_enabled and telegram_bot_token and telegram_chat_id:
            try:
                message_parts = []
                message_parts.append("🚨 STOCK ALERT 🚨")
                message_parts.append(f"ALERT! {symbol} - {data.instrument_type if data.instrument_type else 'N/A'} - {combined_message_type_string}")
                
                if data.ratio is not None:
                    message_parts.append(f"Ratio: {data.ratio:.2f}")
                
                ohlc_info = (
                    f"₹{data.price:.2f}(LTP) -- "
                    f"₹{data.open_price:.2f} (O) -- "
                    f"₹{data.high_price:.2f}(H) -- "
                    f"₹{data.low_price:.2f} (L) -- "
                    f"₹{data.close_price:.2f} (C)"
                )
                message_parts.append(ohlc_info)

                tbq_info = []
                tsq_info = []

                is_tbq_alert = "tbq" in combined_message_type_string.lower() or "tbq spike" in primary_alert_type.lower()
                is_tsq_alert = "tsq" in combined_message_type_string.lower() or "tsq spike" in primary_alert_type.lower()

                if is_tbq_alert:
                    if data.day_high_tbq is not None:
                        tbq_info.append(f"TBQ Day High: {data.day_high_tbq:,}")
                    if data.day_low_tbq is not None: # Though usually only high is relevant for spike alerts
                        if "spike" not in primary_alert_type.lower(): # Only show low if not a spike alert
                            tbq_info.append(f"TBQ Day Low: {data.day_low_tbq:,}")

                if is_tsq_alert:
                    if data.day_high_tsq is not None:
                        tsq_info.append(f"TSQ Day High: {data.day_high_tsq:,}")
                    if data.day_low_tsq is not None: # Though usually only high is relevant for spike alerts
                        if "spike" not in primary_alert_type.lower(): # Only show low if not a spike alert
                            tsq_info.append(f"TSQ Day Low: {data.day_low_tsq:,}")
                
                tbq_tsq_line = []
                if tbq_info:
                    tbq_tsq_line.append(" -- ".join(tbq_info))
                if tsq_info:
                    tbq_tsq_line.append(" -- ".join(tsq_info))
                
                if tbq_tsq_line:
                    message_parts.append(" & ".join(tbq_tsq_line)) # Join with " & " if both are present

                formatted_time = datetime.datetime.strptime(data.timestamp, "%Y-%m-%d %H:%M:%S").strftime("%I:%M:%S %p")
                formatted_date = datetime.datetime.strptime(data.timestamp, "%Y-%m-%d %H:%M:%S").strftime("%d-%m-%Y")
                message_parts.append(f"Time: {formatted_time}")
                message_parts.append(f"Date: {formatted_date}")

                telegram_message = "\n".join(message_parts)

                send_telegram_message(telegram_bot_token, telegram_chat_id, telegram_message)
            except Exception as e:
                QMessageBox.warning(self, "Telegram Error", f"Failed to send Telegram alert: {e}")

        if self.config.auto_trade_enabled:
            self.execute_auto_trade(data, primary_alert_type)
        self.logs_widget.refresh_logs()

    def _get_exchange_for_instrument_type(self, instrument_type: str) -> str:
        if instrument_type == 'EQ':
            return self.kite.EXCHANGE_NSE
        elif instrument_type in ['FUT', 'CE', 'PE']:
            return self.kite.EXCHANGE_NFO
        return self.kite.EXCHANGE_NSE

    def open_trading_dialog(self, data: Dict[str, Any]):
        dialog = TradingDialog(self.db_manager, initial_data=data, kite_instance=self.kite, config=self.config)
        dialog.trade_placed.connect(self.logs_widget.refresh_logs)
        dialog.exec_()

    def open_trading_dialog_from_log(self, log_data: Dict[str, Any]):
        symbol = log_data.get("symbol")
        instrument_type = log_data.get("instrument_type")

        instrument_details = None
        if instrument_type == 'EQ':
            instrument_details = self.stock_manager.get_tradable_instrument_details(symbol)
        elif instrument_type == 'FUT':
            instrument_details = self.futures_manager.get_tradable_instrument_details(symbol)
        elif instrument_type in ['CE', 'PE']:
            instrument_details = self.options_manager.get_tradable_instrument_details(symbol)

        dialog_data = {
            "symbol": symbol,
            "instrument_type": instrument_type,
            "price": log_data.get("price"),
            "alert_id": log_data.get("alert_id"),
            "expiry_date": instrument_details[4] if instrument_details and len(instrument_details) > 4 else None,
            "strike_price": instrument_details[5] if instrument_details and len(instrument_details) > 5 else None
        }
        self.open_trading_dialog(dialog_data)

    def update_auto_trade_config(self):
        self.config.load_settings_from_db(self.db_manager)

    def update_status_bar(self):
        if self.monitoring_thread and self.monitoring_thread.isRunning():
            if self.monitoring_thread.paused:
                self.status_label.setText("Status: Paused")
            else:
                self.status_label.setText("Status: Running")
        else:
            self.status_label.setText("Status: Stopped")

    def closeEvent(self, event):
        if self.monitoring_thread and self.monitoring_thread.isRunning():
            reply = QMessageBox.question(
                self, "Confirm Exit",
                "Monitoring is running. Are you sure you want to exit?",
                QMessageBox.Yes | QMessageBox.No
            )

            if reply == QMessageBox.Yes:
                self.stop_monitoring()
                QApplication.processEvents()
                
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()
        
        self._stop_specific_symbol_quotation_fetch()
        self.trading_widget.stop_account_info_timer()
    
    def close_application(self):
        self.close()

def main():
    app = QApplication(sys.argv)

    app.setApplicationName("VtQube-v1.0.3-beta")
    app.setApplicationVersion("1.0.3")
    app.setOrganizationName("Trading Solutions")

    app.setStyle('Fusion')

    main_window = MainWindow()
    main_window.show()

    sys.exit(app.exec_())

if __name__ == "__main__":
    main()