# Data Model Evolution Plan

This document outlines schema additions and refactors needed to support the next wave of features:

- Recurring billing + reminders
- Payment tracking
- Product/service catalog
- Expense attachments
- Organization-level branding

The goal is to lay out incremental changes that can be implemented over multiple migrations without disrupting the existing flows.

## Guiding Principles

- **Backward compatible**: keep current invoice flow operable until new features are rolled out.
- **Scoped migrations**: introduce small, reversible migrations for each concept, avoiding long-running locks on SQLite.
- **Extensible relationships**: prefer associative tables that allow many-to-many expansions (e.g., invoices referencing product templates, organizations owning multiple branding themes).
- **Auditable events**: log any automated action (scheduled send, payment received) for traceability.

## New Core Tables

### `organization`

Represents an account/workspace. One organization can own many users and invoices.

| Column           | Type        | Notes                                             |
|------------------|-------------|---------------------------------------------------|
| id               | Integer PK  |                                                   |
| name             | String(150) | Display name                                      |
| slug             | String(150) | URL-friendly identifier (unique)                  |
| default_locale   | String(10)  | ISO language/locale code                          |
| currency_code    | String(3)   | ISO 4217 (USD, EUR, etc.)                         |
| timezone         | String(64)  | Olson timezone identifier                         |
| created_at       | DateTime    |                                                   |
| updated_at       | DateTime    |                                                   |

### `organization_branding`

Stores branding preferences.

| Column           | Type        | Notes                                             |
|------------------|-------------|---------------------------------------------------|
| id               | Integer PK  |                                                   |
| organization_id  | FK          | -> organization.id                                |
| logo_path        | String      | Stored asset (S3/local)                           |
| primary_color    | String(7)   | HEX color                                         |
| accent_color     | String(7)   | HEX color                                         |
| footer_text      | Text        | Optional invoice footer                           |
| updated_at       | DateTime    |                                                   |

### `user_profile`

Augments the existing `user` table with organization membership (keeping auth behaviour untouched for now).

| Column           | Type        | Notes                                             |
|------------------|-------------|---------------------------------------------------|
| id               | Integer PK  |                                                   |
| user_id          | FK          | -> user.id                                        |
| organization_id  | FK          | -> organization.id                                |
| role             | String(20)  | `admin`, `member`, future roles                   |
| created_at       | DateTime    |                                                   |

### `product_template`

Templates for reusable line items.

| Column           | Type        | Notes                                             |
|------------------|-------------|---------------------------------------------------|
| id               | Integer PK  |                                                   |
| organization_id  | FK          | -> organization.id                                |
| name             | String(150) |                                                   |
| description      | Text        | Optional                                          |
| default_rate     | Numeric     |                                                   |
| default_tax_rate | Numeric     | Optional percentage                               |
| sku              | String(64)  | Optional identifier                               |
| is_active        | Boolean     |                                                   |
| created_at       | DateTime    |                                                   |

### `recurring_schedule`

Defines recurrence for an invoice template.

| Column             | Type        | Notes                                                      |
|--------------------|-------------|------------------------------------------------------------|
| id                 | Integer PK  |                                                            |
| organization_id    | FK          | -> organization.id                                         |
| invoice_id         | FK          | -> invoice.id (base invoice template)                      |
| frequency          | String(20)  | `weekly`, `monthly`, `quarterly`, etc.                     |
| interval           | Integer     | Number of frequency units between invoices                 |
| anchor_date        | Date        | First issue date                                           |
| next_run_at        | DateTime    | Next scheduled generation                                  |
| auto_send          | Boolean     | Whether to send automatically                              |
| status             | String(20)  | `active`, `paused`, `ended`                                |
| created_at         | DateTime    |                                                            |
| updated_at         | DateTime    |                                                            |

### `recurring_reminder`

Optional reminders tied to schedule.

| Column             | Type        | Notes                                                      |
|--------------------|-------------|------------------------------------------------------------|
| id                 | Integer PK  |                                                            |
| schedule_id        | FK          | -> recurring_schedule.id                                   |
| offset_days        | Integer     | e.g., `-3` before due date, `+5` after                     |
| message_template   | Text        | Custom email body                                          |

