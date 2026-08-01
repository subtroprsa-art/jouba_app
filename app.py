import io
import csv
import os
import psycopg2
from psycopg2.extras import execute_values
from flask import Flask, render_template, request

app = Flask(__name__)

# Neon Connection String from environment variable (or fallback for local testing)
DB_URI = os.getenv(
    "DATABASE_URL",
    "postgresql://neondb_owner:YOUR_PASSWORD@ep-shiny-snow-ay06dic8-pooler.c-5.us-east-2.aws.neon.tech/neondb?sslmode=require"
)

def get_db_connection():
    return psycopg2.connect(DB_URI)

# Serve upload webpage
@app.route('/')
def home():
    return render_template('index.html')

# Stock CSV upload
@app.route('/upload-stock', methods=['POST'])
def upload_stock():
    if 'file' not in request.files:
        return "No file uploaded", 400
    
    file = request.files['file']
    content = file.read().decode('utf-8')
    f = io.StringIO(content.strip())
    reader = csv.DictReader(f, delimiter='\t')
    
    records = []
    for row in reader:
        grn = row.get('GRN_NO')
        if not grn or not str(grn).strip():
            continue
            
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
            commodity, pack, variety, grade, size, count,
            int(row.get('QTY_REC', 0) or 0),
            int(row.get('CS_SUMAGTQTYSORTING', 0) or 0),
            int(row.get('QTY_SOLD', 0) or 0),
            int(row.get('QTY_FLOOR', 0) or 0),
            str(row.get('CSSUM', '0'))
        ))

    if records:
        conn = get_db_connection()
        cursor = conn.cursor()
        query = """
        INSERT INTO stock_records (
            grn, producer, commodity, pack, variety, grade, size, count, 
            qty_rec, qty_sort, qty_sold, qty_floor, coldstore
        ) VALUES %s
        ON CONFLICT (grn) DO UPDATE SET
            producer = EXCLUDED.producer, commodity = EXCLUDED.commodity,
            pack = EXCLUDED.pack, variety = EXCLUDED.variety, grade = EXCLUDED.grade,
            size = EXCLUDED.size, count = EXCLUDED.count, qty_rec = EXCLUDED.qty_rec,
            qty_sort = EXCLUDED.qty_sort, qty_sold = EXCLUDED.qty_sold,
            qty_floor = EXCLUDED.qty_floor, coldstore = EXCLUDED.coldstore;
        """
        execute_values(cursor, query, records)
        conn.commit()
        cursor.close()
        conn.close()
        return f"✅ Successfully synced {len(records)} Stock Records to Neon!"

    return "⚠️ No valid records found.", 400

# Floor CSV upload
@app.route('/upload-floor', methods=['POST'])
def upload_floor():
    if 'file' not in request.files:
        return "No file uploaded", 400
        
    file = request.files['file']
    content = file.read().decode('utf-8')
    f = io.StringIO(content.strip())
    reader = csv.DictReader(f, delimiter='y')
    
    records = []
    grn_seq_counter = {}
    
    for row in reader:
        grn = row.get('GRNID')
        if not grn or not str(grn).strip():
            continue
            
        clean_grn = str(grn).strip()
        grn_seq_counter[clean_grn] = grn_seq_counter.get(clean_grn, 0) + 1
        seq_no = grn_seq_counter[clean_grn]
        
        records.append((
            clean_grn,
            seq_no,
            row.get('PROD', '').strip(),
            row.get('COMMODITY', '').strip(),
            row.get('CONTAINER', '').strip(),
            row.get('VARIETY', '').strip(),
            row.get('CLASS', '1').strip(),
            row.get('SIZ_REF', '*').strip(),
            row.get('CNT_REF', '*').strip(),
            int(row.get('QTY', 0) or row.get('QTY_AVAIL', 0) or 0),
            row.get('CF_CS_FLAG', '0').strip()
        ))

    if records:
        conn = get_db_connection()
        cursor = conn.cursor()
        query = """
        INSERT INTO floor_records (
            grn, seq_no, producer, commodity, pack, variety, grade, size, count, qty_floor, coldstore
        ) VALUES %s
        ON CONFLICT (grn, seq_no) DO UPDATE SET
            producer = EXCLUDED.producer, commodity = EXCLUDED.commodity,
            pack = EXCLUDED.pack, variety = EXCLUDED.variety, grade = EXCLUDED.grade,
            size = EXCLUDED.size, count = EXCLUDED.count, qty_floor = EXCLUDED.qty_floor,
            coldstore = EXCLUDED.coldstore;
        """
        execute_values(cursor, query, records)
        conn.commit()
        cursor.close()
        conn.close()
        return f"✅ Successfully synced {len(records)} Floor Records to Neon!"

    return "⚠️ No valid floor records found.", 400

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)