#!/usr/bin/env python3
"""Check database connectivity and current signal state."""
import mysql.connector

configs = [
    {"host": "localhost", "port": 3306, "user": "root", "password": "", "database": "egx_portfolio"},
    {"host": "localhost", "port": 3306, "user": "root", "password": "root", "database": "egx_portfolio"},
    {"host": "localhost", "port": 3306, "user": "root", "password": "password", "database": "egx_portfolio"},
    {"host": "127.0.0.1", "port": 3306, "user": "root", "password": "", "database": "egx_portfolio"},
    {"host": "127.0.0.1", "port": 3307, "user": "root", "password": "", "database": "egx_portfolio"},
    {"host": "localhost", "port": 3306, "user": "egx_app_user", "password": "EGX_App_7wN!9Qx2#M4Lz8", "database": "egx_portfolio"},
    {"host": "127.0.0.1", "port": 3306, "user": "egx_app_user", "password": "EGX_App_7wN!9Qx2#M4Lz8", "database": "egx_portfolio"},
    {"host": "127.0.0.1", "port": 3307, "user": "egx_app_user", "password": "EGX_App_7wN!9Qx2#M4Lz8", "database": "egx_portfolio"},
    {"host": "localhost", "port": 3306, "user": "root", "password": "EGX_App_7wN!9Qx2#M4Lz8", "database": "egx_portfolio"},
    {"host": "localhost", "port": 3306, "user": "root", "password": "root", "database": "egx_portfolio"},
]

for cfg in configs:
    try:
        conn = mysql.connector.connect(**cfg)
        print(f"Connected with: user={cfg['user']} host={cfg['host']} port={cfg['port']}")
        cursor = conn.cursor()
        cursor.execute("SHOW TABLES")
        tables = [r[0] for r in cursor.fetchall()]
        print(f"Tables: {tables}")

        # Check daily_ai_signals
        if "daily_ai_signals" in tables:
            cursor.execute("SELECT COUNT(*) FROM daily_ai_signals WHERE signal_date = CURDATE()")
            count = cursor.fetchone()[0]
            print(f"Today signals count: {count}")
            cursor.execute("SELECT symbol, action, confidence_score, signal_date FROM daily_ai_signals ORDER BY signal_date DESC, symbol LIMIT 10")
            rows = cursor.fetchall()
            for r in rows:
                print(f"  {r}")

        # Check stock_market_data
        if "stock_market_data" in tables:
            cursor.execute("SELECT COUNT(*) FROM stock_market_data")
            mkt_count = cursor.fetchone()[0]
            print(f"Total market data rows: {mkt_count}")
            cursor.execute("SELECT MAX(trade_date) FROM stock_market_data")
            max_date = cursor.fetchone()[0]
            print(f"Max trade_date in market data: {max_date}")

        conn.close()
        break
    except Exception as e:
        print(f"Failed user={cfg['user']} host={cfg['host']} port={cfg['port']}: {type(e).__name__}: {e}")
