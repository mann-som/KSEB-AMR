from DataGetter.DataGetter import get_timeout
from DataSetter.DataSetter import update_meter_status
from logger import Logger

logger = Logger("METER")

class Meter:
    
    def __init__(self, data: dict = None):
        
        if data:
            self.__dict__.update(data)
        self.arg = self.create_arg()
        
        self.timeout = 10
        try:
            self.timeout = get_timeout(self.METER_ID)
            logger.info(f"Timeout for meter {self.METER_ID}: {self.timeout}")
        except Exception as e:
            logger.error(f"Failed to get timeout for meter : {e}", meter_id=self.METER_ID)
    

    def create_arg(self):
        arg = [ 
                'main.py',
                '-h', 
                self.METER_STATIC_IP, 
                '-p', 
                self.PORT, 
                '-i', 
                self.INTERFACE, 
                '-c', 
                self.CLIENT_ADDRESS, 
                '-a', 
                self.AUTHENTICATION, 
                '-P', 
                self.PASSWORD, 
                '-g',
                '0.0.94.91.10.255:7', 
                '-d', 
                'India'
            ]
        return arg
    
    def update_status(self):
        update_meter_status(self.METER_ID)
    
    def __repr__(self):
        
        attrs = ', '.join(f"{k}={v!r}" for k, v in self.__dict__.items())
        return f"Meter({attrs})"
