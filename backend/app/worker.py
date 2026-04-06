"""Background worker process — placeholder for Phase 2 job processing."""

import time


def main() -> None:
    print("Worker started — waiting for jobs")
    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
