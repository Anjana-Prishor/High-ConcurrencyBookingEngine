-- MySQL 8.0.16+. All DATETIME(6) values are UTC by application convention.
CREATE DATABASE IF NOT EXISTS booking_engine
    CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
USE booking_engine;

CREATE TABLE movies (
    movie_id CHAR(36) NOT NULL PRIMARY KEY,
    title VARCHAR(200) NOT NULL,
    language VARCHAR(60) NOT NULL,
    duration_mins SMALLINT UNSIGNED NOT NULL,
    rating VARCHAR(20) NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    CONSTRAINT chk_movies_duration CHECK (duration_mins > 0)
) ENGINE=InnoDB;

CREATE TABLE theatres (
    theatre_id CHAR(36) NOT NULL PRIMARY KEY,
    name VARCHAR(160) NOT NULL,
    address VARCHAR(500) NOT NULL,
    timezone VARCHAR(64) NOT NULL
) ENGINE=InnoDB;

CREATE TABLE screens (
    screen_id CHAR(36) NOT NULL PRIMARY KEY,
    theatre_id CHAR(36) NOT NULL,
    name VARCHAR(80) NOT NULL,
    CONSTRAINT uq_screens_theatre_name UNIQUE (theatre_id, name),
    CONSTRAINT uq_screens_id_theatre UNIQUE (screen_id, theatre_id),
    CONSTRAINT fk_screens_theatre FOREIGN KEY (theatre_id)
        REFERENCES theatres (theatre_id)
) ENGINE=InnoDB;

CREATE TABLE seats (
    seat_id CHAR(36) NOT NULL PRIMARY KEY,
    screen_id CHAR(36) NOT NULL,
    row_label VARCHAR(8) NOT NULL,
    seat_number SMALLINT UNSIGNED NOT NULL,
    seat_type ENUM('STANDARD', 'PREMIUM', 'ACCESSIBLE') NOT NULL,
    CONSTRAINT uq_seats_position UNIQUE (screen_id, row_label, seat_number),
    CONSTRAINT uq_seats_id_screen UNIQUE (seat_id, screen_id),
    CONSTRAINT chk_seats_number CHECK (seat_number > 0),
    CONSTRAINT fk_seats_screen FOREIGN KEY (screen_id)
        REFERENCES screens (screen_id)
) ENGINE=InnoDB;

CREATE TABLE shows (
    show_id CHAR(36) NOT NULL PRIMARY KEY,
    movie_id CHAR(36) NOT NULL,
    screen_id CHAR(36) NOT NULL,
    starts_at DATETIME(6) NOT NULL COMMENT 'UTC',
    ends_at DATETIME(6) NOT NULL COMMENT 'UTC',
    status ENUM('SCHEDULED', 'CANCELLED') NOT NULL DEFAULT 'SCHEDULED',
    currency CHAR(3) CHARACTER SET ascii NOT NULL,
    CONSTRAINT uq_shows_screen_start UNIQUE (screen_id, starts_at),
    CONSTRAINT uq_shows_id_screen UNIQUE (show_id, screen_id),
    CONSTRAINT chk_shows_time CHECK (ends_at > starts_at),
    CONSTRAINT chk_shows_currency CHECK (currency REGEXP '^[A-Z]{3}$'),
    CONSTRAINT fk_shows_movie FOREIGN KEY (movie_id) REFERENCES movies (movie_id),
    CONSTRAINT fk_shows_screen FOREIGN KEY (screen_id) REFERENCES screens (screen_id),
    INDEX ix_shows_movie_start (movie_id, starts_at),
    INDEX ix_shows_screen_status_start (screen_id, status, starts_at)
) ENGINE=InnoDB;

CREATE TABLE customers (
    customer_id CHAR(36) NOT NULL PRIMARY KEY,
    display_name VARCHAR(160) NOT NULL,
    email VARCHAR(254) NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    CONSTRAINT uq_customers_email UNIQUE (email)
) ENGINE=InnoDB;