### `payment`

Tracks payments against invoices.

| Column           | Type        | Notes                                                      |
|------------------|-------------|------------------------------------------------------------|
| id               | Integer PK  |                                                            |
| organization_id  | FK          | -> organization.id                                         |
| invoice_id       | FK          | -> invoice.id                                               |
| provider         | String(30)  | `stripe`, `paypal`, `manual`                               |
| provider_ref     | String(120) | Charge/transaction ID                                      |
| amount           | Numeric     |                                                            |
| currency         | String(3)   | ISO code                                                    |
| status           | String(20)  | `pending`, `succeeded`, `failed`, `refunded`               |
| received_at      | DateTime    |                                                            |
| created_at       | DateTime    |                                                            |

### `invoice_attachment`

Stores supporting documents per invoice.

| Column           | Type        | Notes                                                      |
|------------------|-------------|------------------------------------------------------------|
| id               | Integer PK  |                                                            |
| invoice_id       | FK          | -> invoice.id                                               |
| organization_id  | FK          | -> organization.id                                         |
| filename         | String      | Original name                                               |
| storage_path     | String      | Absolute/relative path                                     |
| uploaded_by      | FK          | -> user.id                                                  |
| uploaded_at      | DateTime    |                                                            |

### `invoice_audit_event`

Captures key actions for traceability.

| Column           | Type        | Notes                                                      |
|------------------|-------------|------------------------------------------------------------|
| id               | Integer PK  |                                                            |
| invoice_id       | FK          | -> invoice.id                                               |
| organization_id  | FK          | -> organization.id                                         |
| actor_id         | FK (nullable)| -> user.id                                                 |
| event_type       | String(50)  | `generated`, `sent`, `payment_received`, etc.               |
| payload          | JSON/Text   | Additional metadata                                        |
| created_at       | DateTime    |                                                            |

### `notification_subscription`

Configures email/Slack notifications.

| Column           | Type        | Notes                                                      |
|------------------|-------------|------------------------------------------------------------|
| id               | Integer PK  |                                                            |
| organization_id  | FK          | -> organization.id                                         |
| channel          | String(20)  | `email`, `slack`                                           |
| destination      | String      | Email address, webhook URL                                 |
| event_type       | String(50)  | `invoice_created`, `payment_received`, etc.                |
| is_active        | Boolean     |                                                            |
| created_at       | DateTime    |                                                            |

## Existing Table Adjustments

- `invoice`
  - add `organization_id`
  - add `due_date`, `currency`, `locale`, `branding_snapshot`, `source_type` (`manual`, `recurring`)

- `item`
  - add `product_template_id` (nullable) to reference catalog items

- `user`
  - remove or deprecate `email` uniqueness (move to profile). Instead, enforce uniqueness per organization in `user_profile`.

## Migration Phases

1. **Organization groundwork**
   - Add `organization` table
   - Add `organization_id` FK to `user` and populate with default org for current data
   - Seed initial branding row per organization

2. **Product catalog + invoice affiliation**
   - Add `product_template`
   - Add `organization_id`, `currency`, `locale`, `due_date` to `invoice`
   - Backfill existing invoices with defaults (e.g., `USD`, `en-US`, due date = created_at + 14 days)

3. **Recurring schedules & reminders**
   - Create `recurring_schedule`, `recurring_reminder`
   - Update invoice creation flow to optionally derive from a schedule

4. **Payments & attachments**
   - Create `payment`, `invoice_attachment`
   - Wire UI to allow uploads (stored locally for now) and mark invoices as paid when payment added

5. **Audit trail & notifications**
   - Create `invoice_audit_event`, `notification_subscription`
   - Emit events on invoice creation, send, payment; later pipe to notifications

6. **Localization & branding**
   - Ensure templates accept locale-specific formatting and load organization branding snapshot when rendering PDFs/emails

## Next Steps

- Validate the entity list against feature requirements & adjust scope where needed.
- Draft Alembic/Flask-Migrate migrations for Phase 1.
- Update ORM models (`models.py`, `users.py`) to incorporate new relationships gradually.
- Create seed scripts/tests to ensure defaults exist for new tables.
