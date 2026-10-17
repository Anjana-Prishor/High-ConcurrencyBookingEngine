"""MySQL InnoDB contention test for seat holds, expiry, and webhook deduplication."""

from __future__ import annotations

import argparse
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from threading import Barrier
from uuid import uuid4

import mysql.connector
from mysql.connector import IntegrityError


@contextmanager
def connection(config: dict[str, object]):
    db = mysql.connector.connect(**config)
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def create_fixture(config: dict[str, object]) -> dict[str, str]:
    fixture = {key: str(uuid4()) for key in ("theatre", "screen", "movie", "show", "seat_a", "seat_b", "seat_c")}
    with connection(config) as db, db.cursor() as cursor:
        cursor.execute(
            "INSERT INTO theatres (theatre_id, name, address, timezone) VALUES (%s, 'Load Test', 'Fixture', 'UTC')",
            (fixture["theatre"],),
        )
        cursor.execute(
            "INSERT INTO screens (screen_id, theatre_id, name) VALUES (%s, %s, 'Load Screen')",
            (fixture["screen"], fixture["theatre"]),
        )
        cursor.execute(
            "INSERT INTO movies (movie_id, title, language, duration_mins) VALUES (%s, 'Load Test', 'English', 120)",
            (fixture["movie"],),
        )
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        cursor.execute(
            """INSERT INTO shows (show_id, movie_id, screen_id, starts_at, ends_at, status, currency)
               VALUES (%s, %s, %s, %s, %s, 'SCHEDULED', 'USD')""",
            (fixture["show"], fixture["movie"], fixture["screen"], now + timedelta(days=1), now + timedelta(days=1, hours=2)),
        )
        for key, row in (("seat_a", "A"), ("seat_b", "B"), ("seat_c", "C")):
            cursor.execute(
                "INSERT INTO seats (seat_id, screen_id, row_label, seat_number, seat_type) VALUES (%s, %s, %s, 1, 'STANDARD')",
                (fixture[key], fixture["screen"], row),
            )
            cursor.execute(
                "INSERT INTO show_seats (show_id, seat_id, price_amount) VALUES (%s, %s, 25.00)",
                (fixture["show"], fixture[key]),
            )
    return fixture


def try_hold(config: dict[str, object], fixture: dict[str, str], requested: list[str]) -> tuple[str | None, float]:
    started = time.perf_counter()
    booking_id = str(uuid4())
    marks = ", ".join(["%s"] * len(requested))
    with connection(config) as db, db.cursor() as cursor:
        cursor.execute(
            f"""SELECT seat_id, price_amount FROM show_seats
                WHERE show_id = %s AND seat_id IN ({marks}) AND state = 'AVAILABLE'
                ORDER BY seat_id FOR UPDATE SKIP LOCKED""",
            (fixture["show"], *requested),
        )
        locked = cursor.fetchall()
        if len(locked) != len(set(requested)):
            return None, time.perf_counter() - started

        customer_id = str(uuid4())
        cursor.execute(
            "INSERT INTO customers (customer_id, display_name, email) VALUES (%s, %s, %s)",
            (customer_id, f"Load test {fixture['show']}", f"{customer_id}@example.test"),
        )
        cursor.execute(
            """INSERT INTO bookings (booking_id, customer_id, show_id, status, expires_at)
               VALUES (%s, %s, %s, 'HELD', UTC_TIMESTAMP(6) + INTERVAL 5 MINUTE)""",
            (booking_id, customer_id, fixture["show"]),
        )
        cursor.execute(
            f"""UPDATE show_seats SET state = 'HELD', hold_expires_at = UTC_TIMESTAMP(6) + INTERVAL 5 MINUTE
                WHERE show_id = %s AND seat_id IN ({marks}) AND state = 'AVAILABLE'""",
            (fixture["show"], *requested),
        )
        if cursor.rowcount != len(locked):
            raise AssertionError("Inventory changed after the seat locks were acquired")
        cursor.executemany(
            "INSERT INTO booking_seats (booking_id, seat_id, price_amount) VALUES (%s, %s, %s)",
            [(booking_id, seat_id, price) for seat_id, price in locked],
        )
    return booking_id, time.perf_counter() - started


def race_holds(config: dict[str, object], fixture: dict[str, str], seats: list[str], attempts: int, workers: int):
    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda _: try_hold(config, fixture, seats), range(attempts)))
    elapsed = time.perf_counter() - start
    return [booking for booking, _ in results if booking], [latency for _, latency in results], elapsed


