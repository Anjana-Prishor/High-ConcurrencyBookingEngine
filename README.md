# High-Concurrency Movie Booking Database

MySQL 8.0.16+ / InnoDB schema and submission for the theatre date-picker and movie-showtime booking scenario.

## Submission files

- [SUBMISSION.md](SUBMISSION.md): entity attributes, sample records, normalization, locking strategy, and P1/P2 overview.
- [PDF deliverable](submission/High-Concurrency-Booking-Database.pdf): formatted document with the schema, sample inserts, and query appendices.
- [MySQL schema](sql/schema.sql): executable database and table DDL, constraints, indexes, and integrity triggers.
- [Sample data](sql/seed.sql): example rows for every table, including a confirmed booking and successful demo payment.
- [P2 and operational SQL](sql/queries.sql): theatre/date show listing plus MySQL locking, expiry, and webhook patterns.
- [MySQL concurrency test](tests/load_test.py): competing seat holds, expiry release, duplicate webhook delivery, and expiry/payment race.

## Run on MySQL

Use MySQL 8.0.16+ (CHECK constraints must be enforced) with InnoDB and a client that supports `DELIMITER` for trigger creation:

```sh
mysql -u root -p < sql/schema.sql
mysql -u root -p < sql/seed.sql
mysql -u root -p < sql/queries.sql
```

The P2 query uses `@theatre_id` and `@local_date` variables set at the start of `sql/queries.sql`. Load MySQL timezone tables for `CONVERT_TZ` with named zones such as `Asia/Kolkata` to work. Show and hold `DATETIME(6)` values are stored as UTC by convention.

## Load test

Install dependencies with `python -m pip install -r requirements.txt`. Set `MYSQL_HOST`, `MYSQL_USER`, and `MYSQL_PASSWORD` (optionally `MYSQL_PORT` and `MYSQL_DATABASE`) for a disposable MySQL database created from the schema, then run:

```sh
python tests/load_test.py --attempts 1000 --workers 64
```

The test creates and removes its own fixture. It has not been run here because no MySQL server or credentials are configured.

## GitHub submission

Git is available through GitHub Desktop, but this checkout has no configured remote. A PR requires the target repository URL and an authenticated GitHub account; neither the remote nor a PR link is available from this workspace yet.
