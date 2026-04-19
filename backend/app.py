import os
import mysql.connector
from flask import Flask, render_template, request, redirect, send_file, session, url_for
from fpdf import FPDF
import time
from werkzeug.utils import secure_filename
from flask import flash

app = Flask(__name__)
app.secret_key = 'medpro_secret_key_2026'

# Folder where lab reports will be saved
UPLOAD_FOLDER = 'static/uploads/reports'
ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg'}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Create the folder if it doesn't exist
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- DATABASE CONFIGURATION ---
db_config = {
    'host': 'localhost',
    'user': 'root',
    'password': '',
    'database': 'hospital_db'
}

def get_db_connection():
    return mysql.connector.connect(**db_config)

def get_patient_badge(diagnosis):
    if 'Emergency' in diagnosis or 'Critical' in diagnosis:
        return '<span class="badge bg-danger">Critical</span>'
    elif 'Follow-up' in diagnosis:
        return '<span class="badge bg-info text-dark">Follow-up</span>'
    else:
        return '<span class="badge bg-success">Routine</span>'

# --- DIRECTORY SETUP ---
base_dir = os.path.dirname(os.path.abspath(__file__))
reports_dir = os.path.join(base_dir, 'reports')
if not os.path.exists(reports_dir):
    os.makedirs(reports_dir)

# --- GLOBAL UTILITY ---
# This makes 'critical_count' available to all HTML pages automatically
@app.context_processor
def inject_critical_alerts():
    if 'user_id' in session:
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM lab_reports WHERE status = 'Critical'")
            count = cursor.fetchone()[0]
            cursor.close()
            conn.close()
            return dict(critical_count=count)
        except:
            return dict(critical_count=0)
    return dict(critical_count=0)

# --- 1. AUTHENTICATION SYSTEM ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        conn = get_db_connection()
        cursor = conn.cursor()
        query = "SELECT * FROM users WHERE username = %s AND password_hash = %s"
        cursor.execute(query, (username, password))
        user = cursor.fetchone()
        cursor.close()
        conn.close()

        if user:
            session['user_id'] = user[0]
            session['username'] = user[1]
            return redirect(url_for('index'))
        else:
            return render_template('login.html', error="Invalid Credentials")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# --- 2. MAIN ADMIN/DOCTOR DASHBOARD ---

@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # NEW: Only fetch patients where is_active = 1
    cursor.execute("SELECT * FROM patients WHERE is_active = 1")
    patients = cursor.fetchall()
    
    # UPDATED: Using the correct column name 'disease_summary'
    cursor.execute("SELECT disease_summary, COUNT(*) FROM patients GROUP BY disease_summary")
    chart_stats = cursor.fetchall()
    
    # Prepare the lists for Chart.js
    # We clean the data: if it's empty, we show "General"
    labels = [row[0] if row[0] else "General" for row in chart_stats]
    values = [row[1] for row in chart_stats]
    
    # Alert System: Fetch any "Critical" lab reports to show on dashboard
    cursor.execute("""
        SELECT p.name, l.test_name, l.test_result 
        FROM lab_reports l 
        JOIN patients p ON l.patient_id = p.id 
        WHERE l.status = 'Critical'
    """)
    alerts = cursor.fetchall()

    # Fetch pending reports count
    cursor.execute("SELECT COUNT(*) FROM lab_reports WHERE status = 'Pending'")
    pending_count = cursor.fetchone()[0]
    # CALCULATE ACTUAL TOTAL REVENUE
    cursor.execute("SELECT SUM(total_bill) FROM patients WHERE is_active = 1")
    total_revenue = cursor.fetchone()[0] or 0 # Default to 0 if no patients
    # Inside your index() function
    high_risk_count = 0
    for patient in patients:
        age = patient[3]
        summary = str(patient[5]).lower()
        
        # AI Logic: Flag if patient is elderly OR has critical symptoms
        if (age and age > 65) or any(word in summary for word in ['emergency', 'critical', 'severe', 'pain']):
            high_risk_count += 1

    cursor.close()
    conn.close()
    
    return render_template('index.html', 
                           patients=patients, 
                           labels=labels, 
                           values=values,
                           alerts=alerts,
                           pending_count=pending_count,
                           high_risk_count=high_risk_count,
                           revenue=total_revenue,
                           get_badge=get_patient_badge)

