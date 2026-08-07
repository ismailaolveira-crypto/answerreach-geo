import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import models  # noqa: F401
from app.db.session import Base, SessionLocal, engine
from app.services.crawl_scheduler import run_due_crawl_schedules


def main() -> None:
    parser = argparse.ArgumentParser(description="Run due GEO crawl schedules.")
    parser.add_argument("--project-id", type=int, default=None, help="Limit execution to one project.")
    args = parser.parse_args()

    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        checked_at, tasks = run_due_crawl_schedules(db, project_id=args.project_id)
        print(
            json.dumps(
                {
                    "checked_at": checked_at.isoformat(),
                    "due_schedule_count": len(tasks),
                    "task_ids": [task.id for task in tasks],
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
