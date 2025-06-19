import sip
import datetime
import pandas as pd
from threading import Lock
import xlsxwriter
from typing import List, Dict, Any, Tuple, Optional
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView,
    QComboBox, QMenu, QMessageBox, QApplication, QDateEdit
)
from PyQt5.QtCore import Qt, pyqtSignal, QObject, QThread, QTimer, pyqtSlot
from PyQt5.QtGui import QColor, QBrush
from database import DatabaseManager

class LogRefreshWorker(QObject):
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, db_path):
        super().__init__()
        self.db_path = db_path
        self.db_manager = None

    def run(self):
        try:
            print("ICH 1")
            all_logs = []
            db_access_lock = Lock()
            try:
                with db_access_lock:
                    self.db_manager = DatabaseManager(self.db_path)
                    all_volume_data = self.db_manager.get_volume_logs()
                    self.db_manager.close()
                for volume_data in all_volume_data:
                    all_logs.append({
                        "timestamp": volume_data['timestamp'],
                        "symbol": volume_data['symbol'],
                        "instrument_type": volume_data['instrument_type'],
                        "tbq": volume_data['tbq'],
                        "tbq_change_percent": volume_data['tbq_change_percent'],
                        "tsq": volume_data['tsq'],
                        "tsq_change_percent": volume_data['tsq_change_percent'],
                        "price": volume_data['price'],
                        "remark": volume_data['remark'],
                        "open_price": volume_data['open'],
                        "high_price": volume_data['high'],
                        "low_price": volume_data['low'],
                        "close_price": volume_data['close'],
                        "type_filter_category": "Baseline" if volume_data['is_baseline'] == "True" else "Log" if volume_data['alert_triggered'] == "False" else "Alert",
                        "added": False
                    })
                print("ICH 2")
                all_logs.sort(key=lambda x: datetime.datetime.strptime(x['timestamp'], "%Y-%m-%d %H:%M:%S"))
            except Exception as e:
                print(e)
            try:
                baseline_log_tracker = {}
                for log_entry in all_logs:
                    symbol = log_entry['symbol']
                    log_date = datetime.datetime.strptime(log_entry['timestamp'], "%Y-%m-%d %H:%M:%S").date()
                    if (symbol, log_date) not in baseline_log_tracker and log_entry['type_filter_category'] == "Baseline":
                        baseline_log_tracker[(symbol, log_date)] = True
                all_logs.sort(key=lambda x: datetime.datetime.strptime(x['timestamp'], "%Y-%m-%d %H:%M:%S"), reverse=True)
                self.finished.emit(all_logs)
                print("ICH 2.5: Finished emitted")
            except Exception as e:
                print("Here", e)
        except Exception as e:
            print(e)
            self.error.emit(f"Failed to refresh logs: {str(e)}")
        finally:
            self.db_manager.close()

