import os
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, request, jsonify, render_template, redirect, url_for, session

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "jdw-fresh-secret-key-2026")

# Team Credentials
USER_ACCOUNTS = {
    "riaan": {"name": "Riaan Joubert", "pass": os.environ.get("RIAAN_PASSWORD", "riaan2026")},
    "christoff": {"name": "Christoff de Wet", "pass": os.environ.get("CHRISTOFF_PASSWORD", "christoff2026")}
}

def get_db_connection():
    return psycopg2.connect(
        os.environ.get("DATABASE_URL"),
        cursor_factory=RealDictCursor
    )

def get_current_user():
    return session.get("user_fullname")

# --- AUTHENTICATION ROUTES ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip().lower()
        password = request.form.get('password', '').strip()

        if username in USER_ACCOUNTS and USER_ACCOUNTS[username]["pass"] == password:
            session['logged_in'] = True
            session['user_id'] = username
            session['user_fullname'] = USER_ACCOUNTS[username]["name"]
            return redirect(url_for('dashboard'))
        else:
            error = "Invalid username or password."
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# --- DASHBOARD & NAVIGATION ---
@app.route('/')
@app.route('/dashboard')
def dashboard():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return render_template('dashboard.html', user_name=get_current_user())

@app.route('/pipeline')
def pipeline_page():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return render_template('pipeline.html', user_name=get_current_user())

# --- SALES PIPELINE API ---
@app.route('/api/sales-pipeline', methods=['GET'])
def get_sales_pipeline():
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401

    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = """
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

# --- BUYER MATCH DETAILS API (Splits Commodity, Pack Weight, Class, Variety) ---
@app.route('/api/buyer-details/<path:buyer_name>', methods=['GET'])
def get_buyer_details(buyer_name):
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401

    conn = get_db_connection()
    cursor = conn.cursor()

    query = """
        SELECT 
            COALESCE(commodity, 'PRODUCE') AS commodity,
            COALESCE(pack, '') AS raw_pack,
            COALESCE(pack_weight, '') AS pack_weight,
            COALESCE(item_class, '') AS item_class,
            COALESCE(variety, '') AS variety,
            SUM(qty) AS total_qty
        FROM buyer_history
        WHERE UPPER(TRIM(buyer)) = UPPER(TRIM(%s))
        GROUP BY commodity, pack, pack_weight, item_class, variety
        ORDER BY total_qty DESC;
    """
    try:
        cursor.execute(query, (buyer_name,))
        matches = cursor.fetchall()
        
        detail_list = []
        for item in matches:
            raw_pack = item['raw_pack'].strip()
            p_weight = item['pack_weight'].strip()
            i_class = item['item_class'].strip()
            var = item['variety'].strip()

            # Dynamic string splitting fallback if separate columns are empty
            if not p_weight or not i_class or not var:
                tokens = raw_pack.split()
                p_weight = p_weight or (tokens[0] if len(tokens) > 0 else 'STD')
                
                if not i_class:
                    if 'C1' in raw_pack.upper() or 'CLASS 1' in raw_pack.upper():
                        i_class = 'Class 1'
                    elif 'C2' in raw_pack.upper() or 'CLASS 2' in raw_pack.upper():
                        i_class = 'Class 2'
                    else:
                        i_class = 'Class 1'
                        
                if not var:
                    var = ' '.join(tokens[2:]) if len(tokens) > 2 else 'Standard'

            pack_display = f"{p_weight} {i_class} {var}".strip()

            detail_list.append({
                "commodity": item['commodity'],
                "pack": pack_display if pack_display else raw_pack,
                "pack_weight": p_weight,
                "item_class": i_class,
                "variety": var,
                "total_qty": int(item['total_qty'] or 0)
            })
            
        cursor.close()
        conn.close()
        return jsonify(detail_list), 200
    except Exception as e:
        if cursor: cursor.close()
        if conn: conn.close()
        return jsonify({"error": str(e)}), 500

# --- MARK BUYER CONTACTED ---
@app.route('/api/mark-contacted', methods=['POST'])
def mark_contacted():
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json() or {}
    buyer = data.get('buyer', '').strip()
    user_name = get_current_user()

    if not buyer:
        return jsonify({"error": "Buyer name required"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = """
        INSERT INTO buyer_contact_log (buyer, contacted_by)
        VALUES (%s, %s);
    """
    cursor.execute(query, (buyer, user_name))
    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({"status": "success", "contacted_by": user_name}), 200

# --- PROCESS BUYER SLIPS ---
@app.route('/process-buyer-slip', methods=['POST'])
def process_buyer_slip():
    data = request.get_json() or {}
    
    parsed_date = data.get('date')
    buyer = data.get('buyer', '').strip()
    producer = data.get('producer', '').strip()
    commodity = data.get('commodity', '').strip()
    pack = data.get('pack', '').strip()
    qty = data.get('qty', 0)
    price = data.get('price', 0.0)
    total = data.get('total', 0.0)

    if not buyer or not commodity:
        return jsonify({"error": "Missing required details"}), 400

    # Parse pack into separate attributes during insert
    tokens = pack.split()
    pack_weight = tokens[0] if len(tokens) > 0 else 'STD'
    item_class = 'Class 1' if 'C1' in pack.upper() or 'CLASS 1' in pack.upper() else ('Class 2' if 'C2' in pack.upper() or 'CLASS 2' in pack.upper() else 'Class 1')
    variety = ' '.join(tokens[2:]) if len(tokens) > 2 else 'Standard'

    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = """
        INSERT INTO buyer_history (date, buyer, producer, commodity, pack, pack_weight, item_class, variety, qty, price, total)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (buyer, commodity, pack, qty, price, total) 
        DO NOTHING;
    """
    cursor.execute(query, (parsed_date, buyer, producer, commodity, pack, pack_weight, item_class, variety, qty, price, total))
    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({"status": "success"}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)