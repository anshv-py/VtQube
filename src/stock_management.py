import pandas as pd
from typing import List, Optional, Tuple
import traceback
from PyQt5.QtCore import Qt, QStringListModel, pyqtSignal, QObject
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QCompleter,
    QAbstractItemView, QGroupBox
)
from PyQt5.QtGui import QKeyEvent
try:
    from kiteconnect import KiteConnect
except ImportError:
    KiteConnect = None

from database import DatabaseManager
class InstrumentManager(QObject):
    user_instruments_changed = pyqtSignal()

    def __init__(self, db_manager: DatabaseManager, instrument_type: str, user_table_name: str):
        super().__init__()
        self.db_manager = db_manager
        self.instrument_type = instrument_type
        self.user_table_name = user_table_name
        self.kite = None
        
        self.exchange = self._get_default_exchange(instrument_type)
        self.all_tradable_symbols: List[Tuple[str, str, str, int, Optional[str], Optional[float]]] = []
        self.load_all_tradable_instruments_from_db()

        self.user_selected_symbols: List[str] = []
        self.load_user_instruments()

    def _get_default_exchange(self, instrument_type: str) -> str:
        if instrument_type == 'EQ':
            return 'NSE'
        elif instrument_type in ['FUT', 'OPT']:
            return 'NFO'
        return ''


    def set_kite_instance(self, kite_instance: KiteConnect):
        self.kite = kite_instance

    def fetch_all_tradable_instruments(self, raw_instruments_df: pd.DataFrame):
        if self.kite is None:
            return
        thread_db_manager = DatabaseManager(self.db_manager.db_path)
        
        try:
            filtered_df = self.filter_instruments(raw_instruments_df)
            instruments_to_save = [
                (row['tradingsymbol'], row['instrument_type'], row['exchange'],
                 row['instrument_token'], row['expiry'], row['strike'])
                for index, row in filtered_df.iterrows()
            ]
            if instruments_to_save:
                thread_db_manager.bulk_save_tradable_instruments(instruments_to_save)
            else:
                pass
        except Exception as e:
            pass
        finally:
            thread_db_manager.close()

    def filter_instruments(self, raw_instruments_df: pd.DataFrame) -> pd.DataFrame:
        for col in ['instrument_type', 'exchange', 'tradingsymbol', 'instrument_token', 'name', 'expiry', 'strike']:
            if col not in raw_instruments_df.columns:
                raw_instruments_df[col] = None

        filtered_df = pd.DataFrame()
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
            filtered_df = raw_instruments_df[
                (raw_instruments_df['instrument_type_upper'].isin(['CE', 'PE'])) &
                (raw_instruments_df['exchange_upper'] == self.exchange.upper())
            ].copy()
        else:
            return pd.DataFrame()
        if 'instrument_type_upper' in filtered_df.columns:
            filtered_df = filtered_df.drop(columns=['instrument_type_upper'])
        if 'exchange_upper' in filtered_df.columns:
            filtered_df = filtered_df.drop(columns=['exchange_upper'])
        return filtered_df


    def load_all_tradable_instruments_from_db(self, instrument_t: Optional[str] = None, option_category: Optional[str] = None):
        self.all_tradable_symbols = self.db_manager.get_all_tradable_instruments(
            instrument_type=instrument_t or self.instrument_type,
            exchange=self.exchange,
            option_category=option_category
        )


    def get_all_tradable_instruments(self) -> List[Tuple[str, str, str, int, Optional[str], Optional[float]]]:
        return self.all_tradable_symbols


    def load_user_instruments(self):
        self.user_selected_symbols = self.db_manager.load_user_instruments(self.user_table_name)


    def get_user_selected_symbols(self) -> List[str]:
        return self.user_selected_symbols

    def add_user_instrument(self, symbol: str):
        if symbol not in self.user_selected_symbols:
            if not any(inst[0] == symbol for inst in self.all_tradable_symbols):
                QMessageBox.warning(None, "Invalid Symbol", f"'{symbol}' is not a valid tradable {self.instrument_type} symbol. Please select from the available list.")
                return False

            self.db_manager.save_user_instrument(self.user_table_name, symbol)
            self.user_selected_symbols.append(symbol)
            self.user_selected_symbols.sort()
            self.user_instruments_changed.emit()
            return True
        return False


    def remove_user_instrument(self, symbol: str):
        if symbol in self.user_selected_symbols:
            self.db_manager.remove_user_instrument(self.user_table_name, symbol)
            self.user_selected_symbols.remove(symbol)
            self.user_instruments_changed.emit()
            return True
        return False


    def get_tradable_instrument_details(self, symbol: str) -> Optional[Tuple[str, str, str, int, Optional[str], Optional[float]]]:
        for instrument in self.all_tradable_symbols:
            if instrument[0] == symbol:
                return instrument
        return None
