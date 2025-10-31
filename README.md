# InvoicePro

InvoicePro is a Flask-based web application for creating, managing, and sharing invoices. It helps small teams or freelancers streamline billing, send PDF invoices via email, track payments, and review revenue trends without leaving the browser.

## Features

- **Authentication** ? Register/login/logout with hashed passwords.
- **Invoice builder** ? Add multiple line items, set tax, choose currency/locale, and download or email polished PDFs.
- **Recurring schedules** ? Automatically regenerate invoices on a cadence with optional reminders and auto-send.
- **Payment tracking** ? Record payments, update balances, and mark invoices as paid automatically.
- **Product catalog** ? Store reusable items/services to add to invoices in a click.
- **Attachments** ? Upload receipts or supporting documents per invoice.
- **Reporting** ? Monthly revenue summaries for a quick financial overview.
- **Dark/light themes** ? Animated background, responsive layout, and modern UI components.

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

Attachments are stored under `instance/attachments/` (created automatically).

## Tech Stack

- **Backend**: Python, Flask, Flask-SQLAlchemy, Flask-Login, Flask-Mail
- **Database**: SQLite (configurable for PostgreSQL/MySQL via SQLAlchemy URI)
- **PDF rendering**: WeasyPrint
- **Styling**: Handmade CSS with dark/light mode support

## Development Notes

- The database schema is created on startup (`db.create_all()`) and includes safeguards when new columns are added.
- Background automations (recurring invoices/reminders) are triggered on incoming requests; for production, consider moving them to a dedicated worker.
- For deployments, configure a proper mail provider and secure secret keys.

## Roadmap Ideas

- Hosted file storage (S3/GCS) for attachments
- Integrated payment gateway callbacks
- Multi-organization support and audit logs

## License

This project is licensed under the MIT License ? see [`LICENSE`](LICENSE) for details.