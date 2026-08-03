import os
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, request, jsonify, render_template, redirect, url_for, session
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "jdw-fresh-secret-key-2026")

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

@app.route('/inventory')
def inventory_page():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return render_template('inventory.html', user_name=get_current_user())

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

# --- INVENTORY API (STOCK & FLOOR BALANCE) ---
@app.route('/api/inventory/<inv_type>', methods=['GET'])
def get_inventory_data(inv_type):
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401

    table_name = "stock_inventory" if inv_type == "stock" else "floor_balance"
    conn = get_db_connection()
    cursor = conn.cursor()

    query = f"""
        SELECT 
            COALESCE(salesman, 'Unassigned') AS salesman,
            COALESCE(farmer_name, '') AS farmer_name,
            COALESCE(commodity, '') AS commodity,
            COALESCE(variety, '') AS variety,
            COALESCE(size, '') AS size,
            COALESCE(pack_weight, '') AS pack_weight,
            COALESCE(qty, 0) AS qty,
            intake_date,
            (CURRENT_DATE - intake_date) AS age_days
        FROM {table_name}
        ORDER BY salesman, age_days DESC;
    """
    try:
        cursor.execute(query)
        rows = cursor.fetchall()

        # Group data by Salesman
        salesmen_data = {}
        for r in rows:
            sm = r['salesman']
            if sm not in salesmen_data:
                salesmen_data[sm] = []
            
            salesmen_data[sm].append({
                "farmer": r['farmer_name'],
                "commodity": r['commodity'],
                "variety": r['variety'],
                "size": r['size'],
                "pack_weight": r['pack_weight'],
                "qty": r['qty'],
                "intake_date": r['intake_date'].strftime('%Y-%m-%d') if r['intake_date'] else 'N/A',
                "age_days": r['age_days'] if r['age_days'] is not None else 0
            })

        cursor.close()
        conn.close()
        return jsonify({"inventory": salesmen_data}), 200
    except Exception as e:
        if cursor: cursor.close()
        if conn: conn.close()
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)