class LogsWidget(QWidget):
    log_row_double_clicked = pyqtSignal(dict)

    def __init__(self, db_manager: DatabaseManager):
        super().__init__()
        self.db_manager = db_manager
        self.alerts_cache: List[Dict[str, Any]] = []
        self.seen_initial_log_for_symbol_date = set()
        self.current_page = 0
        self.logs_per_page = 50
        self.filtered_logs = []
        self._log_refreshing = False
        self.init_ui()
        self.log_thread = None
        self.log_worker = None
        self.refresh_logs()

    def init_ui(self):
        afps = QApplication.instance().font().pointSize() if QApplication.instance() else 10
        self.setStyleSheet(f"""
            QGroupBox {{
                font-weight: bold;
                border: 2px solid #cccccc;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 15px;
                background-color: #ffffff;
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
            QLineEdit, QSpinBox, QDoubleSpinBox, QTimeEdit, QComboBox, QTextEdit {{
                padding: 8px;
                border: 1px solid #ccc;
                border-radius: 4px;
                font-size: 20px;
            }}
            QPushButton {{
                background-color: #007bff;
                color: white;
                border: none;
                padding: 10px 15px;
                font-size: 20px;
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
                font-size: {afps * 1.1}pt;
            }}
            QHeaderView::section {{
                background-color: #f0f0f0;
                padding: 8px;
                border: 1px solid #ddd;
                font-weight: bold;
                font-size: {afps * 1.2}pt;
            }}
        """)
        main_layout = QVBoxLayout()
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("Filter by Symbol:"))
        self.symbol_filter_combo = QComboBox()
        self.symbol_filter_combo.addItem("All Symbols")
        self.symbol_filter_combo.currentIndexChanged.connect(self.filter_alerts_and_logs)
        filter_layout.addWidget(self.symbol_filter_combo, 1)
        filter_layout.addWidget(QLabel("Filter by Type:"))
        self.type_filter_combo = QComboBox()
        self.type_filter_combo.addItems(["All Types", "Alert", "Log", "Trade"])
        self.type_filter_combo.currentIndexChanged.connect(self.filter_alerts_and_logs)
        filter_layout.addWidget(self.type_filter_combo, 1)

        filter_layout.addWidget(QLabel("From:"))
        self.start_date_edit = QDateEdit(datetime.date.today().replace(day=1))
        self.start_date_edit.setCalendarPopup(True)
        self.start_date_edit.dateChanged.connect(self.filter_alerts_and_logs)
        filter_layout.addWidget(self.start_date_edit)

        filter_layout.addWidget(QLabel("To:"))
        self.end_date_edit = QDateEdit(datetime.date.today())
        self.end_date_edit.setCalendarPopup(True)
        self.end_date_edit.dateChanged.connect(self.filter_alerts_and_logs)
        filter_layout.addWidget(self.end_date_edit)

        main_layout.addLayout(filter_layout)

        self.log_table = QTableWidget()
        self.log_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.log_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.log_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.log_table.customContextMenuRequested.connect(self.show_context_menu)
        self.log_table.doubleClicked.connect(self._on_table_double_clicked)

        main_layout.addWidget(self.log_table)

        button_layout = QHBoxLayout()
        self.export_button = QPushButton("Export to Excel")
        self.export_button.clicked.connect(self.export_logs_to_excel)
        button_layout.addWidget(self.export_button)

        self.clear_button = QPushButton("Clear All Logs")
        self.clear_button.clicked.connect(self.clear_logs)
        button_layout.addWidget(self.clear_button)

        self.prev_button = QPushButton("◀")
        self.next_button = QPushButton("▶")
        self.prev_button.setFixedWidth(40)
        self.next_button.setFixedWidth(40)
        self.page_label = QLabel("Page 1")

        self.prev_button.clicked.connect(self.prev_page)
        self.next_button.clicked.connect(self.next_page)

        button_layout.addWidget(self.prev_button)
        button_layout.addWidget(self.page_label)
        button_layout.addWidget(self.next_button)

        main_layout.addLayout(button_layout)
        self.setLayout(main_layout)

        self.setMinimumSize(800, 600)
    
    @pyqtSlot(object)
    def handle_logs_refreshed_main_thread(self, logs):
        QTimer.singleShot(0, lambda: self.handle_logs_refreshed(logs))

    def populate_symbol_filter_combo(self):
        self.symbol_filter_combo.blockSignals(True)
        self.symbol_filter_combo.clear()
        self.symbol_filter_combo.addItem("All Symbols")

        unique_symbols = sorted(list(set(log['symbol'] for log in self.alerts_cache if log.get('symbol'))))
        self.symbol_filter_combo.addItems(unique_symbols)
        self.symbol_filter_combo.blockSignals(False)


    def filter_alerts_and_logs(self):
        symbol_filter = self.symbol_filter_combo.currentText()
        type_filter = self.type_filter_combo.currentText()
        start_date = self.start_date_edit.date().toPyDate()
        end_date = self.end_date_edit.date().toPyDate()
        filtered_logs = []

        for log_entry in self.alerts_cache:
            log_date = datetime.datetime.strptime(log_entry['timestamp'], "%Y-%m-%d %H:%M:%S").date()
            symbol_match = (symbol_filter == "All Symbols" or log_entry.get('symbol') == symbol_filter)
            type_match = (type_filter == "All Types" or log_entry.get('type_filter_category') == type_filter)
            date_match = (start_date <= log_date <= end_date)

            is_alert = log_entry.get('type_filter_category') == "Alert"
            is_baseline = log_entry.get('typ_filter_category') == "Baseline"

            if symbol_match and type_match and date_match and (is_alert or is_baseline) and not log_entry["added"]:
                log_entry["added"] = True
                filtered_logs.append(log_entry)

        self.filtered_logs = filtered_logs
        self.current_page = 0
        self._populate_table(self.filtered_logs)
    
    def update_page_label(self):
        total_pages = max(1, (len(self.filtered_logs) + self.logs_per_page - 1) // self.logs_per_page)
        self.page_label.setText(f"Page {self.current_page + 1} of {total_pages}")
        print("ICH 3e")

    def next_page(self):
        if (self.current_page + 1) * self.logs_per_page < len(self.filtered_logs):
            self.current_page += 1
            self._populate_table(self.filtered_logs)

    def prev_page(self):
        if self.current_page > 0:
            self.current_page -= 1
            self._populate_table(self.filtered_logs)

    def _populate_table(self, logs_to_display: List[Dict[str, Any]]):
        self.log_table.clearContents()
        self.log_table.setRowCount(0)

        columns = [
            ("Timestamp", 150), ("Symbol", 150), ("Type", 60), ("Price", 100),
            ("TBQ", 90), ("TBQ %", 90), ("TSQ", 90), ("TSQ %", 90),
            ("Open", 70), ("High", 70), ("Low", 70), ("Close", 70), ("Remark", 150)
        ]
        column_names = [col[0] for col in columns]
        self.log_table.setColumnCount(len(column_names))
        self.log_table.setHorizontalHeaderLabels(column_names)

        for i, col_width in enumerate([col[1] for col in columns]):
            self.log_table.setColumnWidth(i, col_width)

        print("ICH 3c")
        self.log_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        
        self.seen_initial_log_for_symbol_date.clear()

        start_idx = self.current_page * self.logs_per_page
        end_idx = start_idx + self.logs_per_page
        paginated_logs = logs_to_display[start_idx:end_idx]

        for row_idx, log_entry in enumerate(paginated_logs):
            self.log_table.insertRow(row_idx)

            row_bg_color = QColor(240, 240, 240) if row_idx % 2 == 0 else QColor(255, 255, 255) # Light grey and white

            if log_entry.get('type_filter_category', "Log") == "Baseline":
                row_bg_color = QColor(200, 220, 255)

            for col_idx, col_name in enumerate(column_names):
                item_text = ""
                bg_brush = QBrush(row_bg_color)

                if col_name == "Timestamp":
                    item_text = log_entry['timestamp']
                elif col_name == "Symbol":
                    item_text = log_entry.get('symbol', '')
                elif col_name == "Type":
                    item_text = log_entry.get('instrument_type', '')
                elif col_name == "Price":
                    price = log_entry.get('price')
                    item_text = f"₹{price:.2f}" if price is not None else ""
                elif col_name == "TBQ":
                    item_text = str(log_entry.get('tbq', ''))
                elif col_name == "TBQ %":
                    tbq_percent = log_entry.get('tbq_change_percent')
                    item_text = f"{tbq_percent:.2f}%" if tbq_percent is not None else ""
                elif col_name == "TSQ":
                    item_text = str(log_entry.get('tsq', ''))
                elif col_name == "TSQ %":
                    tsq_percent = log_entry.get('tsq_change_percent')
                    item_text = f"{tsq_percent:.2f}%" if tsq_percent is not None else ""
                elif col_name == "Open":
                    price = log_entry.get('open_price')
                    item_text = f"₹{price:.2f}" if price is not None else ""
                elif col_name == "High":
                    price = log_entry.get('high_price')
                    item_text = f"₹{price:.2f}" if price is not None else ""
                elif col_name == "Low":
                    price = log_entry.get('low_price')
                    item_text = f"₹{price:.2f}" if price is not None else ""
                elif col_name == "Close":
                    price = log_entry.get('close_price')
                    item_text = f"₹{price:.2f}" if price is not None else ""
                elif col_name == "Remark":
                    remark = log_entry.get('remark', '')
                    item_text = remark
                    if "-" in remark:
                        bg_brush = QBrush(QColor(255, 220, 180))
                    elif ("-" not in remark.lower()) and remark:
                        bg_brush = QBrush(QColor(180, 220, 255))
                    else:
                        bg_brush = QBrush(row_bg_color)

                item = QTableWidgetItem(item_text)
                item.setBackground(bg_brush)
                self.log_table.setItem(row_idx, col_idx, item)
        
        print("ICH 3d")
        self.update_page_label()
        self.log_table.resizeRowsToContents()

    def cleanup_thread(self):
        try:
            if self.log_thread and not sip.isdeleted(self.log_thread):
                if self.log_thread.isRunning():
                    print("Stopping log thread...")
                    self.log_thread.quit()
                    self.log_thread.wait(3000)
                self.log_thread.deleteLater()
            else:
                print("[Cleanup] log_thread is already deleted or None.")
        except Exception as e:
            print(f"[Cleanup] Thread cleanup error: {e}")

        try:
            if self.log_worker and not sip.isdeleted(self.log_worker):
                self.log_worker.deleteLater()
            else:
                print("[Cleanup] log_worker is already deleted or None.")
        except Exception as e:
            print(f"[Cleanup] Worker cleanup error: {e}")

        self.log_thread = None
        self.log_worker = None

    def refresh_logs(self):
        if self._log_refreshing:
            print("Already refreshing logs. Skipping this cycle.")
            return
        self._log_refreshing = True
        try:
            print("ICH")
            self.cleanup_thread()

            self.log_thread = QThread()
            self.log_worker = LogRefreshWorker(self.db_manager.db_path)
            self.log_worker.moveToThread(self.log_thread)
            print("ICH 2.9")
            self.log_thread.started.connect(self.log_worker.run)
            print("ICH 3")
            self.log_worker.finished.connect(self.handle_logs_refreshed_main_thread, Qt.QueuedConnection)
            print("ICH 4")
            self.log_worker.error.connect(self.handle_log_error)

            self.log_worker.finished.connect(self.log_thread.quit)
            self.log_worker.finished.connect(lambda: QTimer.singleShot(100, self.log_worker.deleteLater))
            self.log_thread.finished.connect(lambda: QTimer.singleShot(100, self.log_thread.deleteLater))

            self.log_thread.start()
        except Exception as e:
            print(e)


    def handle_logs_refreshed(self, all_logs: List[Dict[str, Any]]):
        if not self:
            print("Error here")
            return
        print("ICH 3.1")
        self._log_refreshing = False
        try:
            self.alerts_cache = all_logs
            print("ICH 3a")
            self.populate_symbol_filter_combo()
            print("ICH 3b")
            self.filter_alerts_and_logs()
        except Exception as e:
            print("handle_logs_refreshed crashed:", e)

    def handle_log_error(self, error_message: str):
        self._log_refreshing = False
        QMessageBox.critical(self, "Log Refresh Error", error_message)

    def show_context_menu(self, pos):
        menu = QMenu(self)
        export_row_action = menu.addAction("Export Selected Row(s) to Excel")
        export_all_action = menu.addAction("Export All Filtered Logs to Excel")
        
        action = menu.exec_(self.log_table.mapToGlobal(pos))

        if action == export_row_action:
            self._export_selected_rows_to_excel()
        elif action == export_all_action:
            self.export_logs_to_excel()

    def _export_selected_rows_to_excel(self):
        selected_rows_indices = sorted(list(set(index.row() for index in self.log_table.selectedIndexes())))
        if not selected_rows_indices:
            QMessageBox.warning(self, "No Rows Selected", "Please select one or more rows to export.")
            return

        selected_logs_data = [self.alerts_cache[idx] for idx in selected_rows_indices]

        df = pd.DataFrame(selected_logs_data)

        excel_columns_mapping = {
            "timestamp": "Timestamp", "symbol": "Symbol", "instrument_type": "Type",
            "price": "Price", "tbq": "TBQ", "tbq_change_percent": "TBQ %",
            "tsq": "TSQ", "tsq_change_percent": "TSQ %",
            "open_price": "Open", "high_price": "High", "low_price": "Low", "close_price": "Close",
            "remark": "Remark", "type_filter_category": "Category", "is_initial_log": "Is Initial Log" # Keep this temporarily for formatting
        }
        
        df_for_excel = pd.DataFrame(columns=excel_columns_mapping.keys())
        for col_key in excel_columns_mapping.keys():
            if col_key in df.columns:
                df_for_excel[col_key] = df[col_key]
            else:
                df_for_excel[col_key] = None

        df_for_excel = df_for_excel.rename(columns=excel_columns_mapping)

        for col in ["Price", "TBQ %", "TSQ %", "Open", "High", "Low", "Close"]:
            if col in df_for_excel.columns:
                if col == "Price" or col == "Open" or col == "High" or col == "Low" or col == "Close":
                    df_for_excel[col] = df_for_excel[col].apply(lambda x: f"₹{x:.2f}" if pd.notna(x) else "")
                elif col == "TBQ %" or col == "TSQ %":
                    df_for_excel[col] = df_for_excel[col].apply(lambda x: f"{x:.2f}%" if pd.notna(x) else "")
        
        if 'Timestamp' in df_for_excel.columns:
            df_for_excel['Timestamp'] = pd.to_datetime(df_for_excel['Timestamp']).dt.strftime("%Y-%m-%d %H:%M:%S")

        file_name = f"selected_logs_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"

        try:
            writer = pd.ExcelWriter(file_name, engine='xlsxwriter')
            workbook = writer.book
            worksheet = workbook.add_worksheet('Selected Logs')

            light_orange_format = workbook.add_format({'bg_color': '#FFDCAF'})
            light_blue_format = workbook.add_format({'bg_color': '#B4D7F7'})
            lighter_blue_format = workbook.add_format({'bg_color': '#C8DCFF'})
            light_grey_format = workbook.add_format({'bg_color': '#F0F0F0'})
            default_format = workbook.add_format()
            header_format = workbook.add_format({'bold': True, 'bg_color': '#F0F0F0', 'border': 1})
            for col_num, value in enumerate(df_for_excel.columns):
                worksheet.write(0, col_num, value, header_format)

            remark_col_idx = df_for_excel.columns.get_loc('Remark') if 'Remark' in df_for_excel.columns else -1
            is_initial_log_col_idx = df_for_excel.columns.get_loc('Is Initial Log') if 'Is Initial Log' in df_for_excel.columns else -1

            for row_num in range(len(df_for_excel)):
                excel_row = row_num + 1

                row_data = df_for_excel.iloc[row_num]
                
                current_row_base_format = default_format
                if row_num % 2 == 0:
                    current_row_base_format = light_grey_format

                if is_initial_log_col_idx != -1 and row_data.iloc[is_initial_log_col_idx]:
                    current_row_base_format = lighter_blue_format

                for col_idx, cell_value in enumerate(row_data):
                    format_to_apply = current_row_base_format

                    if col_idx == remark_col_idx:
                        remark_text = str(cell_value).lower()
                        if "-" in remark_text:
                            format_to_apply = light_orange_format
                        elif ("-" not in remark_text) and remark_text:
                            format_to_apply = light_blue_format

                    worksheet.write(excel_row, col_idx, cell_value, format_to_apply)
            
            for i, col in enumerate(df_for_excel.columns):
                max_len = max(df_for_excel[col].astype(str).map(len).max(), len(col))
                worksheet.set_column(i, i, max_len + 2) # Add a little padding

            writer.close()
            QMessageBox.information(self, "Export Successful", f"Selected logs exported to {file_name}")
        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"Failed to export selected logs: {str(e)}")

    def export_logs_to_excel(self):
        if not self.alerts_cache:
            QMessageBox.warning(self, "No Data", "No logs to export. Please refresh or check filters.")
            return
        symbol_filter = self.symbol_filter_combo.currentText()
        type_filter = self.type_filter_combo.currentText()
        start_date = self.start_date_edit.date().toPyDate()
        end_date = self.end_date_edit.date().toPyDate()

        filtered_alerts_cache = []
        for log_entry in self.alerts_cache:
            log_date = datetime.datetime.strptime(log_entry['timestamp'], "%Y-%m-%d %H:%M:%S").date()
            
            symbol_match = (symbol_filter == "All Symbols" or log_entry.get('symbol') == symbol_filter)
            type_match = (type_filter == "All Types" or log_entry.get('type_filter_category') == type_filter)
            date_match = (start_date <= log_date <= end_date)

            if symbol_match and type_match and date_match:
                filtered_alerts_cache.append(log_entry)

        df = pd.DataFrame(filtered_alerts_cache)

        excel_columns_mapping = {
            "timestamp": "Timestamp", "symbol": "Symbol", "instrument_type": "Type",
            "price": "Price", "tbq": "TBQ", "tbq_change_percent": "TBQ %",
            "tsq": "TSQ", "tsq_change_percent": "TSQ %",
            "open_price": "Open", "high_price": "High", "low_price": "Low", "close_price": "Close",
            "remark": "Remark", "type_filter_category": "Category", "is_initial_log": "Is Initial Log"
        }
        
        df_for_excel = pd.DataFrame(columns=excel_columns_mapping.keys())
        for col_key in excel_columns_mapping.keys():
            if col_key in df.columns:
                df_for_excel[col_key] = df[col_key]
            else:
                df_for_excel[col_key] = None

        df_for_excel = df_for_excel.rename(columns=excel_columns_mapping)

        for col in ["Price", "TBQ %", "TSQ %", "Open", "High", "Low", "Close"]:
            if col in df_for_excel.columns:
                if col == "Price" or col == "Open" or col == "High" or col == "Low" or col == "Close":
                    df_for_excel[col] = df_for_excel[col].apply(lambda x: f"₹{x:.2f}" if pd.notna(x) else "")
                elif col == "TBQ %" or col == "TSQ %":
                    df_for_excel[col] = df_for_excel[col].apply(lambda x: f"{x:.2f}%" if pd.notna(x) else "")
        
        if 'Timestamp' in df_for_excel.columns:
            df_for_excel['Timestamp'] = pd.to_datetime(df_for_excel['Timestamp']).dt.strftime("%Y-%m-%d %H:%M:%S")

        file_name = f"volume_logs_{datetime.datetime.today()}.xlsx"

        try:
            writer = pd.ExcelWriter(file_name, engine='xlsxwriter')
            workbook = writer.book
            worksheet = workbook.add_worksheet('Logs')

            light_orange_format = workbook.add_format({'bg_color': '#FFDCAF'})
            light_blue_format = workbook.add_format({'bg_color': '#B4D7F7'})
            lighter_blue_format = workbook.add_format({'bg_color': '#C8DCFF'})
            light_grey_format = workbook.add_format({'bg_color': '#F0F0F0'})
            default_format = workbook.add_format()

            header_format = workbook.add_format({'bold': True, 'bg_color': '#F0F0F0', 'border': 1})
            for col_num, value in enumerate(df_for_excel.columns):
                worksheet.write(0, col_num, value, header_format)

            remark_col_idx = df_for_excel.columns.get_loc('Remark') if 'Remark' in df_for_excel.columns else -1
            is_initial_log_col_idx = df_for_excel.columns.get_loc('Is Initial Log') if 'Is Initial Log' in df_for_excel.columns else -1

            for row_num in range(len(df_for_excel)):
                excel_row = row_num + 1

                row_data = df_for_excel.iloc[row_num]
                current_row_base_format = default_format
                if row_num % 2 == 0:
                    current_row_base_format = light_grey_format

                if is_initial_log_col_idx != -1 and row_data.iloc[is_initial_log_col_idx]:
                    current_row_base_format = lighter_blue_format

                for col_idx, cell_value in enumerate(row_data):
                    format_to_apply = current_row_base_format

                    if col_idx == remark_col_idx:
                        remark_text = str(cell_value).lower()
                        if "-" in remark_text:
                            format_to_apply = light_orange_format
                        elif ("-" not in remark_text) and remark_text:
                            format_to_apply = light_blue_format

                    worksheet.write(excel_row, col_idx, cell_value, format_to_apply)
            
            for i, col in enumerate(df_for_excel.columns):
                max_len = max(df_for_excel[col].astype(str).map(len).max(), len(col))
                worksheet.set_column(i, i, max_len + 2)

            writer.close()
            QMessageBox.information(self, "Export Successful", f"Logs exported to {file_name}")
        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"Failed to export logs: {str(e)}")


    def clear_logs(self):
        reply = QMessageBox.question(
            self, "Confirm Clear",
            "Are you sure you want to clear ALL volume logs and alerts and trades from the database?\nThis action cannot be undone.",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            try:
                self.db_manager.clear_all_logs()
                self.populate_symbol_filter_combo()
                QMessageBox.information(self, "Success", "All logs cleared successfully!")

            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to clear logs: {str(e)}")

    def _on_table_double_clicked(self, index):
        row = index.row()
        if 0 <= row < len(self.alerts_cache):
            self.log_row_double_clicked.emit(self.alerts_cache[row])