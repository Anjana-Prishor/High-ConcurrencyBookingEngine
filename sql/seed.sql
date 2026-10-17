USE booking_engine;

INSERT INTO theatres (theatre_id, name, address, timezone) VALUES
('10000000-0000-0000-0000-000000000001', 'PVR Central', 'MG Road, Bengaluru', 'Asia/Kolkata')
ON DUPLICATE KEY UPDATE name = VALUES(name);

INSERT INTO screens (screen_id, theatre_id, name) VALUES
('20000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000001', 'Screen 1')
ON DUPLICATE KEY UPDATE name = VALUES(name);

INSERT INTO seats (seat_id, screen_id, row_label, seat_number, seat_type) VALUES
('30000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000001', 'A', 1, 'STANDARD'),
('30000000-0000-0000-0000-000000000002', '20000000-0000-0000-0000-000000000001', 'A', 2, 'STANDARD'),
('30000000-0000-0000-0000-000000000003', '20000000-0000-0000-0000-000000000001', 'B', 1, 'PREMIUM'),
('30000000-0000-0000-0000-000000000004', '20000000-0000-0000-0000-000000000001', 'B', 2, 'PREMIUM')
ON DUPLICATE KEY UPDATE seat_id = VALUES(seat_id);

INSERT INTO movies (movie_id, title, language, duration_mins, rating) VALUES
('40000000-0000-0000-0000-000000000001', 'The Last Monsoon', 'Kannada', 142, 'U/A'),
('40000000-0000-0000-0000-000000000002', 'Orbit Seven', 'English', 128, 'U/A')
ON DUPLICATE KEY UPDATE title = VALUES(title);

INSERT INTO shows (show_id, movie_id, screen_id, starts_at, ends_at, status, currency) VALUES
('50000000-0000-0000-0000-000000000001', '40000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000001', '2026-10-15 03:30:00', '2026-10-15 06:10:00', 'SCHEDULED', 'INR'),
('50000000-0000-0000-0000-000000000002', '40000000-0000-0000-0000-000000000002', '20000000-0000-0000-0000-000000000001', '2026-10-15 07:00:00', '2026-10-15 09:25:00', 'SCHEDULED', 'INR'),
('50000000-0000-0000-0000-000000000003', '40000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000001', '2026-10-16 03:30:00', '2026-10-16 06:10:00', 'SCHEDULED', 'INR')
ON DUPLICATE KEY UPDATE starts_at = VALUES(starts_at);

INSERT INTO customers (customer_id, display_name, email) VALUES
('60000000-0000-0000-0000-000000000001', 'Sample Customer', 'sample.customer@example.test')
ON DUPLICATE KEY UPDATE display_name = VALUES(display_name);

INSERT INTO show_seats (show_id, seat_id, price_amount)
SELECT sh.show_id, st.seat_id,
       CASE WHEN st.seat_type = 'PREMIUM' THEN 350.00 ELSE 250.00 END
FROM shows AS sh
JOIN seats AS st ON st.screen_id = sh.screen_id
WHERE sh.show_id IN (
    '50000000-0000-0000-0000-000000000001',
    '50000000-0000-0000-0000-000000000002',
    '50000000-0000-0000-0000-000000000003'
)
ON DUPLICATE KEY UPDATE price_amount = VALUES(price_amount);

INSERT INTO bookings (booking_id, customer_id, show_id, status, created_at, expires_at) VALUES
('70000000-0000-0000-0000-000000000001', '60000000-0000-0000-0000-000000000001', '50000000-0000-0000-0000-000000000001', 'CONFIRMED', '2026-10-14 10:00:00.000000', NULL)
ON DUPLICATE KEY UPDATE status = VALUES(status), expires_at = VALUES(expires_at);

INSERT INTO booking_seats (booking_id, seat_id, price_amount) VALUES
('70000000-0000-0000-0000-000000000001', '30000000-0000-0000-0000-000000000001', 250.00)
ON DUPLICATE KEY UPDATE price_amount = VALUES(price_amount);

UPDATE show_seats
SET state = 'BOOKED', hold_expires_at = NULL
WHERE show_id = '50000000-0000-0000-0000-000000000001'
  AND seat_id = '30000000-0000-0000-0000-000000000001';

INSERT INTO payments
    (payment_id, booking_id, provider, provider_payment_id, idempotency_key, amount, status, created_at, updated_at)
VALUES
    ('80000000-0000-0000-0000-000000000001', '70000000-0000-0000-0000-000000000001', 'demo-pay', 'demo-payment-001', 'demo-booking-001', 250.00, 'SUCCEEDED', '2026-10-14 10:01:00.000000', '2026-10-14 10:01:00.000000')
ON DUPLICATE KEY UPDATE status = VALUES(status), amount = VALUES(amount);

INSERT INTO payment_webhook_events
    (provider, provider_event_id, payment_id, received_at, processed_at, payload)
VALUES
    ('demo-pay', 'evt-demo-001', '80000000-0000-0000-0000-000000000001', '2026-10-14 10:01:01.000000', '2026-10-14 10:01:01.000000', JSON_OBJECT('type', 'payment.succeeded', 'payment_id', 'demo-payment-001'))
ON DUPLICATE KEY UPDATE processed_at = VALUES(processed_at);