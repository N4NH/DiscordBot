import sqlite3
from typing import Optional, List, Dict, Tuple

DB_PATH = "movies.db"

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    
    # Kiểm tra xem bảng cũ đã có cột guild_id chưa
    cursor.execute("PRAGMA table_info(movies)")
    columns = [col[1] for col in cursor.fetchall()]
    
    # Nếu bảng cũ chưa có guild_id, drop để tạo bảng mới theo từng server
    if columns and "guild_id" not in columns:
        cursor.execute("DROP TABLE IF EXISTS ratings")
        cursor.execute("DROP TABLE IF EXISTS movies")
    
    # Bảng lưu thông tin phim (phân chia theo guild_id)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS movies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            name TEXT COLLATE NOCASE NOT NULL,
            image_url TEXT NOT NULL,
            created_by TEXT,
            showcase_message_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (guild_id, name COLLATE NOCASE)
        )
    """)
    
    # Đảm bảo cột showcase_message_id và image_data tồn tại nếu bảng đã tạo từ trước
    cursor.execute("PRAGMA table_info(movies)")
    current_cols = [col[1] for col in cursor.fetchall()]
    if "showcase_message_id" not in current_cols:
        cursor.execute("ALTER TABLE movies ADD COLUMN showcase_message_id INTEGER")
    if "image_data" not in current_cols:
        cursor.execute("ALTER TABLE movies ADD COLUMN image_data BLOB")
    
    # Bảng lưu cài đặt riêng của từng server (ví dụ kênh chi tiết phim)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS guild_settings (
            guild_id INTEGER PRIMARY KEY,
            showcase_channel_id INTEGER
        )
    """)
    
    # Bảng lưu đánh giá sao của từng user theo từng server
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ratings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            movie_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            user_name TEXT,
            score REAL NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (movie_id) REFERENCES movies (id) ON DELETE CASCADE,
            UNIQUE (movie_id, user_id)
        )
    """)

    # Bảng lưu lịch nhắc nhở (reminders)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER,
            channel_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            message TEXT NOT NULL,
            remind_at REAL NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    conn.commit()
    conn.close()

# Cài đặt kênh chi tiết phim cho server
def set_showcase_channel(guild_id: int, channel_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO guild_settings (guild_id, showcase_channel_id)
        VALUES (?, ?)
        ON CONFLICT(guild_id) DO UPDATE SET showcase_channel_id = excluded.showcase_channel_id
    """, (guild_id, channel_id))
    conn.commit()
    conn.close()

def get_showcase_channel(guild_id: int) -> Optional[int]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT showcase_channel_id FROM guild_settings WHERE guild_id = ?", (guild_id,))
    row = cursor.fetchone()
    conn.close()
    return row["showcase_channel_id"] if row else None

def set_movie_showcase_message_id(movie_id: int, message_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE movies SET showcase_message_id = ? WHERE id = ?", (message_id, movie_id))
    conn.commit()
    conn.close()

def add_movie(
    guild_id: int,
    name: str,
    image_url: str,
    created_by: str,
    image_data: Optional[bytes] = None
) -> Tuple[bool, str, Optional[int]]:
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO movies (guild_id, name, image_url, image_data, created_by) VALUES (?, ?, ?, ?, ?)",
            (guild_id, name.strip(), image_url.strip() if image_url else "", image_data, created_by)
        )
        movie_id = cursor.lastrowid
        conn.commit()
        return True, "Thêm phim thành công!", movie_id
    except sqlite3.IntegrityError:
        return False, f"Phim '{name}' đã tồn tại trong danh sách server này!", None
    except Exception as e:
        return False, f"Lỗi cơ sở dữ liệu: {e}", None
    finally:
        conn.close()

