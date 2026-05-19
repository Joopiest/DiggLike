import sqlite3
import threading
import os
import json
import time

class DatabaseManager:
    def __init__(self, db_path="digg_cache.db"):
        self.db_path = os.path.join(os.path.dirname(__file__), db_path)
        self.lock = threading.Lock()
        self._create_tables()

    def _get_connection(self):
        return sqlite3.connect(self.db_path, check_same_thread=False)

    def _create_tables(self):
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            # News items table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS news_items (
                    id TEXT PRIMARY KEY,
                    title TEXT,
                    url TEXT,
                    source TEXT,
                    category TEXT,
                    base_score REAL,
                    pub_timestamp REAL,
                    fetch_timestamp REAL,
                    is_monitored INTEGER,
                    match_color TEXT,
                    raw_data TEXT
                )
            ''')
            # Create indexes for performance
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_pub_ts ON news_items(pub_timestamp)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_source ON news_items(source)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_category ON news_items(category)')
            
            # Full-Text Search (FTS5) table for lightning fast searching
            # Note: FTS5 might not be available in all sqlite builds, but standard on most modern ones
            try:
                cursor.execute('''
                    CREATE VIRTUAL TABLE IF NOT EXISTS news_search USING fts5(
                        title, 
                        content='news_items', 
                        content_rowid='rowid'
                    )
                ''')
                # Triggers to keep FTS in sync
                cursor.execute('''
                    CREATE TRIGGER IF NOT EXISTS news_items_ai AFTER INSERT ON news_items BEGIN
                        INSERT INTO news_search(rowid, title) VALUES (new.rowid, new.title);
                    END;
                ''')
            except sqlite3.OperationalError:
                print("FTS5 not supported, skipping virtual table.")

            conn.commit()
            conn.close()

    def insert_items(self, items):
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            for item in items:
                cursor.execute('''
                    INSERT OR REPLACE INTO news_items 
                    (id, title, url, source, category, base_score, pub_timestamp, fetch_timestamp, is_monitored, match_color, raw_data)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    item['id'],
                    item['title'],
                    item['url'],
                    item['source'],
                    item['category'],
                    item.get('base_score', 100),
                    item.get('pub_timestamp', time.time()),
                    item.get('fetch_timestamp', time.time()),
                    1 if item.get('is_monitored') else 0,
                    item.get('match_color', '#FFD700'),
                    json.dumps(item)
                ))
            conn.commit()
            conn.close()

    def get_items(self, sources=None, category=None, search_query=None, max_age_days=7, limit=3000):
        with self.lock:
            conn = self._get_connection()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            query = "SELECT * FROM news_items WHERE 1=1"
            params = []
            
            if sources:
                placeholders = ','.join(['?'] * len(sources))
                query += f" AND source IN ({placeholders})"
                params.extend(sources)
            
            if category and category != "All Feed":
                query += " AND category = ?"
                params.append(category)
                
            if max_age_days:
                min_ts = time.time() - (max_age_days * 86400)
                query += " AND pub_timestamp >= ?"
                params.append(min_ts)

            if search_query:
                # Use LIKE for broad compatibility, FTS would be faster but LIKE is safe
                query += " AND title LIKE ?"
                params.append(f"%{search_query}%")

            query += " ORDER BY pub_timestamp DESC LIMIT ?"
            params.append(limit)
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            conn.close()
            
            return [json.loads(row['raw_data']) for row in rows]

    def prune_old_items(self, max_age_days=30):
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            min_ts = time.time() - (max_age_days * 86400)
            cursor.execute("DELETE FROM news_items WHERE pub_timestamp < ?", (min_ts,))
            conn.commit()
            conn.close()

    def get_count(self):
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM news_items")
            count = cursor.fetchone()[0]
            conn.close()
            return count

# Singleton instance
db_manager = DatabaseManager()
