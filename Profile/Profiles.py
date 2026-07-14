# profiles.py
from enum import Enum
from dataclasses import dataclass
from typing import Optional
from Gurux.gurux_class_single_conn import (
    block_load_profile,
    daily_load_profile,
    instantaneous_profile,
    billing_profile,
    nameplate_profile,
    voltage_event_profile,
    scalar_instantaneous_profile,
    scalar_block_load_profile,
    scalar_daily_load_profile,
    scalar_billing_profile,
    scalar_event_profile,
)

@dataclass(frozen=True)
class ProfileMeta:
    display_name: str        
    obis: str               
    table_name: str         
    gurux_class: type        
    read_type: str           
    default_count: Optional[int] = None   

class Profile(Enum):
    BLOCK_LOAD              = ProfileMeta("Block Load Profile",            "1.0.99.1.0.255",    "01_00_63_01_00_FF", block_load_profile,             "range")
    DAILY_LOAD              = ProfileMeta("Daily Load Profile",            "1.0.99.2.0.255",    "01_00_63_02_00_FF", daily_load_profile,             "range")
    INSTANTANEOUS           = ProfileMeta("Instantaneous Profile",         "1.0.94.91.0.255",   "01_00_5E_5B_00_FF", instantaneous_profile,          "count", 1)
    BILLING                 = ProfileMeta("Billing Profile",               "1.0.98.1.0.255",    "01_00_62_01_00_FF", billing_profile,                "count", 6)
    NAMEPLATE               = ProfileMeta("Nameplate Profile",             "0.0.94.91.10.255",  "00_00_5E_5B_0A_FF", nameplate_profile,              "count", 1)
    VOLTAGE_EVENT           = ProfileMeta("Voltage Event Profile",         "0.0.99.98.0.255",   "00_00_63_62_00_FF", voltage_event_profile,          "count", 50)
    SCALAR_INSTANTANEOUS    = ProfileMeta("Scalar Instantaneous Profile",  "1.0.94.91.3.255",   "01_00_5E_5B_03_FF", scalar_instantaneous_profile,   "count", 1)
    SCALAR_BLOCK_LOAD       = ProfileMeta("Scalar Block Load Profile",     "1.0.94.91.4.255",   "01_00_5E_5B_04_FF", scalar_block_load_profile,      "count", 1)
    SCALAR_DAILY_LOAD       = ProfileMeta("Scalar Daily Load Profile",     "1.0.94.91.5.255",   "01_00_5E_5B_05_FF", scalar_daily_load_profile,      "count", 1)
    SCALAR_BILLING          = ProfileMeta("Scalar Billing Profile",        "1.0.94.91.6.255",   "01_00_5E_5B_06_FF", scalar_billing_profile,         "count", 1)
    SCALAR_EVENT            = ProfileMeta("Scalar Event Profile",          "1.0.94.91.7.255",   "01_00_5E_5B_07_FF", scalar_event_profile,           "count", 1)

    @property
    def meta(self):
        return self.value   # ProfileMeta instance