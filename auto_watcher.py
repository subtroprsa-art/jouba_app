import os
import time
import pandas as pd
import psycopg2
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# 1. SETTINGS
DATABASE_URL = os.environ.get("DATABASE_URL")
WATCH_FOLDER = "./daily_uploads"

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

def parse_filename_protocol(filename):
    fname = os.path.basename(filename).lower()
    salesman = "Unassigned"
    if fname.startswith("cdw"):
        salesman = "Christoff"
    elif fname.startswith("riaa") or fname.startswith("riaan"):
        salesman = "Riaan"
    elif fname.startswith("pot"):
        salesman = "Pot"
    target_table = "floor_records" if "floor" in fname else "stock_records"
    return salesman, target_table

def process_file(filepath):
    print(f"⚡ New file detected: {filepath}")
    time.sleep(2)
    
    salesman, target_table = parse_filename_protocol(filepath)
    print(f"📋 Routing to Salesman: {salesman} | Table: {target_table}")

    try:
        if filepath.endswith('.csv'):
            df = pd.read_csv(filepath)
        elif filepath.endswith(('.xls', '.xlsx')):
            df = pd.read_excel(filepath)
        else:
            return

        # Uppercase columns so we don't miss case-sensitive matches
        df.columns = [str(c).strip().upper() for c in df.columns]

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(f"DELETE FROM {target_table} WHERE salesman = %s;", (salesman,))

        inserted_count = 0
        for _, row in df.iterrows():
            # FIXED: Match your exact CSV columns
            grn = str(row.get('GRN_NO', '')).strip()
            producer = str(row.get('PRODUCER', '')).strip() if pd.notna(row.get('PRODUCER')) else ''
            
            # Parse the COMMODITY string if it exists
            comm_raw = str(row.get('COMMODITY', '')) if pd.notna(row.get('COMMODITY')) else ''
            comm_parts = [p.strip() for p in comm_raw.split(',')] if comm_raw else []
            
            commodity = comm_parts[0] if len(comm_parts) > 0 else comm_raw
            pack = comm_parts[1] if len(comm_parts) > 1 else str(row.get('PACK', ''))
            variety = comm_parts[2] if len(comm_parts) > 2 else str(row.get('VARIETY', ''))
            grade = comm_parts[3] if len(comm_parts) > 3 else str(row.get('GRADE', '1'))
            size = comm_parts[4] if len(comm_parts) > 4 else str(row.get('SIZE', '*'))
            count = comm_parts[5] if len(comm_parts) > 5 else str(row.get('COUNT', '*'))

            def parse_int(val):
                try:
                    return int(float(val)) if pd.notna(val) and str(val).strip() != '' else 0
                except (ValueError, TypeError):
                    return 0

            qty_floor = parse_int(row.get('QTY_FLOOR', 0))
            
            cursor.execute(f"""
                INSERT INTO {target_table} 
                (salesman, grn, producer, commodity, pack, variety, grade, size, count, qty, qty_floor, intake_date)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_DATE)
            """, (
                salesman,
                grn,
                producer,
                commodity,
                pack,
                variety,
                grade,
                size,
                count,
                qty_floor,   # qty for floor table
                qty_floor,   # qty_floor for stock table
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