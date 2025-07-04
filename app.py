from flask import Flask, render_template, request, redirect, session, url_for, flash, g, jsonify
from datetime import datetime, timedelta
import os
import uuid
from functools import wraps
import boto3
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash

# ---------------------------------------
# Load Environment Variables
# ---------------------------------------
if not load_dotenv():
    print("Warning: .env file not found. Using default values.")

# ---------------------------------------
# Flask App Initialization
# ---------------------------------------
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24))
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=1)

# ---------------------------------------
# DynamoDB Setup
# ---------------------------------------
AWS_REGION_NAME = os.environ.get('AWS_REGION_NAME', 'us-east-1')
USERS_TABLE_NAME = os.environ.get('USERS_TABLE_NAME', 'MedTrackUsers')
APPOINTMENTS_TABLE_NAME = os.environ.get('APPOINTMENTS_TABLE_NAME', 'MedTrackAppointments')
PATIENT_DETAILS_TABLE_NAME = os.environ.get('PATIENT_DETAILS_TABLE_NAME', 'MedTrackPatientDetails')
DOCTOR_DETAILS_TABLE_NAME = os.environ.get('DOCTOR_DETAILS_TABLE_NAME', 'MedTrackDoctorDetails')
MEDICAL_HISTORY_TABLE_NAME = os.environ.get('MEDICAL_HISTORY_TABLE_NAME', 'MedTrackMedicalHistory')

try:
    dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION_NAME)
    sns = boto3.client('sns', region_name=AWS_REGION_NAME)
    SNS_TOPIC_ARN = os.environ.get('SNS_TOPIC_ARN')
except Exception as e:
    print(f"Error initializing DynamoDB or SNS: {e}")
    dynamodb = None
    sns = None
    SNS_TOPIC_ARN = None

     print("AWS credentials not found. Running in local mode.")
except Exception as e:
    print(f"Error initializing DynamoDB or SNS: {e}")
    dynamodb = None
    sns = None
    SNS_TOPIC_ARN = None

# SNS helper
def publish_to_sns(message, subject="MedTrack Notification"):
    if sns and SNS_TOPIC_ARN:
        try:
            sns.publish(
                TopicArn=SNS_TOPIC_ARN,
                Message=message,
                Subject=subject
            )
        except Exception as e:
            print(f"Error publishing to SNS: {e}")
    else:
        print("SNS not configured, skipping publish.")

# ---------------------------------------
# Local fallback DB
# ---------------------------------------
# local_db = {
#     'users': {},
#     'appointments': {},
#     'patient_details': {},
#     'doctor_details': {},
#     'medical_history': {}
# }

# ---------------------------------------
# Helper functions
# ---------------------------------------
def get_user_table():
    if dynamodb:
        return dynamodb.Table(USERS_TABLE_NAME)
    return None

def get_appointments_table():
    if dynamodb:
        return dynamodb.Table(APPOINTMENTS_TABLE_NAME)
    return None

def get_patient_details_table():
    if dynamodb:
        return dynamodb.Table(PATIENT_DETAILS_TABLE_NAME)
    return None

def get_doctor_details_table():
    if dynamodb:
        return dynamodb.Table(DOCTOR_DETAILS_TABLE_NAME)
    return None

def get_medical_history_table():
    if dynamodb:
        return dynamodb.Table(MEDICAL_HISTORY_TABLE_NAME)
    return None

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_email' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# ---------------------------------------
# Before Request
# ---------------------------------------
@app.before_request
def load_logged_in_user():
    user_email = session.get('user_email')
    g.user = None
    g.doctor_details = None
    if user_email:
        if dynamodb:
            user_table = get_user_table()
            try:
                response = user_table.get_item(Key={'email': user_email})
                if 'Item' in response:
                    g.user = response['Item']
                    if g.user['role'] == 'doctor':
                        doctor_table = get_doctor_details_table()
                        doc_resp = doctor_table.get_item(Key={'email': user_email})
                        g.doctor_details = doc_resp.get('Item')
            except Exception as e:
                print(f"Error loading user from DynamoDB: {e}")
        # else:
        #     g.user = local_db['users'].get(user_email)
        #     if g.user and g.user['role'] == 'doctor':
        #         g.doctor_details = local_db['doctor_details'].get(user_email)