# app.py
@app.route('/add_patient', methods=['POST'])
def add_patient():
    # 1. Capture data from form
    name = request.form.get('name')
    phone = request.form.get('phone')
    age = request.form.get('age')
    gender = request.form.get('gender')
    disease = request.form.get('disease_summary')
    bill = request.form.get('total_bill')
    
    # NEW: Get the doctor name from the select tag above
    doc_name = request.form.get('assigned_doctor_name')

    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 2. Update your query to include the new column
    # Make sure 'assigned_doctor' is the exact name of the column in phpMyAdmin
    query = """
        INSERT INTO patients 
        (name, phone, age, gender, disease_summary, total_bill, assigned_doctor) 
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """
    
    # 3. Add doc_name to the tuple
    cursor.execute(query, (name, phone, age, gender, disease, bill, doc_name))
    
    conn.commit()
    cursor.close()
    conn.close()
    return redirect(url_for('index'))

@app.route('/print_invoice/<int:id>')
def print_invoice(id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM patients WHERE id = %s", (id,))
    patient = cursor.fetchone()
    cursor.close()
    conn.close()

    # Dynamic Routing Logic based on summary or fee
    summary = str(patient[5]).lower()
    if 'x-ray' in summary or 'scan' in summary:
        room = "Room 102 (Radiology)"
    elif 'blood' in summary or 'test' in summary or 'lab' in summary:
        room = "Room 105 (Pathology Lab)"
    else:
        room = "Consultation Room 01"

    return render_template('invoice.html', patient=patient, room=room)

@app.route('/upload_report/<int:id>', methods=['POST'])
def upload_report(id):
    if 'report_file' not in request.files:
        return redirect(request.url)
    
    file = request.files['report_file']
    
    if file and allowed_file(file.filename):
        filename = f"report_{id}_" + secure_filename(file.filename)
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        
        # Update database with the filename
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE patients SET lab_result_file = %s WHERE id = %s", (filename, id))
        conn.commit()
        cursor.close()
        conn.close()
        
    return redirect(url_for('index'))

@app.route('/delete_patient/<int:id>')
def delete_patient(id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Instead of DELETE, we UPDATE the status to 0
        cursor.execute("UPDATE patients SET is_active = 0 WHERE id = %s", (id,))
        conn.commit()
    except Exception as e:
        print(f"Error during soft delete: {e}")
    finally:
        cursor.close()
        conn.close()
    
    return redirect(url_for('index'))

@app.route('/consultant_room')
def consultant_room():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Fetch patients assigned to 'Consultation' or who haven't had a report yet
    cursor.execute("""
        SELECT id, name, age, gender, disease_summary, lab_result_file 
        FROM patients 
        WHERE is_active = 1 AND (department IS NULL OR department = 'Consultation')
    """)
    waiting_list = cursor.fetchall()
    
    cursor.close()
    conn.close()
    return render_template('consultant.html', patients=waiting_list)

@app.route('/save_prescription', methods=['POST'])
def save_prescription():
    patient_id = request.form.get('patient_id')
    
    if not patient_id:
        return "Error: No patient selected. Please click a patient in the list first.", 400

    diagnosis = request.form.get('diagnosis')
    rx = request.form.get('prescription')

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE patients SET doctor_notes = %s, prescription = %s WHERE id = %s", 
                   (diagnosis, rx, patient_id))
    conn.commit()
    cursor.close()
    conn.close()
    
    # Redirect to the print view
    return redirect(url_for('view_prescription', id=int(patient_id)))
    
    # Ensure this line has exactly the same number of spaces/tabs as the 'conn =' line above
    return redirect(url_for('view_prescription', id=patient_id))
@app.route('/hard_delete_patient/<int:id>')
def hard_delete_patient(id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # This is a permanent removal from the MySQL table
        cursor.execute("DELETE FROM patients WHERE id = %s", (id,))
        conn.commit()
    except Exception as e:
        print(f"Permanent Delete Error: {e}")
    finally:
        cursor.close()
        conn.close()
    
    return redirect(url_for('index'))

@app.route('/archive')
def archive():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Fetch only patients where is_active is 0
    cursor.execute("SELECT * FROM patients WHERE is_active = 0")
    archived_patients = cursor.fetchall()
    
    cursor.close()
    conn.close()
    return render_template('archive.html', patients=archived_patients)

@app.route('/restore_patient/<int:id>')
def restore_patient(id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE patients SET is_active = 1 WHERE id = %s", (id,))
    conn.commit()
    cursor.close()
    conn.close()
    return redirect(url_for('archive'))

@app.route('/view_prescription/<int:id>')
def view_prescription(id):
    conn = get_db_connection()
    cursor = conn.cursor()
    # We fetch the patient details to display on the prescription
    # Ensure your SELECT includes the columns you want to show on the Rx
    cursor.execute("SELECT name, age, gender, prescription, doctor_notes FROM patients WHERE id = %s", (id,))
    patient = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if patient:
        return render_template('prescription_print.html', patient=patient)
    else:
        return "Patient not found", 404
    
# --- 3. LAB MANAGEMENT SYSTEM ---

@app.route('/lab_dashboard', methods=['GET', 'POST'])
def lab_dashboard():
    if 'user_id' not in session: return redirect(url_for('login'))
    
    patient_data = None
    if request.method == 'POST' and 'search_invoice' in request.form:
        invoice_id = request.form['search_invoice']
        conn = get_db_connection()
        cursor = conn.cursor()
        # Find patient by Invoice ID (Patient ID)
        cursor.execute("SELECT * FROM patients WHERE id = %s", (invoice_id,))
        patient_data = cursor.fetchone()
        cursor.close()
        conn.close()

    return render_template('lab_window.html', patient=patient_data)

@app.route('/upload_result/<int:patient_id>', methods=['POST'])
def upload_result(patient_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    
    test_name = request.form['test_name']
    test_result = request.form['test_result']
    ref_range = request.form['ref_range']
    status = request.form['status']
    
    conn = get_db_connection()
    cursor = conn.cursor()
    # Matches your existing 'lab_reports' table structure exactly
    query = """INSERT INTO lab_reports (patient_id, test_name, test_result, reference_range, status) 
               VALUES (%s, %s, %s, %s, %s)"""
    cursor.execute(query, (patient_id, test_name, test_result, ref_range, status))
    conn.commit()
    cursor.close()
    conn.close()
        
    return redirect(url_for('lab_dashboard'))

# --- 4. BILLING & PDF GENERATION ---

@app.route('/print_bill/<int:patient_id>')
def print_bill(patient_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Fetch Patient Details
    cursor.execute("SELECT * FROM patients WHERE id = %s", (patient_id,))
    patient = cursor.fetchone()
    
    # 2. Fetch Lab Results for this patient
    cursor.execute("SELECT test_name, test_result, reference_range, status FROM lab_reports WHERE patient_id = %s", (patient_id,))
    lab_results = cursor.fetchall()
    
    cursor.close()
    conn.close()

    if not patient: return "Patient Record Not Found", 404

    # Create Professional Medical Report
    pdf = FPDF()
    pdf.add_page()
    
    # --- Header ---
    pdf.set_font("Arial", 'B', 22)
    pdf.set_text_color(15, 23, 42) 
    pdf.cell(200, 15, txt="CITY MEDICAL CENTER", ln=True, align='C')
    pdf.set_font("Arial", size=10)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(200, 5, txt="DIAGNOSTIC & CLINICAL LABORATORY REPORT", ln=True, align='C')
    pdf.ln(10)
    pdf.line(10, 45, 200, 45)
    
    # --- Patient Info Table ---
    pdf.set_y(50)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Arial", 'B', 11)
    pdf.cell(30, 8, "Patient ID:", 0)
    pdf.set_font("Arial", '', 11)
    pdf.cell(70, 8, f"#P-00{patient[0]}", 0)
    pdf.set_font("Arial", 'B', 11)
    pdf.cell(30, 8, "Date:", 0)
    pdf.set_font("Arial", '', 11)
    pdf.cell(60, 8, time.strftime('%d-%m-%Y'), 1, ln=True)
    
    pdf.set_font("Arial", 'B', 11)
    pdf.cell(30, 8, "Name:", 0)
    pdf.set_font("Arial", '', 11)
    pdf.cell(70, 8, f"{patient[1]}", 0)
    pdf.set_font("Arial", 'B', 11)
    pdf.cell(30, 8, "Age/Sex:", 0)
    pdf.set_font("Arial", '', 11)
    pdf.cell(60, 8, f"{patient[3]} / {patient[4]}", 0, ln=True)
    
    pdf.ln(10)
    pdf.set_font("Arial", 'B', 12)
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(190, 10, " LABORATORY TEST RESULTS", 0, 1, 'L', True)
    pdf.ln(2)

    # --- Lab Results Table Headers ---
    pdf.set_font("Arial", 'B', 10)
    pdf.cell(60, 10, "TEST NAME", 1)
    pdf.cell(45, 10, "RESULT", 1)
    pdf.cell(45, 10, "REF. RANGE", 1)
    pdf.cell(40, 10, "STATUS", 1, ln=True)

    # --- Lab Results Data ---
    pdf.set_font("Arial", '', 10)
    if lab_results:
        for row in lab_results:
            pdf.cell(60, 10, str(row[0]), 1)
            pdf.cell(45, 10, str(row[1]), 1)
            pdf.cell(45, 10, str(row[2]), 1)
            # Highlight Critical status in bold
            if row[3] == 'Critical':
                pdf.set_font("Arial", 'B', 10)
                pdf.cell(40, 10, str(row[3]), 1, ln=True)
                pdf.set_font("Arial", '', 10)
            else:
                pdf.cell(40, 10, str(row[3]), 1, ln=True)
    else:
        pdf.cell(190, 10, "No laboratory tests recorded for this patient.", 1, ln=True, align='C')

    # --- Footer ---
    pdf.ln(20)
    pdf.set_font("Arial", 'B', 11)
    pdf.cell(190, 10, "Doctor's Remarks:", ln=True)
    pdf.set_font("Arial", 'I', 10)
    pdf.multi_cell(190, 8, f"Initial Diagnosis: {patient[5]}. Please correlate clinical findings with the lab results above.")
    
    pdf.set_y(-40)
    pdf.set_font("Arial", 'I', 8)
    pdf.cell(190, 10, "This report is electronically generated and verified by MedPro.ai Systems.", 0, 0, 'C')

    file_name = f"medical_report_{patient_id}_{int(time.time())}.pdf"
    file_path = os.path.join(reports_dir, file_name)
    pdf.output(file_path)
    
    return send_file(file_path, as_attachment=False)

# --- PATIENT LIST PAGE ---
@app.route('/patients_list')
def patients_list():
    if 'user_id' not in session: return redirect(url_for('login'))
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM patients ORDER BY name ASC")
    all_patients = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('patients.html', patients=all_patients)

# --- ALL REPORTS PAGE ---
@app.route('/all_reports')
def all_reports():
    if 'user_id' not in session: return redirect(url_for('login'))
    conn = get_db_connection()
    cursor = conn.cursor()
    # Fetch all patients so we can pick one to view their full medical history
    cursor.execute("SELECT id, name, phone FROM patients ORDER BY id DESC")
    patients = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('reports_center.html', patients=patients)
@app.route('/add_appointment', methods=['POST'])
def add_appointment():
    if 'user_id' not in session: return redirect(url_for('login'))
    
    name = request.form.get('patient_name')
    time = request.form.get('appt_time')
    reason = request.form.get('reason')
    appt_type = request.form.get('appt_type')

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO appointments (patient_name, appointment_time, reason, type) 
        VALUES (%s, %s, %s, %s)
    """, (name, time, reason, appt_type))
    conn.commit()
    cursor.close()
    conn.close()
    return redirect(url_for('schedule'))

# --- ONLY KEEP THIS ONE ---
@app.route('/schedule')
def schedule():
    if 'user_id' not in session: 
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Fetch appointments
    cursor.execute("SELECT * FROM appointments ORDER BY appointment_time ASC")
    all_appts = cursor.fetchall()
    
    # 2. Fetch pending lab reports count
    cursor.execute("SELECT COUNT(*) FROM lab_reports WHERE status = 'Pending'")
    pending_count = cursor.fetchone()[0]
    
    cursor.close()
    conn.close()
    
    return render_template('schedule.html', appointments=all_appts, pending_count=pending_count)



if __name__ == "__main__":
    # Ensure folder is ready
    if not os.path.exists(reports_dir):
        os.makedirs(reports_dir)
        
    print("[RUNNING] MedPro AI System Active at http://127.0.0.1:5000")
    app.run(debug=True, port=5000)