import argparse
import sys
from pathlib import Path
from typing import List

# Ensure the project root is on sys.path so imports work when running this script.
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from DataBase.DataBase import configure, get_database, reload_config
from DataGetter.DataGetter import get_meters
from Entity.meter import Meter
from logger import Logger
from main import ETL

logger = Logger("test")


def print_section(title: str) -> None:
    print("\n" + "=" * 90)
    print(title)
    print("=" * 90)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run smoke tests for the AMR pipeline")
    parser.add_argument("--group", default="A", help="Meter group to test")
    parser.add_argument("--limit", type=int, default=5, help="Number of meters to inspect")
    parser.add_argument("--config", default=None, help="Optional path to DB config YAML")
    parser.add_argument("--verbose", action="store_true", help="Print extra meter and ETL details")
    parser.add_argument("--skip-db", action="store_true", help="Skip the database connectivity check")
    parser.add_argument("--skip-meters", action="store_true", help="Skip meter discovery")
    parser.add_argument("--skip-etl", action="store_true", help="Skip ETL smoke test")
    return parser.parse_args()


def test_database(db_name: str = "kseb-local", verbose: bool = False) -> None:
    print_section(f"Database connectivity: {db_name}")
    db = get_database(db_name)

    print("Loaded database:", db)
    print("Database type:", db.db_type)

    try:
        with db.cursor() as cur:
            if db.db_type == "mysql":
                cur.execute("SELECT VERSION()")
            else:
                cur.execute("SELECT 1")

            rows = None
            try:
                rows = cur.fetchall()
            except Exception:
                rows = None

            print("Sample query executed successfully.")
            if verbose and rows is not None:
                print("Result:", rows)
    except Exception as exc:
        print("Database cursor test failed:", exc)
        raise


def test_reload(db_name: str = "kseb-local") -> None:
    print_section("Reload database config")
    reload_config()
    print("Reloaded database configuration.")
    db = get_database(db_name)
    print("Loaded database after reload:", db)


def test_get_meters(group: str = "A", limit: int = 5, verbose: bool = False) -> List[dict]:
    print_section(f"Meter discovery for group '{group}'")

    try:
        meters_data = get_meters(group)
        print(f"Successfully fetched {len(meters_data)} meter(s)")

        if not meters_data:
            print(f"No meters found for group '{group}'")
            return []

        selected = meters_data[:limit]
        print(f"Inspecting first {len(selected)} meter(s)")
        for idx, meter_data in enumerate(selected, 1):
            print(f"\n[{idx}] Meter payload:")
            if verbose:
                print(meter_data)
            else:
                print({
                    "METER_ID": meter_data.get("METER_ID"),
                    "METER_SERIAL_NUMBER": meter_data.get("METER_SERIAL_NUMBER"),
                    "GROUPS": meter_data.get("GROUPS"),
                    "METER_STATIC_IP": meter_data.get("METER_STATIC_IP"),
                    "PORT": meter_data.get("PORT"),
                    "INTERFACE": meter_data.get("INTERFACE"),
                })

        return selected
    except Exception as exc:
        print(f"Error fetching meters: {exc}")
        raise


def test_meter_objects(meters_data: List[dict], verbose: bool = False) -> List[Meter]:
    print_section("Meter object initialization")
    meters_list: List[Meter] = []

    for idx, meter_data in enumerate(meters_data, 1):
        meter = Meter(meter_data)
        meters_list.append(meter)

        print(f"[{idx}] Meter ID: {getattr(meter, 'METER_ID', 'N/A')}")
        print(f"    Serial Number: {getattr(meter, 'METER_SERIAL_NUMBER', 'N/A')}")
        print(f"    IP: {getattr(meter, 'METER_STATIC_IP', 'N/A')}")
        print(f"    Timeout: {getattr(meter, 'timeout', 'N/A')}")
        if verbose:
            print(f"    Args: {meter.arg}")

    return meters_list


def run_etl_smoke(meters_data: List[dict], limit: int = 1, verbose: bool = False) -> List[dict]:
    print_section("ETL smoke test")
    results = []

    for idx, meter_data in enumerate(meters_data[:limit], 1):
        meter = Meter(meter_data)
        print(f"[{idx}] Running ETL for meter {meter.METER_ID}")
        etl = ETL(meter)
        result = etl.run()
        print(f"    Loaded: {result.get('loaded')}")
        print(f"    Data keys: {list(result.get('data', {}).keys()) if isinstance(result.get('data'), dict) else None}")
        if verbose:
            print(f"    Result payload: {result}")
        results.append(result)

    return results


def main() -> None:
    args = parse_args()

    if args.config:
        configure(args.config)

    if not args.skip_db:
        test_database(verbose=args.verbose)
        test_reload()

    if args.skip_meters:
        print("Skipping meter discovery per CLI flags.")
        return

    meters_data = test_get_meters(group=args.group, limit=args.limit, verbose=args.verbose)
    if not meters_data:
        print("No meter data available; stopping here.")
        return

    meters_list = test_meter_objects(meters_data, verbose=args.verbose)
    if not args.skip_etl:
        results = run_etl_smoke(meters_data, limit=min(1, len(meters_data)), verbose=args.verbose)
    else:
        results = []

    print_section("Summary")
    print(f"Meters discovered: {len(meters_data)}")
    print(f"Meter objects created: {len(meters_list)}")
    print(f"ETL runs executed: {len(results)}")
    if results:
        print("First ETL result:")
        print(results[0])
    print("Smoke test completed.")


if __name__ == "__main__":
    main()