def release_expired(config: dict[str, object], booking_id: str, show_id: str) -> None:
    with connection(config) as db, db.cursor() as cursor:
        cursor.execute(
            "UPDATE bookings SET expires_at = UTC_TIMESTAMP(6) - INTERVAL 1 SECOND WHERE booking_id = %s AND status = 'HELD'",
            (booking_id,),
        )
        cursor.execute(
            """SELECT ss.seat_id
               FROM show_seats AS ss
               JOIN booking_seats AS bs ON bs.seat_id = ss.seat_id
               WHERE bs.booking_id = %s AND ss.show_id = %s
               ORDER BY ss.seat_id
               FOR UPDATE""",
            (booking_id, show_id),
        )
        seats = [row[0] for row in cursor.fetchall()]
        if not seats:
            return
        marks = ", ".join(["%s"] * len(seats))
        cursor.execute(
            f"""UPDATE show_seats SET state = 'AVAILABLE', hold_expires_at = NULL
                WHERE show_id = %s AND seat_id IN ({marks}) AND state = 'HELD'""",
            (show_id, *seats),
        )
        if cursor.rowcount != len(seats):
            raise AssertionError("Expiry did not release each seat held by the booking")
        cursor.execute("UPDATE bookings SET status = 'EXPIRED', expires_at = NULL WHERE booking_id = %s AND status = 'HELD'", (booking_id,))
        if cursor.rowcount != 1:
            raise AssertionError("Expiry failed to transition the held booking")


def make_payment(config: dict[str, object], booking_id: str) -> str:
    payment_id = str(uuid4())
    with connection(config) as db, db.cursor() as cursor:
        cursor.execute(
            """INSERT INTO payments (payment_id, booking_id, provider, idempotency_key, amount)
               SELECT %s, %s, 'load-test', %s, SUM(price_amount)
               FROM booking_seats WHERE booking_id = %s""",
            (payment_id, booking_id, str(uuid4()), booking_id),
        )
    return payment_id


def deliver_webhook(config: dict[str, object], payment_id: str, event_id: str) -> tuple[bool, float]:
    started = time.perf_counter()
    payload = json.dumps({"id": event_id, "type": "payment.succeeded"})
    with connection(config) as db, db.cursor() as cursor:
        try:
            cursor.execute(
                "INSERT INTO payment_webhook_events (provider, provider_event_id, payment_id, payload) VALUES ('load-test', %s, %s, %s)",
                (event_id, payment_id, payload),
            )
        except IntegrityError as error:
            if error.errno == 1062:
                return False, time.perf_counter() - started
            raise

        cursor.execute(
            """SELECT b.booking_id, b.show_id, b.status, b.expires_at > UTC_TIMESTAMP(6)
               FROM payments AS p JOIN bookings AS b ON b.booking_id = p.booking_id
               WHERE p.payment_id = %s FOR UPDATE""",
            (payment_id,),
        )
        booking_id, show_id, booking_status, is_live = cursor.fetchone()
        cursor.execute(
            """SELECT ss.seat_id FROM show_seats AS ss
               JOIN booking_seats AS bs ON bs.seat_id = ss.seat_id
               WHERE bs.booking_id = %s AND ss.show_id = %s
               ORDER BY ss.seat_id FOR UPDATE""",
            (booking_id, show_id),
        )
        seats = [row[0] for row in cursor.fetchall()]
        cursor.execute(
            "UPDATE payments SET status = 'SUCCEEDED', provider_payment_id = %s, updated_at = UTC_TIMESTAMP(6) WHERE payment_id = %s AND status = 'PENDING'",
            (f"provider-{payment_id}", payment_id),
        )
        if cursor.rowcount != 1:
            raise AssertionError("Webhook did not update one pending payment")

        if booking_status == "HELD" and is_live:
            cursor.execute("UPDATE bookings SET status = 'CONFIRMED', expires_at = NULL WHERE booking_id = %s AND status = 'HELD'", (booking_id,))
            if cursor.rowcount != 1:
                raise AssertionError("Webhook did not confirm the live hold")
            marks = ", ".join(["%s"] * len(seats))
            cursor.execute(
                f"""UPDATE show_seats SET state = 'BOOKED', hold_expires_at = NULL
                    WHERE show_id = %s AND seat_id IN ({marks}) AND state = 'HELD'""",
                (show_id, *seats),
            )
            if cursor.rowcount != len(seats):
                raise AssertionError("Webhook did not confirm every seat")
        cursor.execute(
            "UPDATE payment_webhook_events SET processed_at = UTC_TIMESTAMP(6) WHERE provider = 'load-test' AND provider_event_id = %s",
            (event_id,),
        )
    return True, time.perf_counter() - started


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(int((len(ordered) - 1) * fraction), len(ordered) - 1)] * 1000


