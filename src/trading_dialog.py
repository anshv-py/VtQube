from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QGridLayout, QLabel, 
    QSpinBox, QDoubleSpinBox, QComboBox, QDialogButtonBox, QMessageBox
)
from PyQt5.QtCore import Qt, pyqtSignal
import datetime
from database import DatabaseManager

class TradingDialog(QDialog):
    order_placed = pyqtSignal(dict)

    def __init__(self, db_manager: DatabaseManager, initial_data: dict = None, parent=None, kite_instance=None, config=None):
        super().__init__(parent)
        self.db_manager = db_manager
        self.initial_data = initial_data if initial_data else {}
        self.kite = kite_instance
        self.main_app_config = config
        self.budget_cap = float(self.db_manager.get_setting("budget_cap", "0.0"))
        
        self.init_ui()
        self._populate_initial_data()

    def init_ui(self):
        self.setWindowTitle("Place Order")
        self.setModal(True)

        layout = QVBoxLayout()
        form_layout = QGridLayout()

        row_idx = 0

        form_layout.addWidget(QLabel("Symbol:"), row_idx, 0)
        self.symbol_label = QLabel("")
        self.symbol_label.setStyleSheet("font-weight: bold;")
        form_layout.addWidget(self.symbol_label, row_idx, 1)
        row_idx += 1

        form_layout.addWidget(QLabel("Instrument Type:"), row_idx, 0)
        self.instrument_type_label = QLabel("")
        self.instrument_type_label.setStyleSheet("font-weight: bold;")
        form_layout.addWidget(self.instrument_type_label, row_idx, 1)
        row_idx += 1

        self.expiry_date_label_title = QLabel("Expiry Date:")
        self.expiry_date_label = QLabel("N/A")
        self.expiry_date_label.setStyleSheet("font-weight: bold;")
        form_layout.addWidget(self.expiry_date_label_title, row_idx, 0)
        form_layout.addWidget(self.expiry_date_label, row_idx, 1)
        self.expiry_date_label_title.hide()
        self.expiry_date_label.hide()
        row_idx += 1

        self.strike_price_label_title = QLabel("Strike Price:")
        self.strike_price_label = QLabel("N/A")
        self.strike_price_label.setStyleSheet("font-weight: bold;")
        form_layout.addWidget(self.strike_price_label_title, row_idx, 0)
        form_layout.addWidget(self.strike_price_label, row_idx, 1)
        self.strike_price_label_title.hide()
        self.strike_price_label.hide()
        row_idx += 1

        form_layout.addWidget(QLabel("Action:"), row_idx, 0)
        self.transaction_type_label = QLabel("")
        self.transaction_type_label.setStyleSheet("font-weight: bold; color: green;")
        form_layout.addWidget(self.transaction_type_label, row_idx, 1)
        row_idx += 1

        form_layout.addWidget(QLabel("LTP (₹):"), row_idx, 0)
        self.price_spinbox = QDoubleSpinBox()
        self.price_spinbox.setRange(0.00, 1000000.00)
        self.price_spinbox.setSingleStep(0.05)
        self.price_spinbox.setDecimals(2)
        self.price_spinbox.setReadOnly(True)
        self.price_spinbox.setEnabled(False)
        form_layout.addWidget(self.price_spinbox, row_idx, 1)
        row_idx += 1

        form_layout.addWidget(QLabel("Quantity:"), row_idx, 0)
        self.quantity_spinbox = QSpinBox()
        self.quantity_spinbox.setRange(1, 1000000)
        self.quantity_spinbox.setSingleStep(1)
        form_layout.addWidget(self.quantity_spinbox, row_idx, 1)
        row_idx += 1

        form_layout.addWidget(QLabel("Product Type:"), row_idx, 0)
        self.product_type_combo = QComboBox()
        self.product_type_combo.addItems(["MIS", "CNC", "NRML"])
        self.product_type_combo.setCurrentText("NRML")
        form_layout.addWidget(self.product_type_combo, row_idx, 1)
        row_idx += 1

        form_layout.addWidget(QLabel("Order Type:"), row_idx, 0)
        self.order_type_combo = QComboBox()
        self.order_type_combo.addItems(["MARKET", "LIMIT", "SL", "SL-M"])
        self.order_type_combo.setCurrentText("LIMIT")
        self.order_type_combo.currentIndexChanged.connect(self._toggle_price_and_trigger_fields)
        form_layout.addWidget(self.order_type_combo, row_idx, 1)
        row_idx += 1

        form_layout.addWidget(QLabel("Stop Loss (%):"), row_idx, 0)
        self.stop_loss_percent_spin = QDoubleSpinBox()
        self.stop_loss_percent_spin.setRange(0.00, 100.00)
        self.stop_loss_percent_spin.setSingleStep(0.01)
        self.stop_loss_percent_spin.setDecimals(2)
        self.stop_loss_percent_spin.setValue(0.00)
        form_layout.addWidget(self.stop_loss_percent_spin, row_idx, 1)
        row_idx += 1

        form_layout.addWidget(QLabel("Target Profit (%):"), row_idx, 0)
        self.target_profit_percent_spin = QDoubleSpinBox()
        self.target_profit_percent_spin.setRange(0.00, 100.00)
        self.target_profit_percent_spin.setSingleStep(0.01)
        self.target_profit_percent_spin.setDecimals(2)
        self.target_profit_percent_spin.setValue(0.00)
        form_layout.addWidget(self.target_profit_percent_spin, row_idx, 1)
        row_idx += 1

        self.trigger_price_label_title = QLabel("Trigger Price (₹):")
        self.trigger_price_spinbox = QDoubleSpinBox()
        self.trigger_price_spinbox.setRange(0.00, 1000000.00)
        self.trigger_price_spinbox.setSingleStep(0.05)
        self.trigger_price_spinbox.setDecimals(2)
        form_layout.addWidget(self.trigger_price_label_title, row_idx, 0)
        form_layout.addWidget(self.trigger_price_spinbox, row_idx, 1)
        self.trigger_price_label_title.hide()
        self.trigger_price_spinbox.hide()
        row_idx += 1

        layout.addLayout(form_layout)

        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept_order)
        self.button_box.rejected.connect(self.reject)
        self.button_box.button(QDialogButtonBox.Ok).setText("Place Order")
        self.button_box.button(QDialogButtonBox.Ok).setStyleSheet("background-color: #28a745; color: white; border-radius: 5px; padding: 8px 15px;")
        self.button_box.button(QDialogButtonBox.Cancel).setStyleSheet("background-color: #dc3545; color: white; border-radius: 5px; padding: 8px 15px;")

        layout.addWidget(self.button_box)
        self.setLayout(layout)

        self._toggle_price_and_trigger_fields()

    def _populate_initial_data(self):
        self.symbol_label.setText(self.initial_data.get("symbol", "N/A"))
        instrument_type = self.initial_data.get("instrument_type", "N/A")
        self.instrument_type_label.setText(instrument_type)

        if instrument_type in ['CE', 'PE'] and self.initial_data.get("expiry_date") and self.initial_data.get("strike_price") is not None:
            self.expiry_date_label.setText(self.initial_data["expiry_date"])
            self.strike_price_label.setText(f"₹{self.initial_data['strike_price']:.2f}")
            self.expiry_date_label_title.show()
            self.expiry_date_label.show()
            self.strike_price_label_title.show()
            self.strike_price_label.show()
        else:
            self.expiry_date_label_title.hide()
            self.expiry_date_label.hide()
            self.strike_price_label_title.hide()
            self.strike_price_label.hide()

        transaction_type = self.initial_data.get("transaction_type", "Buy")
        self.transaction_type_label.setText(transaction_type)
        if transaction_type == "Buy":
            self.transaction_type_label.setStyleSheet("font-weight: bold; color: green;")
        else:
            self.transaction_type_label.setStyleSheet("font-weight: bold; color: red;")

        initial_price = float(self.initial_data.get("price", 0.0))
        self.price_spinbox.setValue(initial_price)


        if self.initial_data.get("quantity"):
            calculated_quantity = self.initial_data.get("quantity")
            if calculated_quantity == 0:
                calculated_quantity = 1
            self.quantity_spinbox.setValue(calculated_quantity)
        else:
            self.quantity_spinbox.setValue(1)

    def _toggle_price_and_trigger_fields(self):
        order_type = self.order_type_combo.currentText()
        if order_type == "MARKET":
            self.price_spinbox.setReadOnly(True)
            self.price_spinbox.setEnabled(False)
            self.trigger_price_spinbox.setVisible(False)
            self.trigger_price_label_title.setVisible(False)
        elif order_type == "LIMIT":
            self.price_spinbox.setReadOnly(False)
            self.price_spinbox.setEnabled(True)
            self.trigger_price_spinbox.setVisible(False)
            self.trigger_price_label_title.setVisible(False)
        elif order_type in ["SL", "SL-M"]:
            self.price_spinbox.setReadOnly(False)
            self.price_spinbox.setEnabled(True)
            self.trigger_price_spinbox.setVisible(True)
            self.trigger_price_label_title.setVisible(True)

    def accept_order(self):
        symbol = self.symbol_label.text()
        instrument_type = self.instrument_type_label.text()
        transaction_type = self.transaction_type_label.text()
        quantity = self.quantity_spinbox.value()
        price = self.price_spinbox.value()
        product_type = self.product_type_combo.currentText()
        order_type = self.order_type_combo.currentText()
        trigger_price = self.trigger_price_spinbox.value() if self.trigger_price_spinbox.isVisible() else None

        if quantity <= 0:
            QMessageBox.warning(self, "Validation Error", "Quantity must be greater than 0.")
            return
        if order_type != "MARKET" and price <= 0:
            QMessageBox.warning(self, "Validation Error", "Price must be greater than 0 for LIMIT/SL/SL-M orders.")
            return
        if order_type in ["SL", "SL-M"] and (trigger_price is None or trigger_price <= 0):
            QMessageBox.warning(self, "Validation Error", "Trigger Price must be greater than 0 for SL/SL-M orders.")
            return
        
        if self.budget_cap > 0 and (quantity * price) > self.budget_cap:
            QMessageBox.warning(
                self, "Budget Exceeded",
                f"Estimated order cost (₹{quantity * price:.2f}) exceeds your budget cap (₹{self.budget_cap:.2f})."
            )
            return

        order_id = None
        status = "REJECTED"
        message = "Order failed to place."

        try:
            if self.kite is None:
                raise Exception("KiteConnect instance not available. Cannot place order.")

            kite_product_type = getattr(self.kite, f"PRODUCT_{product_type}")
            kite_order_type = getattr(self.kite, f"ORDER_TYPE_{order_type}")
            kite_transaction_type = getattr(self.kite, f"TRANSACTION_TYPE_{transaction_type}")

            exchange = self.kite.EXCHANGE_NSE
            if instrument_type in ['FUT', 'CE', 'PE']:
                exchange = self.kite.EXCHANGE_NFO

            order_response = self.kite.place_order(
                variety=self.kite.VARIETY_REGULAR,
                exchange=exchange,
                tradingsymbol=symbol,
                transaction_type=kite_transaction_type,
                quantity=quantity,
                product=kite_product_type,
                order_type=kite_order_type,
                price=price if order_type == "LIMIT" else None,
                trigger_price=trigger_price,
            )
            order_id = order_response
            status = "PLACED"
            message = f"Order successfully placed with ID: {order_id}"
            QMessageBox.information(self, "Order Placed", message)

        except Exception as e:
            message = f"Failed to place order: {str(e)}"
            QMessageBox.critical(self, "Order Error", message)

        self.db_manager.log_trade(
            timestamp=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            symbol=symbol,
            instrument_type=instrument_type,
            transaction_type=transaction_type,
            quantity=quantity,
            price=price,
            order_type=order_type,
            product_type=product_type,
            status=status,
            message=message,
            order_id=order_id,
            alert_id=self.initial_data.get("alert_id")
        )
        self.order_placed.emit({
            "symbol": symbol, "status": status, "message": message, "order_id": order_id
        })
        self.accept()

    def reject_order(self):
        self.reject()