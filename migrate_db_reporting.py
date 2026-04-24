import sqlite3
import os

def migrate():
    # File DB hiện tại
    db_path = os.path.join(os.path.dirname(__file__), 'pc06_system.db')
    
    if not os.path.exists(db_path):
        print(f"Database file not found at {db_path}. Please adjust the path if necessary.")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    queries = [
        "ALTER TABLE form_template ADD COLUMN report_type VARCHAR(20) DEFAULT 'adhoc';",
        "ALTER TABLE form_template ADD COLUMN frequency VARCHAR(20);",
        "ALTER TABLE form_template ADD COLUMN deadline_rule VARCHAR(50);",
        "ALTER TABLE reporting_period ADD COLUMN template_id INTEGER;",
        "ALTER TABLE reporting_period ADD COLUMN is_adhoc BOOLEAN DEFAULT 0;"
    ]

    for query in queries:
        try:
            cursor.execute(query)
            print(f"Success: {query}")
        except sqlite3.OperationalError as e:
            # Catch "duplicate column name" error to allow multiple runs
            if "duplicate column name" in str(e).lower():
                print(f"Column already exists, skipping: {query}")
            else:
                print(f"Error executing {query}: {e}")

    conn.commit()
    conn.close()
    print("Migration finished.")

if __name__ == '__main__':
    migrate()
