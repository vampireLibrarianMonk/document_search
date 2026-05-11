"""Background worker for document ingestion.

Polls the job queue in Postgres, processes files concurrently using
asyncio with a configurable concurrency limit. Supports cancellation.

The worker runs as a separate pod and can be scaled horizontally.
"""

import asyncio
import logging
import os
import signal

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Graceful shutdown flag
_shutdown = False


def _handle_signal(sig, frame):
    global _shutdown
    logger.info("Shutdown signal received, finishing current jobs...")
    _shutdown = True


signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT, _handle_signal)


def get_concurrency() -> int:
    return int(os.getenv("WORKER_CONCURRENCY", "3"))


async def process_job(job_id: str, file_path: str, filename: str):
    """Process a single ingestion job."""
    from io import BytesIO

    from starlette.datastructures import UploadFile

    from app.db import get_conn
    from app.pg_store import PgStore
    from app.services import ingest_file_to_store

    store = PgStore()

    try:
        # Check for cancellation
        conn = get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT status FROM jobs WHERE job_id = %s", (job_id,))
            row = cur.fetchone()
            if row and row[0] == "cancelled":
                logger.info("Job %s was cancelled, skipping", job_id)
                conn.close()
                return
        conn.close()

        with open(file_path, "rb") as f:
            content = f.read()

        fake_file = UploadFile(filename=filename, file=BytesIO(content))
        result = await ingest_file_to_store(store, fake_file)

        # Update job with result metadata
        doc = store.get_document(result.document_id)
        category = doc.category if doc else "Uncategorized"
        doc_type = doc.document_type if doc else "general"

        conn = get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE jobs SET status = 'completed', category = %s, document_type = %s, document_id = %s WHERE job_id = %s",
                (category, doc_type, result.document_id, job_id),
            )
        conn.close()
        logger.info("Job %s completed: %s -> %s / %s", job_id, filename, category, doc_type)

    except Exception as e:
        logger.error("Job %s failed: %s", job_id, e)
        conn = get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE jobs SET status = %s WHERE job_id = %s",
                (f"failed: {str(e)[:200]}", job_id),
            )
        conn.close()


async def poll_and_process():
    """Main worker loop: poll for queued jobs and process them concurrently."""
    from app.db import get_conn

    concurrency = get_concurrency()
    semaphore = asyncio.Semaphore(concurrency)
    logger.info("Worker started (concurrency=%d, pid=%d)", concurrency, os.getpid())

    active: set = set()

    while not _shutdown:
        try:
            # How many slots are free?
            free = concurrency - len(active)
            if free <= 0:
                await asyncio.sleep(0.5)
                # Clean up finished tasks
                done = {t for t in active if t.done()}
                active -= done
                continue

            conn = get_conn()
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE jobs SET status = 'processing'
                       WHERE job_id IN (
                           SELECT job_id FROM jobs
                           WHERE status = 'queued' AND file_path IS NOT NULL
                           ORDER BY created_at ASC
                           LIMIT %s
                       )
                       RETURNING job_id, file_path, filename""",
                    (free,),
                )
                jobs = cur.fetchall()
            conn.close()

            if not jobs:
                # Clean up finished tasks
                done = {t for t in active if t.done()}
                active -= done
                await asyncio.sleep(1)
                continue

            for jid, fp, fn in jobs:
                async def _run(job_id, file_path, filename):
                    async with semaphore:
                        await process_job(job_id, file_path, filename)

                task = asyncio.create_task(_run(jid, fp, fn))
                active.add(task)

            # Brief pause before next poll
            await asyncio.sleep(0.5)
            # Clean up finished tasks
            done = {t for t in active if t.done()}
            active -= done

        except Exception as e:
            logger.error("Worker poll error: %s", e)
            await asyncio.sleep(5)

    logger.info("Worker shutting down gracefully")


def main():
    asyncio.run(poll_and_process())


if __name__ == "__main__":
    main()
