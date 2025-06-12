import datetime
import time
import threading
from typing import List, Dict, Any, Optional
from PyQt5.QtCore import QThread, pyqtSignal, QTime
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
    volume_update = pyqtSignal(object)
    alert_triggered = pyqtSignal(str, str, str, VolumeData)
    status_changed = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, kite: KiteConnect, config: AlertConfig, db_path: str,
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
        print("I CAME HERE 1")
        try:
            while self.running:
                print("I CAME HERE 2")
                try:
                    if not self.paused:
                        current_time = QTime.currentTime()
                        market_start_time = datetime.time(9, 0, 0)
                        market_end_time = datetime.time(15, 30, 0)
                        is_market_open = market_start_time <= current_time.toPyTime() <= market_end_time
                        current_date = datetime.date.today()

                        if not is_market_open:
                            self.status_changed.emit("Market is not open yet")
                            self.stop_monitoring()
                            self.msleep(1000)
                            return
                        
                        if current_date != self.last_reset_date:
                            self.symbol_daily_max_tbq = {}
                            self.symbol_daily_min_tbq = {}
                            self.symbol_daily_max_tsq = {}
                            self.symbol_daily_min_tsq = {}
                            self.last_reset_date = current_date
                        
                        tokens = []
                        symbol_map = {}
                        
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
                                
                                if instrument_details:
                                    instrument_token = instrument_details[3]
                                    market = "NSE:" if instrument_details[1] == 'EQ' else "NFO:"
                                    tokens.append(market + symbol)
                                    symbol_map[market + symbol] = {
                                        'instrument_token' : instrument_token,
                                        'type': instrument_details[1],
                                        'expiry': instrument_details[4] if len(instrument_details) > 4 else None,
                                        'strike': instrument_details[5] if len(instrument_details) > 5 else None
                                    }
                                self.msleep(1000)
                            except Exception as e:
                                error_msg = f"Error fetching data for {symbol}: {str(e)}"
                                self.error_occurred.emit(error_msg)
                        
                        if not self.should_continue():
                            break
                            
                        if tokens:
                            self.status_changed.emit(f"Monitoring active. Next update in 5 seconds.")
                            self._fetch_and_process_live_data(tokens, symbol_map)
                            print("I CAME HERE 5")
                        
                        if not self.should_continue():
                            break
                    else:
                        self.status_changed.emit(f"Monitoring paused. Resume to continue.")
                        self.msleep(1000)
                        for i in range(10):
                            if not self.should_continue():
                                break
                            self.msleep(1000)
                        
                except Exception as e:
                    if self.running:
                        print("Error is here")
                        error_msg = f"Error in monitoring loop: {str(e)}"
                        self.error_occurred.emit(error_msg)
                    
        except Exception as e:
            if self.running:
                error_msg = f"Critical error in monitoring thread: {str(e)}"
                self.error_occurred.emit(error_msg)
        finally:
            self._stop_event.set()
            if self.db_manager:
                try:
                    self.db_manager.close()
                except:
                    pass
            
            self.status_changed.emit("Monitoring stopped.")

    def _fetch_and_process_live_data(self, tokens: List, symbol_map: Dict):
        if not self.running:
            return
            
        try:
            quote = self.kite.quote(tokens)
            if not self.running:
                return
                
            self.msleep(1000)
            
            symbol, instrument_token, instrument_type, expiry_date, strike_price = None, None, None, None, None
            
            for token in tokens:
                print("I CAME HERE 6")
                if not self.running:
                    break
                    
                symbol = token.split(':')[1]
                instrument_token = symbol_map[token]['instrument_token']
                instrument_type = symbol_map[token]['type']
                expiry_date = symbol_map[token]['expiry']
                strike_price = symbol_map[token]['strike']
                data = quote.get(token, {})
                tbq = data.get('buy_quantity', 0)
                tsq = data.get('sell_quantity', 0)
                last_price = data.get('last_price', 0.0)
                open_price = data.get('ohlc', {}).get('open', 0.0)
                high_price = data.get('ohlc', {}).get('high', 0.0)
                low_price = data.get('ohlc', {}).get('low', 0.0)
                close_price = data.get('ohlc', {}).get('close', 0.0)

                if symbol not in self.first_monitored:
                    self.first_monitored[symbol] = [tbq, tsq]
                    flag = True

                tbq_change_percent = (tbq - self.first_monitored[symbol][0]) / self.first_monitored[symbol][0] if self.first_monitored[symbol][0] != 0 else 0.0
                tsq_change_percent = (tsq - self.first_monitored[symbol][1]) / self.first_monitored[symbol][1] if self.first_monitored[symbol][1] != 0 else 0.0

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
                if not self.running:
                    break

                triggered_alert_types = self._check_and_trigger_alerts(volume_data)
                alert_triggered_flag = bool(triggered_alert_types)
                volume_data.alert_triggered = alert_triggered_flag
            
                if self.running:
                    print("I CAME HERE 7")
                    self.volume_update.emit(volume_data)

        except Exception as e:
            if self.running:
                print("Fetch Error")
                error_msg = f"Error fetching data: {str(e)}"
                self.error_occurred.emit(error_msg)

    def _check_and_trigger_alerts(self, data: VolumeData) -> List[str]:
        if not self.running:
            return []
            
        triggered_alerts: List[str] = []

        try:
            tbq_tsq_threshold = self.config.tbq_tsq_threshold
            trade_on_tbq_tsq_alert = self.db_manager.get_setting("trade_on_tbq_tsq_alert", 'True') == 'True'
            
            if trade_on_tbq_tsq_alert:
                if data.tbq_change_percent is not None and data.tbq_change_percent >= tbq_tsq_threshold:
                    if self._check_alert_cooldown(data.symbol, "TBQ Spike"):
                        triggered_alerts.append("TBQ Spike")
                        self._update_alert_cooldown(data.symbol, "TBQ Spike")
                        self.stability_check_active[data.symbol] = True
                        self.stability_start_times.pop(data.symbol, None)

                if data.tsq_change_percent is not None and data.tsq_change_percent >= tbq_tsq_threshold:
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
                        self.last_baseline_data[data.symbol] = data
                        self.stability_check_active[data.symbol] = False
                        self.stability_start_times.pop(data.symbol, None)
                else:
                    self.stability_start_times.pop(data.symbol, None)
        
        except Exception as e:
            if self.running:
                error_msg = f"Error checking alerts: {str(e)}"
                self.error_occurred.emit(error_msg)
        
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
        self._stop_event.set()
        self.running = False
        self.paused = False
        self.wait(5000)
    
    def should_continue(self):
        return not self._stop_event.is_set() and self.running

    def pause_monitoring(self):
        self.paused = True

    def resume_monitoring(self):
        self.paused = False