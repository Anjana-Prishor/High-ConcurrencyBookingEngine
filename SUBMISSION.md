# High-Concurrency Movie Ticket Booking

**Database:** MySQL 8.0.16+ with InnoDB  
**Time convention:** store `DATETIME(6)` show/hold timestamps in UTC; convert to the theatre's IANA timezone for display.

## Scenario and behavior

For a theatre, show today and the next six theatre-local dates. After a date is selected, list scheduled movies, screens, local show start/end times, and currently available seat counts. Seats are held transactionally; payment webhook events have a unique provider/event key so duplicate deliveries do not repeat booking effects.

## Files and execution

- `sql/schema.sql`: creates the database, all tables, indexes, constraints, and triggers.
- `sql/seed.sql`: inserts the example theatre, screen, physical seats, movies, shows, customer, and per-show inventory.
- `sql/queries.sql`: executable P2 query plus MySQL hold, expiry, and webhook query patterns.
- `submission/High-Concurrency-Booking-Database.pdf`: formatted submission document.

Run with a MySQL 8.0.16+ client:

```sh
mysql -u root -p < sql/schema.sql
mysql -u root -p < sql/seed.sql
mysql -u root -p < sql/queries.sql
```

The P2 query uses named session variables at the top of `sql/queries.sql`. Change `@theatre_id` and `@local_date` for another request. MySQL named time zones (such as `Asia/Kolkata`) must be loaded into the MySQL time-zone tables for `CONVERT_TZ` to return values.

## Entities and attributes

| Table | Attributes and keys | Purpose |
|---|---|---|
| `movies` | `movie_id` CHAR(36) PK; `title` VARCHAR(200); `language` VARCHAR(60); `duration_mins` SMALLINT UNSIGNED; `rating` VARCHAR(20) nullable; `created_at` DATETIME(6) | Movie catalogue. |
| `theatres` | `theatre_id` CHAR(36) PK; `name` VARCHAR(160); `address` VARCHAR(500); `timezone` VARCHAR(64) | Venue and theatre-local date/time conversion. |
| `screens` | `screen_id` CHAR(36) PK; `theatre_id` CHAR(36) FK; `name` VARCHAR(80); UNIQUE (`theatre_id`, `name`) | Theatre auditorium. |
| `seats` | `seat_id` CHAR(36) PK; `screen_id` CHAR(36) FK; `row_label` VARCHAR(8); `seat_number` SMALLINT UNSIGNED; `seat_type` ENUM; UNIQUE (`screen_id`, `row_label`, `seat_number`) | Physical seating plan. |
| `shows` | `show_id` CHAR(36) PK; `movie_id` CHAR(36) FK; `screen_id` CHAR(36) FK; `starts_at`, `ends_at` DATETIME(6) UTC; `status` ENUM; `currency` CHAR(3); UNIQUE (`screen_id`, `starts_at`) | One movie screening on one screen. Triggers serialize schedule writes on the screen and reject overlapping scheduled intervals. |
| `customers` | `customer_id` CHAR(36) PK; `display_name` VARCHAR(160); `email` VARCHAR(254) UNIQUE; `created_at` DATETIME(6) | Booking customer. |
| `bookings` | `booking_id` CHAR(36) PK; `customer_id` CHAR(36) FK; `show_id` CHAR(36) FK; `status` ENUM; `created_at`, `expires_at` DATETIME(6) | Hold and booking lifecycle. Amount is derived from seat price snapshots; currency is on the show. |
| `show_seats` | (`show_id`, `seat_id`) composite PK and FKs; `price_amount` DECIMAL(12,2); `state` ENUM; `hold_expires_at` DATETIME(6) nullable | One row per seat per show and the seat-locking boundary. A trigger verifies the seat belongs to the show's screen. |
| `booking_seats` | (`booking_id`, `seat_id`) composite PK; both FKs; `price_amount` DECIMAL(12,2) | Booking-to-seat association and historical price snapshot. A trigger verifies the seat has inventory for the booking's show. |
| `payments` | `payment_id` CHAR(36) PK; `booking_id` FK; `provider`; nullable `provider_payment_id`; `idempotency_key`; `amount`; `status`; `created_at`, `updated_at`; UNIQUE (`provider`, `idempotency_key`) and (`provider`, `provider_payment_id`) | Payment attempt and provider idempotency identifiers. |
| `payment_webhook_events` | (`provider`, `provider_event_id`) composite PK; nullable `payment_id` FK; `received_at`, `processed_at`; `payload` JSON | Durable webhook event deduplication and audit record. |

## Sample rows

The seed script uses stable IDs and is safe to rerun. Its example records include:

| Table | Example |
|---|---|
| `theatres` | PVR Central, MG Road, Bengaluru, `Asia/Kolkata` |
| `screens` | Screen 1 at PVR Central |
| `seats` | A1/A2 standard seats and B1/B2 premium seats |
| `movies` | The Last Monsoon (Kannada, 142 min); Orbit Seven (English, 128 min) |
| `shows` | The Last Monsoon at 09:00 local and Orbit Seven at 12:30 local on 2026-10-15; another screening on 2026-10-16 |
| `customers` | Sample Customer (`sample.customer@example.test`) |
| `show_seats` | First show's A1 is `BOOKED` at INR 250.00; other standard/premium seats are available at INR 250.00/350.00 |
| `bookings` | One confirmed booking for the first show, created 2026-10-14 10:00 UTC |
| `booking_seats` | That booking owns seat A1 at the INR 250.00 historical price |
| `payments` | One successful demo payment for INR 250.00 (`demo-payment-001`) |
| `payment_webhook_events` | One processed `payment.succeeded` event (`evt-demo-001`) |

