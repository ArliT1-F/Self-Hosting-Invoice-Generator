import os
from flask import Flask, render_template, request, redirect, send_file, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, logout_user, login_required, current_user, UserMixin
from flask_mail import Mail, Message
from werkzeug.security import generate_password_hash, check_password_hash
from weasyprint import HTML
import io
from datetime import datetime

# --- App and Config ---
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'supersecretkey')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.getenv('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME', 'your-email@gmail.com')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD', 'your-app-password')

# --- Extensions ---
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
mail = Mail(app)

# --- Models ---
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Invoice(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    client_name = db.Column(db.String(100), nullable=False)
    client_email = db.Column(db.String(100), nullable=False)
    client_address = db.Column(db.Text, nullable=False)
    tax = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    items = db.relationship('Item', backref='invoice', lazy=True, cascade="all, delete-orphan")

class Item(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    description = db.Column(db.String(200), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    rate = db.Column(db.Float, nullable=False)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoice.id'), nullable=False)

# Initialize Database
with app.app_context():
    # Ensure schema is up-to-date
    db.create_all()

# --- User Loader ---
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- PDF Generation ---
def generate_pdf(html_content):
    return HTML(string=html_content).write_pdf()

# --- Routes ---
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        if User.query.filter_by(username=username).first():
            return "Username already exists", 400
        new_user = User(username=username, email=email)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and user.check_password(request.form['password']):
            login_user(user)
            return redirect(url_for('landing'))
        return 'Invalid credentials', 401
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/')
def landing():
    return render_template('landing.html')

@app.route('/create', methods=['GET', 'POST'])
@login_required
def create_invoice():
    if request.method == 'POST':
        descs = request.form.getlist('desc')
        qtys = request.form.getlist('qty')
        rates = request.form.getlist('rate')
        if not (len(descs) == len(qtys) == len(rates)):
            return "Mismatched item fields", 400

        invoice = Invoice(
            client_name=request.form['client_name'],
            client_email=request.form['client_email'],
            client_address=request.form['client_address'],
            tax=float(request.form['tax']),
            status=request.form['status']
        )
        db.session.add(invoice)
        db.session.commit()

        for desc, qty, rate in zip(descs, qtys, rates):
            item = Item(description=desc, quantity=int(qty), rate=float(rate), invoice_id=invoice.id)
            db.session.add(item)
        db.session.commit()
        return redirect(url_for('index'))
    return render_template('create_invoice.html')

@app.route('/invoice/<int:invoice_id>/pdf')
@login_required
def download_pdf(invoice_id):
    invoice = Invoice.query.get_or_404(invoice_id)
    html = render_template('invoice_pdf.html', invoice=invoice)
    pdf = generate_pdf(html)
    return send_file(io.BytesIO(pdf), download_name=f'invoice_{invoice.id}.pdf', as_attachment=True)

@app.route('/invoice/<int:invoice_id>/email')
@login_required
def email_invoice(invoice_id):
    invoice = Invoice.query.get_or_404(invoice_id)
    html = render_template('invoice_pdf.html', invoice=invoice)
    pdf = generate_pdf(html)

    msg = Message(
        subject=f"Invoice #{invoice.id}",
        sender=app.config['MAIL_USERNAME'],
        recipients=[invoice.client_email]
    )
    msg.body = f"Dear {invoice.client_name},\nPlease find attached your invoice."
    msg.attach(f"invoice_{invoice.id}.pdf", "application/pdf", pdf)
    mail.send(msg)
    return redirect(url_for('index'))

@app.route('/reports')
@login_required
def reports():
    data = db.session.query(
        db.func.strftime('%Y-%m', Invoice.created_at),
        db.func.sum(Item.quantity * Item.rate)
    ).join(Item).group_by(db.func.strftime('%Y-%m', Invoice.created_at)).all()
    return render_template('reports.html', data=data)

@app.route('/init-admin')
def init_admin():
    if User.query.filter_by(username='admin').first():
        return "Admin already exists"
    admin = User(username='admin', email='arliturka@gmail.com')
    admin.set_password('adminpass')
    db.session.add(admin)
    db.session.commit()
    return "Admin user created! You can now log in at /login"

@app.route('/reset-db')
def reset_db():
    # WARNING: drops all data
    db.drop_all()
    db.create_all()
    return "Database reset complete"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
