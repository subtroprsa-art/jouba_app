import io
import csv
import os
import psycopg2
from psycopg2.extras import execute_values
from flask import Flask, render_template, request, jsonify
from datetime import datetime

app = Flask(__name__)

DB_URI = os.getenv(
    "DATABASE_URL",
    "postgresql://neondb_owner:YOUR_PASSWORD@ep-shiny-snow-ay06dic8-pooler.c-5.us-east-2.aws.neon.tech/neondb?sslmode=require"
)

def get_db_connection():
    return psycopg2.connect(DB_URI)

# ------------------------------------------------------------------
# Health & Dashboard Endpoints
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

@app.route('/api/dashboard-kpis', methods=['GET'])
def get_dashboard_kpis():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT COALESCE(SUM(qty_rec - qty_sold), 0) FROM stock_records;")
    total_stock = cursor.fetchone()[0]
    
    cursor.execute("SELECT COALESCE(SUM(qty_rec), 0), COALESCE(SUM(qty_sold), 0) FROM stock_records;")
    total_rec, total_sold = cursor.fetchone()
    clearance_rate = round((total_sold / total_rec * 100), 1) if total_rec > 0 else 0.0
    
    cursor.execute("""
        SELECT COALESCE(SUM(qty_rec - qty_sold), 0) 
        FROM stock_records 
        WHERE created_at < NOW() - INTERVAL '14 days';
    """)
    urgent_stock = cursor.fetchone()[0]
    
    cursor.close()
    conn.close()
    
    return jsonify({
        "total_stock": total_stock,
        "clearance_rate": f"{clearance_rate}%",
        "urgent_stock": urgent_stock
    })

@app.route('/api/sales-pipeline', methods=['GET'])
def run_sales_pipeline():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = """
    WITH current_stock AS (
        SELECT DISTINCT commodity 
        FROM stock_records 
        WHERE (qty_rec - qty_sold) > 0
    )
    SELECT 
        b.buyer,
        SUM(b.total) AS total_spent,
        SUM(b.qty) AS total_units_bought,
        STRING_AGG(DISTINCT b.commodity, ', ') AS matched_commodities
    FROM buyer_history b
    JOIN current_stock s ON UPPER(b.commodity) = UPPER(s.commodity)
    GROUP BY b.buyer
    ORDER BY total_spent DESC
    LIMIT 30;
    """
    
    cursor.execute(query)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    
    top_buyers = []
    for rank, row in enumerate(rows, 1):
        top_buyers.append({
            "rank": rank,
            "buyer": row[0],
            "total_spent": float(row[1] or 0),
            "units_bought": row[2],
            "commodities": row[3]
        })
        
    return jsonify({"status": "success", "top_30_buyers": top_buyers})

# ------------------------------------------------------------------
# CSV / TXT Upload Endpoints
# ------------------------------------------------------------------

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
        return f"✅ Database updated with {len(records)} Stock Records!"

    return "⚠️ No valid records found.", 400

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
        return f"✅ Database updated with {len(records)} Floor Records!"

    return "⚠️ No valid records found.", 400

# ------------------------------------------------------------------
# OCR Webhook & Contact Endpoints
# ------------------------------------------------------------------

@app.route('/process-coldstore-slip', methods=['POST'])
def process_coldstore_slip():
    data = request.get_json(silent=True) or request.form.to_dict()
    if not data:
        return jsonify({"status": "error", "message": "No data received"}), 400

    date_val = data.get('date', '')
    buyer = data.get('buyer', '').strip().upper()
    producer = data.get('producer', 'UNKNOWN').strip().upper()
    commodity = data.get('commodity', '').strip().upper()
    pack = data.get('pack', '').strip().upper()
    qty = int(data.get('qty', 0) or 0)
    price = float(data.get('price', 0) or 0.0)
    total = float(data.get('total', 0) or 0.0)

    if 'AVOCADO' in commodity or commodity == 'AVO':
        commodity = 'AVOS'

    if buyer and commodity:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        parsed_date = None
        if date_val:
            try:
                parsed_date = datetime.strptime(date_val.strip(), '%d/%m/%Y').strftime('%Y-%m-%d')
            except ValueError:
                parsed_date = None

        query = """
        INSERT INTO buyer_history (
            purchase_date, buyer, producer, commodity, pack, qty, price, total
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
        """
        cursor.execute(query, (parsed_date, buyer, producer, commodity, pack, qty, price, total))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"status": "success", "message": f"Recorded slip for {buyer}"}), 200

    return jsonify({"status": "error", "message": "Missing required fields"}), 400

@app.route('/upload-buyer-phones', methods=['POST'])
def upload_buyer_phones():
    data = request.get_json(silent=True) or []
    if not isinstance(data, list):
        return jsonify({"status": "error", "message": "Expected JSON array of contacts"}), 400

    records = []
    for item in data:
        buyer = item.get('buyerName', '').strip().upper()
        if buyer:
            records.append((
                buyer,
                item.get('phone', '').strip(),
                item.get('contactName', '').strip()
            ))

    if records:
        conn = get_db_connection()
        cursor = conn.cursor()
        query = """
        INSERT INTO buyer_phones (buyer_name, phone, contact_name)
        VALUES %s
        ON CONFLICT (buyer_name) 
        DO UPDATE SET phone = EXCLUDED.phone, contact_name = EXCLUDED.contact_name;
        """
        execute_values(cursor, query, records)
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"status": "success", "message": f"Synced {len(records)} buyer phone contacts"}), 200

    return jsonify({"status": "error", "message": "No valid contact records found"}), 400

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)