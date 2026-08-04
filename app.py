import os
import io
import json
import pandas as pd
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# Initialize Flask app at top-level for Gunicorn
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "jdw_fresh_secret_key_2026")

DATABASE_URL = os.environ.get(
    "DATABASE_URL", 
    "postgresql://neondb_owner:npg_1p3mIsQvTzeF@ep-hidden-rain-a8gq43w7.eastus2.azure.neon.tech/neondb?sslmode=require"
)

# Secret token for external API authentication
APP_SYNC_TOKEN = os.environ.get("APP_SYNC_TOKEN", "jdw_sync_secret_token_2026")

# Google Drive Folder IDs
FOLDERS = {
    "floor_raw": "1akYejLRp-bOvdjJEat4Z1XC1frru9j_Y",
    "floor_processed": "1DKEmqlTMJDBfqv9NsGZJYOuCEZWaf6SG",
    "stock_raw": "1DrYmim6xThu6KfKRplr5SDBVZc-BFMBm",
    "stock_processed": "1fLBZHRN9VsR5OfY2eercGPe8BLhVSO2E"
}

DRIVE_SCOPES = ['https://www.googleapis.com/auth/drive']


def get_db_connection():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def get_current_user():
    return session.get('username', 'Sales Team')


# --- GOOGLE DRIVE DIRECT SYNC LOGIC ---

def get_drive_service():
    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if creds_json:
        info = json.loads(creds_json)
        creds = service_account.Credentials.from_service_account_info(info, scopes=DRIVE_SCOPES)
    else:
        creds = service_account.Credentials.from_service_account_file('credentials.json', scopes=DRIVE_SCOPES)
    return build('drive', 'v3', credentials=creds)

def parse_salesman(filename):
    name = filename.lower()
    if name.startswith("cdw"):
        return "Christoff"
    elif name.startswith("riaa") or name.startswith("riaan"):
        return "Riaan"
    elif name.startswith("pot"):
        return "Pot"
    return "Unassigned"

def move_drive_file(service, file_id, target_folder_id):
    file = service.files().get(file_id=file_id, fields='parents').execute()
    previous_parents = ",".join(file.get('parents', []))
    service.files().update(
        fileId=file_id,
        addParents=target_folder_id,
        removeParents=previous_parents,
        fields='id, parents'
    ).execute()

def process_drive_folder(service, raw_folder_id, processed_folder_id, target_table):
    query = f"'{raw_folder_id}' in parents and trashed = false"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get('files', [])

    if not files:
        return 0

    conn = get_db_connection()
    cursor = conn.cursor()
    total_inserted = 0

    for file_item in files:
        file_id = file_item['id']
        file_name = file_item['name']
        salesman = parse_salesman(file_name)

        request_media = service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request_media)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        fh.seek(0)

        if file_name.lower().endswith('.csv'):
            df = pd.read_csv(fh)
        elif file_name.lower().endswith(('.xls', '.xlsx')):
            df = pd.read_excel(fh)
        else:
            continue

        df.columns = [str(c).strip().lower() for c in df.columns]

        # Clear existing records for this salesman
        cursor.execute(f"DELETE FROM {target_table} WHERE salesman = %s;", (salesman,))

        for idx, row in df.iterrows():
            seq_val = idx + 1
            farmer_val, comm_val, var_val, size_val, pack_val, qty_val = "", "", "", "", "", 0

            for col in df.columns:
                val = str(row[col]).strip() if pd.notna(row[col]) else ""
                if "seq" in col:
                    try: seq_val = int(row[col])
                    except: pass
                if "producer" in col or "farmer" in col: farmer_val = val
                if "commodity" in col: comm_val = val
                if "variety" in col: var_val = val
                if "size" in col: size_val = val
                if "pack" in col: pack_val = val
                if "qty" in col or "quantity" in col:
                    try: qty_val = int(row[col])
                    except: qty_val = 0

            cursor.execute(f"""
                INSERT INTO {target_table} 
                (seq_nr, salesman, producer, commodity, variety, size, pack, qty, intake_date)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, CURRENT_DATE);
            """, (seq_val, salesman, farmer_val, comm_val, var_val, size_val, pack_val, qty_val))
            total_inserted += 1

        conn.commit()
        move_drive_file(service, file_id, processed_folder_id)

    cursor.close()
    conn.close()
    return total_inserted


# --- AUTHENTICATION ROUTES ---

