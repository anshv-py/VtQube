from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QGridLayout, QLabel, QLineEdit,
    QPushButton, QSpinBox, QTimeEdit, QMessageBox, QDoubleSpinBox, QCheckBox,
    QGroupBox, QComboBox, QApplication
)
from PyQt5.QtCore import QTime, pyqtSignal, Qt
from PyQt5.QtGui import QColor
from dataclasses import dataclass
from typing import Optional
import datetime
import webbrowser

from pyqtspinner import WaitingSpinner
from database import DatabaseManager
from utils import RequestTokenServer

try:
    from kiteconnect import KiteConnect
except ImportError:
    QMessageBox.error("KiteConnect not installed. Try re-installing the application")
    KiteConnect = None

@dataclass
class AlertConfig:
    def __init__(self,
                 tbq_tsq_threshold: float,
                 start_time: Optional[datetime.time],
                 end_time: Optional[datetime.time],
                 telegram_enabled: Optional[bool] = False,
                 telegram_bot_token: Optional[str] = None,
                 telegram_chat_id: Optional[str] = None,
                 auto_trade_enabled: bool = False,
                 budget_cap: float = 0.0,
                 trade_ltp_percentage: float = 0.0,
                 ):
        self.tbq_tsq_threshold = tbq_tsq_threshold
        self.start_time = start_time
        self.end_time = end_time
        self.telegram_enabled = telegram_enabled
        self.telegram_bot_token = telegram_bot_token
        self.telegram_chat_id = telegram_chat_id

        self.auto_trade_enabled = auto_trade_enabled
        self.budget_cap = budget_cap
        self.trade_ltp_percentage = trade_ltp_percentage

    def is_valid(self) -> bool:
        if not (self.tbq_tsq_threshold >= 0):
            return False
        if self.start_time is None or self.end_time is None:
            pass
        return True

    def load_settings_from_db(self, db_manager: DatabaseManager):
        self.tbq_tsq_threshold = float(db_manager.get_setting("tbq_tsq_threshold", "0.0"))
        
        start_time_str = db_manager.get_setting("start_time")
        end_time_str = db_manager.get_setting("end_time")
        
        try:
            self.start_time = datetime.datetime.strptime(start_time_str, "%H:%M:%S").time() if start_time_str else None
        except ValueError:
            self.start_time = None
        
        try:
            self.end_time = datetime.datetime.strptime(end_time_str, "%H:%M:%S").time() if end_time_str else None
        except ValueError:
            self.end_time = None

        self.telegram_enabled = db_manager.get_setting("telegram_enabled", "False") == "Enabled"
        self.telegram_bot_token = db_manager.get_setting("telegram_bot_token")
        self.telegram_chat_id = db_manager.get_setting("telegram_chat_id")

        self.auto_trade_enabled = db_manager.get_setting("auto_trade_enabled", "False") == "True"
        self.budget_cap = float(db_manager.get_setting("budget_cap", "0.0"))
        self.trade_ltp_percentage = float(db_manager.get_setting("trade_ltp_percentage", "0.0"))

