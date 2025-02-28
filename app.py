from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, jsonify, session, Response
import sqlite3
import json
import os
import csv
from io import StringIO

app = Flask(__name__)
app.secret_key = 'tu_clave_secreta_aqui'  # Cambia esto por una clave segura

def get_db_connection():
    try:
        conn = sqlite3.connect('database.db')
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as e:
        print(f"Database connection error: {e}")
        return None

def init_db():
    try:
        conn = get_db_connection()
        if conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS payments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    client TEXT NOT NULL,
                    date TEXT NOT NULL,
                    amount REAL NOT NULL,
                    facturado BOOLEAN NOT NULL,
                    payment_type TEXT NOT NULL,
                    payer_name TEXT,
                    grouped BOOLEAN NOT NULL DEFAULT 0
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    payment_id INTEGER NOT NULL,
                    item_name TEXT NOT NULL,
                    item_amount REAL NOT NULL,
                    FOREIGN KEY (payment_id) REFERENCES payments (id)
                )
            ''')
            conn.commit()
            conn.close()
    except sqlite3.Error as e:
        print(f"Database initialization error: {e}")

def get_items():
    items_path = os.path.join(os.path.dirname(__file__), 'static', 'items.json')
    with open(items_path, 'r') as file:
        return json.load(file)

def format_number(value):
    return round(value, 2)

app.jinja_env.globals.update(format_number=format_number)

@app.route('/', methods=['GET', 'POST'])
def index():
    try:
        conn = get_db_connection()
        if conn:
            if request.method == 'POST':
                selected_date = request.form.get('date', '')
                session['date_filter'] = selected_date
            else:
                selected_date = request.args.get('date', session.get('date_filter', ''))

            selected_payment_type = request.form.get('payment_type', request.args.get('payment_type', ''))
            per_page = request.args.get('per_page', 10, type=int)  # Número de pagos por página, por defecto 10
            page = request.args.get('page', 1, type=int)  # Número de página, por defecto 1
            offset = (page - 1) * per_page  # Calcular el desplazamiento

            query = '''SELECT * FROM payments'''
            params = []
            if selected_date:
                query += ''' WHERE date = ?'''
                params.append(selected_date)
            if selected_payment_type:
                if 'WHERE' not in query:
                    query += ''' WHERE'''
                else:
                    query += ''' AND'''
                query += ''' payment_type = ?'''
                params.append(selected_payment_type)
            query += ''' ORDER BY date DESC, id DESC LIMIT ? OFFSET ?'''
            params.extend([per_page, offset])

            payments_query = conn.execute(query, params)
            payments = payments_query.fetchall()

            # Contar el total de pagos para calcular el número de páginas
            count_query = '''SELECT COUNT(*) as total FROM payments'''
            count_params = []
            if selected_date:
                count_query += ''' WHERE date = ?'''
                count_params.append(selected_date)
            if selected_payment_type:
                if 'WHERE' not in count_query:
                    count_query += ''' WHERE'''
                else:
                    count_query += ''' AND'''
                count_query += ''' payment_type = ?'''
                count_params.append(selected_payment_type)
            total_payments = conn.execute(count_query, count_params).fetchone()['total']
            total_pages = (total_payments + per_page - 1) // per_page

            total_amount_query = conn.execute('''SELECT SUM(amount) AS total_amount FROM payments WHERE date = ?''', (selected_date,))
            total_amount = total_amount_query.fetchone()['total_amount'] or 0

            total_efectivo_query = conn.execute('''SELECT SUM(amount) AS total_amount FROM payments WHERE date = ? AND payment_type = 'efectivo' ''', (selected_date,))
            total_efectivo = total_efectivo_query.fetchone()['total_amount'] or 0

            total_banca_query = conn.execute('''SELECT SUM(amount) AS total_amount FROM payments WHERE date = ? AND payment_type = 'banca' ''', (selected_date,))
            total_banca = total_banca_query.fetchone()['total_amount'] or 0

            conn.close()
            return render_template('index.html', payments=payments, selected_date=selected_date, 
                                 selected_payment_type=selected_payment_type, total_amount=total_amount, 
                                 total_efectivo=total_efectivo, total_banca=total_banca,
                                 page=page, per_page=per_page, total_pages=total_pages, total_payments=total_payments)
        else:
            return render_template('error.html', message="Database connection failed"), 500
    except sqlite3.Error as e:
        print(f"Database query error: {e}")
        return render_template('error.html', message="Error fetching payments"), 500

@app.route('/add_payment', methods=['GET', 'POST'])
def add_payment():
    try:
        conn = get_db_connection()
        if conn:
            date_filter = session.get('date_filter', '')
            if request.method == 'POST':
                client = request.form.get('client')
                date = request.form.get('date')
                payment_type = request.form.get('payment_type')
                payer_name = request.form.get('payer_name', '')
                is_facturado = 'is_facturado' in request.form
                items = request.form.getlist('item_name[]')
                amounts = request.form.getlist('item_amount[]')

                if not client or not date or not payment_type or not items or not amounts:
                    return render_template('error.html', message="Missing required fields"), 400

                cursor = conn.execute('''INSERT INTO payments (client, date, amount, facturado, payment_type, payer_name, grouped)
                                         VALUES (?, ?, ?, ?, ?, ?, ?)''', 
                                      (client, date, 0.0, is_facturado, payment_type, payer_name, True))
                payment_id = cursor.lastrowid

                for item, amount in zip(items, amounts):
                    conn.execute('''INSERT INTO items (payment_id, item_name, item_amount)
                                    VALUES (?, ?, ?)''', 
                                 (payment_id, item, float(amount)))

                total_amount = sum(float(amount) for amount in amounts)
                conn.execute('''UPDATE payments SET amount = ? WHERE id = ?''', (total_amount, payment_id))

                conn.commit()
                conn.close()
                return redirect(url_for('index'))

            available_items = get_items()
            return render_template('add_payment.html', available_items=available_items, date=date_filter)
        else:
            return render_template('error.html', message="Database connection failed"), 500
    except sqlite3.Error as e:
        print(f"Database query error: {e}")
        return render_template('error.html', message="Error adding payment"), 500

def row_to_dict(row):
    return dict(row)

@app.route('/payment_details/<int:payment_id>')
def payment_details(payment_id):
    try:
        conn = get_db_connection()
        if conn:
            payment_query = conn.execute('''SELECT * FROM payments WHERE id = ?''', (payment_id,))
            payment = payment_query.fetchone()
            if not payment:
                return render_template('error.html', message="Payment not found"), 404

            items_query = conn.execute('''SELECT item_name, item_amount FROM items WHERE payment_id = ?''', (payment_id,))
            items = items_query.fetchall()

            conn.close()
            return render_template('payment_details.html', payment=payment, items=items)
        else:
            return render_template('error.html', message="Database connection failed"), 500
    except sqlite3.Error as e:
        print(f"Database query error: {e}")
        return render_template('error.html', message="Error fetching payment details"), 500

@app.route('/edit_payment/<int:payment_id>', methods=['GET', 'POST'])
def edit_payment(payment_id):
    try:
        conn = get_db_connection()
        if conn:
            date_filter = request.form.get('date_filter', request.args.get('date', session.get('date_filter', '')))

            if request.method == 'POST':
                client = request.form.get('client')
                date = request.form.get('date')
                payment_type = request.form.get('payment_type')
                payer_name = request.form.get('payer_name', '')
                facturado = 'is_facturado' in request.form
                items = request.form.getlist('item_name[]')
                amounts = request.form.getlist('item_amount[]')

                if not client or not date or not payment_type or not items or not amounts:
                    return render_template('error.html', message="Missing required fields"), 400

                conn.execute('''UPDATE payments
                                SET client = ?, date = ?, payment_type = ?, payer_name = ?, facturado = ?
                                WHERE id = ?''',
                             (client, date, payment_type, payer_name, facturado, payment_id))

                conn.execute('''DELETE FROM items WHERE payment_id = ?''', (payment_id,))

                for item, amount in zip(items, amounts):
                    conn.execute('''INSERT INTO items (payment_id, item_name, item_amount)
                                    VALUES (?, ?, ?)''',
                                 (payment_id, item, float(amount)))

                conn.commit()
                conn.close()
                return redirect(url_for('index'))

            payment_query = conn.execute('''SELECT * FROM payments WHERE id = ?''', (payment_id,))
            payment = payment_query.fetchone()
            if not payment:
                return render_template('error.html', message="Payment not found"), 404

            items_query = conn.execute('''SELECT item_name, item_amount FROM items WHERE payment_id = ?''', (payment_id,))
            items = items_query.fetchall()

            conn.close()
            available_items = get_items()
            return render_template('edit_payment.html', payment=payment, items=items, available_items=available_items, date=date_filter)
        else:
            return render_template('error.html', message="Database connection failed"), 500
    except sqlite3.Error as e:
        print(f"Database query error: {e}")
        return render_template('error.html', message="Error editing payment"), 500

@app.route('/delete_payment', methods=['POST'])
def delete_payment():
    try:
        payment_id = request.form.get('id', type=int)
        conn = get_db_connection()
        if conn:
            conn.execute('''DELETE FROM items WHERE payment_id = ?''', (payment_id,))
            conn.execute('''DELETE FROM payments WHERE id = ?''', (payment_id,))
            conn.commit()
            conn.close()
            return redirect(url_for('index'))
        else:
            return render_template('error.html', message="Database connection failed"), 500
    except sqlite3.Error as e:
        print(f"Database query error: {e}")
        return render_template('error.html', message="Error deleting payment"), 500

@app.route('/summary', methods=['GET', 'POST'])
def summary():
    try:
        conn = get_db_connection()
        if conn:
            if request.method == 'POST':
                selected_date = request.form.get('date', '')
                session['date_filter'] = selected_date
            else:
                selected_date = session.get('date_filter', '')

            grouped_summary_query = conn.execute('''
                SELECT item_name AS item, SUM(item_amount) AS total_amount
                FROM items
                JOIN payments ON items.payment_id = payments.id
                WHERE payments.grouped = 1 AND payments.facturado = 0 AND payments.date = ?
                GROUP BY item_name
            ''', (selected_date,))
            grouped_summary = [dict(row) for row in grouped_summary_query.fetchall()]

            ungrouped_payments_query = conn.execute('''
                SELECT id, client, date, amount, payment_type, payer_name
                FROM payments
                WHERE grouped = 0 AND facturado = 0 AND date = ?
            ''', (selected_date,))
            ungrouped_payments = [dict(row) for row in ungrouped_payments_query.fetchall()]

            ungrouped_summary = []
            for payment in ungrouped_payments:
                items_query = conn.execute('''
                    SELECT item_name, item_amount
                    FROM items
                    WHERE payment_id = ?
                ''', (payment['id'],))
                items = [dict(row) for row in items_query.fetchall()]
                ungrouped_summary.append({
                    'payment': payment,
                    'items': items
                })

            total_amount_query = conn.execute('''SELECT SUM(amount) AS total_amount FROM payments WHERE date = ? AND facturado = 0''', (selected_date,))
            total_amount = total_amount_query.fetchone()['total_amount'] or 0

            total_efectivo_query = conn.execute('''SELECT SUM(amount) AS total_amount FROM payments WHERE date = ? AND payment_type = 'efectivo' AND facturado = 0''', (selected_date,))
            total_efectivo = total_efectivo_query.fetchone()['total_amount'] or 0

            total_banca_query = conn.execute('''SELECT SUM(amount) AS total_amount FROM payments WHERE date = ? AND payment_type = 'banca' AND facturado = 0''', (selected_date,))
            total_banca = total_banca_query.fetchone()['total_amount'] or 0

            conn.close()
            return render_template('summary.html', grouped_summary=grouped_summary, ungrouped_summary=ungrouped_summary, selected_date=selected_date, total_amount=total_amount, total_efectivo=total_efectivo, total_banca=total_banca)
        else:
            return render_template('error.html', message="Database connection failed"), 500
    except sqlite3.Error as e:
        print(f"Database query error: {e}")
        return render_template('error.html', message="Error fetching summary"), 500

@app.route('/update_grouped', methods=['POST'])
def update_grouped():
    data = request.form
    if not data or 'id' not in data or 'grouped' not in data:
        return jsonify({'success': False, 'error': 'Invalid data'}), 400
    try:
        conn = get_db_connection()
        if conn:
            grouped = data['grouped'] == 'true'
            conn.execute('UPDATE payments SET grouped = ? WHERE id = ?', (grouped, data['id']))
            conn.commit()
            conn.close()
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'error': 'Database connection failed'}), 500
    except sqlite3.Error as e:
        print(f"Database update error: {e}")
        return jsonify({'success': False, 'error': 'Database error'}), 500

@app.route('/export_summary')
def export_summary():
    try:
        conn = get_db_connection()
        if conn:
            selected_date = session.get('date_filter', '')
            if not selected_date:
                return render_template('error.html', message="No date selected"), 400

            grouped_summary_query = conn.execute('''
                SELECT item_name AS item, SUM(item_amount) AS total_amount
                FROM items
                JOIN payments ON items.payment_id = payments.id
                WHERE payments.grouped = 1 AND payments.facturado = 0 AND payments.date = ?
                GROUP BY item_name
            ''', (selected_date,))
            grouped_summary = [dict(row) for row in grouped_summary_query.fetchall()]

            ungrouped_payments_query = conn.execute('''
                SELECT id, client, date, amount, payment_type, payer_name
                FROM payments
                WHERE grouped = 0 AND facturado = 0 AND date = ?
            ''', (selected_date,))
            ungrouped_payments = [dict(row) for row in ungrouped_payments_query.fetchall()]

            output = StringIO()
            writer = csv.writer(output)
            writer.writerow(['Ítems Agrupados', '', ''])
            writer.writerow(['Ítem', 'Monto', 'Monto sin 7%'])
            for item in grouped_summary:
                writer.writerow([item['item'], item['total_amount'], round(item['total_amount'] / 1.07, 2)])
            writer.writerow([])
            writer.writerow(['Pagos No Agrupados', '', ''])
            writer.writerow(['ID', 'Cliente', 'Fecha', 'Monto', 'Tipo de Pago', 'Pagador', 'Ítem', 'Monto Ítem', 'Monto sin 7%'])
            for payment in ungrouped_payments:
                items_query = conn.execute('''SELECT item_name, item_amount FROM items WHERE payment_id = ?''', (payment['id'],))
                items = items_query.fetchall()
                for item in items:
                    writer.writerow([payment['id'], payment['client'], payment['date'], payment['amount'], 
                                    payment['payment_type'], payment['payer_name'], item['item_name'], 
                                    item['item_amount'], round(item['item_amount'] / 1.07, 2)])
            conn.close()
            output.seek(0)
            return Response(output.getvalue(), mimetype='text/csv', headers={"Content-Disposition": f"attachment;filename=resumen_{selected_date}.csv"})
        else:
            return render_template('error.html', message="Database connection failed"), 500
    except sqlite3.Error as e:
        print(f"Database query error: {e}")
        return render_template('error.html', message="Error exporting summary"), 500

if __name__ == '__main__':
    init_db()
    app.run(debug=True)