# InvoicePro

InvoicePro is a Flask-based web application for creating, scheduling, and sharing invoices. It helps small teams and freelancers automate billing, send PDF invoices by email, track payments, and review revenue trends?all from one dashboard.

## Features

- **Authentication** - Register/login/logout with hashed passwords.
- **Invoice builder** - Add as many line items as you need, set tax, choose currency/locale, and export or email polished PDFs.
- **Recurring schedules** - Automatically regenerate invoices on a cadence with optional reminders and auto-send.
- **Payment tracking** - Record payments, update balances, and mark invoices as paid automatically.
- **Product catalog** - Store reusable services or products for quick invoice creation.
- **Attachments** - Upload receipts or other supporting documents per invoice.
- **Branding & locales** - Customize logo, colors, footer, and default locale/currency; snapshots travel with each invoice.
- **Reporting** - Monthly revenue summaries for a quick financial overview.
- **Dark/light themes** - Animated background, responsive layout, and modern UI components.

## Quick Start

1. **Install dependencies**

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Run the app**

   ```bash
   FLASK_APP=app.py flask run
   ```

   By default the server listens on `http://127.0.0.1:5000`.

3. **Create an admin user (optional)**

   Visit `/init-admin` once to seed the default admin account (`admin` / `adminpass`).

## Configuration

Environment variables customize behavior:

| Variable | Description | Default |
|----------|-------------|---------|
| `SECRET_KEY` | Flask session key | `supersecretkey` |
| `SQLALCHEMY_DATABASE_URI` | Database path/URI | `sqlite:///database.db` |
| `MAIL_SERVER` / `MAIL_PORT` | SMTP server settings | `smtp.gmail.com` / `587` |
| `MAIL_USERNAME` / `MAIL_PASSWORD` | Mail credentials | placeholder values |

Attachments live under `instance/attachments/`; branding logos live under `static/branding/`.

## Tech Stack

- **Backend**: Python, Flask, Flask-SQLAlchemy, Flask-Login, Flask-Mail
- **Database**: SQLite (configurable for PostgreSQL/MySQL via SQLAlchemy URI)
- **PDF rendering**: WeasyPrint
- **Styling**: Handmade CSS with dynamic theming
- **Localization**: Babel for currency/date formatting

## Development Notes

- The schema is bootstrapped on startup (`db.create_all()`) with light-touch migrations for new columns.
- Recurring invoices and reminders run inside a lightweight scheduler triggered per request?consider moving to a worker for heavy traffic.
- Configure real SMTP credentials and a unique `SECRET_KEY` before deploying.

## Roadmap Ideas

- Hosted file storage (S3/GCS) for attachments and branding assets
- Integrated payment gateway callbacks
- Multi-organization support and audit logging

## License

This project is licensed under the MIT License ? see [`LICENSE`](LICENSE) for details.