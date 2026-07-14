from datetime import datetime, timedelta

from Entity.meter import Meter
from logger import Logger
from DataGetter import DataGetter
import argparse
import sys
from Task.Task import MeterTask

logger = Logger("MAIN-ETL")

class ETL:

    DAILY_RANGE_DAYS = 30

    def __init__(self, meter):
        self.meter = meter
        self.task: MeterTask | None = None
        self.raw_data: dict | None = None
        self.transformed_data: dict | None = None

    def create_task(self) -> MeterTask:
        self.task = MeterTask.from_meter(self.meter)
        return self.task

    def build_time_window(self) -> tuple[datetime, datetime]:
        now = datetime.now()
        start = (now - timedelta(days=self.DAILY_RANGE_DAYS)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        return start, now

    def extract(self) -> dict:
        if self.task is None:
            self.create_task()

        start, end = self.build_time_window()
        logger.info(
            message=f"Extracting meter {self.meter.METER_ID} from {start} to {end}",
            to_file=True,
        )
        self.raw_data = self.task.execute(start, end)
        return self.raw_data or {}

    def transform(self) -> dict:
        if not self.raw_data:
            logger.warning(
                message=f"No raw data available for meter {self.meter.METER_ID}",
                to_file=True,
            )
            self.transformed_data = {}
            return self.transformed_data

        profile_counts = {
            profile_name: len(records) if isinstance(records, list) else 0
            for profile_name, records in self.raw_data.items()
            if profile_name != "scalar_cache"
        }

        self.transformed_data = {
            "meter_id": self.meter.METER_ID,
            "meter_sn": self.meter.METER_SERIAL_NUMBER,
            "profiles": self.raw_data,
            "profile_counts": profile_counts,
        }
        return self.transformed_data

    def load(self) -> bool:
        if not self.transformed_data:
            logger.error(
                message=f"Nothing to load for meter {self.meter.METER_ID}",
                to_file=True,
            )
            return False

        try:
            self.meter.update_status()
            logger.info(
                message=f"Loaded meter {self.meter.METER_ID}",
                to_file=True,
            )
            return True
        except Exception as exc:
            logger.error(
                message=f"Failed to load meter {self.meter.METER_ID}: {exc}",
                to_file=True,
            )
            return False

    def run(self) -> dict:
        self.create_task()
        self.extract()
        self.transform()
        loaded = self.load()
        return {
            "meter_id": self.meter.METER_ID,
            "loaded": loaded,
            "data": self.transformed_data,
        }

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the AMR ETL pipeline for a meter group")
    parser.add_argument("--group", default="A", help="Meter group to process")
    parser.add_argument("--limit", type=int, default=None, help="Optional maximum number of meters to process")
    parser.add_argument("--verbose", action="store_true", help="Print extra debug information")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and print meter metadata without running ETL")
    parser.add_argument("--show-meters", action="store_true", help="Print the full meter payloads before ETL")
    args = parser.parse_args()

    if not args.group:
        logger.error(message="No group in arguments", to_file=True)
        sys.exit()

    logger.info(message=f"Pipeline start - group {args.group}", to_file=True)
    meters_raw = DataGetter.get_meters(args.group)
    print(f"[MAIN] Discovered {len(meters_raw)} meter(s) for group '{args.group}'")

    if args.limit is not None:
        meters_raw = meters_raw[: args.limit]
        print(f"[MAIN] Processing first {len(meters_raw)} meter(s) because --limit={args.limit}")

    meters = []
    for m in meters_raw:
        meter = Meter(m)
        meters.append(meter)

        if args.show_meters or args.verbose:
            print(f"[MAIN] Meter ready: {getattr(meter, 'METER_ID', 'N/A')} / {getattr(meter, 'METER_SERIAL_NUMBER', 'N/A')}")
            if args.show_meters:
                print(f"[MAIN] Meter payload: {m}")

    if args.dry_run:
        print("[MAIN] Dry run complete; ETL was not executed.")
        sys.exit(0)

    results = []
    for idx, meter in enumerate(meters, 1):
        try:
            print(f"[MAIN] Running ETL {idx}/{len(meters)} for meter {meter.METER_ID}")
            etl = ETL(meter)
            result = etl.run()
            if args.verbose:
                print(f"[MAIN] ETL result for {meter.METER_ID}: {result}")
            results.append(result)
        except Exception as exc:
            logger.error(message=f"ETL failed for meter {meter.METER_ID}: {exc}", to_file=True)
            results.append({"meter_id": meter.METER_ID, "loaded": False, "error": str(exc)})

    print("[MAIN] Summary")
    print(results)
    print(type(meters))