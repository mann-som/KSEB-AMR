# task.py
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from Profile.Profiles import Profile, ProfileMeta
from Gurux.gurux_class_single_conn import MeterReader
from DataGetter.DataGetter import get_scalar   
from logger import Logger

logger = Logger("TASK")

DAILY_STATUS_THRESHOLD   = 60  
BILLING_STATUS_THRESHOLD = 5   

@dataclass
class ProfileTask:
    profile: Profile                    
    kwargs:  Dict[str, Any]             
    scalar:  Optional[Dict[str, Any]] = None   

@dataclass
class MeterTask:
    
    meter_id:  str
    meter_sn:  str
    meter_arg: List[Any]                     
    profiles:  List[ProfileTask] = field(default_factory=list)


    @classmethod
    def from_meter(cls, meter) -> "MeterTask":
        
        task = cls(
            meter_id=meter.METER_ID,
            meter_sn=meter.METER_SERIAL_NUMBER,
            meter_arg=meter.arg,
        )

        include_daily   = _should_include_daily(meter)
        include_billing = _should_include_billing(meter)

        instant_scalar = get_scalar(meter.METER_SERIAL_NUMBER, Profile.SCALAR_INSTANTANEOUS)
        if instant_scalar is None:
            task.profiles.append(ProfileTask(
                profile=Profile.SCALAR_INSTANTANEOUS,
                kwargs={"count": Profile.SCALAR_INSTANTANEOUS.meta.default_count},
            ))
        task.profiles.append(ProfileTask(
            profile=Profile.INSTANTANEOUS,
            kwargs={"count": Profile.INSTANTANEOUS.meta.default_count},
            scalar=instant_scalar,   
        ))

        block_scalar = get_scalar(meter.METER_SERIAL_NUMBER, Profile.SCALAR_BLOCK_LOAD)
        if block_scalar is None:
            task.profiles.append(ProfileTask(
                profile=Profile.SCALAR_BLOCK_LOAD,
                kwargs={"count": Profile.SCALAR_BLOCK_LOAD.meta.default_count},
            ))
        task.profiles.append(ProfileTask(
            profile=Profile.BLOCK_LOAD,
            kwargs={},   
            scalar=block_scalar,
        ))

        if include_daily:
            daily_scalar = get_scalar(meter.METER_SERIAL_NUMBER, Profile.SCALAR_DAILY_LOAD)
            if daily_scalar is None:
                task.profiles.append(ProfileTask(
                    profile=Profile.SCALAR_DAILY_LOAD,
                    kwargs={"count": Profile.SCALAR_DAILY_LOAD.meta.default_count},
                ))
            task.profiles.append(ProfileTask(
                profile=Profile.DAILY_LOAD,
                kwargs={},   
                scalar=daily_scalar,
            ))

        if include_billing:
            billing_scalar = get_scalar(meter.METER_SERIAL_NUMBER, Profile.SCALAR_BILLING)
            if billing_scalar is None:
                task.profiles.append(ProfileTask(
                    profile=Profile.SCALAR_BILLING,
                    kwargs={"count": Profile.SCALAR_BILLING.meta.default_count},
                ))
            task.profiles.append(ProfileTask(
                profile=Profile.BILLING,
                kwargs={"count": Profile.BILLING.meta.default_count},
                scalar=billing_scalar,
            ))

        logger.info(
            f"[Task] Meter {meter.METER_ID} → "
            f"{[pt.profile.name for pt in task.profiles]}"
        )
        return task


    def execute(
        self,
        start: datetime,
        end:   datetime,
    ) -> Dict[str, Any]:
        """
        Open ONE connection to the meter and read all decided profiles.

        start / end  — window for range-based profiles (block load, daily load).
                       Typically: end=now, start=end-24h or similar.

        Returns a dict with one entry per profile read, keyed by PROFILE_NAME,
        plus an extra key "scalar_cache" that maps each data profile name to
        its scalar payload. If the scalar was already found in the DB, that
        cached dict is used; otherwise the scalar fetched from the meter is
        stored there as well.
        """
        
        read_list: List[Tuple[type, Dict[str, Any]]] = []

        for pt in self.profiles:
            meta: ProfileMeta = pt.profile.meta
            kwargs = dict(pt.kwargs)   

            if meta.read_type == "range":
                kwargs["start"] = start
                kwargs["end"]   = end

            read_list.append((meta.gurux_class, kwargs))

        logger.info(
            f"[Task] execute() — meter {self.meter_id}, "
            f"{len(read_list)} profiles, window {start} → {end}"
        )

        raw = MeterReader.read_multi(self.meter_arg, read_list)

        if raw is None:
            logger.error(f"[Task] Connection failed for meter {self.meter_id}")
            return {}

        
        scalar_cache: Dict[str, Optional[Dict[str, Any]]] = {}
        for pt in self.profiles:
            data_profile_name = _scalar_to_data_profile(pt.profile)
            if not data_profile_name:
                continue

            if pt.scalar is not None:
                scalar_cache[data_profile_name] = pt.scalar
                continue

            scalar_profile_name = pt.profile.meta.gurux_class.PROFILE_NAME
            fetched_scalar = raw.get(scalar_profile_name) if isinstance(raw, dict) else None
            if isinstance(fetched_scalar, list) and fetched_scalar:
                scalar_record = fetched_scalar[0]
                if isinstance(scalar_record, dict):
                    scalar_cache[data_profile_name] = {
                        key: value
                        for key, value in scalar_record.items()
                        if key not in {"serial_number", "obis"}
                    }
                else:
                    scalar_cache[data_profile_name] = None
            else:
                scalar_cache[data_profile_name] = None

        raw["scalar_cache"] = scalar_cache  
        return raw

    

    def __repr__(self) -> str:
        names = [pt.profile.name for pt in self.profiles]
        return f"MeterTask(meter_id={self.meter_id!r}, profiles={names})"



def _should_include_daily(meter) -> bool:
    status = getattr(meter, "DAILY_STATUS", None)
    if status is None:
        return True   
    try:
        return int(status) < DAILY_STATUS_THRESHOLD
    except (TypeError, ValueError):
        return True


def _should_include_billing(meter) -> bool:
    status = getattr(meter, "BILLING_STATUS", None)
    if status is None:
        return True
    try:
        return int(status) < BILLING_STATUS_THRESHOLD
    except (TypeError, ValueError):
        return True


def _scalar_to_data_profile(profile: Profile) -> Optional[str]:
    
    _map = {
        Profile.SCALAR_INSTANTANEOUS: Profile.INSTANTANEOUS.meta.gurux_class.PROFILE_NAME,
        Profile.SCALAR_BLOCK_LOAD:    Profile.BLOCK_LOAD.meta.gurux_class.PROFILE_NAME,
        Profile.SCALAR_DAILY_LOAD:    Profile.DAILY_LOAD.meta.gurux_class.PROFILE_NAME,
        Profile.SCALAR_BILLING:       Profile.BILLING.meta.gurux_class.PROFILE_NAME,
    }
    return _map.get(profile)