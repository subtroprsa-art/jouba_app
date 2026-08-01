import csv
import psycopg2
from psycopg2.extras import execute_values

# Replace with your actual Neon Connection String
DB_URI = "postgresql://neondb_owner:npg_zHO7L9JcgCXh@ep-shiny-snow-ay06dic8-pooler.c-5.us-east-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require"

def get_db_connection():
    return psycopg2.connect(DB_URI)

# -------------------------------------------------------------
# 1. PROCESS STOCK CSV / TEXT
# -------------------------------------------------------------
def process_stock_csv(file_path):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = """
    INSERT INTO stock_records (
        grn, producer, commodity, pack, variety, grade, size, count, 
        qty_rec, qty_sort, qty_sold, qty_floor, coldstore
    ) VALUES %s
    ON CONFLICT (grn) DO UPDATE SET
        producer = EXCLUDED.producer,
        commodity = EXCLUDED.commodity,
        pack = EXCLUDED.pack,
        variety = EXCLUDED.variety,
        grade = EXCLUDED.grade,
        size = EXCLUDED.size,
        count = EXCLUDED.count,
        qty_rec = EXCLUDED.qty_rec,
        qty_sort = EXCLUDED.qty_sort,
        qty_sold = EXCLUDED.qty_sold,
        qty_floor = EXCLUDED.qty_floor,
        coldstore = EXCLUDED.coldstore;
    """
    
    records = []
    
    # Read as Tab-Delimited
    with open(file_path, mode='r', encoding='utf-8') as f:
        reader = csv.DictReader(f, delimiter='\t')
        
        for row in reader:
            grn = row.get('GRN_NO')
            
            # Skip empty rows or rows missing GRN
            if not grn or not str(grn).strip():
                continue
                
            # Unpack the squashed COMMODITY field (e.g., "APP,CT185,GS,1,*,100,*")
            comm_raw = row.get('COMMODITY', '')
            comm_parts = comm_raw.split(',') if comm_raw else []
            
            commodity = comm_parts[0] if len(comm_parts) > 0 else comm_raw
            pack      = comm_parts[1] if len(comm_parts) > 1 else ''
            variety   = comm_parts[2] if len(comm_parts) > 2 else ''
            grade     = comm_parts[3] if len(comm_parts) > 3 else '1'
            size      = comm_parts[4] if len(comm_parts) > 4 else '*'
            count     = comm_parts[5] if len(comm_parts) > 5 else '*'
            
            records.append((
                str(grn).strip(),
                row.get('PRODUCER', '').strip(),
                commodity,
                pack,
                variety,
                grade,
                size,
                count,
                int(row.get('QTY_REC', 0) or 0),
                int(row.get('CS_SUMAGTQTYSORTING', 0) or 0),
                int(row.get('QTY_SOLD', 0) or 0),
                int(row.get('QTY_FLOOR', 0) or 0),
                str(row.get('CSSUM', '0'))  # Coldstore sum
            ))
            
    if records:
        execute_values(cursor, query, records)
        conn.commit()
        print(f"✅ Successfully synced {len(records)} stock records!")
    else:
        print("⚠️ No valid stock records found.")
        
    cursor.close()
    conn.close()

if __name__ == "__main__":
    process_stock_csv("riaan300072026.csv")