`sql/seed.sql` contains the complete executable INSERT statements and IDs.

## Normalization

- **1NF:** Every column holds one scalar. A booking's seats are rows in `booking_seats`, never a packed list.
- **2NF:** Single-column-key tables satisfy 2NF. In `show_seats`, price/state/expiry depend on the full `(show_id, seat_id)` key. In `booking_seats`, the price snapshot depends on `(booking_id, seat_id)`.
- **3NF:** Movie, theatre, screen, seat, and customer descriptions are stored only with their own entities. Booking currency is not copied from its show, and booking total is calculated from the immutable seat price snapshots.
- **BCNF:** Declared determinants are candidate keys or superkeys. Examples include `screens`: `screen_id` and `(theatre_id, name)`; `seats`: `seat_id` and `(screen_id, row_label, seat_number)`; `shows`: `show_id` and `(screen_id, starts_at)`; `show_seats`: `(show_id, seat_id)`; `booking_seats`: `(booking_id, seat_id)`; `payments`: `(provider, idempotency_key)` and `(provider, provider_payment_id)` when non-null; webhook events: `(provider, provider_event_id)`. Other base entities are keyed by their primary key.

## Concurrency and lifecycle

For a hold, start a transaction and select the requested `show_seats` rows in ascending `seat_id` order using `FOR UPDATE SKIP LOCKED`. Continue only if every unique requested seat was returned and is `AVAILABLE`; otherwise roll back. Insert the `HELD` booking and `booking_seats` price snapshots, update the locked inventory rows to `HELD` with one database-generated expiry, then commit. This makes multi-seat holds all-or-nothing. The composite inventory primary key means only one inventory row exists for each show/seat pair, and its row lock serializes competing buyers.

An expiry worker claims due `HELD` bookings in small batches using `FOR UPDATE SKIP LOCKED`; in one transaction it locks their seat rows in ascending order, changes the booking to `EXPIRED`, and returns the inventory to `AVAILABLE`. An unswept expired hold stays unavailable briefly rather than being double-sold.

Webhook handling inserts `(provider, provider_event_id)` before applying effects, in the same transaction. A duplicate-key error (MySQL error 1062) means the event was already applied; acknowledge it without repeating effects. Lock the booking before its seats and lock seats in ascending order. Confirm only a still-live hold, updating payment, booking, and inventory atomically. If the hold expired first, persist the payment result and trigger a refund/compensation workflow; never confirm seats that were released. External payment/refund calls occur outside database transactions.

MySQL has no PostgreSQL-style exclusion constraint; the show triggers lock the screen row and reject overlapping scheduled shows. All schedule writes must use the same trigger-protected path. Keep transactions short and retry deadlocks with bounded backoff.

## P1 SQL

The complete MySQL table creation and sample INSERT statements are in `sql/schema.sql` and `sql/seed.sql`. Hold, expiry, and webhook SQL patterns are in `sql/queries.sql`.

## P2 SQL

This query is executable in MySQL 8.0 after running the schema and seed files. It uses the theatre-local date, handles daylight-saving day boundaries via `CONVERT_TZ`, returns local show timings, and filters to the next seven local dates.

```sql
SELECT
    sh.show_id,
    m.title AS movie_title,
    sc.name AS screen_name,
    CONVERT_TZ(sh.starts_at, '+00:00', th.timezone) AS starts_at_local,
    CONVERT_TZ(sh.ends_at, '+00:00', th.timezone) AS ends_at_local,
    sh.currency,
    SUM(CASE WHEN ss.state = 'AVAILABLE' THEN 1 ELSE 0 END) AS available_seats
FROM theatres AS th
JOIN screens AS sc ON sc.theatre_id = th.theatre_id
JOIN shows AS sh ON sh.screen_id = sc.screen_id
JOIN movies AS m ON m.movie_id = sh.movie_id
LEFT JOIN show_seats AS ss ON ss.show_id = sh.show_id
WHERE th.theatre_id = @theatre_id
  AND sh.status = 'SCHEDULED'
  AND @local_date >= DATE(CONVERT_TZ(UTC_TIMESTAMP(), '+00:00', th.timezone))
  AND @local_date < DATE_ADD(DATE(CONVERT_TZ(UTC_TIMESTAMP(), '+00:00', th.timezone)), INTERVAL 7 DAY)
  AND sh.starts_at >= CONVERT_TZ(CONCAT(@local_date, ' 00:00:00'), th.timezone, '+00:00')
  AND sh.starts_at < CONVERT_TZ(CONCAT(DATE_ADD(@local_date, INTERVAL 1 DAY), ' 00:00:00'), th.timezone, '+00:00')
GROUP BY sh.show_id, m.title, sc.name, sh.starts_at, sh.ends_at, th.timezone, sh.currency
ORDER BY sh.starts_at, sc.name;
```

## Submission notes

 The referenced theatre screenshot was not available as a workspace file, so the SQL and document use the described date-picker/showtime flow rather than reproducing the image. Git is available through the installed GitHub Desktop bundle, but this checkout has no configured remote; a PR URL cannot be created until the target GitHub repository is supplied and authenticated.

The MySQL concurrency harness is `tests/load_test.py`. With the schema applied to a disposable MySQL database, install `requirements.txt`, set `MYSQL_HOST`, `MYSQL_USER`, and `MYSQL_PASSWORD`, then run `python tests/load_test.py --attempts 1000 --workers 64`. It asserts single-seat exclusivity, all-or-nothing two-seat holds, expiry release, webhook deduplication, and an expiry/payment race outcome.