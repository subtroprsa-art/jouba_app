import os
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, render_template, request, jsonify, redirect, url_for, session

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "jdw_fresh_secret_key_2026")

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://neondb_owner:npg_1p3mIsQvTzeF@ep-hidden-rain-a8gq43w7.eastus2.azure.neon.tech/neondb?sslmode=require")

def get_db_connection():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def get_current_user():
    return session.get('username', 'Sales Team')


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

        # Basic Auth Check
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

    # Query with COALESCE fallbacks for both table schemas (producer vs farmer_name, pack vs pack_weight)
    query = f"""
        SELECT 
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
                "age_days": r['age_days']
            })

        cursor.close()
        conn.close()
        return jsonify({"inventory": salesmen_data}), 200
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


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)