def get_movie(guild_id: int, name: str) -> Optional[Dict]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT m.id, m.guild_id, m.name, m.image_url, m.image_data, m.created_by, m.created_at, m.showcase_message_id,
               COALESCE(AVG(r.score), 0) AS avg_score,
               COUNT(r.id) AS total_votes
        FROM movies m
        LEFT JOIN ratings r ON m.id = r.movie_id
        WHERE m.guild_id = ? AND m.name = ? COLLATE NOCASE
        GROUP BY m.id
    """, (guild_id, name.strip()))
    row = cursor.fetchone()
    conn.close()
    if row:
        return dict(row)
    return None

def search_movies(guild_id: int, query: str = "", limit: int = 25) -> List[str]:
    conn = get_connection()
    cursor = conn.cursor()
    if query:
        cursor.execute(
            "SELECT name FROM movies WHERE guild_id = ? AND name LIKE ? ORDER BY name ASC LIMIT ?",
            (guild_id, f"%{query.strip()}%", limit)
        )
    else:
        cursor.execute(
            "SELECT name FROM movies WHERE guild_id = ? ORDER BY name ASC LIMIT ?",
            (guild_id, limit)
        )
    rows = cursor.fetchall()
    conn.close()
    return [row["name"] for row in rows]

def rate_movie(guild_id: int, movie_name: str, user_id: int, user_name: str, score: float) -> Tuple[bool, str, Optional[Dict], bool, Optional[float]]:
    conn = get_connection()
    cursor = conn.cursor()
    try:
        # Tìm phim trong server hiện tại
        cursor.execute(
            "SELECT id FROM movies WHERE guild_id = ? AND name = ? COLLATE NOCASE",
            (guild_id, movie_name.strip())
        )
        movie = cursor.fetchone()
        if not movie:
            return False, f"Không tìm thấy phim '{movie_name}' trong server này!", None, False, None
        
        movie_id = movie["id"]
        
        # Kiểm tra xem người dùng đã từng đánh giá phim này chưa
        cursor.execute("SELECT score FROM ratings WHERE movie_id = ? AND user_id = ?", (movie_id, user_id))
        existing_vote = cursor.fetchone()
        is_update = existing_vote is not None
        old_score = existing_vote["score"] if is_update else None
        
        # Thêm hoặc cập nhật đánh giá (Upsert)
        cursor.execute("""
            INSERT INTO ratings (guild_id, movie_id, user_id, user_name, score, updated_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(movie_id, user_id) DO UPDATE SET
                score = excluded.score,
                user_name = excluded.user_name,
                updated_at = CURRENT_TIMESTAMP
        """, (guild_id, movie_id, user_id, user_name, score))
        conn.commit()

        # Lấy thông tin thống kê mới kèm showcase_message_id
        cursor.execute("""
            SELECT m.id, m.guild_id, m.name, m.image_url, m.image_data, m.created_by, m.showcase_message_id,
                   COALESCE(AVG(r.score), 0) AS avg_score,
                   COUNT(r.id) AS total_votes
            FROM movies m
            LEFT JOIN ratings r ON m.id = r.movie_id
            WHERE m.id = ?
            GROUP BY m.id
        """, (movie_id,))
        updated_data = dict(cursor.fetchone())
        return True, "Thành công!", updated_data, is_update, old_score
    except Exception as e:
        return False, f"Lỗi khi đánh giá: {e}", None, False, None
    finally:
        conn.close()

def get_user_rating(guild_id: int, movie_name: str, user_id: int) -> Optional[float]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT r.score
        FROM ratings r
        JOIN movies m ON r.movie_id = m.id
        WHERE m.guild_id = ? AND m.name = ? COLLATE NOCASE AND r.user_id = ?
    """, (guild_id, movie_name.strip(), user_id))
    row = cursor.fetchone()
    conn.close()
    return row["score"] if row else None

