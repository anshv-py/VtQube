import sys
import os
import datetime
import threading
import time
import urllib.parse
import webbrowser
from dotenv import load_dotenv
import traceback
from typing import Dict, Any, Optional, List

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTabWidget, QFrame, QStatusBar, QMessageBox,
    QComboBox, QLineEdit, QListWidget, QListWidgetItem, QDialog, QDialogButtonBox,
    QGroupBox, QGridLayout, QTextEdit, QTableWidget, QTableWidgetItem, QScrollArea,
    QCompleter # Added QCompleter
)
from PyQt5.QtCore import QTimer, QThread, pyqtSignal, QTime, Qt, QStringListModel # Added QStringListModel
from PyQt5.QtGui import QFont, QPalette, QColor, QIcon

# Import custom modules
from config import ConfigWidget, AlertConfig
from database import DatabaseManager
from monitoring import MonitoringThread, VolumeData, MonitoringStatus
from logs import LogsWidget
from ui_elements import create_stat_card
from stock_management import InstrumentManager, InstrumentSelectionWidget
from utils import send_telegram_message, RequestTokenServer
from instrument_fetch_thread import InstrumentFetchThread
from quotation_widget import QuotationWidget
from trading_dialog import TradingDialog
from kiteconnect import KiteConnect

# Assuming AutoTradeWidget is in its own file. If not, remove this import and define a stub or actual class here.


