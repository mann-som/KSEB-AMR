import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(BASE_DIR, "logs")
METER_DATA_DIR = os.path.join(BASE_DIR, "meter_data")
LOG_RETENTION_DAYS = 1



# MQTT CONFIG
BROKER = "samastharyana.org.in"
PORT = 8883
USERNAME = "reconnect"
PASSWORD = "reconnect"
TOPIC = "synergy/mqtt/hvpnl/dcu/meterdatazipped/_2115CCE"
INSTATOPIC = "synergy/mqtt/hvpnl/dcu/meterdata/_2115CCE"
CA_CERT = "MqttHandler/CLIENT_MQTT_CLIENT_31.crt"