import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import SessionLocal
from app.services.alert import create_placement_reminder_alerts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-id", type=int, default=None)
    parser.add_argument("--company-id", type=int, default=None)
    args = parser.parse_args()

    with SessionLocal() as db:
        alerts = create_placement_reminder_alerts(
            db,
            project_id=args.project_id,
            company_id=args.company_id,
        )
        db.commit()
        print(
            json.dumps(
                {
                    "created_alert_count": len(alerts),
                    "alert_ids": [alert.id for alert in alerts],
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