@app.route('/')
def home():
    if session.get('logged_in'):
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        if username and password:
            session['logged_in'] = True
            session['username'] = username
            return redirect(url_for('dashboard'))
        else:
            return render_template('login.html', error="Invalid username or password.")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# --- PAGE VIEWS ---

@app.route('/dashboard')
def dashboard():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return render_template('dashboard.html', user=get_current_user())

@app.route('/stock')
def stock_page():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return render_template('stock.html', user=get_current_user())

@app.route('/floor-balance')
def floor_balance_page():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return render_template('floor_balance.html', user=get_current_user())


# --- API ENDPOINTS ---

@app.route('/api/sync-drive', methods=['POST', 'GET'])
def trigger_drive_sync():
    """Endpoint to trigger quota-free direct Google Drive processing"""
    if request.method == 'POST' and not session.get('logged_in'):
        # Allow system/cron invocation via token parameter or logged-in session
        token = request.args.get('token') or (request.json or {}).get('token')
        if token != APP_SYNC_TOKEN:
            return jsonify({"error": "Unauthorized"}), 401

    try:
        service = get_drive_service()
        floor_count = process_drive_folder(service, FOLDERS["floor_raw"], FOLDERS["floor_processed"], "floor_records")
        stock_count = process_drive_folder(service, FOLDERS["stock_raw"], FOLDERS["stock_processed"], "stock_records")
        
        return jsonify({
            "success": True, 
            "message": "Google Drive sync completed successfully!",
            "imported": {"floor_records": floor_count, "stock_records": stock_count}
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/sales-pipeline', methods=['GET'])
def get_sales_pipeline():
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401

    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = """
        WITH available_stock AS (
            SELECT DISTINCT UPPER(TRIM(commodity)) AS commodity_clean
            FROM stock_records
            WHERE qty > 0
            UNION
            SELECT DISTINCT UPPER(TRIM(commodity)) AS commodity_clean
            FROM floor_records
            WHERE qty > 0
        )
        SELECT 
            h.buyer,
            COUNT(DISTINCT h.id) AS total_orders,
            SUM(h.total) AS total_spent,
            SUM(h.qty) AS total_units,
            p.phone,
            ARRAY_AGG(DISTINCT h.commodity) AS matching_commodities,
            l.contacted_by,
            l.contacted_at
        FROM buyer_history h
        INNER JOIN available_stock s ON UPPER(TRIM(h.commodity)) = s.commodity_clean
        LEFT JOIN buyer_phones p ON UPPER(TRIM(h.buyer)) = UPPER(TRIM(p.buyer_name))
        LEFT JOIN (
            SELECT DISTINCT ON (UPPER(TRIM(buyer))) UPPER(TRIM(buyer)) AS buyer_clean, contacted_by, contacted_at
            FROM buyer_contact_log
            ORDER BY UPPER(TRIM(buyer)), contacted_at DESC
        ) l ON UPPER(TRIM(h.buyer)) = l.buyer_clean
        GROUP BY h.buyer, p.phone, l.contacted_by, l.contacted_at
        ORDER BY total_spent DESC;
    """
    try:
        cursor.execute(query)
        results = cursor.fetchall()
        pipeline = []
        for row in results:
            commodities = [c for c in (row['matching_commodities'] or []) if c]
            pipeline.append({
                "buyer": row['buyer'],
                "total_spent": float(row['total_spent'] or 0.0),
                "total_units": int(row['total_units'] or 0),
                "phone": row['phone'] or '',
                "commodities": commodities,
                "contacted_by": row['contacted_by'],
                "contacted_at": row['contacted_at'].strftime('%Y-%m-%d %H:%M') if row['contacted_at'] else None
            })
        cursor.close()
        conn.close()
        return jsonify({"pipeline": pipeline, "current_user": get_current_user()}), 200
    except Exception as e:
        if cursor: cursor.close()
        if conn: conn.close()
        return jsonify({"error": str(e)}), 500


@app.route('/api/inventory/<inv_type>', methods=['GET'])
def get_inventory_data(inv_type):
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401

    table_name = "stock_records" if inv_type == "stock" else "floor_records"
    conn = get_db_connection()
    cursor = conn.cursor()

    order_clause = "seq_nr ASC NULLS LAST, age_days DESC" if inv_type == "floor" else "salesman, age_days DESC"

    query = f"""
        SELECT 
            COALESCE(seq_nr, 0) AS seq_nr,
            COALESCE(NULLIF(salesman, ''), 'Unassigned') AS salesman,
            COALESCE(producer, farmer_name, '') AS farmer_name,
            COALESCE(commodity, '') AS commodity,
            COALESCE(variety, '') AS variety,
            COALESCE(size, '') AS size,
            COALESCE(pack_weight, pack, '') AS pack_weight,
            COALESCE(qty, 0) AS qty,
            intake_date,
            CASE 
                WHEN intake_date IS NOT NULL THEN (CURRENT_DATE - intake_date)
                ELSE 0 
            END AS age_days
        FROM {table_name}
        ORDER BY {order_clause};
    """
    try:
        cursor.execute(query)
        rows = cursor.fetchall()

        salesmen_data = {}
        for r in rows:
            sm = r['salesman']
            if sm not in salesmen_data:
                salesmen_data[sm] = []
            
            salesmen_data[sm].append({
                "seq_nr": r['seq_nr'],
                "farmer": r['farmer_name'],
                "commodity": r['commodity'],
                "variety": r['variety'],
                "size": r['size'],
                "pack_weight": r['pack_weight'],
                "qty": r['qty'],
                "intake_date": r['intake_date'].strftime('%Y-%m-%d') if r['intake_date'] else 'N/A',
                "age_days": r['age_days']
            })

        cursor.close()
        conn.close()
        return jsonify({"inventory": salesmen_data}), 200
    except Exception as e:
        if cursor: cursor.close()
        if conn: conn.close()
        return jsonify({"error": str(e)}), 500


@app.route('/api/upload-inventory', methods=['POST'])
def upload_inventory():
    data = request.json or {}
    
    if data.get('token') != APP_SYNC_TOKEN:
        return jsonify({"error": "Unauthorized"}), 401

    target_table = data.get('target_table')
    salesman = data.get('salesman', 'Unassigned')
    records = data.get('records', [])

    if target_table not in ['stock_records', 'floor_records']:
        return jsonify({"error": "Invalid target table"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(f"DELETE FROM {target_table} WHERE salesman = %s;", (salesman,))

        inserted_count = 0
        for r in records:
            cursor.execute(f"""
                INSERT INTO {target_table} 
                (seq_nr, salesman, producer, commodity, variety, size, pack, qty, intake_date)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, CURRENT_DATE);
            """, (
                r.get('seq_nr', 0),
                salesman,
                r.get('farmer', ''),
                r.get('commodity', ''),
                r.get('variety', ''),
                r.get('size', ''),
                r.get('pack', ''),
                r.get('qty', 0)
            ))
            inserted_count += 1

        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"success": True, "inserted": inserted_count}), 200

    except Exception as e:
        if cursor: cursor.close()
        if conn: conn.close()
        return jsonify({"error": str(e)}), 500


@app.route('/api/log-contact', methods=['POST'])
def log_contact():
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401

    data = request.json or {}
    buyer = data.get('buyer')
    contacted_by = session.get('username', 'Sales Rep')

    if not buyer:
        return jsonify({"error": "Buyer name required"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO buyer_contact_log (buyer, contacted_by, contacted_at)
            VALUES (%s, %s, NOW());
        """, (buyer, contacted_by))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"success": True}), 200
    except Exception as e:
        if cursor: cursor.close()
        if conn: conn.close()
        return jsonify({"error": str(e)}), 500


@app.route('/api/health-check', methods=['GET'])
def health_check():
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401

    conn = get_db_connection()
    cursor = conn.cursor()
    
    diagnostics = {}
    
    try:
        cursor.execute("""
            SELECT COALESCE(salesman, 'UNASSIGNED') AS salesman, COUNT(*) AS count 
            FROM stock_records GROUP BY salesman;
        """)
        diagnostics['stock_records_summary'] = cursor.fetchall()

        cursor.execute("""
            SELECT COALESCE(salesman, 'UNASSIGNED') AS salesman, COUNT(*) AS count 
            FROM floor_records GROUP BY salesman;
        """)
        diagnostics['floor_records_summary'] = cursor.fetchall()

        cursor.close()
        conn.close()
        return jsonify({"status": "OK", "data": diagnostics}), 200
    except Exception as e:
        if cursor: cursor.close()
        if conn: conn.close()
        return jsonify({"status": "ERROR", "error": str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=True)