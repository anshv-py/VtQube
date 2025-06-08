import datetime
import time
import traceback
from typing import List, Dict, Any, Optional
from PyQt5.QtCore import QThread, pyqtSignal, QTime
try:
    from kiteconnect import KiteConnect
except ImportError:
    KiteConnect = None
from database import DatabaseManager
from config import AlertConfig
from volume_data import VolumeData


class MonitoringStatus:
    RUNNING = "Running"
    PAUSED = "Paused"
    STOPPED = "Stopped"
    ERROR = "Error"

class MonitoringThread(QThread):
    volume_update = pyqtSignal(VolumeData)
    alert_triggered = pyqtSignal(str, str, str, VolumeData)
    status_changed = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, kite: KiteConnect, config: AlertConfig, db_path: str,
                 stock_manager: Any, futures_manager: Any, options_manager: Any):
        super().__init__()
        self.kite = kite
        self.config = config
        self.db_path = db_path
        self.db_manager: Optional[DatabaseManager] = None
        self.first_monitored_tbq = {}
        self.first_monitored_tsq = {}
        self.monitored_symbols = []
        self.previous_volume_data = {}
        self.tbq_baselines = {}
        self.tsq_baselines = {}

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
        try:
            while self.running:
                if not self.paused:
                    current_time = QTime.currentTime()
                    market_start_time = datetime.time(9, 0, 0)
                    market_end_time = datetime.time(15, 30, 0)
                    is_market_open = market_start_time <= current_time.toPyTime() <= market_end_time
                    current_date = datetime.date.today()
                    if current_date != self.last_reset_date:
                        self.symbol_daily_max_tbq = {}
                        self.symbol_daily_min_tbq = {}
                        self.symbol_daily_max_tsq = {}
                        self.symbol_daily_min_tsq = {}
                        self.last_reset_date = current_date

                    if not is_market_open:
                        self.status_changed.emit(f"Market closed. Waiting until {market_start_time.strftime('%H:%M')}.")
                        time.sleep(60)
                        continue

                    for symbol in self.monitored_symbols:
                        try:
                            instrument_details = None
                            details = self.stock_manager.get_tradable_instrument_details(symbol)
                            if details:
                                instrument_details = details
                            
                            if not instrument_details:
                                details = self.futures_manager.get_tradable_instrument_details(symbol)
                                if details:
                                    instrument_details = details

                            if not instrument_details:
                                details = self.options_manager.get_tradable_instrument_details(symbol)
                                if details:
                                    instrument_details = details
                            
                            instrument_token = instrument_details[3]
                            instrument_type = instrument_details[1]
                            expiry_date = instrument_details[4] if len(instrument_details) > 4 else None
                            strike_price = instrument_details[5] if len(instrument_details) > 5 else None

                            self._fetch_and_process_live_data(
                                symbol,
                                instrument_token,
                                instrument_type,
                                expiry_date,
                                strike_price
                            )

                        except Exception as e:
                            error_msg = f"Error fetching data for {symbol}: {traceback.format_exc()}"
                            self.error_occurred.emit(error_msg)
                    
                    self.status_changed.emit(f"Monitoring active. Next update in 5 seconds.")
                    time.sleep(5)
                else:
                    self.status_changed.emit(f"Monitoring paused. Resume to continue.")
                    time.sleep(1)
        finally:
            if self.db_manager:
                self.db_manager.close()

    def _fetch_and_process_live_data(self, symbol: str, instrument_token: int,
                                 instrument_type: str, expiry_date: Optional[str], strike_price: Optional[float]):
        try:
            quote = self.kite.quote(f"{instrument_token}")
            data = quote.get(str(instrument_token), {})
            tbq = data.get('Buy_quantity', 0)
            tsq = data.get('sell_quantity', 0)
            current_volume = data.get('ohlc', {}).get('volume', 0)
            last_price = data.get('last_price', 0.0)
            open_price = data.get('ohlc', {}).get('open', 0.0)
            high_price = data.get('ohlc', {}).get('high', 0.0)
            low_price = data.get('ohlc', {}).get('low', 0.0)
            close_price = data.get('ohlc', {}).get('close', 0.0)

            if symbol not in self.first_monitored_tbq:
                self.first_monitored_tbq[symbol] = tbq
            if symbol not in self.first_monitored_tsq:
                self.first_monitored_tsq[symbol] = tsq

            tbq_change_percent = (tbq - self.first_monitored_tbq[symbol]) / self.first_monitored_tbq[symbol] if self.first_monitored_tbq[symbol] != 0 else 0.0
            tsq_change_percent = (tsq - self.first_monitored_tsq[symbol]) / self.first_monitored_tsq[symbol] if self.first_monitored_tsq[symbol] != 0 else 0.0

            ratio = tbq / tsq if tsq else (tbq / 1.0 if tbq else 0.0)
            current_timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            current_day_high_tbq = self.symbol_daily_max_tbq.get(symbol, tbq)
            current_day_low_tbq = self.symbol_daily_min_tbq.get(symbol, tbq)
            if tbq is not None:
                if current_day_high_tbq is None or tbq > current_day_high_tbq:
                    self.symbol_daily_max_tbq[symbol] = tbq
                    current_day_high_tbq = tbq
                if current_day_low_tbq is None or tbq < current_day_low_tbq:
                    self.symbol_daily_min_tbq[symbol] = tbq
                    current_day_low_tbq = tbq

            current_day_high_tsq = self.symbol_daily_max_tsq.get(symbol, tsq)
            current_day_low_tsq = self.symbol_daily_min_tsq.get(symbol, tsq)
            if tsq is not None:
                if current_day_high_tsq is None or tsq > current_day_high_tsq:
                    self.symbol_daily_max_tsq[symbol] = tsq
                    current_day_high_tsq = tsq
                if current_day_low_tsq is None or tsq < current_day_low_tsq:
                    self.symbol_daily_min_tsq[symbol] = tsq
                    current_day_low_tsq = tsq

            volume_data = VolumeData(
                timestamp=current_timestamp,
                symbol=symbol,
                price=last_price,
                tbq=tbq,
                tsq=tsq,
                tbq_change_percent=tbq_change_percent,
                tsq_change_percent=tsq_change_percent,
                ratio=ratio,
                open_price=open_price,
                high_price=high_price,
                low_price=low_price,
                close_price=close_price,
                instrument_type=instrument_type,
                expiry_date=expiry_date,
                strike_price=strike_price,
                day_high_tbq=current_day_high_tbq,
                day_low_tbq=current_day_low_tbq,
                day_high_tsq=current_day_high_tsq,
                day_low_tsq=current_day_low_tsq
            )

            triggered_alert_types = self._check_and_trigger_alerts(volume_data)
            alert_triggered_flag = bool(triggered_alert_types)
            volume_data.alert_triggered = alert_triggered_flag

            self.db_manager.log_volume_data(volume_data, alert_triggered_flag)            
            self.previous_volume_data[symbol] = volume_data

            self.volume_update.emit(volume_data)

            if alert_triggered_flag:
                alert_type_string = ", ".join(triggered_alert_types)
                primary_alert_category = triggered_alert_types[0] if triggered_alert_types else "Alert"
                self.alert_triggered.emit(symbol, alert_type_string, primary_alert_category, volume_data)

        except Exception as e:
            error_msg = f"Error fetching data for {symbol}: {traceback.format_exc()}"
            self.error_occurred.emit(error_msg)

    def _check_and_trigger_alerts(self, data: VolumeData) -> List[str]:
        triggered_alerts: List[str] = []

        tbq_tsq_threshold = self.config.tbq_tsq_threshold
        trade_on_tbq_tsq_alert = self.db_manager.get_setting("trade_on_tbq_tsq_alert", 'True') == 'True'
        
        if trade_on_tbq_tsq_alert:
            if data.tbq_change_percent is not None and data.tbq_change_percent * 100 >= tbq_tsq_threshold:
                if self._check_alert_cooldown(data.symbol, "TBQ Spike"):
                    triggered_alerts.append("TBQ Spike")
                    self._update_alert_cooldown(data.symbol, "TBQ Spike")
                    self.stability_check_active[data.symbol] = True
                    self.stability_start_times.pop(data.symbol, None)

            if data.tsq_change_percent is not None and data.tsq_change_percent * 100 >= tbq_tsq_threshold: # Multiply by 100 for percentage
                if self._check_alert_cooldown(data.symbol, "TSQ Spike"):
                    triggered_alerts.append("TSQ Spike")
                    self._update_alert_cooldown(data.symbol, "TSQ Spike")
                    self.stability_check_active[data.symbol] = True
                    self.stability_start_times.pop(data.symbol, None)

        if self.stability_check_active.get(data.symbol, False) and not (
            "TBQ Spike" in triggered_alerts or "TSQ Spike" in triggered_alerts
        ):
            if self._check_stability(data.symbol, data, self.config.stability_threshold, self.config.stability_duration):
                if data.symbol not in self.stability_start_times:
                    self.stability_start_times[data.symbol] = datetime.datetime.now()
                
                time_in_stable_state = (datetime.datetime.now() - self.stability_start_times[data.symbol]).total_seconds()
                if time_in_stable_state >= self.config.stability_duration:
                    data.is_tbq_baseline = True
                    data.is_tsq_baseline = True
                    self.last_baseline_data[data.symbol] = data
                    self.stability_check_active[data.symbol] = False
                    self.stability_start_times.pop(data.symbol, None)
            else:
                self.stability_start_times.pop(data.symbol, None)
        
        return triggered_alerts

    def _check_stability(self, symbol: str, current_data: VolumeData, stability_threshold: float, stability_duration: int) -> bool:
        last_baseline = self.last_baseline_data.get(symbol)
        if not last_baseline:
            return False

        tbq_deviation_percent = abs(current_data.tbq - last_baseline.tbq) / last_baseline.tbq * 100 if last_baseline.tbq else 0
        tsq_deviation_percent = abs(current_data.tsq - last_baseline.tsq) / last_baseline.tsq * 100 if last_baseline.tsq else 0
        is_stable = (tbq_deviation_percent <= stability_threshold and
                     tsq_deviation_percent <= stability_threshold)
        return is_stable

    def _check_alert_cooldown(self, symbol: str, alert_type: str, cooldown_seconds: int = 300) -> bool:
        key = f"{symbol}_{alert_type}"
        if key in self.alert_cooldown:
            last_alert_time = self.alert_cooldown[key]
            if (datetime.datetime.now() - last_alert_time).total_seconds() < cooldown_seconds:
                return False
        return True

    def _update_alert_cooldown(self, symbol: str, alert_type: str):
        key = f"{symbol}_{alert_type}"
        self.alert_cooldown[key] = datetime.datetime.now()

    def stop_monitoring(self):
        self.running = False
        self.wait()

    def pause_monitoring(self):
        self.paused = True

    def resume_monitoring(self):
        self.paused = False