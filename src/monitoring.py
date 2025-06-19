import datetime
import time
import threading
from typing import List, Dict, Any, Optional
from PyQt5.QtCore import QThread, pyqtSignal, QTime, QTimer
try:
    from kiteconnect import KiteConnect
except ImportError:
    KiteConnect = None
from database import DatabaseManager
from config import AlertConfig
from volume_data import VolumeData
from stock_management import InstrumentManager


class MonitoringStatus:
    RUNNING = "Running"
    PAUSED = "Paused"
    STOPPED = "Stopped"
    ERROR = "Error"

class MonitoringThread(QThread):
    alert_triggered = pyqtSignal(str, str, VolumeData)
    status_changed = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    volume_batch_update = pyqtSignal(list)

    def __init__(self, kite, config: AlertConfig, db_path: str,
                 stock_manager: InstrumentManager, futures_manager: InstrumentManager, options_manager: InstrumentManager):
        super().__init__()
        self.kite = kite
        self._stop_event = threading.Event()
        self.config = config
        self.db_path = db_path
        self.db_manager: Optional[DatabaseManager] = None
        self.first_monitored = {}
        self.flag = False
        self.monitored_symbols = []
        self.timer = None

        self.symbol_daily_max_tbq: Dict[str, Optional[int]] = {}
        self.symbol_daily_min_tbq: Dict[str, Optional[int]] = {}
        self.symbol_daily_max_tsq: Dict[str, Optional[int]] = {}
        self.symbol_daily_min_tsq: Dict[str, Optional[int]] = {}
        self.last_reset_date = datetime.date.today()

        self.running = True
        self.paused = False
        self.stock_manager = stock_manager
        self.futures_manager = futures_manager
        self.options_manager = options_manager

        self.alert_cooldown: Dict[str, datetime.datetime] = {}
        self.stability_check_active: Dict[str, bool] = {}
        self.stability_start_times: Dict[str, datetime.datetime] = {}
        self.last_baseline_data: Dict[str, VolumeData] = {}

    def set_monitored_symbols(self, symbols: List[str]):
        self.monitored_symbols = symbols

    def run(self):
        self.status_changed.emit("Monitoring started...")
        self.db_manager = DatabaseManager(self.db_path)

        self.timer = QTimer()
        self.timer.setInterval(2000)
        self.timer.timeout.connect(self._monitor_once)

        self.timer.moveToThread(self)
        QTimer.singleShot(0, self.timer.start)

        self.exec_()
    
    def _monitor_once(self):
        if not self.running or self.paused or self._stop_event.is_set():
            return

        current_time = QTime.currentTime().toPyTime()
        if not datetime.time(9, 0) <= current_time <= datetime.time(15, 30):
            self.status_changed.emit("Market is closed")
            self.stop_monitoring()
            return

        today = datetime.date.today()
        if today != self.last_reset_date:
            self.symbol_daily_max_tbq.clear()
            self.symbol_daily_min_tbq.clear()
            self.symbol_daily_max_tsq.clear()
            self.symbol_daily_min_tsq.clear()
            self.last_reset_date = today

        tokens = []
        symbol_map = {}

        for symbol in self.monitored_symbols:
            try:
                instrument_details = (
                    self.stock_manager.get_tradable_instrument_details(symbol)
                    or self.futures_manager.get_tradable_instrument_details(symbol)
                    or self.options_manager.get_tradable_instrument_details(symbol)
                )

                if instrument_details:
                    instrument_token = instrument_details[3]
                    market = instrument_details[2]
                    token_key = f"{market}:{symbol}"
                    tokens.append(token_key)
                    symbol_map[token_key] = {
                        'instrument_token': instrument_token,
                        'type': instrument_details[1],
                        'expiry': instrument_details[4] if len(instrument_details) > 4 else None,
                        'strike': instrument_details[5] if len(instrument_details) > 5 else None
                    }
            except Exception as e:
                self.error_occurred.emit(f"Error fetching data for {symbol}: {str(e)}")

        if tokens:
            self.status_changed.emit(f"Monitoring {len(tokens)} symbols...")
            self._fetch_and_process_live_data(tokens, symbol_map)

    def _fetch_and_process_live_data(self, tokens: List[str], symbol_map: Dict):
        all_volume_data = []
        batch_size = 25

        for i in range(0, len(tokens), batch_size):
            batch = tokens[i:i + batch_size]
            batch_map = {symbol: symbol_map[symbol] for symbol in batch}

            try:
                quote = self.kite.quote(batch)
                processed_batch = self._process_quote_data(quote, batch_map)
                all_volume_data.extend(processed_batch)

                QThread.msleep(80)
            except Exception as e:
                self.error_occurred.emit(f"Error fetching batch: {str(e)}")

        if all_volume_data:
            self.volume_batch_update.emit(all_volume_data)

    def _process_quote_data(self, quote: Dict, symbol_map: Dict) -> List[VolumeData]:
        result = []
        threshold = self.config.tbq_tsq_threshold

        for token, data in quote.items():
            if not self.running:
                break

            if token not in symbol_map:
                continue

            symbol = token.split(':')[1]
            details = symbol_map[token]
            tbq = data.get('buy_quantity', 0)
            tsq = data.get('sell_quantity', 0)
            last_price = data.get('last_price', 0.0)
            ohlc = data.get('ohlc', {})

            open_price = ohlc.get('open', 0.0)
            high_price = ohlc.get('high', 0.0)
            low_price = ohlc.get('low', 0.0)
            close_price = ohlc.get('close', 0.0)

            if symbol not in self.first_monitored:
                self.first_monitored[symbol] = [tbq, tsq]

            prev_tbq, prev_tsq = self.first_monitored[symbol]
            tbq_change = (tbq - prev_tbq) / prev_tbq if prev_tbq else 0.0
            tsq_change = (tsq - prev_tsq) / prev_tsq if prev_tsq else 0.0

            ratio = tbq / tsq if tsq else (tbq if tbq else 0.0)
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            self.symbol_daily_max_tbq[symbol] = max(tbq, self.symbol_daily_max_tbq.get(symbol, tbq))
            self.symbol_daily_min_tbq[symbol] = min(tbq, self.symbol_daily_min_tbq.get(symbol, tbq))
            self.symbol_daily_max_tsq[symbol] = max(tsq, self.symbol_daily_max_tsq.get(symbol, tsq))
            self.symbol_daily_min_tsq[symbol] = min(tsq, self.symbol_daily_min_tsq.get(symbol, tsq))

            volume_data = VolumeData(
                timestamp=now,
                symbol=symbol,
                price=last_price,
                tbq=tbq,
                tsq=tsq,
                tbq_change_percent=tbq_change * 100,
                tsq_change_percent=tsq_change * 100,
                ratio=ratio,
                is_baseline=(tbq_change == 0.0 and tsq_change == 0.0),
                open_price=open_price,
                high_price=high_price,
                low_price=low_price,
                close_price=close_price,
                instrument_type=details['type'],
                expiry_date=details.get('expiry', ""),
                strike_price=float(details.get('strike') or 0.0),
                day_high_tbq=self.symbol_daily_max_tbq[symbol],
                day_low_tbq=self.symbol_daily_min_tbq[symbol],
                day_high_tsq=self.symbol_daily_max_tsq[symbol],
                day_low_tsq=self.symbol_daily_min_tsq[symbol]
            )

            remark = ""
            triggered = False
            if abs(tbq_change) >= threshold:
                remark += f"TBQ Spike ({tbq_change * 100:.2f}) - ({volume_data.tbq})" if tbq_change > 0 else f"TBQ Fall ({tbq_change * 100:.2f}) - ({volume_data.tbq})"
                self.first_monitored[symbol][0] = tbq
                tbq_change = 0.0
                triggered = True

            if abs(tsq_change) >= threshold:
                if remark:
                    remark += " || "
                remark += f"TSQ Spike ({tsq_change * 100:.2f}) - ({volume_data.tsq})" if tsq_change > 0 else f"TSQ Fall ({tsq_change:.2f}) - ({volume_data.tsq})"
                self.first_monitored[symbol][1] = tsq
                tsq_change = 0.0
                triggered = True

            volume_data.remark = remark
            volume_data.alert_triggered = str(triggered)
            if triggered:
                self.alert_triggered.emit(symbol, remark, volume_data)
            result.append(volume_data)

        return result

    def stop_monitoring(self):
        self._stop_event.set()
        self.running = False
        self.paused = False
    
    def should_continue(self):
        return not self._stop_event.is_set() and self.running

    def pause_monitoring(self):
        self.paused = True

    def resume_monitoring(self):
        self.paused = False