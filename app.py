import os
import io
import json
from datetime import datetime, date, timedelta
from flask import Flask, render_template, request, redirect, send_file, url_for, flash, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, logout_user, login_required, current_user, UserMixin
from flask_mail import Mail, Message
from werkzeug.security import generate_password_hash, check_password_hash
from weasyprint import HTML
from sqlalchemy import inspect, text
from sqlalchemy.exc import NoSuchTableError
from dateutil.relativedelta import relativedelta
from werkzeug.utils import secure_filename
from babel.numbers import format_currency as babel_format_currency
from babel.dates import format_date as babel_format_date

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
app.config['UPLOAD_FOLDER'] = os.path.join(app.instance_path, 'attachments')
app.config['BRANDING_UPLOAD_FOLDER'] = os.path.join(app.root_path, 'static', 'branding')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['BRANDING_UPLOAD_FOLDER'], exist_ok=True)

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
    branding_snapshot = db.Column(db.Text, nullable=True)

    items = db.relationship('Item', backref='invoice', lazy=True, cascade="all, delete-orphan")
    child_invoices = db.relationship(
        'Invoice',
        cascade="all",
        backref=db.backref('parent_invoice', remote_side=[id]),
        lazy='dynamic'
    )
    schedules = db.relationship('RecurringSchedule', backref='template_invoice', lazy=True, cascade="all, delete-orphan")
    payments = db.relationship('Payment', backref='invoice', lazy=True, cascade="all, delete-orphan")
    attachments = db.relationship('InvoiceAttachment', backref='invoice', lazy=True, cascade="all, delete-orphan")
    audit_events = db.relationship('InvoiceAuditEvent', backref='invoice', lazy=True, cascade="all, delete-orphan")

