from DataBase.DataBase import configure, get_database, reload_config
from DataSetter import DataSetter
from logger import Logger

logger = Logger("DATA-GETTER")

def get_meters(group):
    
    db = get_database("kseb-prod")
    meters_data = []
    
    with db.cursor() as cursor:
        cursor.execute("""
            SELECT
                A.METER_ID,
                A.METER_SERIAL_NUMBER,
                A.`GROUPS`,
                A.METER_STATIC_IP,
                A.PORT,
                A.INTERFACE,
                A.CLIENT_ADDRESS,
                A.AUTHENTICATION,
                A.PASSWORD,
                B.LAST_EXC_TIMESTAMP,
                B.BILLING_STATUS
            FROM KSEB_HES_DR.RSM_METER_MASTER A
            LEFT JOIN KSEB_HES_DR.METER_READING_STATUS B
                ON B.METER_ID = A.METER_ID
            AND B.DELETE_STATUS = 0
            LEFT JOIN DATA_MASTER_CONTROL_READ R
                ON R.METER_ID = A.METER_ID
            AND R.TRANSACTION_STATUS = 0
            LEFT JOIN DATA_MASTER_CONTROL_WRITE W
                ON W.METER_ID = A.METER_ID
            AND W.TRANSACTION_STATUS = 0
            WHERE A.`GROUPS` = %s
            AND A.DELETE_STATUS = 0
            AND R.METER_ID IS NULL
            AND W.METER_ID IS NULL
            ORDER BY B.LAST_EXC_TIMESTAMP;
        """, (group,))
        
        rows = cursor.fetchall()
        
        column_names = [desc[0] for desc in cursor.description]
        
        for row in rows:
            meter_dict = dict(zip(column_names, row))
            meters_data.append(meter_dict)
    
    return meters_data


def get_timeout(meter_id):

    db = get_database("kseb-local")

    try:
        with db.cursor() as cursor:
            cursor.execute(f"SELECT MAX(TIMEOUT) FROM timeouts WHERE METER_ID = '{meter_id}'")
            result = cursor.fetchone()
            
            if result and result[0]:
                timeout_value = result[0]
                logger.info(f"Timeout retrieved for meter {meter_id}: {timeout_value}")
                return timeout_value
            else:
                logger.info(f"No timeout found for meter {meter_id}, setting default timeout")
                DataSetter.set_timeout(meter_id, timeout=10)
                return 10
            
    except Exception as e:
        logger.error(f"Error fetching timeout for meter {meter_id}: {str(e)}")
        return 10
        