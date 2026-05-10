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
    """Get the configured max concurrent file processing."""
    return int(os.getenv("WORKER_CONCURRENCY", "3"))


async def process_job(job_id: str, file_path: str, filename: str):
    """Process a single ingestion job."""
    from io import BytesIO

    from starlette.datastructures import UploadFile

    from app.pg_store import PgStore
    from app.services import ingest_file_to_store

    store = PgStore()

    try:
        # Update status
        from app.db import get_conn

        conn = get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE jobs SET status = 'processing' WHERE job_id = %s",
                (job_id,),
            )
        conn.close()

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

        # Read file and process
        with open(file_path, "rb") as f:
            content = f.read()

        fake_file = UploadFile(filename=filename, file=BytesIO(content))
        await ingest_file_to_store(store, fake_file)

        # Mark complete
        conn = get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE jobs SET status = 'completed' WHERE job_id = %s",
                (job_id,),
            )
        conn.close()
        logger.info("Job %s completed: %s", job_id, filename)

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
    logger.info(
        "Worker started (concurrency=%d, pid=%d)",
        concurrency,
        os.getpid(),
    )

    while not _shutdown:
        try:
            # Fetch queued jobs
            conn = get_conn()
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT job_id, status FROM jobs
                       WHERE status = 'queued'
                       ORDER BY created_at ASC
                       LIMIT %s""",
                    (concurrency,),
                )
                jobs = cur.fetchall()
            conn.close()

            if not jobs:
                await asyncio.sleep(2)
                continue

            # Process jobs concurrently up to the semaphore limit
            async def _run(job_id, file_path, filename):
                async with semaphore:
                    await process_job(job_id, file_path, filename)

            tasks = []
            for job_id, _ in jobs:
                # For now, jobs from the SSE endpoint are processed inline
                # This worker handles jobs queued via the bulk/async path
                # We'll need to store file_path in the jobs table
                tasks.append(
                    asyncio.create_task(process_job(job_id, "", "")),
                )

            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

        except Exception as e:
            logger.error("Worker poll error: %s", e)
            await asyncio.sleep(5)

    logger.info("Worker shutting down gracefully")


def main():
    asyncio.run(poll_and_process())


if __name__ == "__main__":
    main()