CREATE TABLE bookings (
    booking_id CHAR(36) NOT NULL PRIMARY KEY,
    customer_id CHAR(36) NOT NULL,
    show_id CHAR(36) NOT NULL,
    status ENUM('HELD', 'CONFIRMED', 'EXPIRED', 'CANCELLED') NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    expires_at DATETIME(6) NULL,
    CONSTRAINT chk_bookings_expiry CHECK (
        (status = 'HELD' AND expires_at IS NOT NULL)
        OR (status <> 'HELD' AND expires_at IS NULL)
    ),
    CONSTRAINT fk_bookings_customer FOREIGN KEY (customer_id)
        REFERENCES customers (customer_id),
    CONSTRAINT fk_bookings_show FOREIGN KEY (show_id)
        REFERENCES shows (show_id),
    INDEX ix_bookings_expiry (status, expires_at, booking_id),
    INDEX ix_bookings_customer_created (customer_id, created_at)
) ENGINE=InnoDB;

CREATE TABLE show_seats (
    show_id CHAR(36) NOT NULL,
    seat_id CHAR(36) NOT NULL,
    price_amount DECIMAL(12, 2) NOT NULL,
    state ENUM('AVAILABLE', 'HELD', 'BOOKED') NOT NULL DEFAULT 'AVAILABLE',
    hold_expires_at DATETIME(6) NULL,
    PRIMARY KEY (show_id, seat_id),
    CONSTRAINT chk_show_seats_price CHECK (price_amount >= 0),
    CONSTRAINT chk_show_seats_hold CHECK (
        (state = 'HELD' AND hold_expires_at IS NOT NULL)
        OR (state <> 'HELD' AND hold_expires_at IS NULL)
    ),
    CONSTRAINT fk_show_seats_show FOREIGN KEY (show_id)
        REFERENCES shows (show_id),
    CONSTRAINT fk_show_seats_seat FOREIGN KEY (seat_id)
        REFERENCES seats (seat_id),
    INDEX ix_show_seats_state (show_id, state, seat_id)
) ENGINE=InnoDB;

CREATE TABLE booking_seats (
    booking_id CHAR(36) NOT NULL,
    seat_id CHAR(36) NOT NULL,
    price_amount DECIMAL(12, 2) NOT NULL,
    PRIMARY KEY (booking_id, seat_id),
    CONSTRAINT chk_booking_seats_price CHECK (price_amount >= 0),
    CONSTRAINT fk_booking_seats_booking FOREIGN KEY (booking_id)
        REFERENCES bookings (booking_id),
    CONSTRAINT fk_booking_seats_seat FOREIGN KEY (seat_id)
        REFERENCES seats (seat_id),
    INDEX ix_booking_seats_seat (seat_id, booking_id)
) ENGINE=InnoDB;

CREATE TABLE payments (
    payment_id CHAR(36) NOT NULL PRIMARY KEY,
    booking_id CHAR(36) NOT NULL,
    provider VARCHAR(60) NOT NULL,
    provider_payment_id VARCHAR(190) NULL,
    idempotency_key VARCHAR(190) NOT NULL,
    amount DECIMAL(12, 2) NOT NULL,
    status ENUM('PENDING', 'SUCCEEDED', 'FAILED', 'REFUNDED') NOT NULL DEFAULT 'PENDING',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    CONSTRAINT uq_payments_idempotency UNIQUE (provider, idempotency_key),
    CONSTRAINT uq_payments_provider_id UNIQUE (provider, provider_payment_id),
    CONSTRAINT chk_payments_amount CHECK (amount >= 0),
    CONSTRAINT fk_payments_booking FOREIGN KEY (booking_id)
        REFERENCES bookings (booking_id),
    INDEX ix_payments_booking_created (booking_id, created_at)
) ENGINE=InnoDB;

CREATE TABLE payment_webhook_events (
    provider VARCHAR(60) NOT NULL,
    provider_event_id VARCHAR(190) NOT NULL,
    payment_id CHAR(36) NULL,
    received_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    processed_at DATETIME(6) NULL,
    payload JSON NOT NULL,
    PRIMARY KEY (provider, provider_event_id),
    CONSTRAINT fk_webhook_payment FOREIGN KEY (payment_id)
        REFERENCES payments (payment_id),
    INDEX ix_webhook_payment (payment_id)
) ENGINE=InnoDB;

