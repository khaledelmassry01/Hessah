import datetime
import logging
import random

import mysql.connector
import requests
from textblob import TextBlob

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOGGER = logging.getLogger(__name__)

DB_CONFIG = {
    'host': '127.0.0.1',
    'port': 3307,
    'user': 'egx_app_user',
    'password': 'EGX_App_7wN!9Qx2#M4Lz8',
    'database': 'egx_portfolio',
    'autocommit': True
}

def create_tables_if_not_exist():
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor()
        
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_commodities (
            id INT AUTO_INCREMENT PRIMARY KEY,
            trade_date DATE NOT NULL,
            commodity_name VARCHAR(50) NOT NULL,
            price DECIMAL(10,2) NOT NULL,
            UNIQUE KEY uc_daily_comm (trade_date, commodity_name)
        );
        """)
        
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_market_sentiment (
            id INT AUTO_INCREMENT PRIMARY KEY,
            trade_date DATE NOT NULL,
            market_sentiment_score DECIMAL(5,4) NOT NULL,
            headline_count INT NOT NULL,
            UNIQUE KEY uc_daily_sentiment (trade_date)
        );
        """)
        cursor.close()
        conn.close()
    except Exception as e:
        LOGGER.error(f"Error creating tables: {e}")

def fetch_commodity_prices():
    """
    Proxy-aware request logic to fetch alternative data via proxy networks.
    """
    # proxies = {
    #    'http': 'http://username:password@proxy.massive:port',
    #    'https': 'http://username:password@proxy.massive:port',
    # }
    headers = {'User-Agent': 'EGX Alternative Data Scraper 1.0'}
    
    try:
        # Mock API request
        # response = requests.get('https://global-commodity.example.com/api/prices', proxies=proxies, headers=headers, timeout=15)
        # response.raise_for_status()
        # data = response.json()
        pass
    except Exception as e:
        LOGGER.warning(f"Failed to fetch commodity prices via API. Using fallback mock. {e}")

    today = datetime.date.today()
    return [
        (today, 'Urea', round(random.uniform(300, 400), 2)),
        (today, 'Brent Crude', round(random.uniform(70, 90), 2))
    ]

def fetch_news_sentiment():
    """
    Fetch Egyptian financial news headlines and calculate NLP sentiment.
    """
    headers = {'User-Agent': 'EGX Alternative Data Scraper 1.0'}
    try:
        # Mock API request
        # response = requests.get('https://news.example.com/api/egypt-financial', proxies=proxies, headers=headers, timeout=15)
        pass
    except Exception as e:
        LOGGER.warning(f"Failed to fetch news via API. {e}")
        
    headlines = [
        "EGX30 rebounds slightly despite inflation risks.",
        "Central bank signals potential rate cut.",
        "New investments announced in the energy sector.",
        "Urea demand surges in global markets."
    ]
    
    total_score = 0.0
    for h in headlines:
        blob = TextBlob(h)
        total_score += blob.sentiment.polarity
        
    avg_score = total_score / len(headlines) if headlines else 0.0
    return datetime.date.today(), round(avg_score, 4), len(headlines)

def save_commodities(data):
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor()
        sql = """
        INSERT INTO daily_commodities (trade_date, commodity_name, price)
        VALUES (%s, %s, %s)
        ON DUPLICATE KEY UPDATE price = VALUES(price)
        """
        cursor.executemany(sql, data)
        cursor.close()
        conn.close()
        LOGGER.info(f"Saved {len(data)} commodity records.")
    except Exception as e:
        LOGGER.error(f"Error saving commodities: {e}")

def save_sentiment(date_val, score, count):
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor()
        sql = """
        INSERT INTO daily_market_sentiment (trade_date, market_sentiment_score, headline_count)
        VALUES (%s, %s, %s)
        ON DUPLICATE KEY UPDATE market_sentiment_score = VALUES(market_sentiment_score), headline_count = VALUES(headline_count)
        """
        cursor.execute(sql, (date_val, score, count))
        cursor.close()
        conn.close()
        LOGGER.info("Saved sentiment record.")
    except Exception as e:
        LOGGER.error(f"Error saving sentiment: {e}")

def display_results():
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM daily_commodities ORDER BY trade_date DESC LIMIT 3;")
        comms = cursor.fetchall()
        print("\\n--- Top 3 Daily Commodities ---")
        for row in comms:
            print(row)
            
        cursor.execute("SELECT * FROM daily_market_sentiment ORDER BY trade_date DESC LIMIT 3;")
        sents = cursor.fetchall()
        print("\\n--- Top 3 Daily Market Sentiment ---")
        for row in sents:
            print(row)
            
        cursor.close()
        conn.close()
    except Exception as e:
        LOGGER.error(f"Error fetching top rows: {e}")

if __name__ == "__main__":
    create_tables_if_not_exist()
    
    comms = fetch_commodity_prices()
    save_commodities(comms)
    
    date_val, score, count = fetch_news_sentiment()
    save_sentiment(date_val, score, count)
    
    display_results()
