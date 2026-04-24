import sqlite3
import os

def migrate():
    # Tìm file DB
    possible_paths = [
        os.path.join(os.path.dirname(__file__), 'pc06_system.db'),
        os.path.join(os.path.dirname(__file__), 'instance', 'pc06_system.db'),
        'pc06_system.db',
        'instance/pc06_system.db'
    ]
    
    db_path = None
    for path in possible_paths:
        if os.path.exists(path) and os.path.getsize(path) > 0:
            db_path = path
            break
    
    if not db_path:
        # Fallback to the first one if none found with size > 0
        db_path = possible_paths[0]
        print(f"Warning: No active database found. Using default path: {db_path}")
    else:
        print(f"Found active database at: {db_path}")

    try:
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
                if "duplicate column name" in str(e).lower():
                    print(f"Column already exists, skipping: {query}")
                else:
                    print(f"Error executing {query}: {e}")

        conn.commit()
        conn.close()
        print("\nMigration finished successfully.")
        print("IMPORTANT: Please restart your web server (Gunicorn/Flask) to apply changes.")
    except Exception as e:
        print(f"Critical Error: {e}")

if __name__ == '__main__':
    migrate()
