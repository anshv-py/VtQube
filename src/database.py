import sqlite3
import datetime
from typing import List, Tuple, Optional, Any, Dict

# Assuming VolumeData is defined elsewhere, e.g., in monitoring.py
# from monitoring import VolumeData
from stock_volume_monitor import VolumeData


class DatabaseManager:
    """Manages SQLite database operations for the stock volume monitor."""

    def __init__(self, db_path="volume_monitor.db"):
        self.db_path = db_path
        self.conn = None
        self.create_tables()

    def _get_connection(self):
        """Establishes and returns a database connection. Ensures it's open."""
        if self.conn is None:
            self.conn = sqlite3.connect(self.db_path)
            self.conn.row_factory = sqlite3.Row
        return self.conn

    def reopen_connection(self):
        """Closes and re-opens the database connection to ensure latest data is read."""
        self.close() # Close existing connection
        self._get_connection() # Re-open connection
        print("DEBUG: DatabaseManager connection re-opened.")

    def create_tables(self):
        """Creates necessary tables if they don't exist, including new OHLC and baseline columns."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='alerts'")
        alerts_table_exists = cursor.fetchone()
        
        if alerts_table_exists:
            cursor.execute("PRAGMA table_info(alerts)")
            alerts_columns = [info[1] for info in cursor.fetchall()]
            if 'id' not in alerts_columns:
                print("WARNING: Old 'alerts' table schema detected (missing 'id' column). Dropping and recreating 'alerts' table.")
                cursor.execute("DROP TABLE IF EXISTS alerts")
                conn.commit()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        # Add new auto-trade settings columns if they don't exist
        self._add_column_if_not_exists(cursor, "settings", "auto_trade_enabled", "TEXT DEFAULT 'False'")
        self._add_column_if_not_exists(cursor, "settings", "default_quantity", "INTEGER DEFAULT 1")
        self._add_column_if_not_exists(cursor, "settings", "product_type", "TEXT DEFAULT 'MIS'")
        self._add_column_if_not_exists(cursor, "settings", "order_type", "TEXT DEFAULT 'MARKET'")
        self._add_column_if_not_exists(cursor, "settings", "stop_loss_percent", "REAL DEFAULT 0.0")
        self._add_column_if_not_exists(cursor, "settings", "target_profit_percent", "REAL DEFAULT 0.0")
        self._add_column_if_not_exists(cursor, "settings", "trade_on_tbq_tsq_alert", "TEXT DEFAULT 'True'")
        self._add_column_if_not_exists(cursor, "settings", "budget_cap", "REAL DEFAULT 0.0")
        self._add_column_if_not_exists(cursor, "settings", "trade_ltp_percentage", "REAL DEFAULT 0.0")
        self._add_column_if_not_exists(cursor, "settings", "last_instrument_fetch_date", "TEXT")

        # Table for tradable instruments (fetched from Kite)
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
        # Add new columns to tradable_instruments if they don't exist (for schema migration)
        self._add_column_if_not_exists(cursor, "tradable_instruments", "tradingsymbol", "TEXT")
        self._add_column_if_not_exists(cursor, "tradable_instruments", "expiry", "TEXT")
        self._add_column_if_not_exists(cursor, "tradable_instruments", "strike", "REAL")
        self._add_column_if_not_exists(cursor, "tradable_instruments", "lot_size", "INTEGER")
        self._add_column_if_not_exists(cursor, "tradable_instruments", "segment", "TEXT")
        self._add_column_if_not_exists(cursor, "tradable_instruments", "tick_size", "REAL")
        self._add_column_if_not_exists(cursor, "tradable_instruments", "last_price", "REAL")


        # Table for user-selected instruments (watchlist/monitoring list)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_instruments (
                symbol TEXT PRIMARY KEY,
                instrument_token INTEGER,
                instrument_type TEXT,
                FOREIGN KEY (instrument_token) REFERENCES tradable_instruments(instrument_token)
            )
        """)
        # Ensure instrument_type column exists for user_instruments
        self._add_column_if_not_exists(cursor, "user_instruments", "instrument_type", "TEXT DEFAULT 'EQ'")


        # Volume logs table, including new OHLC and baseline columns
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS volume_logs (
                timestamp TEXT,
                symbol TEXT,
                volume INTEGER,
                opening_volume INTEGER,
                change_percent REAL,
                price REAL,
                tbq INTEGER,
                tsq INTEGER,
                tbq_change_percent REAL,
                tsq_change_percent REAL,
                ratio REAL,
                alert_triggered BOOLEAN,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                is_tbq_baseline BOOLEAN DEFAULT 0,
                is_tsq_baseline BOOLEAN DEFAULT 0,
                instrument_type TEXT DEFAULT 'EQ',
                expiry_date TEXT,
                strike_price REAL
            )
        """)
        # Add new columns to volume_logs if they don't exist
        self._add_column_if_not_exists(cursor, "volume_logs", "open", "REAL")
        self._add_column_if_not_exists(cursor, "volume_logs", "high", "REAL")
        self._add_column_if_not_exists(cursor, "volume_logs", "low", "REAL")
        self._add_column_if_not_exists(cursor, "volume_logs", "close", "REAL")
        self._add_column_if_not_exists(cursor, "volume_logs", "is_tbq_baseline", "BOOLEAN DEFAULT 0")
        self._add_column_if_not_exists(cursor, "volume_logs", "is_tsq_baseline", "BOOLEAN DEFAULT 0")
        self._add_column_if_not_exists(cursor, "volume_logs", "instrument_type", "TEXT DEFAULT 'EQ'")
        self._add_column_if_not_exists(cursor, "volume_logs", "expiry_date", "TEXT")
        self._add_column_if_not_exists(cursor, "volume_logs", "strike_price", "REAL")


        # Alerts table
        # Explicitly ensure the 'id' column is present, whether new or existing table.
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
        # Ensure volume_log_id column exists for alerts (added here for completeness)
        self._add_column_if_not_exists(cursor, "alerts", "volume_log_id", "INTEGER")


        # Trades table (new)
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
        """Helper to add a column to a table if it doesn't already exist."""
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = [info[1] for info in cursor.fetchall()]
        if column_name not in columns:
            try:
                cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
                print(f"DEBUG: Added column '{column_name}' to table '{table_name}'.")
            except sqlite3.OperationalError as e:
                print(f"WARNING: Could not add column '{column_name}' to table '{table_name}': {e}")


    def close(self):
        """Closes the database connection."""
        if self.conn:
            self.conn.close()
            self.conn = None

    def save_setting(self, key: str, value: str):
        """Saves a key-value pair to the settings table."""
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
    
    def log_volume_data(self, data: VolumeData, alert_triggered: bool) -> int:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO volume_logs (
                timestamp, symbol, volume, opening_volume, change_percent, price,
                tbq, tsq, tbq_change_percent, tsq_change_percent, ratio, alert_triggered,
                open, high, low, close, is_tbq_baseline, is_tsq_baseline, instrument_type,
                expiry_date, strike_price
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data.timestamp,
            data.symbol,
            data.volume,
            data.opening_volume,
            data.change_percent,
            data.price,
            data.tbq,
            data.tsq,
            data.tbq_change_percent,
            data.tsq_change_percent,
            data.ratio,
            alert_triggered,
            data.open_price,
            data.high_price,
            data.low_price,
            data.close_price,
            data.is_tbq_baseline,
            data.is_tsq_baseline,
            data.instrument_type,
            data.expiry_date,
            data.strike_price
        ))
        conn.commit()
        return cursor.lastrowid

    def get_volume_logs(self, limit: int = 500, symbol: Optional[str] = None,
                        tbq_change_filter: Optional[Tuple[str, float]] = None,
                        tsq_change_filter: Optional[Tuple[str, float]] = None,
                        alert_status: Optional[str] = None) -> List[Tuple]:
        """
        Retrieves volume logs with optional filters.
        tbq_change_filter/tsq_change_filter: ('greater_than'/'lesser_than', value)
        alert_status: 'triggered'/'not_triggered'
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        query = "SELECT timestamp, symbol, volume, opening_volume, change_percent, price, tbq, tsq, tbq_change_percent, tsq_change_percent, ratio, alert_triggered, open, high, low, close, is_tbq_baseline, is_tsq_baseline, instrument_type, expiry_date, strike_price FROM volume_logs WHERE 1=1"
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

        if alert_status == "triggered":
            query += " AND alert_triggered = 1"
        elif alert_status == "not_triggered":
            query += " AND alert_triggered = 0"

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)
        return cursor.fetchall()

    def get_alerts_count_today(self) -> int:
        """Returns the count of alerts triggered today."""
        conn = self._get_connection()
        cursor = conn.cursor()
        today_start = datetime.datetime.now().strftime("%Y-%m-%d 00:00:00")
        today_end = datetime.datetime.now().strftime("%Y-%m-%d 23:59:59")
        cursor.execute(
            "SELECT COUNT(*) FROM alerts WHERE timestamp BETWEEN ? AND ?",
            (today_start, today_end)
        )
        return cursor.fetchone()[0]

    def log_alert(self, timestamp: str, symbol: str, message: str, alert_type: str, volume_log_id: Optional[int] = None):
        """Logs an alert to the alerts table."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO alerts (timestamp, symbol, message, alert_type, volume_log_id)
            VALUES (?, ?, ?, ?, ?)
        """, (timestamp, symbol, message, alert_type, volume_log_id))
        conn.commit()

    def get_all_alerts(self) -> List[Tuple]:
        """Retrieves all alerts from the alerts table."""
        conn = self._get_connection()
        cursor = conn.cursor()
        # Select all columns from alerts table
        cursor.execute("SELECT id, timestamp, symbol, message, alert_type, volume_log_id FROM alerts ORDER BY timestamp DESC")
        return cursor.fetchall()
    
    def log_trade(self, timestamp: str, symbol: str, instrument_type: str, transaction_type: str,
                  quantity: int, price: float, order_type: str, product_type: str,
                  status: str, message: str, order_id: Optional[str] = None, alert_id: Optional[int] = None):
        """Logs a trade to the trades table."""
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
        """Retrieves all trades from the trades table."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, timestamp, symbol, instrument_type, transaction_type, quantity, price, order_type, product_type, status, message, order_id, alert_id FROM trades ORDER BY timestamp DESC")
        return cursor.fetchall()
    
    def get_volume_data_by_alert_id(self, alert_id: int) -> Optional[Dict[str, Any]]:
        """
        Retrieves volume data associated with a given alert ID.
        Since there's no direct link in the schema from alerts to volume_logs via ID,
        this method would need to either:
        1. Query volume_logs by timestamp and symbol from the alert (less precise).
        2. Have a `volume_log_id` column in the `alerts` table. (Added this in create_tables)

        Assuming `alerts.volume_log_id` links to a unique timestamp for now.
        For exact match, you might need to reconsider logging mechanism.
        Let's retrieve by timestamp and symbol from the alert entry itself for now.
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        # First, get the alert's timestamp and symbol
        cursor.execute("SELECT timestamp, symbol FROM alerts WHERE id = ?", (alert_id,))
        alert_info = cursor.fetchone()

        if alert_info:
            timestamp_str, symbol = alert_info
            # Retrieve the most relevant volume log entry around that timestamp for the symbol
            # This is an approximation. For precise linkage, store volume_log_id in alerts table.
            # We'll fetch the volume log entry that was created at the exact timestamp and for the symbol
            cursor.execute("""
                SELECT timestamp, symbol, volume, opening_volume, change_percent, price,
                       tbq, tsq, tbq_change_percent, tsq_change_percent, ratio, alert_triggered,
                       open, high, low, close, is_tbq_baseline, is_tsq_baseline, instrument_type,
                       expiry_date, strike_price
                FROM volume_logs
                WHERE timestamp = ? AND symbol = ?
                LIMIT 1
            """, (timestamp_str, symbol))
            
            volume_data = cursor.fetchone()
            if volume_data:
                # Convert sqlite3.Row to a dictionary
                return {col[0]: volume_data[i] for i, col in enumerate(cursor.description)}
        return None

    def get_all_tradable_instruments(self, instrument_type: Optional[str] = None, exchange: Optional[str] = None) -> List[Tuple[str, str, str, int, Optional[str], Optional[float]]]:
        """
        Retrieves all tradable instruments from the database, optionally filtered by type and exchange.
        Returns a list of (symbol, instrument_type, exchange, instrument_token, expiry_date, strike_price) tuples.
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        # Select all 6 columns, including expiry_date and strike_price
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
        query += " ORDER BY tradingsymbol"
        
        print(f"DEBUG: database.py - get_all_tradable_instruments query: {query}, params: {params}")
        cursor.execute(query, params)
        instruments = cursor.fetchall()
        print(f"DEBUG: database.py - get_all_tradable_instruments fetched {len(instruments)} results for type '{instrument_type}'.")
        return instruments

    def bulk_save_tradable_instruments(self, instruments_data: List[Tuple[str, str, str, int, Optional[str], Optional[float]]]):
        """
        Performs a bulk insert of tradable instruments into the tradable_instruments table.
        This is optimized for saving a large number of instruments at once.
        instruments_data: List of tuples (tradingsymbol, instrument_type, exchange, instrument_token, expiry, strike)
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        # Prepare data for insertion (ensure correct order and handling of None)
        # The schema is: instrument_token, exchange, tradingsymbol, instrument_type, name, expiry, strike, lot_size, segment, tick_size, last_price
        # Note: 'name', 'lot_size', 'segment', 'tick_size', 'last_price' are not provided in the input tuple.
        # We will need to either get them from the original Kite data if available
        # or use default/None values for them during insertion.

        # From fetch_all_tradable_instruments in stock_management.py, the tuple is:
        # (row['tradingsymbol'], row['instrument_type'], row['exchange'],
        #  row['instrument_token'], row['expiry'], row['strike'])

        # Let's assume for name we use tradingsymbol, and other fields are None/default if not provided.
        data_to_insert = []
        for symbol, inst_type, exchange, token, expiry, strike in instruments_data:
            data_to_insert.append((
                token,
                exchange,
                symbol,
                inst_type,
                symbol, # Using symbol as name, adjust if a proper 'name' field is available
                expiry,
                strike,
                None, # lot_size
                None, # segment
                None, # tick_size
                None  # last_price
            ))
        
        # Use INSERT OR REPLACE to handle potential primary key conflicts gracefully
        # (if an instrument with the same token already exists, it will be updated)
        cursor.executemany("""
            INSERT OR REPLACE INTO tradable_instruments (
                instrument_token, exchange, tradingsymbol, instrument_type,
                name, expiry, strike, lot_size, segment, tick_size, last_price
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, data_to_insert)
        conn.commit()
        print(f"DEBUG: bulk_save_tradable_instruments: Inserted/Updated {len(data_to_insert)} instruments.")


    def clear_all_logs(self):
        """Clears all entries from volume_logs, alerts, and trades tables."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM volume_logs")
        cursor.execute("DELETE FROM alerts")
        cursor.execute("DELETE FROM trades")
        conn.commit()
        print("DEBUG: All logs (volume, alerts, trades) cleared from database.")

    def update_user_instruments_for_type(self, symbols: List[str], instrument_type: str):
        """Updates the user_instruments table for a specific instrument type."""
        conn = self._get_connection()
        cursor = conn.cursor()

        # Get all tradable instruments of the specified type to map symbols to tokens
        cursor.execute(
            "SELECT tradingsymbol, instrument_token FROM tradable_instruments WHERE instrument_type = ? OR instrument_type IN ('CE', 'PE')",
            (instrument_type,) if instrument_type != 'OPT' else () # Handle 'OPT' to include 'CE', 'PE'
        )
        tradable_map = {row['tradingsymbol']: row['instrument_token'] for row in cursor.fetchall()}

        # Clear existing user instruments of this type
        cursor.execute("DELETE FROM user_instruments WHERE instrument_type = ?", (instrument_type,))

        # Insert new selected instruments
        for symbol in symbols:
            token = tradable_map.get(symbol)
            if token:
                cursor.execute(
                    "INSERT INTO user_instruments (symbol, instrument_token, instrument_type) VALUES (?, ?, ?)",
                    (symbol, token, instrument_type)
                )
            else:
                print(f"WARNING: Could not find instrument token for symbol '{symbol}' of type '{instrument_type}'. Skipping.")
        conn.commit()
        print(f"DEBUG: Updated user instruments for type '{instrument_type}'. Added {len(symbols)} symbols.")

    def get_user_instruments_by_type(self, instrument_type: str) -> List[Tuple[str, int]]:
        """Retrieves user-selected instruments (symbol, instrument_token) for a given type."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT symbol, instrument_token FROM user_instruments WHERE instrument_type = ?",
            (instrument_type,)
        )
        return cursor.fetchall()

    def load_user_instruments(self, user_table_name_alias: str) -> List[str]:
        """
        Loads user-selected instruments (symbols only) from the user_instruments table.
        This method serves as an adapter for existing calls in InstrumentManager
        that may still be passing a 'user_table_name' argument, which should be
        interpreted as an instrument_type in the current database schema.
        """
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
            # For options, we need to select both 'CE' and 'PE' types
            query_parts.append("AND instrument_type IN (?, ?)")
            params.extend(['CE', 'PE'])
        else:
            # Fallback for unknown user_table_name_alias, might log a warning
            print(f"WARNING: load_user_instruments received unhandled alias '{user_table_name_alias}'. Fetching all.")
            # No additional filters for now, fetch all or raise error if strict
            pass

        query = " ".join(query_parts)
        cursor.execute(query, params)
        return [row[0] for row in cursor.fetchall()]
    
    def get_user_selected_symbols_for_quotation(self) -> List[Dict[str, Any]]:
        """
        Retrieves all user-selected instruments across all types,
        including their instrument token, instrument type, expiry, and strike for quotation.
        Returns a list of dictionaries.
        """
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
        print(f"DEBUG: database.py - get_user_selected_symbols_for_quotation fetched {len(results)} results.")
        return results

    def save_user_instrument(self, user_table_name_alias: str, symbol: str):
        conn = self._get_connection()
        cursor = conn.cursor()

        # Determine instrument_type from alias
        # This mapping is based on how InstrumentManager uses these aliases
        instrument_type_map = {
            'user_stocks': 'EQ',
            'user_futures': 'FUT',
            'user_options': 'OPT' # This will be handled differently below for CE/PE
        }
        
        # Get the actual instrument_type from the map, default to 'EQ' if not found
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
            # Use the exact instrument_type (e.g., 'CE' or 'PE') found in tradable_instruments
            type_to_save_in_user_instruments = result['instrument_type'] 

            cursor.execute("""
                INSERT OR REPLACE INTO user_instruments (symbol, instrument_token, instrument_type)
                VALUES (?, ?, ?)
            """, (symbol, instrument_token, type_to_save_in_user_instruments))
            conn.commit()
            print(f"DEBUG: Saved user instrument '{symbol}' (token: {instrument_token}, type: {type_to_save_in_user_instruments}).")
        else:
            print(f"WARNING: Could not find tradable instrument for symbol '{symbol}' and alias '{user_table_name_alias}'. Not saving to user_instruments.")


    def remove_user_instrument(self, user_table_name_alias: str, symbol: str):
        """
        Removes a user-selected instrument from the user_instruments table.
        The user_table_name_alias is mapped to instrument_type.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        instrument_type_map = {
            'user_stocks': 'EQ',
            'user_futures': 'FUT',
            'user_options': 'OPT'
        }
        
        target_instrument_type = instrument_type_map.get(user_table_name_alias, 'EQ')

        if target_instrument_type == 'OPT':
            # For options, delete both 'CE' and 'PE' types for the given symbol
            cursor.execute("DELETE FROM user_instruments WHERE symbol = ? AND instrument_type IN ('CE', 'PE')", (symbol,))
            conn.commit()
            print(f"DEBUG: Removed user option instrument '{symbol}'.")
        else:
            # For EQ and FUT, delete by their specific instrument_type
            cursor.execute("DELETE FROM user_instruments WHERE symbol = ? AND instrument_type = ?", (symbol, target_instrument_type))
            conn.commit()
            print(f"DEBUG: Removed user instrument '{symbol}' (type: {target_instrument_type}).")