# ---------------------------------------
# Routes
# ---------------------------------------

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/getstarted')
def get_started():
    return render_template('getstarted.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        role = request.form.get('role')
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        age = request.form.get('age')
        gender = request.form.get('gender')
        specialization = request.form.get('specialization') if role == 'doctor' else ''

        if password != confirm_password:
            return render_template('signup.html', password_error="Passwords do not match")

        hashed_password = generate_password_hash(password)

        user_data = {
            'email': email,
            'name': name,
            'password': hashed_password,
            'role': role,
            'age': age,
            'gender': gender,
            'specialization': specialization,
            'created_at': datetime.now().isoformat()
        }

        if dynamodb:
            user_table = get_user_table()
            try:
                user_table.put_item(Item=user_data)
                publish_to_sns(
                    f"Welcome {name}! Your {role} account has been created successfully.",
                    "New User Registration"
                )
            except Exception as e:
                print(f"Error saving user to DynamoDB: {e}")
        # else:
        #     local_db['users'][email] = user_data

        session.clear()
        session['user_email'] = email

        return redirect(url_for('doctor_details' if role == 'doctor' else 'patient_details'))

    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = None

        if dynamodb:
            user_table = get_user_table()
            try:
                response = user_table.get_item(Key={'email': email})
                if 'Item' in response:
                    user = response['Item']
            except Exception as e:
                print(f"Error fetching user: {e}")
        # else:
        #     user = local_db['users'].get(email)

        if user and check_password_hash(user['password'], password):
            session.clear()
            session['user_email'] = email
            return redirect(url_for('doctor_dashboard' if user['role'] == 'doctor' else 'patient_dashboard'))
        else:
            flash("Invalid credentials")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/patient_details')
@login_required
def patient_details():
    if g.user['role'] != 'patient':
        return redirect(url_for('login'))
    return render_template('patient_details.html', user=g.user)

@app.route('/save_patient_details', methods=['POST'])
@login_required
def save_patient_details():
    patient_data = {
        'email': g.user['email'],
        'contact': request.form['contact'],
        'address': request.form['address'],
        'height': request.form['height'],
        'weight': request.form['weight'],
        'blood_group': request.form['blood_group'],
        'allergies': request.form['allergies'],
        'conditions': request.form['conditions'],
        'history': request.form['history']
    }
    if dynamodb:
        table = get_patient_details_table()
        table.put_item(Item=patient_data)
    # else:
    #     local_db['patient_details'][g.user['email']] = patient_data
    return redirect(url_for('patient_dashboard'))

@app.route('/appointment_dashboard')
@login_required
def appointment_dashboard():
    if g.user['role'] != 'patient':
        return redirect(url_for('login'))

    doctors = []
    if dynamodb:
        user_table = get_user_table()
        doctor_details_table = get_doctor_details_table()
        try:
            response = user_table.scan()
            doctors = [u for u in response['Items'] if u['role'] == 'doctor']

            for doc in doctors:
                details_resp = doctor_details_table.get_item(Key={'email': doc['email']})
                details = details_resp.get('Item')
                if details:
                    doc['availability'] = details.get('availability', 'Not provided')
                else:
                    doc['availability'] = 'Not provided'
        except Exception as e:
            print(f"Error fetching doctors: {e}")
    # else:
    #     doctors = [u for u in local_db['users'].values() if u['role'] == 'doctor']
    #     for doc in doctors:
    #         details = local_db['doctor_details'].get(doc['email'])
    #         if details:
    #             doc['availability'] = details.get('availability', 'Not provided')
    #         else:
    #             doc['availability'] = 'Not provided'

    return render_template('appointment_booking.html', user=g.user, doctors=doctors)

@app.route('/submit-appointment', methods=['POST'])
@login_required
def submit_appointment():
    appointment_data = {
        'id': str(uuid.uuid4()),
        'patient_name': request.form['patient_name'],
        'email': request.form['email'],
        'phone': request.form['phone'],
        'doctor': request.form['doctor'],
        'date': request.form['date'],
        'time': request.form['time'],
        'problem': request.form['problem'],
        'status': 'Scheduled'
    }

    if dynamodb:
        table = get_appointments_table()
        try:
            table.put_item(Item=appointment_data)
            publish_to_sns(
                f"New appointment booked for {appointment_data['patient_name']} with Dr.{appointment_data['doctor']} on {appointment_data['date']} at {appointment_data['time']}",
                "New Appointment Booked"
            )
        except Exception as e:
            print(f"Error saving appointment to DynamoDB: {e}")
    # else:
    #     local_db['appointments'].setdefault(g.user['email'], []).append(appointment_data)

    return redirect(url_for('patient_dashboard'))

@app.route('/save-doctor-details', methods=['POST'])
@login_required
def save_doctor_details():
    doctor_data = {
        'email': g.user['email'],
        'experience': request.form['experience'],
        'clinic_address': request.form['clinic_address'],
        'contact': request.form['contact'],
        'availability': request.form['availability']
    }
    if dynamodb:
        table = get_doctor_details_table()
        table.put_item(Item=doctor_data)
    # else:
    #     local_db['doctor_details'][g.user['email']] = doctor_data
    return redirect(url_for('doctor_dashboard'))

@app.route('/doctor_details')
@login_required
def doctor_details():
    if g.user['role'] != 'doctor':
        return redirect(url_for('login'))
    return render_template('doctor_details.html')

@app.route('/view_patient/<patient_email>')
@login_required
def view_patient(patient_email):
    if g.user['role'] != 'doctor':
        return redirect(url_for('login'))

    patient = None
    patient_details = None
    history = []

    if dynamodb:
        user_table = get_user_table()
        details_table = get_patient_details_table()
        history_table = get_medical_history_table()
        try:
            resp = user_table.get_item(Key={'email': patient_email})
            patient = resp.get('Item')
            resp = details_table.get_item(Key={'email': patient_email})
            patient_details = resp.get('Item')
            scan_resp = history_table.scan()
            history = [h for h in scan_resp['Items'] if h['email'] == patient_email]
        except Exception as e:
            print(f"Error fetching patient data: {e}")
    # else:
    #     patient = local_db['users'].get(patient_email)
    #     patient_details = local_db['patient_details'].get(patient_email)
    #     history = [h for h in local_db['medical_history'].values() if h['email'] == patient_email]

    return render_template('view_patient.html', patient=patient, details=patient_details, medical_history=history)

@app.route('/doctor_dashboard')
@login_required
def doctor_dashboard():
    if g.user['role'] != 'doctor':
        return redirect(url_for('login'))

    appointments = []

    if dynamodb:
        table = get_appointments_table()
        try:
            response = table.scan()
            appointments = [
                a for a in response['Items']
                if a['doctor'] == g.user['name']
            ]
        except Exception as e:
            print(f"Error fetching appointments: {e}")
    # else:
    #     appointments = [
    #         a for patient_appts in local_db['appointments'].values()
    #         for a in patient_appts
    #         if a['doctor'] == g.user['name']
    #     ]

    for a in appointments:
        if 'status' not in a:
            a['status'] = 'Scheduled'

    return render_template(
        'doctor_dashboard.html',
        user=g.user,
        appointments=appointments,
        doctor_details=g.doctor_details
    )

@app.route('/submit_prescription', methods=['POST'])
@login_required
def submit_prescription():
    appt_id = request.form.get('appt_index')
    prescription = request.form.get('prescription')
    if appt_id and prescription:
        if dynamodb:
            appt_table = get_appointments_table()
            history_table = get_medical_history_table()
            try:
                response = appt_table.scan()
                target = [a for a in response['Items'] if a['id'] == appt_id]
                if target:
                    appt = target[0]
                    appt['prescription'] = prescription
                    appt['status'] = 'Completed'
                    appt_table.put_item(Item=appt)

                    history = {
                        'id': str(uuid.uuid4()),
                        'email': appt['email'],
                        'date': appt['date'],
                        'doctor': appt['doctor'],
                        'diagnosis': appt['problem'],
                        'prescription': prescription
                    }
                    history_table.put_item(Item=history)
            except Exception as e:
                print(f"Error submitting prescription: {e}")
        # else:
        #     for patient_email, appts in local_db['appointments'].items():
        #         for appt in appts:
        #             if appt['id'] == appt_id:
        #                 appt['prescription'] = prescription
        #                 appt['status'] = 'Completed'
        #                 local_db['medical_history'][str(uuid.uuid4())] = {
        #                     'email': appt['email'],
        #                     'date': appt['date'],
        #                     'doctor': appt['doctor'],
        #                     'diagnosis': appt['problem'],
        #                     'prescription': prescription
        #                 }
        #                 break
    return redirect(url_for('doctor_dashboard'))

@app.route('/patient_dashboard')
@login_required
def patient_dashboard():
    if g.user['role'] != 'patient':
        return redirect(url_for('login'))

    appointments = []
    history = []
    patient_details = None
    if dynamodb:
        appointments_table = get_appointments_table()
        details_table = get_patient_details_table()
        history_table = get_medical_history_table()
        try:
            a_resp = appointments_table.scan()
            appointments = [a for a in a_resp['Items'] if a['email'] == g.user['email']]
            d_resp = details_table.get_item(Key={'email': g.user['email']})
            patient_details = d_resp.get('Item')
            h_resp = history_table.scan()
            history = [h for h in h_resp['Items'] if h['email'] == g.user['email']]
        except Exception as e:
            print(f"Error loading patient dashboard: {e}")
    # else:
    #     appointments = local_db['appointments'].get(g.user['email'], [])
    #     patient_details = local_db['patient_details'].get(g.user['email'])
    #     history = [h for h in local_db['medical_history'].values() if h['email'] == g.user['email']]

    return render_template(
        'patient_dashboard.html',
        user=g.user,
        appointments=appointments,
        details=patient_details,
        medical_history=history,
        full_dashboard=True
    )

@app.route('/aboutus')
def aboutus():
    return render_template('aboutus.html')

@app.route('/contactus')
def contactus():
    return render_template('contactus.html')

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000, debug=True)