def cleanup(config: dict[str, object], fixture: dict[str, str]) -> None:
    with connection(config) as db, db.cursor() as cursor:
        cursor.execute("DELETE FROM payment_webhook_events WHERE payment_id IN (SELECT payment_id FROM payments WHERE booking_id IN (SELECT booking_id FROM bookings WHERE show_id = %s))", (fixture["show"],))
        cursor.execute("DELETE FROM payments WHERE booking_id IN (SELECT booking_id FROM bookings WHERE show_id = %s)", (fixture["show"],))
        cursor.execute("DELETE FROM booking_seats WHERE booking_id IN (SELECT booking_id FROM bookings WHERE show_id = %s)", (fixture["show"],))
        cursor.execute("DELETE FROM bookings WHERE show_id = %s", (fixture["show"],))
        cursor.execute("DELETE FROM customers WHERE display_name = %s", (f"Load test {fixture['show']}",))
        cursor.execute("DELETE FROM show_seats WHERE show_id = %s", (fixture["show"],))
        cursor.execute("DELETE FROM shows WHERE show_id = %s", (fixture["show"],))
        cursor.execute("DELETE FROM seats WHERE screen_id = %s", (fixture["screen"],))
        cursor.execute("DELETE FROM screens WHERE screen_id = %s", (fixture["screen"],))
        cursor.execute("DELETE FROM movies WHERE movie_id = %s", (fixture["movie"],))
        cursor.execute("DELETE FROM theatres WHERE theatre_id = %s", (fixture["theatre"],))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attempts", type=int, default=1000)
    parser.add_argument("--workers", type=int, default=64)
    args = parser.parse_args()
    if args.attempts < 2 or args.workers < 1:
        parser.error("--attempts must be at least 2; --workers must be positive")
    try:
        config: dict[str, object] = {
            "host": os.environ["MYSQL_HOST"],
            "port": int(os.environ.get("MYSQL_PORT", "3306")),
            "user": os.environ["MYSQL_USER"],
            "password": os.environ.get("MYSQL_PASSWORD", ""),
            "database": os.environ.get("MYSQL_DATABASE", "booking_engine"),
            "autocommit": False,
        }
    except KeyError as error:
        parser.error(f"Set {error.args[0]} for the disposable MySQL test database")

    fixture = create_fixture(config)
    try:
        show_id = fixture["show"]
        winners, latencies, elapsed = race_holds(config, fixture, [fixture["seat_a"]], args.attempts, args.workers)
        print(f"single-seat: winners={len(winners)}/{args.attempts}, throughput={args.attempts / elapsed:.1f}/s, p95={percentile(latencies, .95):.2f}ms")
        if len(winners) != 1:
            raise AssertionError("Expected exactly one winner for the contested seat")

        release_expired(config, winners[0], show_id)
        with connection(config) as db, db.cursor() as cursor:
            cursor.execute("SELECT state FROM show_seats WHERE show_id = %s AND seat_id = %s", (show_id, fixture["seat_a"]))
            if cursor.fetchone()[0] != "AVAILABLE":
                raise AssertionError("Expired seat was not released")

        requested = [fixture["seat_a"], fixture["seat_b"]]
        winners, latencies, elapsed = race_holds(config, fixture, requested, args.attempts, args.workers)
        print(f"two-seat atomic: winners={len(winners)}/{args.attempts}, throughput={args.attempts / elapsed:.1f}/s, p95={percentile(latencies, .95):.2f}ms")
        if len(winners) != 1:
            raise AssertionError("Expected one all-or-nothing multi-seat hold")

        payment_id = make_payment(config, winners[0])
        event_id = str(uuid4())
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            deliveries = list(pool.map(lambda _: deliver_webhook(config, payment_id, event_id), range(args.attempts)))
        applied = sum(applied for applied, _ in deliveries)
        print(f"duplicate webhook: applied={applied}/{args.attempts}, p95={percentile([latency for _, latency in deliveries], .95):.2f}ms")
        if applied != 1:
            raise AssertionError("Expected exactly one webhook application")

        race_winners, _, _ = race_holds(config, fixture, [fixture["seat_c"]], 2, 2)
        if len(race_winners) != 1:
            raise AssertionError("Could not create hold for expiry/payment race")
        race_payment = make_payment(config, race_winners[0])
        barrier = Barrier(2)

        def expire_race() -> None:
            barrier.wait()
            release_expired(config, race_winners[0], show_id)

        def webhook_race():
            barrier.wait()
            return deliver_webhook(config, race_payment, str(uuid4()))

        with ThreadPoolExecutor(max_workers=2) as pool:
            expiry_future = pool.submit(expire_race)
            webhook_future = pool.submit(webhook_race)
            expiry_future.result()
            webhook_future.result()
        with connection(config) as db, db.cursor() as cursor:
            cursor.execute(
                """SELECT b.status, ss.state FROM bookings AS b
                   JOIN booking_seats AS bs ON bs.booking_id = b.booking_id
                   JOIN show_seats AS ss ON ss.show_id = b.show_id AND ss.seat_id = bs.seat_id
                   WHERE b.booking_id = %s""",
                (race_winners[0],),
            )
            final_states = cursor.fetchall()
        if final_states not in [[("CONFIRMED", "BOOKED")], [("EXPIRED", "AVAILABLE")]]:
            raise AssertionError(f"Expiry/payment race produced mixed state: {final_states}")

        print("PASS: exclusive seat holds, atomic multi-seat selection, expiry release, webhook idempotency, and expiry/payment race.")
        return 0
    finally:
        cleanup(config, fixture)


if __name__ == "__main__":
    raise SystemExit(main())
