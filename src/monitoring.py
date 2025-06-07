import sqlite3
import datetime
import time
import requests
import json
import traceback
from typing import List, Dict, Any, Optional, Tuple

from PyQt5.QtCore import QThread, pyqtSignal, QTime, QDate

try:
    from kiteconnect import KiteConnect
except ImportError:
    KiteConnect = None

# Import custom modules
from database import DatabaseManager
from config import AlertConfig
from stock_volume_monitor import VolumeData # Importing VolumeData from its dedicated file


class MonitoringStatus:
    """Enum for monitoring thread status."""
    RUNNING = "Running"
    PAUSED = "Paused"
    STOPPED = "Stopped"
    ERROR = "Error"

class MonitoringThread(QThread):
    """
    A QThread subclass for continuously monitoring stock volumes
    and triggering alerts based on configured thresholds.
    """
    volume_update = pyqtSignal(VolumeData)
    alert_triggered = pyqtSignal(str, str, str, VolumeData) # symbol, combined_message_type_string, primary_alert_type, data
    status_changed = pyqtSignal(str) # For status bar updates
    error_occurred = pyqtSignal(str) # For general errors

    def __init__(self, kite: KiteConnect, config: AlertConfig, db_path: str,
                 stock_manager: Any, futures_manager: Any, options_manager: Any): # Use Any for managers
        super().__init__()
        self.kite = kite
        self.config = config
        self.db_path = db_path
        self.db_manager: Optional[DatabaseManager] = None # Will be initialized in run() for thread safety
        self.monitored_symbols = [] # List of symbols to monitor
        self.previous_volume_data = {} # Stores last fetched data for comparison
        self.tbq_baselines = {} # Stores TBQ baselines for each symbol
        self.tsq_baselines = {} # Stores TSQ baselines for each symbol

        self.symbol_daily_max_tbq: Dict[str, Optional[int]] = {}
        self.symbol_daily_min_tbq: Dict[str, Optional[int]] = {}
        self.symbol_daily_max_tsq: Dict[str, Optional[int]] = {}
        self.symbol_daily_min_tsq: Dict[str, Optional[int]] = {}
        self.last_reset_date = datetime.date.today() # To reset daily highs/lows

        self.running = True
        self.paused = False
        self.stock_manager = stock_manager
        self.futures_manager = futures_manager
        self.options_manager = options_manager

        self.alert_cooldown: Dict[str, datetime.datetime] = {}
        self.stability_check_active: Dict[str, bool] = {} # True if an alert was triggered and we're looking for stability
        self.stability_start_times: Dict[str, datetime.datetime] = {} # Tracks when a symbol entered a stable state
        self.last_baseline_data: Dict[str, VolumeData] = {} # Initialize this for stability checks

    def set_monitored_symbols(self, symbols: List[str]):
        self.monitored_symbols = symbols
        print(f"DEBUG: MonitoringThread - Set monitored symbols: {self.monitored_symbols}")

    def run(self):
        """Main monitoring loop."""
        self.status_changed.emit("Monitoring started...")
        self.db_manager = DatabaseManager(self.db_path)
        try:
            while self.running:
                if not self.paused:
                    current_time = QTime.currentTime()
                    # Ensure config.start_time and config.end_time are not None before accessing .toPyTime()
                    # This check was already somewhat handled in MainWindow.start_monitoring via config.is_valid()
                    # but adding defensive check here for robustness.
                    market_start_time = datetime.time(9, 0, 0)
                    market_end_time = datetime.time(15, 30, 0)


                    is_market_open = market_start_time <= current_time.toPyTime() <= market_end_time

                    # Reset daily high/lows if a new day has started
                    current_date = datetime.date.today()
                    if current_date != self.last_reset_date:
                        self.symbol_daily_max_tbq = {}
                        self.symbol_daily_min_tbq = {}
                        self.symbol_daily_max_tsq = {}
                        self.symbol_daily_min_tsq = {}
                        self.last_reset_date = current_date
                        print("DEBUG: MonitoringThread - Daily high/lows for TBQ/TSQ reset for new day.")


                    if not is_market_open:
                        self.status_changed.emit(f"Market closed. Waiting until {market_start_time.strftime('%H:%M')}.")
                        time.sleep(60) # Sleep longer when market is closed
                        continue

                    for symbol in self.monitored_symbols:
                        try:
                            # Determine the correct InstrumentManager for the symbol
                            instrument_details = None
                            manager = None

                            # Check stock_manager first
                            details = self.stock_manager.get_tradable_instrument_details(symbol)
                            if details:
                                instrument_details = details
                                manager = self.stock_manager
                            
                            # If not found in stock_manager, check futures_manager
                            if not instrument_details:
                                details = self.futures_manager.get_tradable_instrument_details(symbol)
                                if details:
                                    instrument_details = details
                                    manager = self.futures_manager

                            # If not found in futures_manager, check options_manager
                            if not instrument_details:
                                details = self.options_manager.get_tradable_instrument_details(symbol)
                                if details:
                                    instrument_details = details
                                    manager = self.options_manager
                            
                            if not instrument_details:
                                print(f"WARNING: MonitoringThread - Could not find instrument details for symbol: {symbol}. Skipping.")
                                continue

                            # instrument_details tuple: (symbol, instrument_type, exchange, instrument_token, expiry_date, strike_price)
                            # The tuple length could be 4 for EQ, or 6 for FUT/OPT.
                            # Extract token based on expected tuple structure from InstrumentManager
                            
                            instrument_token = instrument_details[3]
                            instrument_type = instrument_details[1] # 'EQ', 'FUT', 'CE', 'PE'
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
                    time.sleep(1) # Short sleep while paused
        finally:
            if self.db_manager:
                self.db_manager.close()
                print(f"DEBUG: MonitoringThread - DatabaseManager closed in thread {self.currentThreadId()}.")

    def _fetch_and_process_live_data(self, symbol: str, instrument_token: int,
                                     instrument_type: str, expiry_date: Optional[str], strike_price: Optional[float]):
        """Fetches live data for a single symbol and processes it."""
        try:
            quote = self.kite.quote(f"{instrument_token}")
            
            # Extract main data
            data = quote.get(str(instrument_token), {})

            # Calculate TBQ (Total Buy Quantity) and TSQ (Total Sell Quantity)
            tbq = data.get('buy_quantity', 0)
            tsq = data.get('sell_quantity', 0)

            # Get current volume and LTP
            current_volume = data.get('ohlc', {}).get('volume', 0)
            last_price = data.get('last_price', 0.0)
            
            # Get OHLC prices
            open_price = data.get('ohlc', {}).get('open', 0.0)
            high_price = data.get('ohlc', {}).get('high', 0.0)
            low_price = data.get('ohlc', {}).get('low', 0.0)
            close_price = data.get('ohlc', {}).get('close', 0.0)

            # Get opening volume from initial data or current volume if not set
            if symbol not in self.previous_volume_data or self.previous_volume_data[symbol].opening_volume is None:
                opening_volume = current_volume
            else:
                opening_volume = self.previous_volume_data[symbol].opening_volume

            # Calculate volume change percentage
            volume_change_percent = (current_volume - opening_volume) / opening_volume if opening_volume else 0

            # Calculate TBQ/TSQ change percentages
            # Use previous TBQ/TSQ from self.previous_volume_data for calculation
            prev_tbq_data = self.previous_volume_data.get(symbol)
            prev_tbq = prev_tbq_data.tbq if prev_tbq_data else 0
            prev_tsq = prev_tbq_data.tsq if prev_tbq_data else 0

            tbq_change_percent = (tbq - prev_tbq) / prev_tbq if prev_tbq and prev_tbq != 0 else (1.0 if tbq > 0 else 0.0)
            tsq_change_percent = (tsq - prev_tsq) / prev_tsq if prev_tsq and prev_tsq != 0 else (1.0 if tsq > 0 else 0.0)

            # Calculate TBQ/TSQ ratio (avoid division by zero)
            ratio = tbq / tsq if tsq else (tbq / 1.0 if tbq else 0.0)

            current_timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            is_tbq_baseline_flag = False
            is_tsq_baseline_flag = False

            # Check if TBQ/TSQ baselines need to be set
            if symbol not in self.tbq_baselines:
                self.tbq_baselines[symbol] = tbq
                is_tbq_baseline_flag = True
            if symbol not in self.tsq_baselines:
                self.tsq_baselines[symbol] = tsq
                is_tsq_baseline_flag = True
            
            # Update daily high/lows for TBQ
            current_day_high_tbq = self.symbol_daily_max_tbq.get(symbol, tbq)
            current_day_low_tbq = self.symbol_daily_min_tbq.get(symbol, tbq)
            if tbq is not None:
                if current_day_high_tbq is None or tbq > current_day_high_tbq:
                    self.symbol_daily_max_tbq[symbol] = tbq
                    current_day_high_tbq = tbq # Update for the VolumeData object
                if current_day_low_tbq is None or tbq < current_day_low_tbq:
                    self.symbol_daily_min_tbq[symbol] = tbq
                    current_day_low_tbq = tbq # Update for the VolumeData object
            else: # If tbq is None, reset daily high/low for tbq for this symbol
                self.symbol_daily_max_tbq[symbol] = None
                self.symbol_daily_min_tbq[symbol] = None

            # Update daily high/lows for TSQ
            current_day_high_tsq = self.symbol_daily_max_tsq.get(symbol, tsq)
            current_day_low_tsq = self.symbol_daily_min_tsq.get(symbol, tsq)
            if tsq is not None:
                if current_day_high_tsq is None or tsq > current_day_high_tsq:
                    self.symbol_daily_max_tsq[symbol] = tsq
                    current_day_high_tsq = tsq # Update for the VolumeData object
                if current_day_low_tsq is None or tsq < current_day_low_tsq:
                    self.symbol_daily_min_tsq[symbol] = tsq
                    current_day_low_tsq = tsq # Update for the VolumeData object
            else: # If tsq is None, reset daily high/low for tsq for this symbol
                self.symbol_daily_max_tsq[symbol] = None
                self.symbol_daily_min_tsq[symbol] = None


            volume_data = VolumeData(
                timestamp=current_timestamp,
                symbol=symbol,
                volume=current_volume,
                opening_volume=opening_volume,
                change_percent=volume_change_percent,
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
                is_tbq_baseline=is_tbq_baseline_flag,
                is_tsq_baseline=is_tsq_baseline_flag,
                instrument_type=instrument_type,
                expiry_date=expiry_date,   # Pass expiry_date
                strike_price=strike_price,  # Pass strike_price
                day_high_tbq=current_day_high_tbq, # Pass current day high TBQ
                day_low_tbq=current_day_low_tbq,   # Pass current day low TBQ
                day_high_tsq=current_day_high_tsq, # Pass current day high TSQ
                day_low_tsq=current_day_low_tsq    # Pass current day low TSQ
            )

            # Determine if any alerts are triggered and get their types
            triggered_alert_types = self._check_and_trigger_alerts(volume_data)
            alert_triggered_flag = bool(triggered_alert_types) # True if list is not empty

            # Update the VolumeData object's alert_triggered flag
            volume_data.alert_triggered = alert_triggered_flag

            # Log volume data to DB (this happens regardless of alert status)
            self.db_manager.log_volume_data(volume_data, alert_triggered_flag)
            
            # Update previous volume data cache
            self.previous_volume_data[symbol] = volume_data

            # Emit signal for general UI update (live data table, stat cards)
            self.volume_update.emit(volume_data)

            # If an alert was triggered, emit the alert signal for the main window to handle
            if alert_triggered_flag:
                # Combine alert types into a single string for the 'message' part of the signal
                alert_type_string = ", ".join(triggered_alert_types)
                # Use the first alert type as the primary category, or 'Multiple Alerts' if preferred
                primary_alert_category = triggered_alert_types[0] if triggered_alert_types else "Alert"
                self.alert_triggered.emit(symbol, alert_type_string, primary_alert_category, volume_data)

        except Exception as e:
            error_msg = f"Error fetching data for {symbol}: {traceback.format_exc()}"
            self.error_occurred.emit(error_msg)

    def _check_and_trigger_alerts(self, data: VolumeData) -> List[str]:
        triggered_alerts: List[str] = []

        # Access thresholds from config
        tbq_tsq_threshold = self.config.tbq_tsq_threshold
        trade_on_tbq_tsq_alert = self.db_manager.get_setting("trade_on_tbq_tsq_alert", 'True') == 'True'
        
        # Alert 2: TBQ/TSQ Percentage Change Alerts
        if trade_on_tbq_tsq_alert:
            # Check TBQ increase
            if data.tbq_change_percent is not None and data.tbq_change_percent * 100 >= tbq_tsq_threshold: # Multiply by 100 for percentage
                if self._check_alert_cooldown(data.symbol, "TBQ Spike"):
                    triggered_alerts.append("TBQ Spike")
                    self._update_alert_cooldown(data.symbol, "TBQ Spike")
                    self.stability_check_active[data.symbol] = True # Activate stability check after a TBQ alert
                    self.stability_start_times.pop(data.symbol, None) # Clear any previous stability start time

            # Check TSQ increase
            if data.tsq_change_percent is not None and data.tsq_change_percent * 100 >= tbq_tsq_threshold: # Multiply by 100 for percentage
                if self._check_alert_cooldown(data.symbol, "TSQ Spike"):
                    triggered_alerts.append("TSQ Spike")
                    self._update_alert_cooldown(data.symbol, "TSQ Spike")
                    self.stability_check_active[data.symbol] = True # Activate stability check after a TSQ alert
                    self.stability_start_times.pop(data.symbol, None) # Clear any previous stability start time

        # Check for stability if a stability check is active and no *new* TBQ/TSQ alerts are triggered
        # This part should ideally follow the primary alert checks.
        # If the symbol was previously alerted on TBQ/TSQ and is now stable for duration,
        # it might not trigger a new "Stability" alert but mark a new baseline.
        # The stability check logic should manage self.stability_check_active and self.last_baseline_data.
        
        # If an alert was just triggered and we activated stability_check_active, we don't need to
        # check stability *now*. We wait for subsequent data points.

        # The stability check should only happen if stability_check_active is True AND
        # there are no NEW TBQ/TSQ alerts (which would reset the stability process)
        if self.stability_check_active.get(data.symbol, False) and not (
            "TBQ Spike" in triggered_alerts or "TSQ Spike" in triggered_alerts
        ):
            # Pass relevant config values to _check_stability
            if self._check_stability(data.symbol, data, self.config.stability_threshold, self.config.stability_duration):
                if data.symbol not in self.stability_start_times:
                    self.stability_start_times[data.symbol] = datetime.datetime.now()
                    print(f"DEBUG: {data.symbol}: Entered stable state at {self.stability_start_times[data.symbol].strftime('%H:%M:%S')}")
                
                time_in_stable_state = (datetime.datetime.now() - self.stability_start_times[data.symbol]).total_seconds()
                if time_in_stable_state >= self.config.stability_duration: # Use config.stability_duration
                    # Stock has stabilized for the required duration, set new baseline
                    # Mark volume_data for logging in DB as a baseline trigger
                    data.is_tbq_baseline = True
                    data.is_tsq_baseline = True
                    self.last_baseline_data[data.symbol] = data # Update baseline
                    self.stability_check_active[data.symbol] = False # Deactivate stability check
                    self.stability_start_times.pop(data.symbol, None) # Clear stability start time
                    print(f"DEBUG: {data.symbol}: Stabilized and new baseline set at {datetime.datetime.now().strftime('%H:%M:%S')}")
            else:
                # If not stable, reset stability start time
                self.stability_start_times.pop(data.symbol, None)
                print(f"DEBUG: {data.symbol}: Stability broken, resetting stability timer.")
        
        return triggered_alerts # Return the list of triggered alert types

    def _check_stability(self, symbol: str, current_data: VolumeData, stability_threshold: float, stability_duration: int) -> bool:
        """
        Checks if the volume for a given symbol has stabilized within a threshold
        compared to its last baseline.
        """
        last_baseline = self.last_baseline_data.get(symbol)
        if not last_baseline:
            # If no baseline is set, it cannot be stable.
            return False

        # Calculate percentage deviation from the baseline TBQ and TSQ
        tbq_deviation_percent = abs(current_data.tbq - last_baseline.tbq) / last_baseline.tbq * 100 if last_baseline.tbq else 0
        tsq_deviation_percent = abs(current_data.tsq - last_baseline.tsq) / last_baseline.tsq * 100 if last_baseline.tsq else 0

        # Check if both TBQ and TSQ are within the stability threshold
        is_stable = (tbq_deviation_percent <= stability_threshold and
                     tsq_deviation_percent <= stability_threshold)
        
        # print(f"DEBUG: {symbol} - Stability check: TBQ Dev: {tbq_deviation_percent:.2f}%, TSQ Dev: {tsq_deviation_percent:.2f}%, Stable: {is_stable}")
        return is_stable

    def _check_alert_cooldown(self, symbol: str, alert_type: str, cooldown_seconds: int = 300) -> bool:
        """Checks if an alert for a given symbol and type is on cooldown."""
        key = f"{symbol}_{alert_type}"
        if key in self.alert_cooldown:
            last_alert_time = self.alert_cooldown[key]
            if (datetime.datetime.now() - last_alert_time).total_seconds() < cooldown_seconds:
                return False
        return True

    def _update_alert_cooldown(self, symbol: str, alert_type: str):
        """Updates the last alert time for a given symbol and type."""
        key = f"{symbol}_{alert_type}"
        self.alert_cooldown[key] = datetime.datetime.now()

    def stop_monitoring(self):
        """Stops the monitoring loop gracefully."""
        self.running = False
        self.wait() # Wait for the thread to finish

    def pause_monitoring(self):
        """Pauses the monitoring loop."""
        self.paused = True

    def resume_monitoring(self):
        """Resumes the monitoring loop."""
        self.paused = False