import sqlite3
import os

db_path = 'pc06_system.db'
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT DISTINCT category FROM master_data;")
    print(c.fetchall())
    conn.close()
else:
    print("DB not found")
