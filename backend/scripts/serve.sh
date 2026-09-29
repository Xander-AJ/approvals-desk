#!/bin/sh
# One image, two roles. Compose sets its own commands; PaaS deploys pick a role with SERVICE_ROLE.
#   api    (default): [RUN_MIGRATIONS=1: alembic upgrade head] [RUN_SEED=1: demo tenants] then uvicorn on $PORT
#   worker           : wait for the migrated schema, then the arq worker
set -eu
case "${SERVICE_ROLE:-api}" in
  api)
    if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then alembic upgrade head; fi
    if [ "${RUN_SEED:-0}" = "1" ]; then python -m app.seed; fi
    exec uvicorn app.entrypoint:app --host 0.0.0.0 --port "${PORT:-8000}"
    ;;
  worker)
    python scripts/wait_for_schema.py
    exec arq app.worker.WorkerSettings
    ;;
  *)
    echo "unknown SERVICE_ROLE: ${SERVICE_ROLE}" >&2
    exit 2
    ;;
esac
