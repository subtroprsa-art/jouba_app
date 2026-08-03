import os
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, request, jsonify, render_template, redirect, url_for, session

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

# --- DEDICATED SEPARATE INVENTORY PAGES ---
@app.route('/stock')
def stock_page():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return render_template('stock.html', user_name=get_current_user())

@app.route('/floor-balance')
def floor_balance_page():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return render_template('floor_balance.html', user_name=get_current_user())

# --- AI SMART MATCHING PIPELINE API ---
@app.route('/api/sales-pipeline', methods=['GET'])
def get_sales_pipeline():
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401

    conn = get_db_connection()
    cursor = conn.cursor()

    # Smart Match: Aggregates active stock and scores match capability based on age & history
    query = """
        WITH live_stock AS (
            SELECT 
                UPPER(TRIM(commodity)) AS commodity_clean,
                MIN(CURRENT_DATE - intake_date) AS min_age_days,
                MAX(CURRENT_DATE - intake_date) AS max_age_days,
                SUM(qty) AS total_qty
            FROM (
                SELECT commodity, intake_date, qty FROM stock_inventory WHERE qty > 0
                UNION ALL
                SELECT commodity, intake_date, qty FROM floor_balance WHERE qty > 0
            ) s
            GROUP BY UPPER(TRIM(commodity))
        ),
        buyer_habits AS (
            SELECT 
                UPPER(TRIM(buyer)) AS buyer_clean,
                UPPER(TRIM(commodity)) AS commodity_clean,
                COUNT(id) AS buy_count,
                SUM(total) AS spent
            FROM buyer_history
            GROUP BY UPPER(TRIM(buyer)), UPPER(TRIM(commodity))
        )
        SELECT 
            h.buyer,
            SUM(bh.spent) AS total_spent,
            ARRAY_AGG(DISTINCT bh.commodity_clean) AS matching_commodities,
            p.phone,
            l.contacted_by,
            l.contacted_at
        FROM buyer_history h
        INNER JOIN buyer_habits bh ON UPPER(TRIM(h.buyer)) = bh.buyer_clean
        INNER JOIN live_stock ls ON bh.commodity_clean = ls.commodity_clean
        LEFT JOIN buyer_phones p ON UPPER(TRIM(h.buyer)) = UPPER(TRIM(p.buyer_name))
        LEFT JOIN (
            SELECT DISTINCT ON (UPPER(TRIM(buyer))) UPPER(TRIM(buyer)) AS buyer_clean, contacted_by, contacted_at
            FROM buyer_contact_log
            ORDER BY UPPER(TRIM(buyer)), contacted_at DESC
        ) l ON UPPER(TRIM(h.buyer)) = l.buyer_clean
        -- AI Rules: Filter out fresh-only buyers (e.g. FLM) if stock min_age is too old (> 3 days)
        LEFT JOIN buyer_preferences pref ON UPPER(TRIM(h.buyer)) = pref.buyer
        WHERE (pref.max_stock_age_accepted IS NULL OR ls.min_age_days <= pref.max_stock_age_accepted)
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