class ConfigWidget(QWidget):
    api_keys_saved = pyqtSignal()
    fetch_instruments_requested = pyqtSignal()
    login_success = pyqtSignal(str)
    config_saved = pyqtSignal()

    token_fetch_started = pyqtSignal(str)
    token_fetch_success = pyqtSignal(str)
    token_fetch_failure = pyqtSignal(str)

    def __init__(self, db_manager: DatabaseManager):
        super().__init__()
        self.db_manager = db_manager
        self.kite = None
        self.request_token_server: Optional[RequestTokenServer] = None
        self.init_ui()
        self.load_settings()

    def init_ui(self):
        layout = QVBoxLayout()
        afps = QApplication.instance().font().pointSize() if QApplication.instance() else 10
        self.setStyleSheet(f"""
            QGroupBox {{
                font-weight: bold;
                border: 2px solid #cccccc;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 15px;
                background-color: #ffffff;
                font-size: {int(afps * 1.2)}pt;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
                color: #333;
            }}
            QLabel {{
                font-size: {int(afps * 1.3)}pt;
            }}
            QLineEdit, QSpinBox, QDoubleSpinBox, QTimeEdit, QComboBox, QCheckBox {{
                padding: 8px;
                border: 1px solid #ccc;
                border-radius: 4px;
                font-size: {int(afps * 1.1)}pt;
            }}
            QPushButton {{
                background-color: #007bff;
                color: white;
                border: none;
                padding: 10px 15px;
                font-size: {int(afps * 1.3)}pt;
                font-weight: bold;
                border-radius: 5px;
            }}
            QPushButton:hover {{
                background-color: #0056b3;
            }}
        """)
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
        api_group = QGroupBox("KiteConnect API Settings")
        api_layout = QGridLayout()

        api_layout.addWidget(QLabel("API Key:"), 0, 0)
        self.api_key_input = QLineEdit()
        self.api_key_input.setPlaceholderText("Enter your KiteConnect API Key")
        api_layout.addWidget(self.api_key_input, 0, 1)

        api_layout.addWidget(QLabel("API Secret:"), 1, 0)
        self.api_secret_input = QLineEdit()
        self.api_secret_input.setPlaceholderText("Enter your KiteConnect API Secret")
        self.api_secret_input.setEchoMode(QLineEdit.Password)
        api_layout.addWidget(self.api_secret_input, 1, 1)

        self.show_hide_secret_checkbox = QCheckBox("Show Secret")
        self.show_hide_secret_checkbox.stateChanged.connect(self.toggle_api_secret_visibility)
        api_layout.addWidget(self.show_hide_secret_checkbox, 1, 2)

        self.fetch_token_btn = QPushButton("Fetch Access Token")
        self.fetch_token_btn.clicked.connect(self.fetch_access_token)
        api_layout.addWidget(self.fetch_token_btn, 3, 0, 1, 2)

        api_group.setLayout(api_layout)
        layout.addWidget(api_group)

        alert_group = QGroupBox("Alert Thresholds & Market Hours")
        alert_layout = QGridLayout()

        alert_layout.addWidget(QLabel("TBQ/TSQ Threshold (% Change):"), 1, 0)
        self.tbq_tsq_threshold_spin = QDoubleSpinBox()
        self.tbq_tsq_threshold_spin.setRange(0.01, 1000.00)
        self.tbq_tsq_threshold_spin.setSingleStep(0.01)
        self.tbq_tsq_threshold_spin.setDecimals(2)
        alert_layout.addWidget(self.tbq_tsq_threshold_spin, 1, 1)

        alert_layout.addWidget(QLabel("Market Start Time:"), 6, 0)
        self.start_time_edit = QTimeEdit()
        self.start_time_edit.setDisplayFormat("HH:mm:ss")
        alert_layout.addWidget(self.start_time_edit, 6, 1)

        alert_layout.addWidget(QLabel("Market End Time:"), 7, 0)
        self.end_time_edit = QTimeEdit()
        self.end_time_edit.setDisplayFormat("HH:mm:ss")
        alert_layout.addWidget(self.end_time_edit, 7, 1)

        alert_layout.addWidget(QLabel("Refresh Interval (seconds):"), 8, 0)
        self.refresh_interval_spin = QSpinBox()
        self.refresh_interval_spin.setRange(1, 60)
        self.refresh_interval_spin.setSingleStep(1)
        self.refresh_interval_spin.setValue(5)
        alert_layout.addWidget(self.refresh_interval_spin, 8, 1)

        alert_group.setLayout(alert_layout)
        layout.addWidget(alert_group)

        auto_trade_group = QGroupBox("Auto Trading Settings")
        auto_trade_layout = QGridLayout()

        auto_trade_layout.addWidget(QLabel("Enable Auto Trading:"), 0, 0)
        self.enable_auto_trade_checkbox = QCheckBox()
        auto_trade_layout.addWidget(self.enable_auto_trade_checkbox, 0, 1)

        auto_trade_layout.addWidget(QLabel("Budget Cap (₹):"), 2, 0)
        self.budget_cap_spin = QDoubleSpinBox()
        self.budget_cap_spin.setRange(0.00, 1000000000.00)
        self.budget_cap_spin.setSingleStep(100.00)
        self.budget_cap_spin.setDecimals(2)
        auto_trade_layout.addWidget(self.budget_cap_spin, 2, 1)

        auto_trade_layout.addWidget(QLabel("Trade LTP % (for Buy/Sell):"), 7, 0)
        self.trade_ltp_percentage_spin = QDoubleSpinBox()
        self.trade_ltp_percentage_spin.setRange(0.00, 100.00)
        self.trade_ltp_percentage_spin.setSingleStep(0.01)
        self.trade_ltp_percentage_spin.setDecimals(2)
        auto_trade_layout.addWidget(self.trade_ltp_percentage_spin, 7, 1)

        auto_trade_group.setLayout(auto_trade_layout)
        layout.addWidget(auto_trade_group)

        telegram_group = QGroupBox("Telegram Notifications")
        telegram_layout = QGridLayout()

        telegram_layout.addWidget(QLabel("Enable Telegram Notifications:"), 0, 0)
        self.telegram_enabled_combo = QComboBox()
        self.telegram_enabled_combo.addItems(["Enabled", "Disabled"])
        telegram_layout.addWidget(self.telegram_enabled_combo, 0, 1)

        telegram_layout.addWidget(QLabel("Telegram Bot Token:"), 1, 0)
        self.telegram_bot_token_input = QLineEdit()
        self.telegram_bot_token_input.setPlaceholderText("Enter your Telegram Bot Token")
        self.telegram_bot_token_input.setEchoMode(QLineEdit.Password)
        telegram_layout.addWidget(self.telegram_bot_token_input, 1, 1)

        self.show_hide_token_checkbox = QCheckBox("Show Token")
        self.show_hide_token_checkbox.stateChanged.connect(self.toggle_telegram_token_visibility)
        telegram_layout.addWidget(self.show_hide_token_checkbox, 1, 2)

        telegram_layout.addWidget(QLabel("Telegram Chat ID:"), 2, 0)
        self.telegram_chat_id_input = QLineEdit()
        self.telegram_chat_id_input.setPlaceholderText("Enter your Telegram Chat ID")
        telegram_layout.addWidget(self.telegram_chat_id_input, 2, 1)

        telegram_group.setLayout(telegram_layout)
        layout.addWidget(telegram_group)

        self.save_btn = QPushButton("Save Settings")
        self.save_btn.clicked.connect(self.save_settings)
        layout.addWidget(self.save_btn)

        layout.addStretch(1)

        self.setLayout(layout)

    def toggle_api_secret_visibility(self, state):
        if state == Qt.Checked:
            self.api_secret_input.setEchoMode(QLineEdit.Normal)
        else:
            self.api_secret_input.setEchoMode(QLineEdit.Password)

    def toggle_telegram_token_visibility(self, state):
        if state == Qt.Checked:
            self.telegram_bot_token_input.setEchoMode(QLineEdit.Normal)
        else:
            self.telegram_bot_token_input.setEchoMode(QLineEdit.Password)

    def load_settings(self):
        defaults = AlertConfig(
            tbq_tsq_threshold=0.05,
            start_time=QTime(9, 0, 0),
            end_time=QTime(15, 30, 0)
        )

        self.api_key_input.setText(self.db_manager.get_setting("api_key", ""))
        self.api_secret_input.setText(self.db_manager.get_setting("api_secret", ""))

        self.tbq_tsq_threshold_spin.setValue(float(self.db_manager.get_setting("tbq_tsq_threshold", str(defaults.tbq_tsq_threshold))))

        start_time_str = self.db_manager.get_setting("start_time", defaults.start_time.toString("HH:mm:ss"))
        end_time_str = self.db_manager.get_setting("end_time", defaults.end_time.toString("HH:mm:ss"))
        self.start_time_edit.setTime(QTime.fromString(start_time_str, "HH:mm:ss"))
        self.end_time_edit.setTime(QTime.fromString(end_time_str, "HH:mm:ss"))

        self.telegram_bot_token_input.setText(self.db_manager.get_setting("telegram_bot_token", ""))
        self.telegram_chat_id_input.setText(self.db_manager.get_setting("telegram_chat_id", ""))
        telegram_enabled_text = self.db_manager.get_setting("telegram_enabled", "Disabled")
        self.telegram_enabled_combo.setCurrentText(telegram_enabled_text)

        self.enable_auto_trade_checkbox.setChecked(
            self.db_manager.get_setting("auto_trade_enabled", str(defaults.auto_trade_enabled)) == "True"
        )
        self.budget_cap_spin.setValue(
            float(self.db_manager.get_setting("budget_cap", str(defaults.budget_cap)))
        )
        self.trade_ltp_percentage_spin.setValue(
            float(self.db_manager.get_setting("trade_ltp_percentage", str(defaults.trade_ltp_percentage)))
        )

    def save_settings(self):
        self.db_manager.save_setting("api_key", self.api_key_input.text())
        self.db_manager.save_setting("api_secret", self.api_secret_input.text())

        self.db_manager.save_setting("tbq_tsq_threshold", str(self.tbq_tsq_threshold_spin.value()))

        self.db_manager.save_setting("start_time", self.start_time_edit.time().toString("HH:mm:ss"))
        self.db_manager.save_setting("end_time", self.end_time_edit.time().toString("HH:mm:ss"))

        self.db_manager.save_setting("telegram_bot_token", self.telegram_bot_token_input.text())
        self.db_manager.save_setting("telegram_chat_id", self.telegram_chat_id_input.text())
        self.db_manager.save_setting("telegram_enabled", self.telegram_enabled_combo.currentText())

        self.db_manager.save_setting("auto_trade_enabled", str(self.enable_auto_trade_checkbox.isChecked()))
        self.db_manager.save_setting("budget_cap", str(self.budget_cap_spin.value()))
        self.db_manager.save_setting("trade_ltp_percentage", str(self.trade_ltp_percentage_spin.value()))
        self.api_keys_saved.emit()

        QMessageBox.information(self, "Settings Saved", "Application settings have been saved successfully!")

    def get_config(self) -> AlertConfig:
        return AlertConfig(
            tbq_tsq_threshold=self.tbq_tsq_threshold_spin.value(),
            start_time=self.start_time_edit.time(),
            end_time=self.end_time_edit.time(),

            telegram_bot_token=self.telegram_bot_token_input.text() if self.telegram_enabled_combo.currentText() == "Enabled" else None,
            telegram_chat_id=self.telegram_chat_id_input.text() if self.telegram_enabled_combo.currentText() == "Enabled" else None,
            
            auto_trade_enabled=self.enable_auto_trade_checkbox.isChecked(),
            budget_cap=self.budget_cap_spin.value(),
            trade_ltp_percentage=self.trade_ltp_percentage_spin.value(),
        )

    def fetch_access_token(self):
        self.spinner.start()
        api_key = self.api_key_input.text()
        api_secret = self.api_secret_input.text()

        if not api_key or not api_secret:
            QMessageBox.warning(self, "Missing Info", "Please provide API Key and API Secret")
            return

        if KiteConnect is None:
            QMessageBox.critical(self, "Error", "KiteConnect library not found. Please install it (`pip install kiteconnect`).")
            return

        try:
            self.kite = KiteConnect(api_key=api_key)
            login_url = self.kite.login_url()

            self.token_fetch_started.emit("Opening browser for KiteConnect login. Please complete the login and authorize the app.")
            webbrowser.open(login_url)

            self.request_token_server = RequestTokenServer(self.kite, self.db_manager.db_path)
            self.request_token_server.token_received.connect(self._on_token_received)
            self.request_token_server.server_error.connect(self._on_server_error)
            self.request_token_server.start()

        except Exception as e:
            self.token_fetch_failure.emit(f"Error initiating token fetch: {str(e)}")

    def _on_token_received(self, access_token: str):
        if self.request_token_server:
            self.request_token_server.stop()
            self.request_token_server = None

        self.db_manager.save_setting("access_token", access_token)
        self.db_manager.save_setting("last_instrument_fetch_date", str(datetime.datetime.now()))
        self.token_fetch_success.emit("Access Token fetched and saved successfully!")
        self.spinner.stop()
        self.login_success.emit(access_token)

    def _on_server_error(self, error_message: str):
        if self.request_token_server:
            self.request_token_server.stop()
            self.request_token_server = None
        self.token_fetch_failure.emit(f"Token server error: {error_message}")