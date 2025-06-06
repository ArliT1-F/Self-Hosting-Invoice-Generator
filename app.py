from flask import Flask, render_template, request, redirect, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_mail import Mail, Message
from models import db, Invoice, Item
from users import User
from utils.pdf import generate_pdf
import io
from datetime import datetime
from sqlalchemy import func

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SECRET_KEY'] = 'supersecretkey'
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'your-email@gmail.com'
app.config['MAIL_PASSWORD'] = 'your-app-password'

mail = Mail(app)
db.init_app(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

with app.app_context():
    db.create_all()

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.route('/')
@login_required
def index():
    invoices = Invoice.query.all()
    return render_template('invoices_list.html', invoices=invoices)

@app.route('/create', methods=['GET', 'POST'])
@login_required
def create_invoice():
    if request.method == 'POST':
        data = request.form
        invoice = Invoice(
            client_name=data['client_name'],
            client_email=data['client_email'],
            client_address=data['client_address'],
            tax=float(data['tax']),
            status=data['status'],
            created_at=datetime.utcnow()
        )
        db.session.add(invoice)
        db.session.commit()

        for desc, qty, rate in zip(request.form.getlist('desc'), request.form.getlist('qty'), request.form.getlist('rate')):
            item = Item(description=desc, quantity=int(qty), rate=float(rate), invoice_id=invoice.id)
            db.session.add(item)

        db.session.commit()
        return redirect('/')
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

    msg = Message(subject=f"Invoice #{invoice.id}",
                  sender=app.config['MAIL_USERNAME'],
                  recipients=[invoice.client_email])
    msg.body = f"Dear {invoice.client_name},\nPlease find attached your invoice."
    msg.attach(f"invoice_{invoice.id}.pdf", "application/pdf", pdf)

    mail.send(msg)
    return redirect('/')

@app.route('/reports')
@login_required
def reports():
    data = db.session.query(
        func.strftime('%Y-%m', Invoice.created_at),
        func.sum(Item.quantity * Item.rate)
    ).join(Item).group_by(func.strftime('%Y-%m', Invoice.created_at)).all()
    return render_template('reports.html', data=data)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and user.check_password(request.form['password']):
            login_user(user)
            return redirect('/')
        return 'Invalid credentials'
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect('/login')

if __name__ == '__main__':
    app.run(debug=True)