def get_leaderboard(guild_id: int, limit: int = 10) -> List[Dict]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT m.id, m.name, m.image_url, m.image_data,
               COALESCE(AVG(r.score), 0) AS avg_score,
               COUNT(r.id) AS total_votes
        FROM movies m
        LEFT JOIN ratings r ON m.id = r.movie_id
        WHERE m.guild_id = ?
        GROUP BY m.id
        ORDER BY avg_score DESC, total_votes DESC, m.name ASC
        LIMIT ?
    """, (guild_id, limit))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def delete_movie(guild_id: int, name: str) -> Tuple[bool, str, Optional[int]]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, showcase_message_id FROM movies WHERE guild_id = ? AND name = ? COLLATE NOCASE", (guild_id, name.strip()))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return False, f"Không tìm thấy phim '{name}' trong server này!", None
    
    movie_id = row["id"]
    showcase_msg_id = row["showcase_message_id"]
    cursor.execute("DELETE FROM ratings WHERE movie_id = ?", (movie_id,))
    cursor.execute("DELETE FROM movies WHERE id = ?", (movie_id,))
    conn.commit()
    conn.close()
    try:
        from helpers import delete_poster_file
        delete_poster_file(movie_id)
    except Exception:
        pass
    return True, f"Đã xóa phim '{name}' thành công!", showcase_msg_id

def get_user_profile(guild_id: int, user_id: int) -> Dict:
    conn = get_connection()
    cursor = conn.cursor()
    
    # Thống kê tổng số đánh giá và điểm trung bình trong server này
    cursor.execute("""
        SELECT COUNT(r.id) AS total_rated,
               COALESCE(AVG(r.score), 0) AS avg_given_score
        FROM ratings r
        WHERE r.guild_id = ? AND r.user_id = ?
    """, (guild_id, user_id))
    stats = dict(cursor.fetchone())
    
    # Phim chấm cao nhất trong server này
    cursor.execute("""
        SELECT m.name, r.score
        FROM ratings r
        JOIN movies m ON r.movie_id = m.id
        WHERE r.guild_id = ? AND r.user_id = ?
        ORDER BY r.score DESC, r.updated_at DESC
        LIMIT 1
    """, (guild_id, user_id))
    highest = cursor.fetchone()
    stats["highest_movie"] = dict(highest) if highest else None
    
    # Phim chấm thấp nhất trong server này
    cursor.execute("""
        SELECT m.name, r.score
        FROM ratings r
        JOIN movies m ON r.movie_id = m.id
        WHERE r.guild_id = ? AND r.user_id = ?
        ORDER BY r.score ASC, r.updated_at DESC
        LIMIT 1
    """, (guild_id, user_id))
    lowest = cursor.fetchone()
    stats["lowest_movie"] = dict(lowest) if lowest else None
    
    # Các phim đánh giá gần đây nhất trong server này (tối đa 3 phim)
    cursor.execute("""
        SELECT m.name, r.score, r.updated_at
        FROM ratings r
        JOIN movies m ON r.movie_id = m.id
        WHERE r.guild_id = ? AND r.user_id = ?
        ORDER BY r.updated_at DESC
        LIMIT 3
    """, (guild_id, user_id))
    recent = cursor.fetchall()
    stats["recent_reviews"] = [dict(r) for r in recent]
    
    # Thứ hạng trong server này (dựa theo số phim đánh giá)
    cursor.execute("""
        SELECT user_id, COUNT(id) as total_rated
        FROM ratings
        WHERE guild_id = ?
        GROUP BY user_id
        ORDER BY total_rated DESC, AVG(score) DESC
    """, (guild_id,))
    all_users = cursor.fetchall()
    rank = None
    for idx, u in enumerate(all_users, start=1):
        if u["user_id"] == user_id:
            rank = idx
            break
    stats["server_rank"] = rank
    stats["total_reviewers"] = len(all_users)
    
    conn.close()
    return stats

def get_top_reviewers(guild_id: int, limit: int = 10) -> List[Dict]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT r.user_id, r.user_name,
               COUNT(r.id) AS total_rated,
               COALESCE(AVG(r.score), 0) AS avg_given_score
        FROM ratings r
        WHERE r.guild_id = ?
        GROUP BY r.user_id
        ORDER BY total_rated DESC, avg_given_score DESC
        LIMIT ?
    """, (guild_id, limit))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_movie_by_id(movie_id: int) -> Optional[Dict]:
    """Lấy thông tin phim theo movie_id"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT m.id, m.guild_id, m.name, m.image_url, m.image_data, m.created_by, m.created_at, m.showcase_message_id,
               COALESCE(AVG(r.score), 0) AS avg_score,
               COUNT(r.id) AS total_votes
        FROM movies m
        LEFT JOIN ratings r ON m.id = r.movie_id
        WHERE m.id = ?
        GROUP BY m.id
    """, (movie_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_movie_by_showcase_message_id(guild_id: int, message_id: int) -> Optional[Dict]:
    """Tìm thông tin phim dựa trên ID tin nhắn trong kênh chi tiết"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT m.id, m.guild_id, m.name, m.image_url, m.image_data, m.created_by, m.created_at, m.showcase_message_id,
               COALESCE(AVG(r.score), 0) AS avg_score,
               COUNT(r.id) AS total_votes
        FROM movies m
        LEFT JOIN ratings r ON m.id = r.movie_id
        WHERE m.guild_id = ? AND m.showcase_message_id = ?
        GROUP BY m.id
    """, (guild_id, message_id))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_recent_ratings_for_movie(movie_id: int, limit: int = 10) -> List[Dict]:
    """Lấy danh sách các đánh giá gần nhất của một bộ phim"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT user_id, user_name, score, updated_at
        FROM ratings
        WHERE movie_id = ?
        ORDER BY updated_at DESC, id DESC
        LIMIT ?
    """, (movie_id, limit))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_showcase_movies(guild_id: int) -> List[Dict]:
    """Lấy tất cả các phim đã được đăng vào kênh showcase của một server"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT m.id, m.guild_id, m.name, m.image_url, m.image_data, m.created_by, m.created_at, m.showcase_message_id,
               COALESCE(AVG(r.score), 0) AS avg_score,
               COUNT(r.id) AS total_votes
        FROM movies m
        LEFT JOIN ratings r ON m.id = r.movie_id
        WHERE m.guild_id = ? AND m.showcase_message_id IS NOT NULL
        GROUP BY m.id
    """, (guild_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def update_movie(
    guild_id: int,
    old_name: str,
    new_name: Optional[str] = None,
    new_image_url: Optional[str] = None,
    new_image_data: Optional[bytes] = None
) -> Tuple[bool, str, Optional[Dict]]:
    """Cập nhật tên và/hoặc ảnh poster cho một bộ phim trong server và giữ nguyên toàn bộ đánh giá"""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        old_clean = old_name.strip()
        cursor.execute(
            "SELECT id, name, image_url, image_data FROM movies WHERE guild_id = ? AND name = ? COLLATE NOCASE",
            (guild_id, old_clean)
        )
        movie = cursor.fetchone()
        if not movie:
            return False, f"Không tìm thấy phim '{old_name}' trong server này!", None

        movie_id = movie["id"]
        updates = []
        params = []
        name_changed = False
        image_changed = False

        if new_name is not None and new_name.strip():
            new_clean = new_name.strip()
            if new_clean.lower() != movie["name"].lower():
                # Kiểm tra xem tên mới đã bị phim khác sử dụng chưa
                cursor.execute(
                    "SELECT id FROM movies WHERE guild_id = ? AND name = ? COLLATE NOCASE AND id != ?",
                    (guild_id, new_clean, movie_id)
                )
                if cursor.fetchone():
                    return False, f"Tên phim '{new_clean}' đã tồn tại trong server rồi!", None
                updates.append("name = ?")
                params.append(new_clean)
                name_changed = True
            elif new_clean != movie["name"]:
                # Thay đổi chữ hoa/thường
                updates.append("name = ?")
                params.append(new_clean)
                name_changed = True
            elif not new_image_url and new_image_data is None:
                return False, "Tên phim mới trùng với tên phim hiện tại!", None

        if new_image_data is not None:
            updates.append("image_data = ?")
            params.append(new_image_data)
            image_changed = True

        if new_image_url is not None and new_image_url.strip():
            img_clean = new_image_url.strip()
            if img_clean != movie["image_url"]:
                updates.append("image_url = ?")
                params.append(img_clean)
                image_changed = True
            elif not name_changed and not image_changed and (new_name is None or new_name.strip().lower() == movie["name"].lower()):
                return False, "Link ảnh poster mới trùng với ảnh hiện tại của phim!", None

        if not updates:
            return False, "Bạn chưa thay đổi thông tin nào (tên hoặc ảnh)!", None

        params.append(movie_id)
        cursor.execute(
            f"UPDATE movies SET {', '.join(updates)} WHERE id = ?",
            params
        )
        conn.commit()

        # Lấy dữ liệu phim cập nhật
        cursor.execute("""
            SELECT m.id, m.guild_id, m.name, m.image_url, m.image_data, m.created_by, m.created_at, m.showcase_message_id,
                   COALESCE(AVG(r.score), 0) AS avg_score,
                   COUNT(r.id) AS total_votes
            FROM movies m
            LEFT JOIN ratings r ON m.id = r.movie_id
            WHERE m.id = ?
            GROUP BY m.id
        """, (movie_id,))
        updated_movie = dict(cursor.fetchone())

        msg_parts = []
        if name_changed:
            msg_parts.append(f"đổi tên thành **'{updated_movie['name']}'**")
        if image_changed:
            msg_parts.append("cập nhật ảnh poster mới")

        return True, f"Đã {' và '.join(msg_parts)} thành công!", updated_movie
    except Exception as e:
        return False, f"Lỗi cơ sở dữ liệu: {e}", None
    finally:
        conn.close()

def rename_movie(guild_id: int, old_name: str, new_name: str) -> Tuple[bool, str, Optional[Dict]]:
    """Hàm tương thích ngược để đổi tên phim"""
    return update_movie(guild_id=guild_id, old_name=old_name, new_name=new_name)


# ─────────────────────────────────────────────────────────────
# REMINDERS DATABASE FUNCTIONS
# ─────────────────────────────────────────────────────────────

def add_reminder(guild_id: Optional[int], channel_id: int, user_id: int, message: str, remind_at: float) -> int:
    """Thêm một nhắc nhở mới vào cơ sở dữ liệu."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO reminders (guild_id, channel_id, user_id, message, remind_at)
        VALUES (?, ?, ?, ?, ?)
    """, (guild_id, channel_id, user_id, message, remind_at))
    conn.commit()
    reminder_id = cursor.lastrowid
    conn.close()
    return reminder_id

def get_due_reminders(current_time: float) -> List[Dict]:
    """Lấy tất cả các nhắc nhở đã đến hạn."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, guild_id, channel_id, user_id, message, remind_at, created_at
        FROM reminders
        WHERE remind_at <= ?
        ORDER BY remind_at ASC
    """, (current_time,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def delete_reminder(reminder_id: int):
    """Xóa một nhắc nhở sau khi đã thông báo hoặc bị hủy."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
    conn.commit()
    conn.close()

def get_user_reminders(user_id: int) -> List[Dict]:
    """Lấy danh sách các nhắc nhở đang chờ của người dùng."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, guild_id, channel_id, user_id, message, remind_at, created_at
        FROM reminders
        WHERE user_id = ?
        ORDER BY remind_at ASC
    """, (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]




