import os
import time
import requests
import io
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from io import StringIO
from datetime import date, datetime

# ========== CONFIGURATION ==========
BOT_TOKEN = "8892437952:AAGhhRg_aldkl-t3iyFjmkr-P1XDuCeJFos"        
CHANNEL_ID = "@JDW_Daily_files"
DATABASE_URL = "postgresql://neondb_owner:npg_zHO7L9JcgCXh@ep-shiny-snow-ay06dic8-pooler.c-5.us-east-2.aws.neon.tech/neondb?sslmode=require"
# ====================================

last_update_id = 0

def parse_salesman(filename):
    name = filename.lower()
    if "cdw" in name: return "Christoff"
    if "riaan" in name: return "Riaan"
    if "pot" in name: return "Pot"
    return "Unassigned"

def is_file_already_processed(conn, filename):
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM processed_files WHERE filename = %s", (filename,))
    result = cursor.fetchone()
    cursor.close()
    return result is not None

def mark_file_as_processed(conn, filename):
    cursor = conn.cursor()
    cursor.execute("INSERT INTO processed_files (filename) VALUES (%s)", (filename,))
    conn.commit()
    cursor.close()

def process_file_from_url(file_url, file_name):
    print(f"⚡ Starting to process {file_name}...")
    try:
        conn = psycopg2.connect(DATABASE_URL)
        
        if is_file_already_processed(conn, file_name):
            print(f"⏭️ Skipping {file_name} — already processed today.")
            conn.close()
            return

        print("📥 Downloading file from Telegram...")
        response = requests.get(file_url)
        response.raise_for_status()
        print("✅ Download complete.")

        print("📄 Reading file data...")
        csv_data = response.content.decode('utf-8')
        
        # Auto-detect delimiter
        try:
            # === CRITICAL FIX: Force WHOLESALER to be read as text ===
            df = pd.read_csv(StringIO(csv_data), delimiter='\t', dtype={'WHOLESALER': str})
            if len(df.columns) <= 1:
                df = pd.read_csv(StringIO(csv_data), delimiter=',', dtype={'WHOLESALER': str})
        except:
            df = pd.read_csv(StringIO(csv_data), delimiter=',', dtype={'WHOLESALER': str})
            
        df.columns = [str(c).strip().upper() for c in df.columns]
        print(f"✅ File has {len(df)} rows.")

        salesman = parse_salesman(file_name)
        
        lower_name = file_name.lower()
        if "floor" in lower_name:
            table = "floor_records"
        else:
            table = "stock_records"
        print(f"📋 Routing to {table} for {salesman}")

        cursor = conn.cursor()

        print(f"🗑️ Clearing old {table} data for {salesman}...")
        cursor.execute(f"DELETE FROM {table} WHERE salesman = %s;", (salesman,))
        
        records = []
        for _, row in df.iterrows():
            if table == "stock_records":
                grn = str(row.get('GRN_NO', '')).strip() if pd.notna(row.get('GRN_NO')) else ''
                if not grn:
                    continue
                producer = str(row.get('PRODUCER', '')).strip() if pd.notna(row.get('PRODUCER')) else ''
                commodity = str(row.get('COMMODITY', '')).strip() if pd.notna(row.get('COMMODITY')) else ''
                pack = str(row.get('PACK', '')).strip() if pd.notna(row.get('PACK')) else ''
                variety = str(row.get('VARIETY', '')).strip() if pd.notna(row.get('VARIETY')) else ''
                size = str(row.get('SIZE', '')).strip() if pd.notna(row.get('SIZE')) else ''
                count = str(row.get('COUNT', '')).strip() if pd.notna(row.get('COUNT')) else ''
                qty_val = row.get('QTY_FLOOR') if pd.notna(row.get('QTY_FLOOR')) else 0
                qty = int(qty_val) if pd.notna(qty_val) else 0
                date_received = row.get('DATE_RECEIVED') if pd.notna(row.get('DATE_RECEIVED')) else None

                if qty == 0:
                    continue

                records.append((salesman, grn, producer, commodity, pack, variety, size, count, qty, date_received))

            else:  # floor_records
                # === DIRECT MAPPING TO YOUR CSV COLUMNS ===
                seq_nr = int(row.get('SHORTSEQ', 0)) if pd.notna(row.get('SHORTSEQ')) else 0
                
                grn = str(row.get('GRNID', '')).strip() if pd.notna(row.get('GRNID')) else ''
                
                # === FALLBACK FIX: Try WHOLESALER, PROD, or PRODUCER ===
                producer = str(row.get('WHOLESALER', '')).strip() if pd.notna(row.get('WHOLESALER')) else str(row.get('PROD', '')).strip() if pd.notna(row.get('PROD')) else str(row.get('PRODUCER', '')).strip() if pd.notna(row.get('PRODUCER')) else ''
                
                commodity = str(row.get('COMMODITY', '')).strip() if pd.notna(row.get('COMMODITY')) else ''
                pack = str(row.get('CONTAINER', '')).strip() if pd.notna(row.get('CONTAINER')) else ''
                variety = str(row.get('VARIETY', '')).strip() if pd.notna(row.get('VARIETY')) else ''
                grade = str(row.get('CLASS', '')).strip() if pd.notna(row.get('CLASS')) else ''
                size = str(row.get('SIZ_REF', '')).strip() if pd.notna(row.get('SIZ_REF')) else ''
                count = str(row.get('CNT_REF', '')).strip() if pd.notna(row.get('CNT_REF')) else ''
                
                qty = int(row.get('QTY_AVAIL', 0)) if pd.notna(row.get('QTY_AVAIL')) else 0
                date_received = row.get('DN_DATE') if pd.notna(row.get('DN_DATE')) else None

                if qty == 0:
                    continue

                records.append((salesman, seq_nr, grn, producer, commodity, pack, variety, grade, size, count, qty, date_received))

        if records:
            print(f"📤 Inserting {len(records)} rows...")
            if table == "stock_records":
                insert_query = f"""INSERT INTO {table} (salesman, grn, producer, commodity, pack, variety, size, count, qty, date_received) VALUES %s;"""
            else:
                insert_query = f"""INSERT INTO {table} (salesman, seq_nr, grn, producer, commodity, pack, variety, grade, size, count, qty, date_received) VALUES %s;"""
            
            execute_values(cursor, insert_query, records)
            conn.commit()
            print(f"✅ Inserted {len(records)} rows into {table} for {salesman}")
            
            mark_file_as_processed(conn, file_name)
            print(f"📝 Marked {file_name} as processed.")
        else:
            print("⚠️ No valid rows to insert.")
        
        cursor.close()
        conn.close()
        print("🎉 Processing complete!")

    except Exception as e:
        print(f"❌ ERROR processing {file_name}: {e}")
        import traceback
        traceback.print_exc()

def watch_telegram():
    global last_update_id
    print("👀 Telegram Watcher started. Waiting for files...")
    
    while True:
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?offset={last_update_id + 1}&timeout=30"
            response = requests.get(url)
            
            if response.status_code == 200:
                data = response.json()
                if data.get("ok"):
                    for update in data.get("result", []):
                        last_update_id = update["update_id"]
                        
                        if "channel_post" in update and "document" in update["channel_post"]:
                            doc = update["channel_post"]["document"]
                            file_id = doc["file_id"]
                            file_name = doc["file_name"]
                            if file_name.endswith('.csv'):
                                print(f"📥 New file detected: {file_name}")
                                file_url = f"https://api.telegram.org/bot{BOT_TOKEN}/getFile?file_id={file_id}"
                                file_data = requests.get(file_url).json()
                                if file_data.get("ok"):
                                    download_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_data['result']['file_path']}"
                                    process_file_from_url(download_url, file_name)
        except Exception as e:
            pass

if __name__ == "__main__":
    watch_telegram()