class Item(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    description = db.Column(db.String(200), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    rate = db.Column(db.Float, nullable=False)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoice.id'), nullable=False)


class ProductTemplate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=True)
    default_rate = db.Column(db.Float, nullable=False, default=0.0)
    default_tax_rate = db.Column(db.Float, nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Branding(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    logo_filename = db.Column(db.String(255), nullable=True)
    primary_color = db.Column(db.String(7), nullable=True)
    accent_color = db.Column(db.String(7), nullable=True)
    footer_text = db.Column(db.Text, nullable=True)
    default_locale = db.Column(db.String(10), nullable=False, default='en-US')
    default_currency = db.Column(db.String(3), nullable=False, default='USD')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)



class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoice.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    currency = db.Column(db.String(3), nullable=False, default='USD')
    provider = db.Column(db.String(50), nullable=False, default='manual')
    reference = db.Column(db.String(120), nullable=True)
    status = db.Column(db.String(20), nullable=False, default='succeeded')
    received_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class InvoiceAttachment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoice.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    storage_path = db.Column(db.String(500), nullable=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)


class InvoiceAuditEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoice.id'), nullable=False)
    event_type = db.Column(db.String(50), nullable=False)
    message = db.Column(db.Text, nullable=True)
    payload = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class NotificationSubscription(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    channel = db.Column(db.String(20), nullable=False)
    destination = db.Column(db.String(255), nullable=False)
    event_type = db.Column(db.String(50), nullable=False, default='invoice_created')
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


def serialize_branding(branding: Branding | None) -> dict:
    if not branding:
        return {
            'name': 'InvoicePro',
            'logo_filename': None,
            'primary_color': '#4f46e5',
            'accent_color': '#10b981',
            'footer_text': 'Thank you for your business!',
        }
    return {
        'name': branding.name or 'InvoicePro',
        'logo_filename': branding.logo_filename,
        'primary_color': branding.primary_color or '#4f46e5',
        'accent_color': branding.accent_color or '#10b981',
        'footer_text': branding.footer_text or 'Thank you for your business!',
        'default_locale': branding.default_locale or 'en-US',
        'default_currency': branding.default_currency or 'USD',
    }


def get_active_branding() -> Branding:
    branding = Branding.query.order_by(Branding.id.asc()).first()
    if not branding:
        branding = Branding(name='InvoicePro')
        db.session.add(branding)
        db.session.commit()
    return branding


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


def ensure_column(table_name, column_name, ddl, default=None):
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


def ensure_invoice_columns():
    ensure_column('invoice', 'due_date', 'DATE')
    ensure_column('invoice', 'currency', "VARCHAR(3) DEFAULT 'USD'", 'USD')
    ensure_column('invoice', 'locale', "VARCHAR(10) DEFAULT 'en-US'", 'en-US')
    ensure_column('invoice', 'source_type', "VARCHAR(20) DEFAULT 'manual'", 'manual')
    ensure_column('invoice', 'parent_invoice_id', 'INTEGER')
    ensure_column('invoice', 'branding_snapshot', 'TEXT')


def ensure_branding_columns():
    ensure_column('branding', 'logo_filename', 'VARCHAR(255)')
    ensure_column('branding', 'primary_color', 'VARCHAR(7)')
    ensure_column('branding', 'accent_color', 'VARCHAR(7)')
    ensure_column('branding', 'footer_text', 'TEXT')
    ensure_column('branding', 'default_locale', "VARCHAR(10) DEFAULT 'en-US'", 'en-US')
    ensure_column('branding', 'default_currency', "VARCHAR(3) DEFAULT 'USD'", 'USD')


# Initialize Database
with app.app_context():
    # Ensure schema is up-to-date
    ensure_invoice_columns()
    ensure_branding_columns()
    db.create_all()

# --- User Loader ---
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- PDF Generation ---
def generate_pdf(html_content):
    return HTML(string=html_content, base_url=request.host_url).write_pdf()


def calculate_invoice_totals(invoice):
    subtotal = sum(item.quantity * item.rate for item in invoice.items)
    tax_amount = subtotal * (invoice.tax / 100)
    total = subtotal + tax_amount
    return subtotal, tax_amount, total


def calculate_invoice_balance(invoice: Invoice) -> tuple[float, float]:
    subtotal, tax_amount, total = calculate_invoice_totals(invoice)
    paid = sum(payment.amount for payment in invoice.payments if payment.status.lower() == 'succeeded')
    return total, max(total - paid, 0.0)


def update_invoice_payment_status(invoice: Invoice) -> None:
    total, balance = calculate_invoice_balance(invoice)
    if balance <= 0 and invoice.status.lower() != 'paid':
        invoice.status = 'Paid'
    elif balance > 0 and invoice.status.lower() == 'paid':
        invoice.status = 'Unpaid'


def allowed_attachment(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_ATTACHMENT_EXTENSIONS


def allowed_logo(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_LOGO_EXTENSIONS


def format_currency_locale(amount: float, currency: str, locale: str) -> str:
    try:
        return babel_format_currency(amount, currency, locale=locale.replace('-', '_'))
    except Exception:  # pragma: no cover - fallback path
        return f"{currency} {amount:,.2f}"


def format_date_locale(value: date | datetime, locale: str) -> str:
    try:
        if isinstance(value, datetime):
            value = value.date()
        return babel_format_date(value, format='long', locale=locale.replace('-', '_'))
    except Exception:  # pragma: no cover
        return value.strftime('%Y-%m-%d') if hasattr(value, 'strftime') else str(value)


def load_invoice_branding(invoice: Invoice) -> dict:
    defaults = serialize_branding(get_active_branding())
    if invoice.branding_snapshot:
        try:
            data = json.loads(invoice.branding_snapshot)
            for key, value in data.items():
                if value not in (None, ''):
                    defaults[key] = value
        except json.JSONDecodeError:
            pass
    return defaults


def record_audit_event(invoice: Invoice, event_type: str, message: str = '', payload: dict | None = None) -> InvoiceAuditEvent:
    if event_type not in AUDIT_EVENT_TYPES:
        app.logger.warning('Unknown audit event type: %s', event_type)
    event = InvoiceAuditEvent(
        invoice_id=invoice.id,
        event_type=event_type,
        message=message,
        payload=json.dumps(payload) if payload else None,
    )
    db.session.add(event)
    db.session.flush()
    dispatch_notifications(event)
    return event


def dispatch_notifications(event: InvoiceAuditEvent) -> None:
    subscriptions = NotificationSubscription.query.filter(
        NotificationSubscription.is_active.is_(True),
        NotificationSubscription.event_type.in_([event.event_type, 'all'])
    ).all()
    if not subscriptions:
        return
    summary = event.message or f"Event '{event.event_type}' recorded for invoice #{event.invoice_id}."
    for subscription in subscriptions:
        if subscription.channel == 'email':
            app.logger.info("[Notification::Email] -> %s | %s", subscription.destination, summary)
        elif subscription.channel == 'slack':
            app.logger.info("[Notification::Slack] -> %s | %s", subscription.destination, summary)
        else:
            app.logger.info("[Notification::%s] -> %s | %s", subscription.channel, subscription.destination, summary)


ALLOWED_FREQUENCIES = {'daily', 'weekly', 'monthly', 'yearly'}
SCHEDULE_PROCESS_INTERVAL_SECONDS = 60
REMINDER_PROCESS_INTERVAL_SECONDS = 120
_last_schedule_run = None
_last_reminder_run = None
ALLOWED_ATTACHMENT_EXTENSIONS = {
    'pdf', 'png', 'jpg', 'jpeg', 'gif', 'doc', 'docx', 'xls', 'xlsx', 'csv', 'txt', 'zip'
}
ATTACHMENT_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
ALLOWED_LOGO_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'svg'}
LOGO_MAX_BYTES = 2 * 1024 * 1024  # 2 MB
AUDIT_EVENT_TYPES = [
    'invoice_created',
    'invoice_auto_generated',
    'invoice_email_sent',
    'payment_recorded',
    'attachment_uploaded',
    'attachment_deleted',
    'reminder_sent',
]


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

    snapshot_data = template.branding_snapshot or json.dumps(serialize_branding(get_active_branding()))

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
        due_date=(datetime.utcnow() + timedelta(days=schedule.due_after_days)).date(),
        branding_snapshot=snapshot_data,
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
    branding = load_invoice_branding(invoice)
    html = render_template(
        'invoice_pdf.html',
        invoice=invoice,
        subtotal=subtotal,
        tax_amount=tax_amount,
        total=total,
        branding=branding,
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
    record_audit_event(
        invoice,
        'invoice_email_sent',
        message=f"Invoice emailed to {invoice.client_email}.",
        payload={'subject': message.subject},
    )


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
        record_audit_event(
            new_invoice,
            'invoice_auto_generated',
            message=f"Invoice #{new_invoice.id} generated from schedule #{schedule.id}.",
            payload={'schedule_id': schedule.id},
        )
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
                record_audit_event(
                    invoice,
                    'reminder_sent',
                    message=f"Reminder email sent ({reminder.offset_days} day offset).",
                    payload={'offset_days': reminder.offset_days},
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
    branding = serialize_branding(get_active_branding())
    css_vars = {
        '--primary': branding['primary_color'],
        '--accent': branding['accent_color'],
        '--primary-dark': branding['primary_color'],
    }
    branding_style = '; '.join(f"{key}: {value}" for key, value in css_vars.items())
    return {
        'datetime': datetime,
        'active_branding': branding,
        'branding_style': branding_style,
        'format_money': format_currency_locale,
        'format_date_locale': format_date_locale,
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


@app.route('/catalog', methods=['GET', 'POST'])
@login_required
def catalog():
    if request.method == 'POST':
        name = (request.form.get('name') or '').strip()
        description = (request.form.get('description') or '').strip() or None
        default_rate_raw = request.form.get('default_rate') or '0'
        default_tax_raw = request.form.get('default_tax_rate') or None

        if not name:
            flash('Name is required for catalog items.', 'error')
            return redirect(url_for('catalog'))

        try:
            default_rate = float(default_rate_raw)
        except ValueError:
            flash('Default rate must be numeric.', 'error')
            return redirect(url_for('catalog'))

        try:
            default_tax_rate = float(default_tax_raw) if default_tax_raw else None
        except ValueError:
            flash('Default tax must be numeric.', 'error')
            return redirect(url_for('catalog'))

        template = ProductTemplate(
            name=name,
            description=description,
            default_rate=default_rate,
            default_tax_rate=default_tax_rate,
            is_active=True
        )
        db.session.add(template)
        db.session.commit()
        flash('Catalog item saved.', 'success')
        return redirect(url_for('catalog'))

    templates = ProductTemplate.query.order_by(ProductTemplate.is_active.desc(), ProductTemplate.name.asc()).all()
    return render_template('catalog.html', templates=templates)


@app.route('/catalog/<int:template_id>/toggle', methods=['POST'])
@login_required
def toggle_catalog_template(template_id):
    template = ProductTemplate.query.get_or_404(template_id)
    template.is_active = not template.is_active
    db.session.commit()
    flash(f"Catalog item '{template.name}' is now {'active' if template.is_active else 'inactive'}.", 'success')
    return redirect(url_for('catalog'))


@app.route('/catalog/<int:template_id>/delete', methods=['POST'])
@login_required
def delete_catalog_template(template_id):
    template = ProductTemplate.query.get_or_404(template_id)
    db.session.delete(template)
    db.session.commit()
    flash('Catalog item deleted.', 'success')
    return redirect(url_for('catalog'))

@app.route('/branding', methods=['GET', 'POST'])
@login_required
def branding_settings():
    branding = get_active_branding()
    if request.method == 'POST':
        if request.form.get('action') == 'delete_logo':
            if branding.logo_filename:
                logo_path = os.path.join(app.config['BRANDING_UPLOAD_FOLDER'], branding.logo_filename)
                try:
                    if os.path.exists(logo_path):
                        os.remove(logo_path)
                except OSError as exc:  # pragma: no cover
                    app.logger.warning('Failed to delete branding logo: %s', exc)
                branding.logo_filename = None
                db.session.commit()
                flash('Logo removed.', 'success')
            return redirect(url_for('branding_settings'))

        branding.name = (request.form.get('name') or branding.name or 'InvoicePro').strip() or 'InvoicePro'
        branding.primary_color = (request.form.get('primary_color') or '#4f46e5').strip() or '#4f46e5'
        if branding.primary_color and not branding.primary_color.startswith('#'):
            branding.primary_color = f"#{branding.primary_color}"
        branding.accent_color = (request.form.get('accent_color') or '#10b981').strip() or '#10b981'
        if branding.accent_color and not branding.accent_color.startswith('#'):
            branding.accent_color = f"#{branding.accent_color}"
        branding.footer_text = (request.form.get('footer_text') or '').strip() or 'Thank you for your business!'
        branding.default_locale = (request.form.get('default_locale') or 'en-US').strip() or 'en-US'
        branding.default_currency = (request.form.get('default_currency') or 'USD').strip().upper() or 'USD'

        upload = request.files.get('logo')
        if upload and upload.filename:
            filename = secure_filename(upload.filename)
            if filename:
                if not allowed_logo(filename):
                    flash('Logo must be an image (png, jpg, jpeg, gif, svg).', 'error')
                    return redirect(url_for('branding_settings'))
                if upload.content_length and upload.content_length > LOGO_MAX_BYTES:
                    flash('Logo file too large (limit 2MB).', 'error')
                    return redirect(url_for('branding_settings'))
                storage_name = f"logo_{int(datetime.utcnow().timestamp())}_{filename}"
                storage_path = os.path.join(app.config['BRANDING_UPLOAD_FOLDER'], storage_name)
                upload.save(storage_path)
                if branding.logo_filename:
                    old_path = os.path.join(app.config['BRANDING_UPLOAD_FOLDER'], branding.logo_filename)
                    try:
                        if os.path.exists(old_path):
                            os.remove(old_path)
                    except OSError:
                        pass
                branding.logo_filename = storage_name

        db.session.commit()
        flash('Branding updated.', 'success')
        return redirect(url_for('branding_settings'))

    preview = serialize_branding(branding)
    return render_template('branding.html', branding=branding, preview=preview)


@app.route('/activity')
@login_required
def activity_dashboard():
    recent_events = InvoiceAuditEvent.query.order_by(InvoiceAuditEvent.created_at.desc()).limit(50).all()
    stats = db.session.query(
        InvoiceAuditEvent.event_type,
        db.func.count(InvoiceAuditEvent.id)
    ).group_by(InvoiceAuditEvent.event_type).all()
    invoice_stats = db.session.query(
        Invoice.status,
        db.func.count(Invoice.id)
    ).group_by(Invoice.status).all()
    return render_template(
        'audit_dashboard.html',
        events=recent_events,
        stats=stats,
        invoice_stats=invoice_stats,
    )


@app.route('/notifications', methods=['GET', 'POST'])
@login_required
def notification_settings():
    if request.method == 'POST':
        action = request.form.get('action', 'create')
        if action == 'delete':
            subscription = NotificationSubscription.query.get_or_404(int(request.form['subscription_id']))
            db.session.delete(subscription)
            db.session.commit()
            flash('Notification subscription deleted.', 'success')
            return redirect(url_for('notification_settings'))
        if action == 'toggle':
            subscription = NotificationSubscription.query.get_or_404(int(request.form['subscription_id']))
            subscription.is_active = not subscription.is_active
            db.session.commit()
            flash(f"Subscription {'activated' if subscription.is_active else 'paused'}.", 'success')
            return redirect(url_for('notification_settings'))

        channel = (request.form.get('channel') or 'email').strip()
        destination = (request.form.get('destination') or '').strip()
        event_type = (request.form.get('event_type') or 'invoice_created').strip()
        if not destination:
            flash('Destination is required.', 'error')
            return redirect(url_for('notification_settings'))
        if event_type not in AUDIT_EVENT_TYPES + ['all']:
            flash('Unknown event type.', 'error')
            return redirect(url_for('notification_settings'))
        subscription = NotificationSubscription(
            channel=channel,
            destination=destination,
            event_type=event_type,
            is_active=True,
        )
        db.session.add(subscription)
        db.session.commit()
        flash('Notification subscription saved.', 'success')
        return redirect(url_for('notification_settings'))

    subscriptions = NotificationSubscription.query.order_by(NotificationSubscription.created_at.desc()).all()
    return render_template(
        'notifications.html',
        subscriptions=subscriptions,
        event_types=AUDIT_EVENT_TYPES,
    )


@app.route('/admin/users', methods=['GET', 'POST'])
@login_required
def manage_users():
    if current_user.username != 'admin':
        abort(403)

    users = User.query.order_by(User.username.asc()).all()
    if request.method == 'POST':
        username = request.form.get('username')
        raw_password = request.form.get('raw_password')
        password_hash = request.form.get('password_hash')
        user = User.query.filter_by(username=username).first()
        if not user:
            flash('User not found.', 'error')
            return redirect(url_for('manage_users'))

        if raw_password:
            user.set_password(raw_password)
            flash(f"Password updated for {username}.", 'success')
        elif password_hash:
            user.password_hash = password_hash.strip()
            flash(f"Password hash replaced for {username}.", 'success')
        else:
            flash('Provide a new password or password hash.', 'error')
            return redirect(url_for('manage_users'))

        db.session.commit()
        return redirect(url_for('manage_users'))

    return render_template('admin_users.html', users=users)


@app.route('/create', methods=['GET', 'POST'])
@login_required
def create_invoice():
    product_templates = ProductTemplate.query.filter_by(is_active=True).order_by(ProductTemplate.name.asc()).all()
    branding_defaults = serialize_branding(get_active_branding())
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

        currency = (request.form.get('currency') or branding_defaults['default_currency']).upper()
        if len(currency) != 3:
            currency = 'USD'

        locale_value = request.form.get('locale') or branding_defaults['default_locale']

        invoice = Invoice(
            client_name=request.form['client_name'],
            client_email=request.form['client_email'],
            client_address=request.form['client_address'],
            tax=tax_value,
            status=request.form['status'],
            due_date=due_date,
            currency=currency,
            locale=locale_value,
            branding_snapshot=json.dumps(branding_defaults),
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

        total_value = calculate_invoice_totals(invoice)[2]
        record_audit_event(
            invoice,
            'invoice_created',
            message=f"Invoice #{invoice.id} created for {invoice.client_name}.",
            payload={'total': total_value, 'status': invoice.status},
        )
        db.session.commit()

        if schedule_created:
            flash('Invoice and recurring schedule created successfully.', 'success')
        else:
            flash('Invoice created successfully.', 'success')
        return redirect(url_for('invoices'))
    return render_template('create_invoice.html', product_templates=product_templates, branding_defaults=branding_defaults)

@app.route('/invoice/<int:invoice_id>/pdf')
@login_required
def download_pdf(invoice_id):
    invoice = Invoice.query.get_or_404(invoice_id)
    subtotal, tax_amount, total = calculate_invoice_totals(invoice)
    branding = load_invoice_branding(invoice)
    html = render_template(
        'invoice_pdf.html',
        invoice=invoice,
        subtotal=subtotal,
        tax_amount=tax_amount,
        total=total,
        branding=branding,
    )
    pdf = generate_pdf(html)
    return send_file(io.BytesIO(pdf), download_name=f'invoice_{invoice.id}.pdf', as_attachment=True)

@app.route('/invoice/<int:invoice_id>/email')
@login_required
def email_invoice(invoice_id):
    invoice = Invoice.query.get_or_404(invoice_id)
    try:
        send_invoice_email(invoice)
        db.session.commit()
        flash('Invoice emailed to client.', 'success')
    except Exception as exc:  # pragma: no cover - defensive logging
        app.logger.exception("Failed to send invoice email: %s", exc)
        flash('Failed to send invoice email. Check server logs.', 'error')
    return redirect(url_for('invoices'))


@app.route('/invoice/<int:invoice_id>/payment', methods=['GET', 'POST'])
@login_required
def record_payment(invoice_id):
    invoice = Invoice.query.get_or_404(invoice_id)
    total_due, balance = calculate_invoice_balance(invoice)

    if request.method == 'POST':
        try:
            amount = float(request.form.get('amount') or 0)
        except ValueError:
            flash('Invalid payment amount.', 'error')
            return redirect(url_for('record_payment', invoice_id=invoice.id))

        if amount <= 0:
            flash('Payment amount must be greater than zero.', 'error')
            return redirect(url_for('record_payment', invoice_id=invoice.id))

        provider = request.form.get('provider', 'manual') or 'manual'
        reference = request.form.get('reference') or None
        status = request.form.get('status', 'succeeded') or 'succeeded'

        received_at_raw = request.form.get('received_at')
        received_at = datetime.utcnow()
        if received_at_raw:
            try:
                received_at = datetime.strptime(received_at_raw, '%Y-%m-%d')
            except ValueError:
                flash('Invalid received date format. Use YYYY-MM-DD.', 'error')
                return redirect(url_for('record_payment', invoice_id=invoice.id))

        payment = Payment(
            invoice_id=invoice.id,
            amount=amount,
            currency=invoice.currency,
            provider=provider,
            reference=reference,
            status=status,
            received_at=received_at
        )
        db.session.add(payment)

        update_invoice_payment_status(invoice)
        record_audit_event(
            invoice,
            'payment_recorded',
            message=f"Payment of {amount:.2f} {invoice.currency} recorded via {provider}.",
            payload={'amount': amount, 'status': status, 'provider': provider, 'reference': reference},
        )
        try:
            db.session.commit()
            flash('Payment recorded successfully.', 'success')
        except Exception as exc:  # pragma: no cover
            db.session.rollback()
            app.logger.exception("Failed to record payment: %s", exc)
            flash('Failed to record payment. Please try again.', 'error')
            return redirect(url_for('record_payment', invoice_id=invoice.id))

        return redirect(url_for('invoices'))

    return render_template(
        'record_payment.html',
        invoice=invoice,
        total_due=total_due,
        balance=balance,
    )

@app.route('/invoice/<int:invoice_id>', methods=['GET', 'POST'])
@login_required
def invoice_detail(invoice_id):
    invoice = Invoice.query.get_or_404(invoice_id)
    total_due, balance = calculate_invoice_balance(invoice)
    branding = load_invoice_branding(invoice)
    events = InvoiceAuditEvent.query.filter_by(invoice_id=invoice.id).order_by(InvoiceAuditEvent.created_at.desc()).limit(20).all()

    if request.method == 'POST':
        if 'attachment' not in request.files:
            flash('Select a file to upload.', 'error')
            return redirect(url_for('invoice_detail', invoice_id=invoice.id))
        upload = request.files['attachment']
        if not upload or upload.filename == '':
            flash('Select a file to upload.', 'error')
            return redirect(url_for('invoice_detail', invoice_id=invoice.id))

        filename = secure_filename(upload.filename)
        if not filename:
            flash('Invalid file name.', 'error')
            return redirect(url_for('invoice_detail', invoice_id=invoice.id))
        if not allowed_attachment(filename):
            flash('Unsupported file type.', 'error')
            return redirect(url_for('invoice_detail', invoice_id=invoice.id))

        if request.content_length and request.content_length > ATTACHMENT_MAX_BYTES:
            flash('File too large. Limit is 10MB.', 'error')
            return redirect(url_for('invoice_detail', invoice_id=invoice.id))

        timestamp = datetime.utcnow().strftime('%Y%m%d%H%M%S')
        stored_filename = f"{invoice.id}_{timestamp}_{filename}"
        storage_path = os.path.join(app.config['UPLOAD_FOLDER'], stored_filename)
        upload.save(storage_path)

        attachment = InvoiceAttachment(
            invoice_id=invoice.id,
            filename=filename,
            storage_path=storage_path
        )
        db.session.add(attachment)
        record_audit_event(
            invoice,
            'attachment_uploaded',
            message=f"Attachment '{filename}' uploaded.",
            payload={'filename': filename},
        )
        db.session.commit()
        flash('Attachment uploaded.', 'success')
        return redirect(url_for('invoice_detail', invoice_id=invoice.id))

    return render_template(
        'invoice_detail.html',
        invoice=invoice,
        total_due=total_due,
        balance=balance,
        branding=branding,
        events=events,
    )


@app.route('/invoice/<int:invoice_id>/attachment/<int:attachment_id>/download')
@login_required
def download_attachment(invoice_id, attachment_id):
    attachment = InvoiceAttachment.query.filter_by(id=attachment_id, invoice_id=invoice_id).first_or_404()
    if not os.path.exists(attachment.storage_path):
        flash('Attachment file not found on server.', 'error')
        return redirect(url_for('invoice_detail', invoice_id=invoice_id))
    return send_file(attachment.storage_path, as_attachment=True, download_name=attachment.filename)


@app.route('/invoice/<int:invoice_id>/attachment/<int:attachment_id>/delete', methods=['POST'])
@login_required
def delete_attachment(invoice_id, attachment_id):
    attachment = InvoiceAttachment.query.filter_by(id=attachment_id, invoice_id=invoice_id).first_or_404()
    try:
        if os.path.exists(attachment.storage_path):
            os.remove(attachment.storage_path)
    except OSError as exc:  # pragma: no cover - cleanup safety
        app.logger.warning('Failed to delete attachment file: %s', exc)
    db.session.delete(attachment)
    record_audit_event(
        attachment.invoice,
        'attachment_deleted',
        message=f"Attachment '{attachment.filename}' deleted.",
        payload={'filename': attachment.filename},
    )
    db.session.commit()
    flash('Attachment removed.', 'success')
    return redirect(url_for('invoice_detail', invoice_id=invoice_id))


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