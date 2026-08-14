import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from datetime import datetime, date

# === CONFIGURATION ===
DATABASE_URL = "postgresql://neondb_owner:npg_zHO7L9JcgCXh@ep-shiny-snow-ay06dic8-pooler.c-5.us-east-2.aws.neon.tech/neondb?sslmode=require"
FILE_PATH = r"C:/project jouba/daily_uploads/cdwstock04082026.csv"

def parse_salesman(filename):
    name = filename.lower()
    if "cdw" in name: return "Christoff"
    if "riaan" in name: return "Riaan"
    if "pot" in name: return "Pot"
    return "Unassigned"

def parse_date(date_str):
    """Convert 28-JUL-26 string into a proper date object"""
    try:
        return datetime.strptime(str(date_str).strip(), '%d-%b-%y').date()
    except:
        return date.today()  # Fallback to today only if really broken

try:
    print(f"📂 Reading {FILE_PATH}...")
    df = pd.read_csv(FILE_PATH, delimiter='\t')
    df.columns = [str(c).strip().upper() for c in df.columns]
    print(f"✅ Read {len(df)} rows.")

    salesman = parse_salesman(FILE_PATH)
    table = "stock_records"

    print(f"🔌 Connecting to Neon...")
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()

    print(f"🗑️ Clearing old {salesman} data...")
    cursor.execute(f"DELETE FROM {table} WHERE salesman = %s;", (salesman,))

    records = []
    for _, row in df.iterrows():
        grn = str(row.get('GRN_NO', '')).strip()
        if not grn or grn.lower() == 'nan': 
            continue

        producer = str(row.get('PRODUCER', '')).strip() if pd.notna(row.get('PRODUCER')) else ''
        comm_raw = str(row.get('COMMODITY', '')) if pd.notna(row.get('COMMODITY')) else ''
        comm_parts = [p.strip() for p in comm_raw.split(',')] if comm_raw else []

        commodity = comm_parts[0] if len(comm_parts) > 0 else comm_raw
        pack = comm_parts[1] if len(comm_parts) > 1 else ''
        variety = comm_parts[2] if len(comm_parts) > 2 else ''
        grade = comm_parts[3] if len(comm_parts) > 3 else '1'
        size = comm_parts[4] if len(comm_parts) > 4 else '*'
        count = comm_parts[5] if len(comm_parts) > 5 else '*'

        def parse_int(val):
            try:
                return int(float(val)) if pd.notna(val) and str(val).strip() != '' else 0
            except:
                return 0

        qty_floor = parse_int(row.get('QTY_FLOOR', 0))
        
        # === CRITICAL FIX: Parse the date correctly ===
        date_received = parse_date(row.get('DATE_RECEIVED', date.today()))

        records.append((salesman, grn, producer, commodity, pack, variety, grade, size, count, qty_floor, qty_floor, date_received))

    if records:
        print(f"📤 Inserting {len(records)} rows...")
        insert_query = f"""INSERT INTO {table} (salesman, grn, producer, commodity, pack, variety, grade, size, count, qty, qty_floor, date_received) VALUES %s;"""
        execute_values(cursor, insert_query, records)
        conn.commit()
        print(f"✅ Inserted {len(records)} rows into {table} for {salesman}")
    else:
        print("⚠️ No valid rows found.")

    cursor.close()
    conn.close()

except Exception as e:
    print(f"❌ ERROR: {e}")
    import traceback
    traceback.print_exc()