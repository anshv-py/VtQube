import sqlite3
import datetime
from typing import List, Tuple, Optional, Any, Dict
from volume_data import VolumeData

class DatabaseManager:
    def __init__(self, db_path="volume_monitor.db"):
        self.db_path = db_path
        self.conn = None
        self.create_tables()

    def _get_connection(self):
        if self.conn is None:
            self.conn = sqlite3.connect(self.db_path, timeout=10.0, check_same_thread=False)
            self.conn.execute("PRAGMA journal_mode=WAL;")
            self.conn.row_factory = sqlite3.Row
        return self.conn

    def reopen_connection(self):
        self.close()
        self._get_connection()
    def create_tables(self):
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='alerts'")
        alerts_table_exists = cursor.fetchone()
        
        if alerts_table_exists:
            cursor.execute("PRAGMA table_info(alerts)")
            alerts_columns = [info[1] for info in cursor.fetchall()]
            if 'id' not in alerts_columns:
                cursor.execute("DROP TABLE IF EXISTS alerts")
                conn.commit()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        self._add_column_if_not_exists(cursor, "settings", "auto_trade_enabled", "TEXT DEFAULT 'False'")
        self._add_column_if_not_exists(cursor, "settings", "default_quantity", "INTEGER DEFAULT 1")
        self._add_column_if_not_exists(cursor, "settings", "product_type", "TEXT DEFAULT 'MIS'")
        self._add_column_if_not_exists(cursor, "settings", "order_type", "TEXT DEFAULT 'MARKET'")
        self._add_column_if_not_exists(cursor, "settings", "stop_loss_percent", "REAL DEFAULT 0.0")
        self._add_column_if_not_exists(cursor, "settings", "target_profit_percent", "REAL DEFAULT 0.0")
        self._add_column_if_not_exists(cursor, "settings", "trade_on_tbq_tsq_alert", "TEXT DEFAULT 'True'")
        self._add_column_if_not_exists(cursor, "settings", "budget_cap", "REAL DEFAULT 0.0")
        self._add_column_if_not_exists(cursor, "settings", "trade_ltp_percentage", "REAL DEFAULT 0.0")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tradable_instruments (
                instrument_token INTEGER PRIMARY KEY,
                exchange TEXT,
                tradingsymbol TEXT,
                instrument_type TEXT,
                name TEXT,
                expiry TEXT,
                strike REAL,
                lot_size INTEGER,
                segment TEXT,
                tick_size REAL,
                last_price REAL,
                UNIQUE(tradingsymbol, instrument_type, expiry, strike) ON CONFLICT REPLACE
            )
        """)
        self._add_column_if_not_exists(cursor, "tradable_instruments", "tradingsymbol", "TEXT")
        self._add_column_if_not_exists(cursor, "tradable_instruments", "expiry", "TEXT")
        self._add_column_if_not_exists(cursor, "tradable_instruments", "strike", "REAL")
        self._add_column_if_not_exists(cursor, "tradable_instruments", "lot_size", "INTEGER")
        self._add_column_if_not_exists(cursor, "tradable_instruments", "segment", "TEXT")
        self._add_column_if_not_exists(cursor, "tradable_instruments", "tick_size", "REAL")
        self._add_column_if_not_exists(cursor, "tradable_instruments", "last_price", "REAL")


        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_instruments (
                symbol TEXT PRIMARY KEY,
                instrument_token INTEGER,
                instrument_type TEXT,
                FOREIGN KEY (instrument_token) REFERENCES tradable_instruments(instrument_token)
            )
        """)
        self._add_column_if_not_exists(cursor, "user_instruments", "instrument_type", "TEXT DEFAULT 'EQ'")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS volume_logs (
                timestamp TEXT,
                symbol TEXT,
                price REAL,
                tbq INTEGER,
                tsq INTEGER,
                tbq_change_percent REAL,
                tsq_change_percent REAL,
                ratio REAL,
                remark TEXT,
                alert_triggered TEXT,
                is_baseline TEXT,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                instrument_type TEXT DEFAULT 'EQ',
                expiry_date TEXT,
                strike_price REAL
            )
        """)
        self._add_column_if_not_exists(cursor, "volume_logs", "remark", "TEXT")
        self._add_column_if_not_exists(cursor, "volume_logs", "alert_triggered", "TEXT")
        self._add_column_if_not_exists(cursor, "volume_logs", "is_baseline", "TEXT")
        self._add_column_if_not_exists(cursor, "volume_logs", "open", "REAL")
        self._add_column_if_not_exists(cursor, "volume_logs", "high", "REAL")
        self._add_column_if_not_exists(cursor, "volume_logs", "low", "REAL")
        self._add_column_if_not_exists(cursor, "volume_logs", "close", "REAL")
        self._add_column_if_not_exists(cursor, "volume_logs", "instrument_type", "TEXT DEFAULT 'EQ'")
        self._add_column_if_not_exists(cursor, "volume_logs", "expiry_date", "TEXT")
        self._add_column_if_not_exists(cursor, "volume_logs", "strike_price", "REAL")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                symbol TEXT,
                message TEXT,
                alert_type TEXT,
                volume_log_id INTEGER
            )
        """)
        self._add_column_if_not_exists(cursor, "alerts", "volume_log_id", "INTEGER")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                symbol TEXT,
                instrument_type TEXT,
                transaction_type TEXT, -- 'Buy' or 'SELL'
                quantity INTEGER,
                price REAL,
                order_type TEXT, -- 'MARKET', 'LIMIT', 'SL', 'SL-M'
                product_type TEXT, -- 'MIS', 'CNC', 'NRML'
                status TEXT, -- 'PLACED', 'FILLED', 'REJECTED'
                message TEXT,
                order_id TEXT UNIQUE, -- Kite order ID
                alert_id INTEGER -- Link to alerts table
            )
        """)
        conn.commit()

    def _add_column_if_not_exists(self, cursor, table_name, column_name, column_type):
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = [info[1] for info in cursor.fetchall()]
        if column_name not in columns:
            try:
                cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
            except sqlite3.OperationalError as e:
                pass

    def close(self):
        if self.conn:
            self.conn.close()
            self.conn = None

    def save_setting(self, key: str, value: str):
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
        conn.commit()

    def get_setting(self, key: str, default: str = None) -> Optional[str]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
        result = cursor.fetchone()
        return result[0] if result else default
    
    def log_volume_data(self, data: VolumeData, remark: Optional[str] = None) -> int:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO volume_logs (
                timestamp, symbol, price, tbq, tsq, tbq_change_percent, tsq_change_percent, ratio, remark,
                alert_triggered, is_baseline, open, high, low, close, instrument_type,
                expiry_date, strike_price
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data.timestamp,
            data.symbol,
            data.price,
            data.tbq,
            data.tsq,
            data.tbq_change_percent,
            data.tsq_change_percent,
            data.ratio,
            remark,
            data.alert_triggered,
            data.is_baseline,
            data.open_price,
            data.high_price,
            data.low_price,
            data.close_price,
            data.instrument_type,
            data.expiry_date,
            data.strike_price
        ))
        conn.commit()
        return cursor.lastrowid

    def get_volume_logs(self, symbol: Optional[str] = None,
                        tbq_change_filter: Optional[Tuple[str, float]] = None,
                        tsq_change_filter: Optional[Tuple[str, float]] = None) -> List[Tuple]:
        conn = self._get_connection()
        cursor = conn.cursor()
        query = "SELECT timestamp, symbol, price, tbq, tsq, alert_triggered, is_baseline, tbq_change_percent, tsq_change_percent, ratio, remark, open, high, low, close, instrument_type, expiry_date, strike_price FROM volume_logs WHERE 1=1"
        params = []

        if symbol:
            query += " AND symbol = ?"
            params.append(symbol)   
        if tbq_change_filter:
            filter_type, value = tbq_change_filter
            if filter_type == 'greater_than':
                query += " AND tbq_change_percent >= ?"
                params.append(value)
            elif filter_type == 'lesser_than':
                query += " AND tbq_change_percent <= ?"
                params.append(value)

        if tsq_change_filter:
            filter_type, value = tsq_change_filter
            if filter_type == 'greater_than':
                query += " AND tsq_change_percent >= ?"
                params.append(value)
            elif filter_type == 'lesser_than':
                query += " AND tsq_change_percent <= ?"
                params.append(value)

        query += " ORDER BY timestamp DESC"
        cursor.execute(query, params)
        return cursor.fetchall()

    def get_alerts_count_today(self) -> int:
        conn = self._get_connection()
        cursor = conn.cursor()
        today_start = datetime.datetime.now().strftime("%Y-%m-%d 00:00:00")
        today_end = datetime.datetime.now().strftime("%Y-%m-%d 23:59:59")
        cursor.execute(
            "SELECT COUNT(*) FROM volume_logs WHERE alert_triggered='True'",
            (today_start, today_end)
        )
        return cursor.fetchone()[0]
    
    def log_trade(self, timestamp: str, symbol: str, instrument_type: str, transaction_type: str,
                  quantity: int, price: float, order_type: str, product_type: str,
                  status: str, message: str, order_id: Optional[str] = None, alert_id: Optional[int] = None):
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO trades (
                timestamp, symbol, instrument_type, transaction_type, quantity, price,
                order_type, product_type, status, message, order_id, alert_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            timestamp, symbol, instrument_type, transaction_type, quantity, price,
            order_type, product_type, status, message, order_id, alert_id
        ))
        conn.commit()

    def get_all_trades(self) -> List[Tuple]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, timestamp, symbol, instrument_type, transaction_type, quantity, price, order_type, product_type, status, message, order_id, alert_id FROM trades ORDER BY timestamp DESC")
        return cursor.fetchall()
    
    def get_volume_data_by_id(self, alert_id: int) -> Optional[Dict[str, Any]]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT timestamp, symbol FROM alerts WHERE id = ?", (alert_id,))
        alert_info = cursor.fetchone()

        if alert_info:
            timestamp_str, symbol = alert_info
            cursor.execute("""
                SELECT timestamp, symbol, price, tbq, tsq, tbq_change_percent, tsq_change_percent, ratio, alert_triggered,
                       open, high, low, close, instrument_type
                FROM volume_logs
                WHERE timestamp = ? AND symbol = ?
                LIMIT 1
            """, (timestamp_str, symbol))
            
            volume_data = cursor.fetchone()
            if volume_data:
                return {col[0]: volume_data[i] for i, col in enumerate(cursor.description)}
        return None

    def get_all_tradable_instruments(self, instrument_type: Optional[str] = None, exchange: Optional[str] = None, option_category: Optional[str] = None) -> List[Tuple[str, str, str, int, Optional[str], Optional[float]]]:
        conn = self._get_connection()
        cursor = conn.cursor()
        query = "SELECT tradingsymbol, instrument_type, exchange, instrument_token, expiry, strike FROM tradable_instruments WHERE 1=1"
        params = []
        if instrument_type:
            if instrument_type == 'OPT':
                query += " AND instrument_type IN (?, ?)"
                params.extend(['CE', 'PE'])
            else:
                query += " AND instrument_type = ?"
                params.append(instrument_type)
        if exchange:
            query += " AND exchange = ?"
            params.append(exchange)
        if option_category:
            if option_category == 'NIFTY':
                query += " AND tradingsymbol LIKE ?"
                params.append('NIFTY%')
            elif option_category == 'BANK':
                query += " AND tradingsymbol LIKE ?"
                params.append('BANK%')
            elif option_category == 'FIN':
                query += " AND tradingsymbol LIKE ?"
                params.append('FIN%')
            elif option_category == 'MIDCP':
                query += " AND tradingsymbol LIKE ?"
                params.append('MIDCP%')
            elif option_category == 'STOCK':
                query += """ 
                    AND tradingsymbol NOT LIKE ? 
                    AND tradingsymbol NOT LIKE ? 
                    AND tradingsymbol NOT LIKE ? 
                    AND tradingsymbol NOT LIKE ?
                """
                params.extend(['NIFTY%', 'BANK%', 'FIN%', 'MIDCP%'])
        query += " ORDER BY tradingsymbol"
        
        cursor.execute(query, params)
        instruments = [row for row in cursor.fetchall()]
        return instruments

    def bulk_save_tradable_instruments(self, instruments_data: List[Tuple[str, str, str, int, Optional[str], Optional[float]]]):
        conn = self._get_connection()
        cursor = conn.cursor()

        data_to_insert = []
        for symbol, inst_type, exchange, token, expiry, strike in instruments_data:
            data_to_insert.append((
                token,
                exchange,
                symbol,
                inst_type,
                symbol,
                expiry,
                strike,
                None,
                None,
                None,
                None
            ))
        
        cursor.executemany("""
            INSERT OR REPLACE INTO tradable_instruments (
                instrument_token, exchange, tradingsymbol, instrument_type,
                name, expiry, strike, lot_size, segment, tick_size, last_price
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, data_to_insert)
        conn.commit()


    def clear_all_logs(self):
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM volume_logs")
        cursor.execute("DELETE FROM alerts")
        cursor.execute("DELETE FROM trades")
        conn.commit()

    def update_user_instruments_for_type(self, symbols: List[str], instrument_type: str):
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT tradingsymbol, instrument_token FROM tradable_instruments WHERE instrument_type = ? OR instrument_type IN ('CE', 'PE')",
            (instrument_type,) if instrument_type != 'OPT' else () # Handle 'OPT' to include 'CE', 'PE'
        )
        tradable_map = {row['tradingsymbol']: row['instrument_token'] for row in cursor.fetchall()}

        cursor.execute("DELETE FROM user_instruments WHERE instrument_type = ?", (instrument_type,))

        for symbol in symbols:
            token = tradable_map.get(symbol)
            if token:
                cursor.execute(
                    "INSERT INTO user_instruments (symbol, instrument_token, instrument_type) VALUES (?, ?, ?)",
                    (symbol, token, instrument_type)
                )
            else:
                pass
        conn.commit()

    def get_user_instruments_by_type(self, instrument_type: str) -> List[Tuple[str, int]]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT symbol, instrument_token FROM user_instruments WHERE instrument_type = ?",
            (instrument_type,)
        )
        return cursor.fetchall()

    def load_user_instruments(self, user_table_name_alias: str) -> List[str]:
        conn = self._get_connection()
        cursor = conn.cursor()
        
        query_parts = ["SELECT symbol FROM user_instruments WHERE 1=1"]
        params = []

        if user_table_name_alias == 'user_stocks':
            query_parts.append("AND instrument_type = ?")
            params.append('EQ')
        elif user_table_name_alias == 'user_futures':
            query_parts.append("AND instrument_type = ?")
            params.append('FUT')
        elif user_table_name_alias == 'user_options':
            query_parts.append("AND instrument_type IN (?, ?)")
            params.extend(['CE', 'PE'])
        else:
            pass

        query = " ".join(query_parts)
        cursor.execute(query, params)
        return [row[0] for row in cursor.fetchall()]
    
    def get_user_selected_symbols_for_quotation(self) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        cursor = conn.cursor()
        query = """
            SELECT
                ui.symbol,
                ui.instrument_token,
                ti.instrument_type,
                ti.expiry,
                ti.strike
            FROM
                user_instruments ui
            JOIN
                tradable_instruments ti ON ui.instrument_token = ti.instrument_token
            ORDER BY ui.symbol
        """
        cursor.execute(query)
        
        results = []
        for row in cursor.fetchall():
            results.append({
                "symbol": row['symbol'],
                "instrument_token": row['instrument_token'],
                "instrument_type": row['instrument_type'],
                "expiry_date": row['expiry'],
                "strike_price": row['strike']
            })
        return results

    def save_user_instrument(self, user_table_name_alias: str, symbol: str):
        conn = self._get_connection()
        cursor = conn.cursor()

        instrument_type_map = {
            'user_stocks': 'EQ',
            'user_futures': 'FUT',
            'user_options': 'OPT' # This will be handled differently below for CE/PE
        }
        
        actual_instrument_type_to_save = instrument_type_map.get(user_table_name_alias, 'EQ')
        if actual_instrument_type_to_save == 'OPT':
            cursor.execute(
                "SELECT instrument_token, instrument_type FROM tradable_instruments WHERE tradingsymbol = ? AND instrument_type IN ('CE', 'PE') LIMIT 1",
                (symbol,)
            )
        else:
            cursor.execute(
                "SELECT instrument_token, instrument_type FROM tradable_instruments WHERE tradingsymbol = ? AND instrument_type = ? LIMIT 1",
                (symbol, actual_instrument_type_to_save)
            )

        result = cursor.fetchone()
        
        if result:
            instrument_token = result['instrument_token']
            type_to_save_in_user_instruments = result['instrument_type'] 

            cursor.execute("""
                INSERT OR REPLACE INTO user_instruments (symbol, instrument_token, instrument_type)
                VALUES (?, ?, ?)
            """, (symbol, instrument_token, type_to_save_in_user_instruments))
            conn.commit()
        else:
            pass


    def remove_user_instrument(self, user_table_name_alias: str, symbol: str):
        conn = self._get_connection()
        cursor = conn.cursor()

        instrument_type_map = {
            'user_stocks': 'EQ',
            'user_futures': 'FUT',
            'user_options': 'OPT'
        }
        
        target_instrument_type = instrument_type_map.get(user_table_name_alias, 'EQ')

        if target_instrument_type == 'OPT':
            cursor.execute("DELETE FROM user_instruments WHERE symbol = ? AND instrument_type IN ('CE', 'PE')", (symbol,))
            conn.commit()
        else:
            cursor.execute("DELETE FROM user_instruments WHERE symbol = ? AND instrument_type = ?", (symbol, target_instrument_type))
            conn.commit()