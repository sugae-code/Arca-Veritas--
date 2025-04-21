import sqlite3
import os

class RunnerDatabase:
    def __init__(self, db_path="data/db/runners.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS runners (
                    guild_id INTEGER PRIMARY KEY,
                    user_id INTEGER,
                    player_name TEXT
                )
            """)
            conn.commit()

    def set_runner(self, guild_id: int, user_id: int, player_name: str):
        """指定ギルドにランナーを登録"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO runners (guild_id, user_id, player_name)
                VALUES (?, ?, ?)
            """, (guild_id, user_id, player_name))
            conn.commit()

    def get_runner(self, guild_id: int):
        """ギルドIDに対応するランナーを取得"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT user_id, player_name FROM runners WHERE guild_id = ?", (guild_id,))
            result = cursor.fetchone()
            if result:
                return {"user_id": result[0], "player_name": result[1]}
            return None

    def delete_runner(self, guild_id: int):
        """登録されたランナー情報を削除"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM runners WHERE guild_id = ?", (guild_id,))
            conn.commit()
