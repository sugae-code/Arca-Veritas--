import os
import datetime
import re
import sqlite3
import requests
import plotly.graph_objects as go
from runner_db import RunnerDatabase  # type: ignore
import sys
import time
from PIL import Image

class APIClient:
    BASE_URL = "https://bestdori.com/api"

    @staticmethod
    def fetch_json(url):
        for attempt in range(5):
            try:
                response = requests.get(url, timeout=10)
                if response.status_code == 200:
                    return response.json()
            except Exception as e:
                print(f"API request failed (attempt {attempt+1}/5): {e}")
                time.sleep(1)
        return None

class T10Database:
    def __init__(self, db_path):
        self.db_path = db_path
        self.create_db()

    def create_db(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS t10 (
                    rank INTEGER,
                    player_name TEXT,
                    user_id INTEGER PRIMARY KEY,
                    previous_points INTEGER,
                    points INTEGER,
                    speed INTEGER,
                    event_id INTEGER
                )
            """)
            conn.commit()

    def save_data(self, data, event_id):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.executemany("""
                INSERT OR REPLACE INTO t10 (rank, player_name, user_id, previous_points, points, speed, event_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, [
                (row["rank"], row["player_name"], row["user_id"], row["previous_points"], row["points"], row["speed"], event_id)
                for row in data
            ])
            conn.commit()

    def load_previous_data(self, event_id):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT user_id, points FROM t10 WHERE event_id = ?", (event_id,))
            return {str(user_id): points for user_id, points in cursor.fetchall()}

class T10DataProcessor:
    @staticmethod
    def calculate_rankings(entries, runner_id=None):
        entries.sort(key=lambda x: x["points"], reverse=True)
        for i, entry in enumerate(entries):
            entry["rank"] = i + 1

        entries.sort(key=lambda x: x["speed"], reverse=True)
        rank = 1
        prev_speed = None
        for i, entry in enumerate(entries):
            if entry["speed"] != prev_speed:
                rank = i + 1
            entry["speed_rank"] = rank
            prev_speed = entry["speed"]

        entries.sort(key=lambda x: x["points"], reverse=True)
        for i in range(1, len(entries)):
            entries[i]["point_diff"] = entries[i - 1]["points"] - entries[i]["points"]
        if entries:
            entries[0]["point_diff"] = "ー"

        if runner_id:
            runner_entry = next((e for e in entries if e["user_id"] == runner_id), None)
            if runner_entry:
                runner_points = runner_entry["points"]
                for entry in entries:
                    entry["diff_with_runner"] = entry["points"] - runner_points
            else:
                for entry in entries:
                    entry["diff_with_runner"] = "N/A"
        else:
            for entry in entries:
                entry["diff_with_runner"] = "N/A"

        return entries

class T10Fetcher:
    def __init__(self, database):
        self.database = database

    def get_current_event_id(self, server):
        data = APIClient.fetch_json(f"{APIClient.BASE_URL}/events/all.5.json")
        if not data:
            return None
        now = datetime.datetime.now(datetime.timezone.utc).timestamp() * 1000
        for event_id, info in data.items():
            if not isinstance(info, dict):
                continue
            start_list = info.get("startAt")
            end_list = info.get("endAt")
            if not start_list or not end_list:
                continue
            try:
                start = float(start_list[server])
                end = float(end_list[server])
                if start < now < end:
                    return int(event_id)
            except (IndexError, TypeError, ValueError):
                continue
        return None

    def get_event_info(self, event_id):
        data = APIClient.fetch_json(f"{APIClient.BASE_URL}/events/all.5.json")
        if not data:
            return None, None, None, None
        info = data.get(str(event_id))
        if not info:
            return None, None, None, None
        name = info.get("eventName", [])[0] if info.get("eventName") else "Unknown"
        start = datetime.datetime.fromtimestamp(int(info.get("startAt", [0])[0]) / 1000, datetime.timezone.utc)
        end = datetime.datetime.fromtimestamp(int(info.get("endAt", [0])[0]) / 1000, datetime.timezone.utc)
        now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
        try:
            progress = max(0, min(100, ((now - start).total_seconds() / (end - start).total_seconds()) * 100))
        except Exception:
            progress = None
        return name, start, end, progress

    def get_t10_data(self, server, event_id):
        url = f"{APIClient.BASE_URL}/eventtop/data?server={server}&event={event_id}&mid=0&latest=1"
        return APIClient.fetch_json(url)

    def fetch_and_store_t10(self, server, event_id, guild_id):
        previous = self.database.load_previous_data(event_id)
        data = self.get_t10_data(server, event_id)
        if not data:
            return [], ""
        user_map = {u["uid"]: re.sub(r"\[.*?\]", "", u["name"]).strip() for u in data["users"]}
        entries = []
        for p in data["points"]:
            uid = str(p["uid"])
            prev = previous.get(uid, 0)
            entries.append({
                "player_name": user_map.get(p["uid"], "Unknown"),
                "user_id": p["uid"],
                "points": p["value"],
                "previous_points": prev,
                "speed": p["value"] - prev if prev > 0 else 0, 
            })

        runner_db = RunnerDatabase()
        runner_info = runner_db.get_runner(guild_id)
        runner_id = runner_info["user_id"] if runner_info else None

        processed = T10DataProcessor.calculate_rankings(entries, runner_id)
        self.database.save_data(processed, event_id)
        return processed, runner_info["player_name"] if runner_info else "未設定"

class T10PlotRenderer:
    @staticmethod
    def format_number(val):
        return f"{val:,}" if isinstance(val, int) else val

    @staticmethod
    def render(entries, current_time, progress, runner_name, output_path):
        progress_str = f"{progress:.2f}%" if progress is not None else "不明"
        header = ["順位", "プレイヤー名", "累計ポイント", "時速", "時速順位", "上位との差", f"{runner_name} さんとの差"]
        columns = [[] for _ in header]
        for entry in entries:
            columns[0].append(entry["rank"])
            columns[1].append(entry["player_name"])
            columns[2].append(T10PlotRenderer.format_number(entry["points"]))
            columns[3].append(T10PlotRenderer.format_number(entry["speed"]))
            columns[4].append(entry["speed_rank"])
            columns[5].append(T10PlotRenderer.format_number(entry["point_diff"]) if entry["point_diff"] != "ー" else "ー")
            columns[6].append(T10PlotRenderer.format_number(entry["diff_with_runner"]) if entry["diff_with_runner"] != "N/A" else "N/A")

        speed_cells_color = []
        speed_cells_text_color = []
        for speed, speed_rank in zip(columns[3], columns[4]):
            if speed == "0" or speed == 0:
                speed_cells_color.append("#000000")
                speed_cells_text_color.append("white")
            elif speed_rank == 1:
                speed_cells_color.append("#fff176")
                speed_cells_text_color.append("black")
            elif speed_rank == 2:
                speed_cells_color.append("#e0e0e0")
                speed_cells_text_color.append("black")
            elif speed_rank == 3:
                speed_cells_color.append("#d7a86e")
                speed_cells_text_color.append("black")
            else:
                speed_cells_color.append("white")
                speed_cells_text_color.append("black")

        fig = go.Figure(data=[go.Table(
            columnwidth=[30, 100, 90, 70, 45, 80, 170],
            header=dict(
                values=header,
                fill_color='lightsteelblue',
                align='center',
                line_color='black',
                font=dict(size=13)
            ),
            cells=dict(
                values=columns,
                fill_color=[
                    ['white'] * len(columns[0]),
                    ['white'] * len(columns[0]),
                    ['white'] * len(columns[0]),
                    ['white'] * len(columns[0]),
                    speed_cells_color,
                    ['white'] * len(columns[0]),
                    ['white'] * len(columns[0])
                ],
                font_color=[
                    ['black'] * len(columns[0]),
                    ['black'] * len(columns[0]),
                    ['black'] * len(columns[0]),
                    ['black'] * len(columns[0]),
                    speed_cells_text_color,
                    ['black'] * len(columns[0]),
                    ['black'] * len(columns[0])
                ],
                align='center',
                line_color='black',
                font=dict(size=12)
            )
        )])

        row_height = 35
        base_height = 80
        num_rows = len(columns[0])
        height = base_height + row_height * num_rows

        fig.update_layout(
            height=height,
            margin=dict(l=5, r=5, t=30, b=5),
            title=dict(
                text=f"現在時刻: {current_time}　イベント進行度: {progress_str}",
                x=0.5,
                y=0.96,
                font=dict(size=14)
            )
        )
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        fig.write_image(output_path)

        def crop_bottom(image_path, px=160):
            im = Image.open(image_path)
            w, h = im.size
            im.crop((0, 0, w, h - px)).save(image_path)

        crop_bottom(output_path)
        print(f"画像として保存されました: {output_path}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("使い方: python h1.py <server> <guild_id> [event_id]")
        sys.exit(1)

    server = int(sys.argv[1])
    guild_id = int(sys.argv[2])
    event_id = int(sys.argv[3]) if len(sys.argv) > 3 else 0

    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
    current_time = now.strftime("%Y/%m/%d %H:%M")

    db_path = f"data/db/t10_plot_1h_{guild_id}.db"
    output_path = f"data/output/t10_1h_{guild_id}.png"

    db = T10Database(db_path)
    fetcher = T10Fetcher(db)

    if event_id == 0:
        event_id = fetcher.get_current_event_id(server)

    entries, runner_name = fetcher.fetch_and_store_t10(server, event_id, guild_id)
    if not entries:
        print("❌ データ取得失敗のため画像生成をスキップ")
        sys.exit(1)

    _, _, _, progress = fetcher.get_event_info(event_id)
    if progress is None:
        print("⚠️ 進行度データの取得に失敗しました（progress=None）")

    T10PlotRenderer.render(entries, current_time, progress, runner_name, output_path)





