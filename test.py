import sys
from pathlib import Path

# Ensure the project root is on sys.path so imports work when running this script.
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from DataBase.DataBase import configure, get_database, reload_config
from DataGetter.DataGetter import get_meters
from Entity.meter import Meter
from logger import Logger

logger = Logger("test")

def test_database(db_name: str = "kseb-local"):
    # configure(config_path)
    db = get_database(db_name)

    print("Loaded database:", db)
    print("Database type:", db.db_type)

    try:
        with db.cursor() as cur:
            if db.db_type == "mysql":
                cur.execute("SELECT VERSION()")
            else:
                cur.execute("SELECT 1")

            try:
                rows = cur.fetchall()
            except Exception:
                rows = None

            print("Sample query executed successfully.")
            if rows is not None:
                print("Result:", rows)

    except Exception as exc:
        print("Database cursor test failed:", exc)
        raise


def test_reload(db_name: str = "kseb-local"):
    reload_config()
    print("Reloaded database configuration.")
    db = get_database(db_name)
    print("Loaded database after reload:", db)


def test_get_meters(group: str = "A"):
   
    print(f"\n--- Testing get_meters for group '{group}' ---")
    
    try:
        
        meters_data = get_meters(group)
        print(f"Successfully fetched {len(meters_data)} meter(s)")
       
        meters_list = []
        if meters_data:
            print("\nCreating Meter objects and displaying details:")
            print("-" * 100)
            for idx, meter_data in enumerate(meters_data, 1):
                # Create Meter object by passing the dictionary
                meter = Meter(meter_data)
                meters_list.append(meter)
                
                print(f"\nMeter {idx}:")
                print(f"  ID: {getattr(meter, 'METER_ID', 'N/A')}")
                print(f"  Serial Number: {getattr(meter, 'METER_SERIAL_NUMBER', 'N/A')}")
                print(f"  Group: {getattr(meter, 'GROUPS', 'N/A')}")
                print(f"  IP: {getattr(meter, 'METER_STATIC_IP', 'N/A')}")
                print(f"  Port: {getattr(meter, 'PORT', 'N/A')}")
                print(f"  Interface: {getattr(meter, 'INTERFACE', 'N/A')}")
                print(f"  Client Address: {getattr(meter, 'CLIENT_ADDRESS', 'N/A')}")
                print(f"  Authentication: {getattr(meter, 'AUTHENTICATION', 'N/A')}")
                print(f"  Password: {getattr(meter, 'PASSWORD', 'N/A')}")
                print(f"  Last Execution Timestamp: {getattr(meter, 'LAST_EXC_TIMESTAMP', 'N/A')}")
                print(f"  Billing Status: {getattr(meter, 'BILLING_STATUS', 'N/A')}")
                logger.info(f"{meter.arg}")
                logger.info(f"{meter.METER_ID} timeout -> {meter.timeout}")
                meter.update_status()
                
            print("-" * 100)
        else:
            print(f"No meters found for group '{group}'")
            
        return meters_list
        
    except Exception as exc:
        print(f"Error fetching meters: {exc}")
        raise


if __name__ == "__main__":
    # config_path = PROJECT_ROOT / "DataBase" / "config.yaml"
    # print("Testing database configuration at", config_path)

    # if not config_path.exists():
    #     raise FileNotFoundError(f"Database config not found: {config_path}")

    test_database()
    test_reload()
    
    # Test get_meters function and create Meter objects
    meters_list = test_get_meters(group="A")
    
    print("\n--- Summary ---")
    print(f"Total meters retrieved: {len(meters_list)}")
    if meters_list:
        print(f"First meter object: {meters_list[0]}")
        print(f"Meter type: {type(meters_list[0]).__name__}")
    print("Database tests completed.")