DELIMITER $$

-- Serialize schedule writes on the screen row, then reject overlapping intervals.
CREATE TRIGGER shows_no_overlap_before_insert
BEFORE INSERT ON shows
FOR EACH ROW
BEGIN
    DECLARE locked_screen CHAR(36);
    DECLARE overlapping_show CHAR(36) DEFAULT NULL;
    SELECT screen_id INTO locked_screen
    FROM screens
    WHERE screen_id = NEW.screen_id
    FOR UPDATE;

    IF NEW.status = 'SCHEDULED' THEN
                SELECT show_id INTO overlapping_show
        FROM shows
        WHERE screen_id = NEW.screen_id
          AND status = 'SCHEDULED'
          AND starts_at < NEW.ends_at
                    AND ends_at > NEW.starts_at
                LIMIT 1
                FOR UPDATE;
                IF overlapping_show IS NOT NULL THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Show overlaps another scheduled show on this screen';
        END IF;
    END IF;
END$$

CREATE TRIGGER shows_no_overlap_before_update
BEFORE UPDATE ON shows
FOR EACH ROW
BEGIN
    DECLARE locked_screen CHAR(36);
    DECLARE overlapping_show CHAR(36) DEFAULT NULL;
    SELECT screen_id INTO locked_screen
    FROM screens
    WHERE screen_id = NEW.screen_id
    FOR UPDATE;

    IF NEW.status = 'SCHEDULED' THEN
                SELECT show_id INTO overlapping_show
        FROM shows
        WHERE screen_id = NEW.screen_id
          AND show_id <> OLD.show_id
          AND status = 'SCHEDULED'
          AND starts_at < NEW.ends_at
                    AND ends_at > NEW.starts_at
                LIMIT 1
                FOR UPDATE;
                IF overlapping_show IS NOT NULL THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Show overlaps another scheduled show on this screen';
        END IF;
    END IF;
END$$

CREATE TRIGGER show_seats_screen_match_before_insert
BEFORE INSERT ON show_seats
FOR EACH ROW
BEGIN
    DECLARE matching_rows INT DEFAULT 0;
    SELECT COUNT(*) INTO matching_rows
    FROM shows AS sh
    JOIN seats AS st ON st.seat_id = NEW.seat_id
    WHERE sh.show_id = NEW.show_id
      AND sh.screen_id = st.screen_id;
    IF matching_rows <> 1 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Seat does not belong to the screen for this show';
    END IF;
END$$

CREATE TRIGGER show_seats_screen_match_before_update
BEFORE UPDATE ON show_seats
FOR EACH ROW
BEGIN
    DECLARE matching_rows INT DEFAULT 0;
    SELECT COUNT(*) INTO matching_rows
    FROM shows AS sh
    JOIN seats AS st ON st.seat_id = NEW.seat_id
    WHERE sh.show_id = NEW.show_id
      AND sh.screen_id = st.screen_id;
    IF matching_rows <> 1 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Seat does not belong to the screen for this show';
    END IF;
END$$

CREATE TRIGGER booking_seats_show_match_before_insert
BEFORE INSERT ON booking_seats
FOR EACH ROW
BEGIN
    DECLARE matching_rows INT DEFAULT 0;
    SELECT COUNT(*) INTO matching_rows
    FROM bookings AS b
    JOIN show_seats AS ss ON ss.show_id = b.show_id
    WHERE b.booking_id = NEW.booking_id
      AND ss.seat_id = NEW.seat_id;
    IF matching_rows <> 1 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Seat has no inventory for this booking show';
    END IF;
END$$

CREATE TRIGGER booking_seats_show_match_before_update
BEFORE UPDATE ON booking_seats
FOR EACH ROW
BEGIN
    DECLARE matching_rows INT DEFAULT 0;
    SELECT COUNT(*) INTO matching_rows
    FROM bookings AS b
    JOIN show_seats AS ss ON ss.show_id = b.show_id
    WHERE b.booking_id = NEW.booking_id
      AND ss.seat_id = NEW.seat_id;
    IF matching_rows <> 1 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Seat has no inventory for this booking show';
    END IF;
END$$

DELIMITER ;