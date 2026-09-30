"""One-time migration: add Phase 2 columns to schedule_rows and create quantities table."""
from sqlalchemy import create_engine, text
import os

db_path = os.path.join('data', 'expo.db')
engine = create_engine(f'sqlite:///{db_path}')

with engine.begin() as conn:
    # Check existing columns
    result = conn.execute(text('PRAGMA table_info(schedule_rows)'))
    columns = [row[1] for row in result.fetchall()]
    print('Existing columns:', columns)

    # Add missing columns
    additions = [
        ('doc', "ALTER TABLE schedule_rows ADD COLUMN doc TEXT DEFAULT ''"),
        ('page', "ALTER TABLE schedule_rows ADD COLUMN page INTEGER"),
        ('table_name', "ALTER TABLE schedule_rows ADD COLUMN table_name TEXT DEFAULT ''"),
        ('row_key', "ALTER TABLE schedule_rows ADD COLUMN row_key TEXT DEFAULT ''"),
        ('row_values', "ALTER TABLE schedule_rows ADD COLUMN row_values TEXT"),
        ('revision', "ALTER TABLE schedule_rows ADD COLUMN revision TEXT DEFAULT ''"),
    ]

    for col_name, sql in additions:
        if col_name not in columns:
            try:
                conn.execute(text(sql))
                print(f'Added column: {col_name}')
            except Exception as e:
                print(f'Error adding {col_name}: {e}')
        else:
            print(f'Column already exists: {col_name}')

    # Create quantities table if not exists
    conn.execute(text('''
        CREATE TABLE IF NOT EXISTS quantities (
            id INTEGER PRIMARY KEY,
            project_id INTEGER,
            building TEXT DEFAULT '',
            metric TEXT DEFAULT '',
            value TEXT DEFAULT '',
            unit TEXT DEFAULT '',
            source_doc TEXT DEFAULT '',
            source_page INTEGER,
            revision TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (project_id) REFERENCES projects (id)
        )
    '''))
    print('Quantities table created/verified')

print('Migration complete')
