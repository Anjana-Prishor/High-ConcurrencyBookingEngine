USE booking_engine;

-- P2: list scheduled shows at one theatre for a theatre-local calendar date.
-- Set @theatre_id and @local_date before running. Requires MySQL time-zone tables.
SET @theatre_id = '10000000-0000-0000-0000-000000000001';
SET @local_date = DATE '2026-10-15';

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

-- P1 seat hold: run in one transaction. Bind the selected IDs as parameters.
-- The application must compare the returned row count with the unique seat count;
-- rollback if any requested seat is missing. Insert booking + booking_seats and
-- update inventory before COMMIT. Example lock:
-- SELECT seat_id, price_amount
-- FROM show_seats
-- WHERE show_id = ? AND seat_id IN (?, ?) AND state = 'AVAILABLE'
-- ORDER BY seat_id
-- FOR UPDATE SKIP LOCKED;

-- Expiry worker claim (execute in a transaction; workers skip already-claimed holds).
SELECT booking_id, show_id
FROM bookings
WHERE status = 'HELD' AND expires_at <= UTC_TIMESTAMP(6)
ORDER BY expires_at, booking_id
LIMIT 100
FOR UPDATE SKIP LOCKED;

-- Webhook idempotency gate. A duplicate-key error means this event was already applied.
-- Catch MySQL error 1062 and acknowledge the duplicate without repeating effects.
INSERT INTO payment_webhook_events (provider, provider_event_id, payment_id, payload)
VALUES ('example-provider', 'evt-example-001', NULL, JSON_OBJECT('type', 'payment.succeeded'));