class InstrumentSelectionWidget(QWidget):
    def __init__(self, instrument_manager: InstrumentManager, display_name: str):
        super().__init__()
        self.instrument_manager = instrument_manager
        self.display_name = display_name
        
        self.available_instruments_list = QListWidget()
        self.add_selected_button = QPushButton(f"Add Selected {self.display_name}")
        self.monitored_instruments_list = QListWidget()
        self.completer_model = QStringListModel()
        self.completer = QCompleter(self.completer_model, self)
        self.monitored_instruments_list = QListWidget()

        self.init_ui()

        self.instrument_manager.user_instruments_changed.connect(self.update_monitored_list)
        self.instrument_manager.user_instruments_changed.connect(self.populate_available_instruments_list)
        self.populate_available_instruments_list()


    def populate_available_instruments_list(self):
        self.available_instruments_list.clear()
        all_tradable = self.instrument_manager.get_all_tradable_instruments()
        user_selected = set(self.instrument_manager.get_user_selected_symbols())

        for instrument_data in all_tradable:
            symbol = instrument_data[0]
            item = QListWidgetItem(symbol)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            if symbol in user_selected:
                item.setCheckState(Qt.Checked)
            else:
                item.setCheckState(Qt.Unchecked)
            self.available_instruments_list.addItem(item)


    def update_monitored_list(self):
        self.monitored_instruments_list.clear()
        for symbol in self.instrument_manager.get_user_selected_symbols():
            self.monitored_instruments_list.addItem(symbol)
    
    def populate_all_symbols(self):
        tradable_symbols = [inst[0] for inst in self.instrument_manager.get_all_tradable_instruments()]
        self.completer_model.setStringList(tradable_symbols)

    def add_selected_instruments(self):
        symbols_to_add = []
        for i in range(self.available_instruments_list.count()):
            item = self.available_instruments_list.item(i)
            if item.checkState() == Qt.Checked:
                symbols_to_add.append(item.text())
        
        added_count = 0
        for symbol in symbols_to_add:
            if self.instrument_manager.add_user_instrument(symbol):
                added_count += 1
        
        if added_count > 0:
            QMessageBox.information(self, "Success", f"{added_count} {self.display_name.lower()}(s) added to monitored list.")
            self.populate_available_instruments_list()
        else:
            QMessageBox.information(self, "No Change", "No new instruments were selected or added.")


    def remove_selected_instruments(self):
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
            
            removed_count = 0
            for symbol in symbols_to_remove:
                if self.instrument_manager.remove_user_instrument(symbol):
                    removed_count += 1
            
            if removed_count > 0:
                QMessageBox.information(self, "Success", f"{removed_count} {self.display_name.lower()}(s) removed.")
                self.populate_available_instruments_list()
            else:
                QMessageBox.warning(self, "Error", "Failed to remove selected instruments.")

    def init_ui(self):
        layout = QVBoxLayout()
        self.setLayout(layout)

        available_group = QGroupBox(f"Available {self.display_name}")
        available_layout = QVBoxLayout()
        available_group.setLayout(available_layout)

        filter_layout = QHBoxLayout()
        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText("Filter available instruments...")
        self.filter_input.textChanged.connect(self.filter_available_instruments)
        filter_layout.addWidget(self.filter_input)
        available_layout.addLayout(filter_layout)

        available_layout.addWidget(self.available_instruments_list)

        available_buttons_layout = QHBoxLayout()
        self.add_selected_button.clicked.connect(self.add_selected_instruments)
        available_buttons_layout.addWidget(self.add_selected_button)
        available_layout.addLayout(available_buttons_layout)
        layout.addWidget(available_group)

        monitored_group = QGroupBox(f"Monitored {self.display_name}")
        monitored_layout = QVBoxLayout()
        monitored_group.setLayout(monitored_layout)

        self.monitored_instruments_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        monitored_layout.addWidget(self.monitored_instruments_list)

        remove_monitored_buttons_layout = QHBoxLayout()
        monitored_layout.addLayout(remove_monitored_buttons_layout)
        layout.addWidget(monitored_group)
    
    def filter_available_instruments(self, text):
        for i in range(self.available_instruments_list.count()):
            item = self.available_instruments_list.item(i)
            if text.lower() in item.text().lower():
                item.setHidden(False)
            else:
                item.setHidden(True)

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key_Delete and self.monitored_instruments_list.hasFocus():
            self.remove_selected_instruments()
            event.accept()
            return
        super().keyPressEvent(event)