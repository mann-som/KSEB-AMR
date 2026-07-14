from DataBase.DataBase import get_database
from logger import Logger
from datetime import datetime, timedelta

logger = Logger("DATA-SETTER")


def set_timeout(meter_id, timeout=10):

    db = get_database("kseb-local")

    try:
        with db.cursor() as cursor:
            last_error = None
            for table_name in ("timeout", "timeouts"):
                try:
                    cursor.execute(
                        f"INSERT INTO {table_name} (METER_ID, timeout) VALUES (?, ?)",
                        (meter_id, timeout),
                    )
                    rows = cursor.rowcount
                    logger.info(
                        message=f"Timeout set successfully for meter {meter_id} with value {timeout}. Rows affected: {rows}",
                        meter_id=meter_id,
                        to_file=True,
                    )
                    return True
                except Exception as exc:
                    last_error = exc
                    continue

            raise last_error or RuntimeError("Unable to write timeout")

    except Exception as e:
        logger.error(
            message=f"Error setting timeout for meter {meter_id}: {str(e)}",
            meter_id=meter_id,
            to_file=True,
        )
        return False
    

def update_meter_status(meter_id):
    
    db = get_database("kseb-prod")

    try:
        today = datetime.now().replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0
        )

        daily_start = today - timedelta(days=59)
        billing_end = today.replace(day=1)
        billing_month = billing_end.month - 4
        billing_year = billing_end.year

        while billing_month <= 0:
            billing_month += 12
            billing_year -= 1

        billing_start = billing_end.replace(
            year=billing_year,
            month=billing_month
        )

        with db.cursor() as cursor:

            query = """
                UPDATE METER_READING_STATUS mrs
                SET
                    DAILY_STATUS = (
                        SELECT COUNT(*)
                        FROM `01_00_63_02_00_FF` d
                        WHERE d.METER_ID = %s
                        AND d.`00_00_01_00_00_FF` >= %s
                        AND d.`00_00_01_00_00_FF` <= %s
                    ),

                    BILLING_STATUS = (
                        SELECT COUNT(*)
                        FROM `01_00_62_01_00_FF` b
                        WHERE b.METER_ID = %s
                        AND b.`00_00_00_01_02_FF` >= %s
                        AND b.`00_00_00_01_02_FF` <= %s
                    ),

                    UPDATED_TIMESTAMP = CURRENT_TIMESTAMP,
                    LAST_EXC_TIMESTAMP = CURRENT_TIMESTAMP

                WHERE mrs.METER_ID = %s
            """

            values = (
                meter_id,
                daily_start,
                today,

                meter_id,
                billing_start,
                billing_end,

                meter_id
            )

            cursor.execute(query, values)
            rows = cursor.rowcount

            logger.info(
                message="Read status updated",
                meter_id=meter_id,
                to_file=True
            )

    except Exception as e:
        logger.error(
            message=f"Read status update failed : {e}",
            meter_id=meter_id,
            to_file=True
        )