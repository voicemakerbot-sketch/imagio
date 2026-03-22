"""Debug: show users and presets in DB."""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "app.db"

conn = sqlite3.connect(str(DB_PATH))
c = conn.cursor()

print("=== USERS ===")
c.execute("SELECT id, telegram_id, username, subscription_tier, daily_generations FROM users")
for row in c.fetchall():
    print(f"  id={row[0]}, tg_id={row[1]}, user={row[2]}, tier={row[3]}, gens={row[4]}")

print("\n=== PRESETS ===")
c.execute("SELECT id, user_id, name, is_active, aspect_ratio, num_variants, style_suffix FROM presets")
for row in c.fetchall():
    print(f"  id={row[0]}, user_id={row[1]}, name={row[2]}, active={row[3]}, ratio={row[4]}, vars={row[5]}, style={row[6]}")

conn.close()
