import os
import io
from datetime import datetime, date, timedelta
from flask import Flask, render_template, request, redirect, send_file, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, logout_user, login_required, current_user, UserMixin
from flask_mail import Mail, Message
from werkzeug.security import generate_password_hash, check_password_hash
from weasyprint import HTML
from sqlalchemy import inspect, text
from sqlalchemy.exc import NoSuchTableError
from dateutil.relativedelta import relativedelta

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
    due_date = db.Column(db.Date, nullable=True)
    currency = db.Column(db.String(3), nullable=False, default='USD')
    locale = db.Column(db.String(10), nullable=False, default='en-US')
    source_type = db.Column(db.String(20), nullable=False, default='manual')
    parent_invoice_id = db.Column(db.Integer, db.ForeignKey('invoice.id'), nullable=True)

    items = db.relationship('Item', backref='invoice', lazy=True, cascade="all, delete-orphan")
    child_invoices = db.relationship(
        'Invoice',
        cascade="all",
        backref=db.backref('parent_invoice', remote_side=[id]),
        lazy='dynamic'
    )
    schedules = db.relationship('RecurringSchedule', backref='template_invoice', lazy=True, cascade="all, delete-orphan")

class Item(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    description = db.Column(db.String(200), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    rate = db.Column(db.Float, nullable=False)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoice.id'), nullable=False)


class RecurringSchedule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoice.id'), nullable=False)
    frequency = db.Column(db.String(20), nullable=False)
    interval = db.Column(db.Integer, nullable=False, default=1)
    anchor_date = db.Column(db.Date, nullable=False)
    next_run_at = db.Column(db.DateTime, nullable=False)
    due_after_days = db.Column(db.Integer, nullable=False, default=14)
    auto_send = db.Column(db.Boolean, default=False)
    status = db.Column(db.String(20), nullable=False, default='active')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    reminders = db.relationship('RecurringReminder', backref='schedule', lazy=True, cascade="all, delete-orphan")
    executions = db.relationship('ScheduleExecutionLog', backref='schedule', lazy=True, cascade="all, delete-orphan")


class RecurringReminder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    schedule_id = db.Column(db.Integer, db.ForeignKey('recurring_schedule.id'), nullable=False)
    offset_days = db.Column(db.Integer, nullable=False)
    message_template = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    logs = db.relationship('InvoiceReminderLog', backref='reminder', lazy=True, cascade="all, delete-orphan")


class ScheduleExecutionLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    schedule_id = db.Column(db.Integer, db.ForeignKey('recurring_schedule.id'), nullable=False)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoice.id'), nullable=False)
    run_at = db.Column(db.DateTime, default=datetime.utcnow)

    invoice = db.relationship('Invoice', backref=db.backref('recurring_execution', uselist=False))


class InvoiceReminderLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    reminder_id = db.Column(db.Integer, db.ForeignKey('recurring_reminder.id'), nullable=False)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoice.id'), nullable=False)
    sent_at = db.Column(db.DateTime, default=datetime.utcnow)


def ensure_invoice_columns():
    def ensure(table_name, column_name, ddl, default=None):
        inspector = inspect(db.engine)
        try:
            existing_columns = {col['name'] for col in inspector.get_columns(table_name)}
        except NoSuchTableError:
            return
        if column_name in existing_columns:
            return
        db.session.execute(text(f'ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}'))
        if default is not None:
            db.session.execute(
                text(f'UPDATE {table_name} SET {column_name} = :default WHERE {column_name} IS NULL'),
                {'default': default}
            )
        db.session.commit()

    ensure('invoice', 'due_date', 'DATE')
    ensure('invoice', 'currency', "VARCHAR(3) DEFAULT 'USD'", 'USD')
    ensure('invoice', 'locale', "VARCHAR(10) DEFAULT 'en-US'", 'en-US')
    ensure('invoice', 'source_type', "VARCHAR(20) DEFAULT 'manual'", 'manual')
    ensure('invoice', 'parent_invoice_id', 'INTEGER')


# Initialize Database
with app.app_context():
    # Ensure schema is up-to-date
    ensure_invoice_columns()
    db.create_all()

# --- User Loader ---
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- PDF Generation ---
def generate_pdf(html_content):
    return HTML(string=html_content).write_pdf()


def calculate_invoice_totals(invoice):
    subtotal = sum(item.quantity * item.rate for item in invoice.items)
    tax_amount = subtotal * (invoice.tax / 100)
    total = subtotal + tax_amount
    return subtotal, tax_amount, total


ALLOWED_FREQUENCIES = {'daily', 'weekly', 'monthly', 'yearly'}
SCHEDULE_PROCESS_INTERVAL_SECONDS = 60
REMINDER_PROCESS_INTERVAL_SECONDS = 120
_last_schedule_run = None
_last_reminder_run = None


def parse_date(value, fallback=None):
    if not value:
        return fallback
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return fallback


def add_frequency(base_datetime: datetime, frequency: str, interval: int) -> datetime:
    interval = max(interval or 1, 1)
    frequency = (frequency or '').lower()
    if frequency == 'daily':
        return base_datetime + timedelta(days=interval)
    if frequency == 'weekly':
        return base_datetime + timedelta(weeks=interval)
    if frequency == 'monthly':
        return base_datetime + relativedelta(months=interval)
    if frequency == 'yearly':
        return base_datetime + relativedelta(years=interval)
    # fallback: treat as days
    return base_datetime + timedelta(days=interval)


def calculate_next_run(schedule: RecurringSchedule, reference: datetime | None = None) -> datetime | None:
    if schedule.status != 'active':
        return None
    base = schedule.next_run_at or datetime.combine(schedule.anchor_date, datetime.min.time())
    reference = reference or datetime.utcnow()
    candidate = base
    guard = 0
    while candidate <= reference and guard < 100:
        candidate = add_frequency(candidate, schedule.frequency, schedule.interval)
        guard += 1
    return candidate if guard < 100 else None


def clone_invoice_from_schedule(schedule: RecurringSchedule) -> Invoice | None:
    template = schedule.template_invoice
    if not template:
        return None

    status_value = template.status
    if status_value.lower() == 'paid':
        status_value = 'Unpaid'

    new_invoice = Invoice(
        client_name=template.client_name,
        client_email=template.client_email,
        client_address=template.client_address,
        tax=template.tax,
        status=status_value,
        currency=template.currency,
        locale=template.locale,
        source_type='recurring',
        parent_invoice_id=template.id,
        due_date=(datetime.utcnow() + timedelta(days=schedule.due_after_days)).date()
    )
    db.session.add(new_invoice)
    db.session.flush()

    for item in template.items:
        cloned_item = Item(
            description=item.description,
            quantity=item.quantity,
            rate=item.rate,
            invoice_id=new_invoice.id
        )
        db.session.add(cloned_item)

    execution = ScheduleExecutionLog(schedule_id=schedule.id, invoice_id=new_invoice.id)
    db.session.add(execution)
    return new_invoice


def send_invoice_email(invoice: Invoice, subject: str | None = None, body: str | None = None, attach_pdf: bool = True) -> None:
    subtotal, tax_amount, total = calculate_invoice_totals(invoice)
    html = render_template(
        'invoice_pdf.html',
        invoice=invoice,
        subtotal=subtotal,
        tax_amount=tax_amount,
        total=total,
    )
    pdf = generate_pdf(html) if attach_pdf else None

    message = Message(
        subject=subject or f"Invoice #{invoice.id}",
        sender=app.config['MAIL_USERNAME'],
        recipients=[invoice.client_email]
    )
    message.body = body or f"Dear {invoice.client_name},\nPlease find attached your invoice."
    if attach_pdf and pdf:
        message.attach(f"invoice_{invoice.id}.pdf", "application/pdf", pdf)
    mail.send(message)


def process_recurring_schedules(now: datetime | None = None) -> int:
    now = now or datetime.utcnow()
    schedules = RecurringSchedule.query.filter(
        RecurringSchedule.status == 'active',
        RecurringSchedule.next_run_at <= now
    ).all()

    processed = 0
    changes = False
    for schedule in schedules:
        next_run = calculate_next_run(schedule, reference=now)
        new_invoice = clone_invoice_from_schedule(schedule)
        if not new_invoice:
            schedule.status = 'paused'
            changes = True
            continue

        processed += 1
        schedule.next_run_at = next_run or add_frequency(now, schedule.frequency, schedule.interval)
        schedule.updated_at = datetime.utcnow()
        changes = True

        if schedule.auto_send:
            try:
                send_invoice_email(
                    new_invoice,
                    subject=f"Invoice #{new_invoice.id} from recurring schedule",
                    body=f"Hello {new_invoice.client_name},\nYour recurring invoice #{new_invoice.id} is ready.",
                )
                new_invoice.status = 'Sent'
                changes = True
            except Exception as exc:  # pragma: no cover - defensive logging
                app.logger.exception("Failed to auto-send recurring invoice: %s", exc)

    if processed or changes:
        db.session.commit()
    return processed


def process_recurring_reminders(now: datetime | None = None) -> int:
    now = now or datetime.utcnow()
    reminders = RecurringReminder.query.join(RecurringSchedule).filter(
        RecurringSchedule.status == 'active'
    ).all()

    sent = 0
    for reminder in reminders:
        schedule = reminder.schedule
        if not schedule:
            continue
        for execution in schedule.executions:
            invoice = execution.invoice
            if not invoice or invoice.status.lower() == 'paid' or invoice.due_date is None:
                continue

            target_datetime = datetime.combine(invoice.due_date, datetime.min.time()) + timedelta(days=reminder.offset_days)
            if target_datetime > now:
                continue

            already_sent = InvoiceReminderLog.query.filter_by(
                reminder_id=reminder.id,
                invoice_id=invoice.id
            ).first()
            if already_sent:
                continue

            try:
                send_invoice_email(
                    invoice,
                    subject=f"Reminder: Invoice #{invoice.id} is due {invoice.due_date.strftime('%Y-%m-%d')}",
                    body=reminder.message_template or (
                        f"Hi {invoice.client_name},\nThis is a friendly reminder that your invoice "
                        f"#{invoice.id} is due on {invoice.due_date.strftime('%Y-%m-%d')}."
                    )
                )
                db.session.add(InvoiceReminderLog(reminder_id=reminder.id, invoice_id=invoice.id))
                sent += 1
            except Exception as exc:  # pragma: no cover - defensive logging
                app.logger.exception("Failed to send reminder email: %s", exc)

    if sent:
        db.session.commit()
    return sent


def should_run(last_run: datetime | None, interval_seconds: int) -> bool:
    if last_run is None:
        return True
    return (datetime.utcnow() - last_run).total_seconds() >= interval_seconds


def trigger_automations():
    global _last_schedule_run, _last_reminder_run
    if should_run(_last_schedule_run, SCHEDULE_PROCESS_INTERVAL_SECONDS):
        process_recurring_schedules()
        _last_schedule_run = datetime.utcnow()
    if should_run(_last_reminder_run, REMINDER_PROCESS_INTERVAL_SECONDS):
        process_recurring_reminders()
        _last_reminder_run = datetime.utcnow()

# --- Template Helpers ---
@app.context_processor
def inject_utilities():
    return {
        'datetime': datetime,
    }


@app.before_request
def run_automations():
    try:
        trigger_automations()
    except Exception as exc:  # pragma: no cover - safety net
        app.logger.exception("Automation processing failed: %s", exc)


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


@app.route('/invoices')
@login_required
def invoices():
    all_invoices = Invoice.query.order_by(Invoice.created_at.desc()).all()
    return render_template('invoices_list.html', invoices=all_invoices)


@app.route('/recurring')
@login_required
def recurring_overview():
    schedules = RecurringSchedule.query.order_by(RecurringSchedule.next_run_at.asc()).all()
    return render_template('recurring_list.html', schedules=schedules)

@app.route('/create', methods=['GET', 'POST'])
@login_required
def create_invoice():
    if request.method == 'POST':
        descs = request.form.getlist('desc')
        qtys = request.form.getlist('qty')
        rates = request.form.getlist('rate')
        if not (len(descs) == len(qtys) == len(rates)):
            return "Mismatched item fields", 400

        try:
            tax_value = float(request.form['tax'])
        except (KeyError, ValueError):
            flash('Invalid tax percentage.', 'error')
            return redirect(url_for('create_invoice'))

        due_date = parse_date(request.form.get('due_date'))
        if due_date is None:
            due_date = datetime.utcnow().date() + timedelta(days=14)

        currency = (request.form.get('currency') or 'USD').upper()
        if len(currency) != 3:
            currency = 'USD'

        locale_value = request.form.get('locale') or 'en-US'

        invoice = Invoice(
            client_name=request.form['client_name'],
            client_email=request.form['client_email'],
            client_address=request.form['client_address'],
            tax=tax_value,
            status=request.form['status'],
            due_date=due_date,
            currency=currency,
            locale=locale_value,
        )

        db.session.add(invoice)
        db.session.flush()

        try:
            for desc, qty, rate in zip(descs, qtys, rates):
                item = Item(
                    description=desc,
                    quantity=int(qty),
                    rate=float(rate),
                    invoice_id=invoice.id
                )
                db.session.add(item)
        except ValueError:
            db.session.rollback()
            flash('Invalid quantity or rate in line items.', 'error')
            return redirect(url_for('create_invoice'))

        schedule_created = False
        frequency = (request.form.get('recurring_frequency') or '').lower()
        if frequency and frequency != 'none':
            if frequency not in ALLOWED_FREQUENCIES:
                flash('Unsupported recurring frequency.', 'error')
            else:
                try:
                    interval = max(int(request.form.get('recurring_interval') or 1), 1)
                except ValueError:
                    interval = 1
                anchor_date = parse_date(request.form.get('recurring_start_date'), fallback=due_date)
                try:
                    due_after_days = int(request.form.get('recurring_due_after') or 14)
                except ValueError:
                    due_after_days = 14
                initial_next_run = datetime.combine(anchor_date, datetime.min.time())
                now = datetime.utcnow()
                guard = 0
                while initial_next_run <= now and guard < 100:
                    initial_next_run = add_frequency(initial_next_run, frequency, interval)
                    guard += 1

                schedule = RecurringSchedule(
                    invoice_id=invoice.id,
                    frequency=frequency,
                    interval=interval,
                    anchor_date=anchor_date,
                    next_run_at=initial_next_run,
                    auto_send=bool(request.form.get('recurring_auto_send')),
                    due_after_days=due_after_days,
                    status='active'
                )
                db.session.add(schedule)
                db.session.flush()

                reminder_offsets = request.form.get('recurring_reminders', '').strip()
                if reminder_offsets:
                    for token in reminder_offsets.split(','):
                        token = token.strip()
                        if not token:
                            continue
                        try:
                            offset_days = int(token)
                        except ValueError:
                            continue
                        db.session.add(RecurringReminder(schedule_id=schedule.id, offset_days=offset_days))
                schedule_created = True

        db.session.commit()

        if schedule_created:
            flash('Invoice and recurring schedule created successfully.', 'success')
        else:
            flash('Invoice created successfully.', 'success')
        return redirect(url_for('invoices'))
    return render_template('create_invoice.html')

@app.route('/invoice/<int:invoice_id>/pdf')
@login_required
def download_pdf(invoice_id):
    invoice = Invoice.query.get_or_404(invoice_id)
    subtotal, tax_amount, total = calculate_invoice_totals(invoice)
    html = render_template(
        'invoice_pdf.html',
        invoice=invoice,
        subtotal=subtotal,
        tax_amount=tax_amount,
        total=total,
    )
    pdf = generate_pdf(html)
    return send_file(io.BytesIO(pdf), download_name=f'invoice_{invoice.id}.pdf', as_attachment=True)

@app.route('/invoice/<int:invoice_id>/email')
@login_required
def email_invoice(invoice_id):
    invoice = Invoice.query.get_or_404(invoice_id)
    try:
        send_invoice_email(invoice)
        flash('Invoice emailed to client.', 'success')
    except Exception as exc:  # pragma: no cover - defensive logging
        app.logger.exception("Failed to send invoice email: %s", exc)
        flash('Failed to send invoice email. Check server logs.', 'error')
    return redirect(url_for('invoices'))

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
