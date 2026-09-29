"""Block until the database schema is migrated (used by the worker, which must not start before the API's migration).

Exits 0 once `alembic_version` reports the head revision; exits 1 after the timeout so a misconfigured deploy fails
loudly instead of hanging forever."""
import os
import sys
import time

import psycopg
from alembic.config import Config
from alembic.script import ScriptDirectory

TIMEOUT = float(os.environ.get("WAIT_FOR_SCHEMA_SECONDS", "300"))


def main() -> int:
    dsn = os.environ["AD_CHECKPOINT_DSN"]  # owner DSN (psycopg form)
    HEAD = ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()  # never hard-coded
    deadline = time.monotonic() + TIMEOUT
    last = "no connection yet"
    while time.monotonic() < deadline:
        try:
            with psycopg.connect(dsn, connect_timeout=5) as c:
                row = c.execute("SELECT version_num FROM alembic_version").fetchone()
                if row and row[0] == HEAD:
                    print(f"schema at {HEAD}", flush=True)
                    return 0
                last = f"alembic_version={row[0] if row else None}, waiting for {HEAD}"
        except psycopg.Error as e:
            last = f"{type(e).__name__}: {e}".splitlines()[0]
        print(f"waiting for schema: {last}", flush=True)
        time.sleep(3)
    print(f"gave up after {TIMEOUT:.0f}s: {last}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
