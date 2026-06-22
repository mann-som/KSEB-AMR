from Entity.meter import Meter
from logger import Logger
from DataGetter import DataGetter
import argparse
import sys

logger = Logger("MAIN-ETL")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--group", required=True)
    args = parser.parse_args()

    if not args.group:
        logger.error(
            message="No group in arguments",
            to_file=True
        )
        sys.exit()

    logger.info(
        message=f"Pipeline start - group {args.group}",
        to_file=True
    )
    meters_raw = DataGetter.get_meters(args.group)
    meters = []
    for m in meters_raw:
        meter = Meter(m)
        meters.append(meter)
    
    print(meters)
    print(type(meters))