class MainWindow(QMainWindow):
    """Main application window for the Stock Volume Monitor."""

    def __init__(self):
        super().__init__()
        self.db_manager = DatabaseManager()

        # Initialize InstrumentManagers for different types
        self.stock_manager = InstrumentManager(self.db_manager, instrument_type='EQ', user_table_name='user_stocks')
        self.futures_manager = InstrumentManager(self.db_manager, instrument_type='FUT', user_table_name='user_futures')
        self.options_manager = InstrumentManager(self.db_manager, instrument_type='OPT', user_table_name='user_options')

        # Initialize AlertConfig with dummy values; these will be overwritten by load_settings_from_db
        self.config = AlertConfig(
            tbq_tsq_threshold=0.0, stability_threshold=0.0, stability_duration=0,
            start_time=None, end_time=None, # These will be loaded from DB
            budget_cap=0.0, trade_ltp_percentage=0.0, trade_on_tbq_tsq_alert=True
        )
        self.config.load_settings_from_db(self.db_manager) # Load settings for initial config

        # Initialize ConfigWidget and AutoTradeWidget here so they are available for signal connections
        self.config_widget = ConfigWidget(self.db_manager)


        self.kite = None # Will be initialized on successful API login or from saved token
        self.monitoring_thread: Optional[MonitoringThread] = None
        self.request_token_server: Optional[RequestTokenServer] = None
        self.instrument_fetch_thread: Optional[InstrumentFetchThread] = None

        self.current_live_data: Dict[str, VolumeData] = {}
        self.previous_prices: Dict[str, float] = {}
        self.specific_monitored_symbol: Optional[str] = None

        # Timer for end-of-day access token deletion - INITIALIZED EARLIER
        self.end_of_day_timer = QTimer(self)
        self.end_of_day_timer.setSingleShot(True) # Ensure it fires only once
        self.end_of_day_timer.timeout.connect(self._delete_access_token_and_reschedule)

        self.init_ui()
        self.load_settings() # Load general settings and API keys

        # Attempt to initialize KiteConnect from saved settings at startup
        self._initialize_kite_from_db_settings()

        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self.update_status_bar)
        self.status_timer.start(1000)


    def init_ui(self):
        """Initializes the main application UI."""
        self.setWindowTitle("VtQube v1.0.0")
        # Use availableGeometry to maximize while respecting tSellbar
        screen_rect = QApplication.desktop().availableGeometry(self)
        self.setGeometry(screen_rect)
        self.showMaximized()
        self.setWindowIcon(QIcon('assets/icon.jpg')) # Set application icon here, ensure 'app_icon.png' exists
        afps = QApplication.instance().font().pointSize() if QApplication.instance() else 10

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout()
        central_widget.setLayout(main_layout)

        self.tab_widget = QTabWidget()
        main_layout.addWidget(self.tab_widget)

        # 1. Configuration Tab
        self.tab_widget.addTab(self.config_widget, "Configuration")
        self.config_widget.api_keys_saved.connect(self.on_api_keys_saved)
        self.config_widget.login_success.connect(self.on_login_success)

        # 2. Instruments Tab
        instruments_main_tab = QWidget()
        instruments_main_layout = QVBoxLayout()
        instruments_main_tab.setLayout(instruments_main_layout)
        self.tab_widget.addTab(instruments_main_tab, "Instruments")

        self.instrument_sub_tab_widget = QTabWidget()
        instruments_main_layout.addWidget(self.instrument_sub_tab_widget)

        # Instrument Selection Widgets for each sub-tab
        self.stock_selection_widget = InstrumentSelectionWidget(self.stock_manager, "Stocks")
        self.futures_selection_widget = InstrumentSelectionWidget(self.futures_manager, "Futures")
        self.options_selection_widget = InstrumentSelectionWidget(self.options_manager, "Options")

        self.instrument_sub_tab_widget.addTab(self.stock_selection_widget, "Stocks")
        self.instrument_sub_tab_widget.addTab(self.futures_selection_widget, "Futures")
        self.instrument_sub_tab_widget.addTab(self.options_selection_widget, "Options")

        # 3. Monitoring Tab
        monitoring_tab = QWidget()
        monitoring_layout = QVBoxLayout()
        monitoring_tab.setLayout(monitoring_layout)
        self.tab_widget.addTab(monitoring_tab, "Monitoring")

        # Monitoring Controls
        control_frame = QFrame()
        control_layout = QHBoxLayout()
        control_frame.setLayout(control_layout)

        self.start_monitor_btn = QPushButton("Start Monitoring")
        self.start_monitor_btn.clicked.connect(self.start_monitoring)
        self.start_monitor_btn.setEnabled(False) # Initially disabled
        control_layout.addWidget(self.start_monitor_btn)

        # Unified Pause/Resume Button
        self.toggle_pause_resume_btn = QPushButton("Pause Monitoring")
        self.toggle_pause_resume_btn.setStyleSheet("background-color: #f0ad4e;")
        self.toggle_pause_resume_btn.clicked.connect(self.toggle_monitoring_state)
        self.toggle_pause_resume_btn.setEnabled(False) # Initially disabled
        control_layout.addWidget(self.toggle_pause_resume_btn)

        self.stop_monitor_btn = QPushButton("Stop Monitoring")
        self.stop_monitor_btn.clicked.connect(self.stop_monitoring)
        self.stop_monitor_btn.setEnabled(False) # Initially disabled
        control_layout.addWidget(self.stop_monitor_btn)

        # Instrument Selector for Monitoring (New Feature)
        specific_monitor_group = QGroupBox("Monitor Specific Instrument (Optional)")
        specific_monitor_layout = QHBoxLayout()
        specific_monitor_group.setLayout(specific_monitor_layout)

        specific_monitor_layout.addWidget(QLabel("Symbol:"))
        self.specific_symbol_input = QLineEdit()
        self.specific_symbol_input.setPlaceholderText("Enter symbol (e.g., RELIANCE) and press Enter")
        
        # Set up QCompleter for the specific symbol input
        self.completer_model = QStringListModel()
        self.completer = QCompleter(self.completer_model, self)
        self.completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.specific_symbol_input.setCompleter(self.completer)
        # Connect returnPressed signal instead of a separate button click
        self.specific_symbol_input.returnPressed.connect(self.set_specific_monitored_symbol)

        specific_monitor_layout.addWidget(self.specific_symbol_input)

        monitoring_layout.addWidget(control_frame)
        monitoring_layout.addWidget(specific_monitor_group)


        # Live Data Display (Table) - Updated Columns
        self.live_data_table = QTableWidget()
        self.live_data_table.setColumnCount(11) # Added Open, High, Low, Close, and 'Remark'
        self.live_data_table.setHorizontalHeaderLabels([
            "Timestamp", "Symbol", "Type", "TBQ", "TSQ", "Remark", "LTP", "Open", "High", "Low", "Close",
        ])
        self.live_data_table.horizontalHeader().setStretchLastSection(True)
        monitoring_layout.addWidget(self.live_data_table)
        self.live_data_table.doubleClicked.connect(self.on_monitoring_table_double_clicked)

        # Stat Cards Layout - Updated count and types
        self.stat_cards_layout = QHBoxLayout()
        monitoring_layout.addLayout(self.stat_cards_layout)
        self.init_stat_cards() # Initialize stat cards

        # 4. Logs Tab
        self.logs_widget = LogsWidget(self.db_manager)
        self.tab_widget.addTab(self.logs_widget, "Logs")
        self.logs_widget.log_row_double_clicked.connect(self.open_trading_dialog_from_log)

        # 5. Quotation Tab
        self.quotation_widget = QuotationWidget(
            self.db_manager,
            self.stock_manager,
            self.futures_manager,
            self.options_manager
        )
        self.tab_widget.addTab(self.quotation_widget, "Quotations")
        self.quotation_widget.open_trading_dialog.connect(self.open_trading_dialog)

        # 6. Auto Trade Tab

        # Status Bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_label = QLabel("Status: Stopped")
        self.status_bar.addWidget(self.status_label)

    def init_stat_cards(self):
        """Initializes the static stat cards."""
        self.stat_cards = {}
        card_data = [
            ("Total Alerts Today", "0", "#e74c3c"), # Red
            ("Monitored Instruments", "0", "#f39c12"), # Orange
            ("Total TBQ", "0", "#3498db"), # Blue
            ("Total TSQ", "0", "#e67e22"), # Dark Orange
            ("Avg TBQ Change %", "0.00%", "#27ae60"), # Green
            ("Avg TSQ Change %", "0.00%", "#c0392b") # Dark Red
        ]
        for title, value, color in card_data:
            card = create_stat_card(title, value, color)
            self.stat_cards_layout.addWidget(card)
            self.stat_cards[title.lower().replace(' ', '_').replace('%', '')] = card

    def update_stat_card(self, title: str, value: str):
        """Updates the value of a specific stat card."""
        key = title.lower().replace(' ', '_').replace('%', '')
        if key in self.stat_cards:
            value_label = self.stat_cards[key].findChild(QLabel, f"{key}_value")
            if value_label:
                value_label.setText(value)
            else:
                print(f"ERROR: Could not find value label for stat card: {title}")
        else:
            print(f"ERROR: Stat card with title '{title}' not found.")

    def update_monitoring_stat_cards(self):
        """
        Calculates and updates the monitoring stat cards based on current live data.
        """
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
        
        # Filter out None values before summing for averages
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
        """Loads API keys and other settings from the database into the UI."""
        self.config_widget.load_settings()

    def on_api_keys_saved(self):
        """Callback when API keys are saved in ConfigWidget."""
        api_key = self.db_manager.get_setting("api_key")
        api_secret = self.db_manager.get_setting("api_secret")
        
        if api_key and api_secret:
            if KiteConnect is None:
                QMessageBox.critical(self, "Error", "KiteConnect library not found. Please install it (`pip install kiteconnect`).")
                return

            self.kite = KiteConnect(api_key=api_key)
            print(f"DEBUG: MainWindow.on_api_keys_saved - self.kite initialized: {self.kite is not None}") # Debug print
        else:
            QMessageBox.warning(self, "Missing API Keys", "Please provide Kite API Key and API Secret.")
            self.start_monitor_btn.setEnabled(False) # Disable start monitoring button if API keys are missing

    def on_login_success(self, access_token: str):
        """Callback when Kite login is successful."""
        if self.kite:
            self.kite.set_access_token(access_token)
            QMessageBox.information(self, "Login Success", "KiteConnect login successful!")
            # Save the access token to the database or a secure config if needed
            self.db_manager.save_setting("access_token", access_token)
            self.config.access_token = access_token # Update config object
            # Automatically fetch tradable instruments
            self.fetch_all_tradable_instruments()
            self.start_monitor_btn.setEnabled(True) # Enable start monitoring button
            self.quotation_widget.populate_table() # Populate quotation table after successful login
            self._populate_completer_with_all_tradable_symbols() # Populate completer after login
            self._schedule_access_token_deletion() # Schedule token deletion
        else:
            QMessageBox.critical(self, "Login Error", "KiteConnect instance not initialized. Please ensure API keys are saved.")
            self.start_monitor_btn.setEnabled(False)


    def _populate_completer_with_all_tradable_symbols(self):
        """Populates the QCompleter with all tradable symbols from all managers."""
        all_symbols = set()
        # Correctly access the trading symbol (first element) from each tuple in the list
        all_symbols.update(inst[0] for inst in self.stock_manager.all_tradable_symbols)
        all_symbols.update(inst[0] for inst in self.futures_manager.all_tradable_symbols)
        all_symbols.update(inst[0] for inst in self.options_manager.all_tradable_symbols)
        self.completer_model.setStringList(sorted(list(all_symbols)))
        print(f"DEBUG: Completer populated with {len(all_symbols)} symbols.")

    def set_specific_monitored_symbol(self):
        """Sets the specific symbol to monitor or clears it."""
        symbol = self.specific_symbol_input.text().strip().upper()
        if symbol:
            # Validate if the symbol exists in any of the tradable instruments
            is_valid_symbol = False
            if self.stock_manager.get_tradable_instrument_details(symbol) or \
               self.futures_manager.get_tradable_instrument_details(symbol) or \
               self.options_manager.get_tradable_instrument_details(symbol):
                is_valid_symbol = True

            if is_valid_symbol:
                self.specific_monitored_symbol = symbol
                QMessageBox.information(self, "Monitoring Selection", f"Monitoring set to: {symbol}")
                # Restart monitoring if it's already running to apply the new selection
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
            # Restart monitoring if it's already running to apply the new selection
            if self.monitoring_thread and self.monitoring_thread.isRunning():
                self.stop_monitoring()
                self.start_monitoring()
    
    def on_monitoring_table_double_clicked(self, index):
        """
        Handles double-click on a monitoring tab table row to open the trading dialog.
        """
        row = index.row()
        if row < 0: # No valid row selected
            return

        symbol_item = self.live_data_table.item(row, 1) # Symbol is in column 1
        if not symbol_item:
            return

        symbol = symbol_item.text()
        live_data_for_symbol = self.current_live_data.get(symbol)

        if live_data_for_symbol:
            # Prepare data for the trading dialog
            dialog_data = {
                "symbol": live_data_for_symbol.symbol,
                "instrument_type": live_data_for_symbol.instrument_type,
                "transaction_type": "Buy", # Default to Buy when opening from live data
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

        print(f"DEBUG: _initialize_kite_from_db_settings - Loaded API Key: {api_key}, API Secret: {'*' * len(api_secret) if api_secret else 'None'}, Access Token: {'*' * len(access_token) if access_token else 'None'}")

        if api_key and api_secret:
            try:
                self.kite = KiteConnect(api_key=api_key)
                if access_token:
                    self.kite.set_access_token(access_token)
                    print("DEBUG: KiteConnect initialized with saved access token successfully.")
                    self.config.access_token = access_token
                    self.start_monitor_btn.setEnabled(True)
                    # Automatically fetch tradable instruments
                    self.fetch_all_tradable_instruments()
                    self._populate_completer_with_all_tradable_symbols() # Populate completer at startup
                    self._schedule_access_token_deletion() # Schedule token deletion
                else:
                    print("DEBUG: KiteConnect initialized with API keys, but no access token found in DB. User needs to fetch.")
                    self.config_widget.show_login_button() # Show login button if only API keys are present
                    # No need to enable fetch instruments button, as it's now automated.
            except ImportError:
                QMessageBox.critical(self, "Error", "KiteConnect library not found. Please install it (`pip install kiteconnect`).")
                self.kite = None # Ensure kite is None if import fails
                return
            except Exception as e:
                print(f"ERROR: Failed to initialize KiteConnect from DB settings (possibly expired token): {e}")
                self.kite = None # Ensure kite is None on failure
                QMessageBox.critical(self, "KiteConnect Error", f"Failed to initialize KiteConnect from saved settings (possibly expired token): {e}\nPlease click 'Fetch Access Token' to re-login.")
                # Ensure buttons are disabled if initialization fails
                self.start_monitor_btn.setEnabled(False)
        else:
            print("DEBUG: API Key or Secret missing. KiteConnect not initialized at startup.")
            # Buttons remain disabled by default from init_ui

    def fetch_all_tradable_instruments(self):
        """Fetches tradable instruments in a separate thread."""
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
        QMessageBox.information(self, "Fetch Complete", "All tradable instruments fetched and saved.")

        # Force the main DatabaseManager connection to refresh after other threads have written
        self.db_manager.reopen_connection()
        print("DEBUG: Main DatabaseManager connection explicitly re-opened before reloading instrument caches.")

        print(f"DEBUG: MainWindow.on_all_fetches_complete - ID of self.stock_manager before loading from DB: {id(self.stock_manager)}")
        self.stock_manager.load_all_tradable_instruments_from_db() # Reload cache for main thread

        print(f"DEBUG: MainWindow.on_all_fetches_complete - ID of self.futures_manager before loading from DB: {id(self.futures_manager)}")
        self.futures_manager.load_all_tradable_instruments_from_db() # Reload cache for main thread

        print(f"DEBUG: MainWindow.on_all_fetches_complete - ID of self.options_manager before loading from DB: {id(self.options_manager)}")
        self.options_manager.load_all_tradable_instruments_from_db() # Reload cache for main thread

        self.stock_manager.set_default_monitored_stocks_if_empty()
        print(f"DEBUG: main.py on_all_fetches_complete - Default stocks set.")

        self.stock_selection_widget.populate_all_symbols() # Refresh completer after fetch
        self.futures_selection_widget.populate_all_symbols()
        self.options_selection_widget.populate_all_symbols()
        self._populate_completer_with_all_tradable_symbols() # Also update the specific monitor completer

        self.quotation_widget.populate_table() # Refresh quotation table with potentially new instruments

    def _delete_access_token_and_reschedule(self):
        """
        Deletes the access token from the database and reschedules the timer
        for the next day's market end time.
        """
        print("DEBUG: _delete_access_token_and_reschedule called. Deleting access token.")
        self.db_manager.remove_setting("access_token")
        self.config.access_token = None
        self.kite = None # Invalidate kite instance
        self.start_monitor_btn.setEnabled(False) # Disable start monitoring as token is gone
        self.toggle_pause_resume_btn.setEnabled(False)
        self.stop_monitor_btn.setEnabled(False)

        QMessageBox.information(self, "Access Token Expired",
                                "Your KiteConnect access token has been automatically deleted as per market end time. "
                                "Please re-login to fetch a new token for the next trading session.")
        
        # Reschedule for the next occurrence
        self._schedule_access_token_deletion()

    def _schedule_access_token_deletion(self):
        """
        Schedules the access token deletion timer based on the configured end time.
        If the end time for today has passed, schedules for tomorrow.
        """
        self.end_of_day_timer.stop() # Stop any existing timer

        end_time_config = self.config.end_time # This is a datetime.time object
        if end_time_config is None:
            print("WARNING: End time not configured in settings. Cannot schedule access token deletion.")
            return

        now = datetime.datetime.now()
        
        # Construct today's end time as a datetime object
        # Access hour, minute, second as attributes, not methods, for datetime.time objects
        end_time_today = datetime.datetime(now.year, now.month, now.day,
                                            end_time_config.hour, end_time_config.minute,
                                            end_time_config.second)

        delay_seconds = 0.0
        if now < end_time_today:
            # End time is today and in the future
            delay_seconds = (end_time_today - now).total_seconds()
            print(f"DEBUG: Scheduling token deletion for today at {end_time_today.strftime('%H:%M:%S')}. Delay: {delay_seconds:.0f} seconds.")
        else:
            # End time is today and in the past, schedule for tomorrow
            end_time_tomorrow = end_time_today + datetime.timedelta(days=1)
            delay_seconds = (end_time_tomorrow - now).total_seconds()
            print(f"DEBUG: End time today already passed. Scheduling token deletion for tomorrow at {end_time_tomorrow.strftime('%H:%M:%S')}. Delay: {delay_seconds:.0f} seconds.")

        if delay_seconds > 0:
            self.end_of_day_timer.start(int(delay_seconds * 1000)) # QTimer expects milliseconds
        else:
            # This case should ideally not be hit with the logic above, but as a safeguard,
            # if somehow the delay is 0 or negative, trigger deletion immediately.
            print("WARNING: Calculated delay for token deletion is zero or negative. Deleting token immediately.")
            self._delete_access_token_and_reschedule() # Directly call if past time

    def start_monitoring(self):
        """Starts the monitoring thread."""
        if not self.kite:
            QMessageBox.warning(self, "KiteConnect Error", "Please log in to KiteConnect first.")
            return

        if self.monitoring_thread and self.monitoring_thread.isRunning():
            QMessageBox.information(self, "Monitoring", "Monitoring is already running.")
            return

        # Get the latest config for monitoring
        self.config.load_settings_from_db(self.db_manager)

        if not self.config.is_valid():
            QMessageBox.critical(self, "Configuration Error", "Please complete all required fields in the Configuration tab.")
            return

        monitored_symbols_for_thread = []
        if self.specific_monitored_symbol:
            monitored_symbols_for_thread.append(self.specific_monitored_symbol)
        else:
            # Get all user-selected symbols across all instrument managers
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
        self.monitoring_thread.volume_update.connect(self.update_live_data_table)
        self.monitoring_thread.alert_triggered.connect(self.on_alert_triggered)
        self.monitoring_thread.status_changed.connect(self.status_label.setText)
        self.monitoring_thread.error_occurred.connect(lambda msg: QMessageBox.critical(self, "Monitoring Error", msg))
        
        self.monitoring_thread.start()

        self.start_monitor_btn.setEnabled(False)
        self.toggle_pause_resume_btn.setEnabled(True)
        self.toggle_pause_resume_btn.setText("Pause Monitoring")
        self.toggle_pause_resume_btn.setStyleSheet("background-color: #f0ad4e;") # Orange for active pause button
        self.stop_monitor_btn.setEnabled(True)
        self.status_label.setText("Status: Running")

    def toggle_monitoring_state(self):
        """Toggles the pause/resume state of the monitoring thread."""
        if self.monitoring_thread and self.monitoring_thread.isRunning():
            if self.monitoring_thread.paused:
                self.monitoring_thread.resume_monitoring()
                self.toggle_pause_resume_btn.setText("Pause Monitoring")
                self.toggle_pause_resume_btn.setStyleSheet("background-color: #f0ad4e;") # Orange
                self.status_label.setText("Status: Running")
            else:
                self.monitoring_thread.pause_monitoring()
                self.toggle_pause_resume_btn.setText("Resume Monitoring")
                self.toggle_pause_resume_btn.setStyleSheet("background-color: #5bc0de;") # Light Blue
                self.status_label.setText("Status: Paused")

    def stop_monitoring(self):
        """Stops the monitoring thread."""
        if self.monitoring_thread and self.monitoring_thread.isRunning():
            self.monitoring_thread.stop_monitoring()
            self.monitoring_thread.wait() # Wait for the thread to fully finish
            self.monitoring_thread = None

        self.start_monitor_btn.setEnabled(True)
        self.toggle_pause_resume_btn.setEnabled(False)
        self.toggle_pause_resume_btn.setText("Pause Monitoring") # Reset text
        self.toggle_pause_resume_btn.setStyleSheet("") # Reset style
        self.stop_monitor_btn.setEnabled(False)
        self.status_label.setText("Status: Stopped")
        self.live_data_table.setRowCount(0) # Clear table on stop
        self.current_live_data.clear() # Clear cached live data
        self.previous_prices.clear() # Clear previous prices
        self.update_monitoring_stat_cards() # Update stat cards to zero

    def update_live_data_table(self, data: VolumeData):
        """Updates the live data table with new volume data and updates stat cards."""
        # Find if symbol already exists in table
        row_idx = -1
        for i in range(self.live_data_table.rowCount()):
            if self.live_data_table.item(i, 1) and self.live_data_table.item(i, 1).text() == data.symbol:
                row_idx = i
                break

        if row_idx == -1:
            row_idx = self.live_data_table.rowCount()
            self.live_data_table.insertRow(row_idx)

        # Store current data and previous price for remark logic
        self.current_live_data[data.symbol] = data
        
        previous_price = self.previous_prices.get(data.symbol, data.price) # Default to current price if no previous
        self.previous_prices[data.symbol] = data.price


        self.live_data_table.setItem(row_idx, 0, QTableWidgetItem(data.timestamp.split(' ')[1])) # Only show time
        self.live_data_table.setItem(row_idx, 1, QTableWidgetItem(data.symbol))
        self.live_data_table.setItem(row_idx, 2, QTableWidgetItem(data.instrument_type if data.instrument_type else "N/A"))
        self.live_data_table.setItem(row_idx, 3, QTableWidgetItem(f"₹{data.price:.2f}"))
        self.live_data_table.setItem(row_idx, 4, QTableWidgetItem(f"{data.tbq:,}"))
        self.live_data_table.setItem(row_idx, 5, QTableWidgetItem(f"{data.tsq:,}"))
        self.live_data_table.setItem(row_idx, 6, QTableWidgetItem(f"₹{data.open_price:.2f}"))
        self.live_data_table.setItem(row_idx, 7, QTableWidgetItem(f"₹{data.high_price:.2f}"))
        self.live_data_table.setItem(row_idx, 8, QTableWidgetItem(f"₹{data.low_price:.2f}"))
        self.live_data_table.setItem(row_idx, 9, QTableWidgetItem(f"₹{data.close_price:.2f}"))
        
        # Remark Column Logic
        remark_text = ""
        remark_color = QColor(255, 255, 255) # Default white background

        tbq_threshold_percent = self.config.tbq_tsq_threshold # Convert from percentage to decimal for comparison
        
        tbq_changed = data.tbq_change_percent is not None and abs(data.tbq_change_percent) >= tbq_threshold_percent
        tsq_changed = data.tsq_change_percent is not None and abs(data.tsq_change_percent) >= tbq_threshold_percent


        if tbq_changed and tsq_changed:
            remark_text = f"TBQ ({data.tbq_change_percent:.2%}) || TSQ ({data.tsq_change_percent:.2%})"
            remark_color = QColor(192, 255, 192) # Light Green for both
        elif tbq_changed:
            remark_text = f"TBQ ({data.tbq_change_percent:.2%})"
        elif tsq_changed:
            remark_text = f"TSQ ({data.tsq_change_percent:.2%})"

        # Color based on price movement (rise/fall)
        # Apply price color only if no TBQ/TSQ change triggered or as an overlay
        if data.price > previous_price and data.price != previous_price: # Price strictly increased
            if not (tbq_changed or tsq_changed): # Only apply price color if no TBQ/TSQ trigger
                 remark_color = QColor(173, 216, 230) # Light Blue for rise
            if remark_text: # If there's already TBQ/TSQ text, append price movement
                remark_text += " | Price Rise"
            else:
                remark_text = "Price Rise"
        elif data.price < previous_price and data.price != previous_price: # Price strictly decreased
            if not (tbq_changed or tsq_changed): # Only apply price color if no TBQ/TSQ trigger
                remark_color = QColor(255, 223, 186) # Light Orange for fall
            if remark_text:
                remark_text += " | Price Fall"
            else:
                remark_text = "Price Fall"

        remark_item = QTableWidgetItem(remark_text)
        remark_item.setBackground(remark_color)
        self.live_data_table.setItem(row_idx, 10, remark_item) # Set in the 13th column (index 10)

        self.live_data_table.resizeColumnsToContents()

        # Update quotation widget if it's the active tab and data exists
        if self.tab_widget.currentWidget() == self.quotation_widget:
            self.quotation_widget.update_quotation_data(data)
        
        self.db_manager.log_volume_data(data, False)
        self.logs_widget.refresh_logs()

        # Update stat cards after processing the current symbol's data
        self.update_monitoring_stat_cards()

    def on_alert_triggered(self, symbol: str, combined_message_type_string: str, primary_alert_type: str, data: VolumeData, volume_log_id: int):
        """Callback when an alert is triggered in the monitoring thread."""
        QMessageBox.information(self, f"Alert: {primary_alert_type}", f"Symbol: {symbol}\nMessage: {combined_message_type_string}\nLTP: {data.price:.2f}")
        
        # Log the alert to the alerts table, linking to the volume log using volume_log_id
        self.db_manager.log_alert(data.timestamp, data.symbol, combined_message_type_string, primary_alert_type, volume_log_id=volume_log_id)
        self.logs_widget.refresh_logs() # Refresh logs tab

        # Update stat card for total alerts today
        alerts_count = self.db_manager.get_alerts_count_today()
        self.update_stat_card("Total Alerts Today", str(alerts_count))

        # --- Telegram Notification Logic ---
        telegram_enabled = self.db_manager.get_setting("enable_telegram_notifications", "False") == "True"
        telegram_bot_token = self.db_manager.get_setting("telegram_bot_token")
        telegram_chat_id = self.db_manager.get_setting("telegram_chat_id")

        if telegram_enabled and telegram_bot_token and telegram_chat_id:
            try:
                # Build the Telegram message
                message_parts = []
                message_parts.append("🚨 STOCK ALERT 🚨")
                message_parts.append(f"ALERT! {symbol} - {data.instrument_type if data.instrument_type else 'N/A'} - {combined_message_type_string}")
                
                if data.ratio is not None:
                    message_parts.append(f"Ratio: {data.ratio:.2f}")
                
                # OHLC
                ohlc_info = (
                    f"₹{data.price:.2f}(LTP) -- "
                    f"₹{data.open_price:.2f} (O) -- "
                    f"₹{data.high_price:.2f}(H) -- "
                    f"₹{data.low_price:.2f} (L) -- "
                    f"₹{data.close_price:.2f} (C)"
                )
                message_parts.append(ohlc_info)

                # TBQ/TSQ Day High/Low based on alert type
                tbq_info = []
                tsq_info = []

                # Determine if TBQ or TSQ are part of the alert message
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

                # Time and Date
                formatted_time = datetime.datetime.strptime(data.timestamp, "%Y-%m-%d %H:%M:%S").strftime("%I:%M:%S %p")
                formatted_date = datetime.datetime.strptime(data.timestamp, "%Y-%m-%d %H:%M:%S").strftime("%d-%m-%Y")
                message_parts.append(f"Time: {formatted_time}")
                message_parts.append(f"Date: {formatted_date}")

                telegram_message = "\n".join(message_parts)

                send_telegram_message(telegram_bot_token, telegram_chat_id, telegram_message)
                print("DEBUG: Telegram message sent successfully.")
            except Exception as e:
                print(f"ERROR: Failed to send Telegram message: {e}")
                QMessageBox.warning(self, "Telegram Error", f"Failed to send Telegram alert: {e}")


        # Check auto-trade settings and trigger trade if enabled
        if self.config.auto_trade_enabled:
            print(f"Auto-trade enabled for {symbol}. Triggering trade...")
            self.execute_auto_trade(data, primary_alert_type)

        # Check budget cap
        # if budget_cap > 0 and (default_quantity * trade_price) > budget_cap:
        #     QMessageBox.warning(self, "Auto Trade Blocked", f"Trade for {data.symbol} blocked: Exceeds Budget Cap (₹{budget_cap:.2f}).")
        #     self.db_manager.log_trade(
        #         timestamp=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        #         symbol=data.symbol,
        #         instrument_type=data.instrument_type,
        #         transaction_type=transaction_type,
        #         quantity=default_quantity,
        #         price=trade_price,
        #         order_type=order_type,
        #         product_type=product_type,
        #         status="REJECTED",
        #         message=f"Exceeded budget cap ₹{budget_cap:.2f}",
        #         alert_id=None # Link to alert later if needed
        #     )
        #     self.logs_widget.refresh_logs()
        #     return

        # try:
        #     # Place the order using KiteConnect
        #     order_id = self.kite.place_order(
        #         variety=self.kite.VARIETY_REGULAR, # or MIS/CO/BO based on config
        #         exchange=self._get_exchange_for_instrument_type(data.instrument_type),
        #         tradingsymbol=data.symbol,
        #         transaction_type=getattr(self.kite, f"TRANSACTION_TYPE_{transaction_type}"),
        #         quantity=default_quantity,
        #         product=getattr(self.kite, f"PRODUCT_{product_type}"),
        #         order_type=getattr(self.kite, f"ORDER_TYPE_{order_type}"),
        #         price=trade_price if order_type == "LIMIT" else None, # Price only for LIMIT orders
        #         trigger_price=trade_price if order_type in ["SL", "SL-M"] else None, # Trigger price for SL/SL-M
        #     )
        #     message = f"Auto {transaction_type} order placed for {data.symbol} (Qty: {default_quantity}, Price: {trade_price:.2f}). Order ID: {order_id}"
        #     status = "PLACED"
        # except Exception as e:
        #     message = f"Auto {transaction_type} order failed for {data.symbol}: {str(e)}"
        #     status = "REJECTED"
        #     order_id = None
        #     QMessageBox.critical(self, "Auto Trade Error", message)

        # self.db_manager.log_trade(
        #     timestamp=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        #     symbol=data.symbol,
        #     instrument_type=data.instrument_type,
        #     transaction_type=transaction_type,
        #     price=trade_price,
        #     alert_id=None # Link to alert later if needed
        # )
        self.logs_widget.refresh_logs() # Refresh logs tab to show new trade

    def _get_exchange_for_instrument_type(self, instrument_type: str) -> str:
        if instrument_type == 'EQ':
            return self.kite.EXCHANGE_NSE
        elif instrument_type in ['FUT', 'CE', 'PE']:
            return self.kite.EXCHANGE_NFO
        return self.kite.EXCHANGE_NSE # Default

    def open_trading_dialog(self, data: Dict[str, Any]):
        dialog = TradingDialog(self.kite, data, self.db_manager, self.config)
        dialog.trade_placed.connect(self.logs_widget.refresh_logs)
        dialog.exec_() # Show dialog modally

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

        # Prepare data for TradingDialog, including expiry and strike if available
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
        """Updates the AlertConfig object from the config widget settings."""
        self.config.load_settings_from_db(self.db_manager)
        print("MainWindow: AlertConfig updated from main config settings.")

    def update_status_bar(self):
        """Updates the status bar with current monitoring status."""
        if self.monitoring_thread and self.monitoring_thread.isRunning():
            if self.monitoring_thread.paused:
                self.status_label.setText("Status: Paused")
            else:
                self.status_label.setText("Status: Running")
        else:
            self.status_label.setText("Status: Stopped")

    def closeEvent(self, event):
        """Handles application close event, prompting user if monitoring is active."""
        if self.monitoring_thread and self.monitoring_thread.isRunning():
            reply = QMessageBox.question(
                self, "Confirm Exit",
                "Monitoring is running. Are you sure you want to exit?",
                QMessageBox.Yes | QMessageBox.No
            )

            if reply == QMessageBox.Yes:
                self.stop_monitoring()
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()

    def close_application(self):
        """Closes the application gracefully."""
        self.close()

def main():
    """Main application entry point."""
    app = QApplication(sys.argv)

    app.setApplicationName("Stock Volume Monitor Pro")
    app.setApplicationVersion("1.0.0")
    app.setOrganizationName("Trading Solutions")

    app.setStyle('Fusion')

    main_window = MainWindow()
    main_window.show()

    sys.exit(app.exec_())

if __name__ == "__main__":
    main()