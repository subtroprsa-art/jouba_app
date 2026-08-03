import io
import csv
import os
import psycopg2
from psycopg2.extras import execute_values
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

# Neon Connection String from environment variable (or fallback for local testing)
DB_URI = os.getenv(
    "DATABASE_URL",
    "postgresql://neondb_owner:YOUR_PASSWORD@ep-shiny-snow-ay06dic8-pooler.c-5.us-east-2.aws.neon.tech/neondb?sslmode=require"
)

def get_db_connection():
    return psycopg2.connect(DB_URI)

# ------------------------------------------------------------------
# Health & Web Interface Endpoints
# ------------------------------------------------------------------

@app.route('/')
def home():
    try:
        return render_template('index.html')
    except Exception:
        return "App is running!", 200

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok", "message": "Service is healthy"}), 200

@app.route('/process-coldstore-slip', methods=['POST'])
def process_coldstore_slip():
    data = request.get_json(silent=True) or request.form.to_dict()
    return jsonify({
        "status": "success",
        "message": "Coldstore slip received successfully",
        "data_received": data
    }), 200

# ------------------------------------------------------------------
# CSV / TXT Upload Endpoints (Clears Old Data First)
# ------------------------------------------------------------------

# Stock CSV / TXT upload
@app.route('/upload-stock', methods=['POST'])
def upload_stock():
    if 'file' not in request.files:
        return "No file uploaded", 400
    
    file = request.files['file']
    content = file.read().decode('utf-8', errors='ignore')
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
        
        # 🗑️ Wipe previous stock records so only the latest remains
        cursor.execute("TRUNCATE TABLE stock_records;")
        
        query = """
        INSERT INTO stock_records (
            grn, producer, commodity, pack, variety, grade, size, count, 
            qty_rec, qty_sort, qty_sold, qty_floor, coldstore
        ) VALUES %s;
        """
        execute_values(cursor, query, records)
        conn.commit()
        cursor.close()
        conn.close()
        return f"✅ Database wiped & updated with {len(records)} NEW Stock Records!"

    return "⚠️ No valid stock records found.", 400

# Floor CSV / TXT upload
@app.route('/upload-floor', methods=['POST'])
def upload_floor():
    if 'file' not in request.files:
        return "No file uploaded", 400
        
    file = request.files['file']
    content = file.read().decode('utf-8', errors='ignore')
    f = io.StringIO(content.strip())
    reader = csv.DictReader(f, delimiter='\t')
    
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
        
        # 🗑️ Wipe previous floor records so only the latest remains
        cursor.execute("TRUNCATE TABLE floor_records;")
        
        query = """
        INSERT INTO floor_records (
            grn, seq_no, producer, commodity, pack, variety, grade, size, count, qty_floor, coldstore
        ) VALUES %s;
        """
        execute_values(cursor, query, records)
        conn.commit()
        cursor.close()
        conn.close()
        return f"✅ Database wiped & updated with {len(records)} NEW Floor Records!"

    return "⚠️ No valid floor records found.", 400

# ------------------------------------------------------------------

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

from datetime import datetime

# Buyer History CSV / TXT upload
@app.route('/upload-buyer-history', methods=['POST'])
def upload_buyer_history():
    if 'file' not in request.files:
        return "No file uploaded", 400
        
    file = request.files['file']
    content = file.read().decode('utf-8', errors='ignore')
    f = io.StringIO(content.strip())
    reader = csv.DictReader(f, delimiter='\t')
    
    records = []
    for row in reader:
        buyer = row.get('buyer') or row.get('BUYER')
        if not buyer or not str(buyer).strip():
            continue
            
        raw_date = row.get('date') or row.get('DATE') or ''
        parsed_date = None
        if raw_date:
            try:
                # Converts '18/07/2026' to '2026-07-18' for PostgreSQL DATE
                parsed_date = datetime.strptime(raw_date.strip(), '%d/%m/%Y').strftime('%Y-%m-%d')
            except ValueError:
                parsed_date = None

        records.append((
            parsed_date,
            str(buyer).strip(),
            row.get('producer', '').strip(),
            row.get('commodity', '').strip(),
            row.get('pack', '').strip(),
            int(row.get('qty', 0) or 0),
            float(row.get('price', 0) or 0.0),
            float(row.get('total', 0) or 0.0)
        ))

    if records:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 🗑️ Wipe old history so only the latest full report is active
        cursor.execute("TRUNCATE TABLE buyer_history;")
        
        query = """
        INSERT INTO buyer_history (
            purchase_date, buyer, producer, commodity, pack, qty, price, total
        ) VALUES %s;
        """
        execute_values(cursor, query, records)
        conn.commit()
        cursor.close()
        conn.close()
        return f"✅ Database updated with {len(records)} NEW Buyer History Records!"

    return "⚠️ No valid buyer history records found.", 400

