import os
import time
import re
import pandas as pd
import psycopg2
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# 1. SETTINGS
DATABASE_URL = os.environ.get("DATABASE_URL", "YOUR_NEON_DATABASE_URL_HERE")
WATCH_FOLDER = "./daily_uploads"  # Path to your daily uploads folder

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

def parse_filename_protocol(filename):
    """
    Decodes filename rules:
    - cdwfloor -> Christoff, floor_records
    - cdw20260804 -> Christoff, stock_records
    - riaafloor / riaanfloor -> Riaan, floor_records
    - riaan20260804 -> Riaan, stock_records
    - potfloor -> Pot, floor_records
    - pot20260804 -> Pot, stock_records
    """
    fname = os.path.basename(filename).lower()
    
    # Identify Salesman
    salesman = "Unassigned"
    if fname.startswith("cdw"):
        salesman = "Christoff"
    elif fname.startswith("riaa") or fname.startswith("riaan"):
        salesman = "Riaan"
    elif fname.startswith("pot"):
        salesman = "Pot"
        
    # Identify Target Table
    if "floor" in fname:
        target_table = "floor_records"
    else:
        target_table = "stock_records"
        
    return salesman, target_table

def process_file(filepath):
    print(f"⚡ New file detected: {filepath}")
    time.sleep(2)  # Short delay to ensure file copy completes
    
    salesman, target_table = parse_filename_protocol(filepath)
    print(f"📋 Routing to Salesman: {salesman} | Table: {target_table}")

    try:
        # Read Excel or CSV
        if filepath.endswith('.csv'):
            df = pd.read_csv(filepath)
        elif filepath.endswith(('.xls', '.xlsx')):
            df = pd.read_excel(filepath)
        else:
            return

        conn = get_db_connection()
        cursor = conn.cursor()

        # Delete existing entries for this salesman to keep stock fresh
        cursor.execute(f"DELETE FROM {target_table} WHERE salesman = %s;", (salesman,))

        # Insert new rows
        inserted_count = 0
        for _, row in df.iterrows():
            cursor.execute(f"""
                INSERT INTO {target_table} 
                (salesman, farmer_name, commodity, variety, size, pack_weight, qty, intake_date)
                VALUES (%s, %s, %s, %s, %s, %s, %s, CURRENT_DATE)
            """, (
                salesman,
                str(row.get('farmer_name', row.get('Producer', ''))),
                str(row.get('commodity', row.get('Commodity', ''))),
                str(row.get('variety', row.get('Variety', ''))),
                str(row.get('size', row.get('Size', ''))),
                str(row.get('pack_weight', row.get('Pack', ''))),
                int(row.get('qty', row.get('Qty', 0)))
            ))
            inserted_count += 1

        conn.commit()
        cursor.close()
        conn.close()
        print(f"✅ Successfully inserted {inserted_count} rows into {target_table} for {salesman}!")

    except Exception as e:
        print(f"❌ Error processing {filepath}: {e}")

class FileWatcherHandler(FileSystemEventHandler):
    def on_created(self, event):
        if not event.is_directory and event.src_path.endswith(('.csv', '.xlsx', '.xls')):
            process_file(event.src_path)

if __name__ == "__main__":
    event_handler = FileWatcherHandler()
    observer = Observer()
    observer.schedule(event_handler, path=WATCH_FOLDER, recursive=False)
    
    print(f"👀 Automated watcher listening on '{WATCH_FOLDER}'...")
    observer.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()