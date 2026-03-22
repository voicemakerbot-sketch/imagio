"""One-time migration: add subscription_tier + daily_generations to users table."""
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "app.db"

def main():
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()

    c.execute("PRAGMA table_info(users)")
    cols = [r[1] for r in c.fetchall()]
    print("Current columns:", cols)

    if "subscription_tier" not in cols:
        c.execute('ALTER TABLE users ADD COLUMN subscription_tier VARCHAR(16) DEFAULT "free"')
        print("Added subscription_tier")

    if "daily_generations" not in cols:
        c.execute("ALTER TABLE users ADD COLUMN daily_generations INTEGER DEFAULT 0")
        print("Added daily_generations")

    if "is_premium" in cols:
        c.execute('UPDATE users SET subscription_tier = "premium" WHERE is_premium = 1')
        print("Migrated is_premium -> subscription_tier")

    conn.commit()

    c.execute("SELECT COUNT(*) FROM users")
    print("Users:", c.fetchone()[0])
    conn.close()
    print("Migration done")

if __name__ == "__main__":
    main()
