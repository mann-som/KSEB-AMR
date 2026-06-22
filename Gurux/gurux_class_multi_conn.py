#
#  --------------------------------------------------------------------------
#   Gurux Ltd
#
#
#
#  Filename: $HeadURL$
#
#  Version: $Revision$,
#                   $Date$
#                   $Author$
#
#  Copyright (c) Gurux Ltd
#
# ---------------------------------------------------------------------------
#
#   DESCRIPTION
#
#  This file is a part of Gurux Device Framework.
#
#  Gurux Device Framework is Open Source software; you can redistribute it
#  and/or modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; version 2 of the License.
#  Gurux Device Framework is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
#  See the GNU General Public License for more details.
#
#  More information of Gurux products: http://www.gurux.org
#
#  This code is licensed under the GNU General Public License v2.
#  Full text may be retrieved at http://www.gnu.org/licenses/gpl-2.0.txt
# ---------------------------------------------------------------------------
from gurux_serial import GXSerial
from gurux_net import GXNet
from gurux_dlms.enums import ObjectType
from gurux_dlms.objects.GXDLMSObjectCollection import GXDLMSObjectCollection
from gurux_dlms.objects.GXDLMSData import GXDLMSData
from gurux_dlms.objects.GXDLMSClock import GXDLMSClock
from gurux_dlms.enums.DataType import DataType
from gurux_dlms.objects.enums import SortMethod 
from gurux_dlms import (
    GXDLMSException,
    GXDLMSExceptionResponse,
    GXDLMSConfirmedServiceError,
)
from typing import List, Dict, Optional, Any
from gurux_dlms.GXDateTime import GXDateTime
from gurux_dlms.GXUInt32 import GXUInt32
 
from .GXSettings import GXSettings
from .GXDLMSReader import GXDLMSReader
import os
from logger import logger
from .utils import _extract_headers, _rows_to_records, _safe_close
import traceback
from datetime import datetime

try:
    import pkg_resources
except Exception:
    print("pkg_resources not found")


# BASE CLASS

class MeterReader:
    """
    Shared lifecycle for all profile reads.
 
    Subclasses override `_read_data` which receives an open, initialised
    (reader, settings, sn) and must return a list[dict] or raise.
    """
 
    PROFILE_NAME = "base"
 
    @classmethod
    def main(cls, args):  # type: (List[Any]) -> Optional[List[Dict[str, Any]]]
        """
        Entry point called by Task.execute().
        Returns a list of row-dicts on success, None on failure.
        """
        meter_ip = args[2] if len(args) > 2 else "unknown"
        logger.info(
            "[{}] Reading started — meter {}".format(cls.PROFILE_NAME, meter_ip),
            to_file=True,
        )
 
        reader = None
        settings = GXSettings()
 
        try:
            if settings.getParameters(args) != 0:
                logger.error(
                    "[{}] Failed to parse args for {}".format(cls.PROFILE_NAME, meter_ip),
                    to_file=True,
                )
                return None
 
            if not isinstance(settings.media, (GXSerial, GXNet)):
                raise ValueError("Unsupported media type: {}".format(type(settings.media)))
 
            reader = GXDLMSReader(
                settings.client,
                settings.media,
                settings.trace,
                settings.invocationCounter,
            )
            settings.media.open()
 
            if not settings.readObjects:
                logger.warning(
                    "[{}] No readObjects configured for {}".format(cls.PROFILE_NAME, meter_ip),
                    to_file=True,
                )
                return None
 
            reader.initializeConnection()
            reader.getAssociationView()
 
            sn_obj = settings.client.objects.findByLN(ObjectType.DATA, "0.0.96.1.0.255")
            sn = reader.read(sn_obj, 2) if sn_obj else "UNKNOWN_SN"
 
            result = cls._read_data(reader, settings, sn)
 
            if settings.outputFile:
                settings.client.objects.save(settings.outputFile)
 
            logger.info(
                "[{}] Read complete — meter {}, {} records".format(
                    cls.PROFILE_NAME,
                    meter_ip,
                    len(result) if result else 0,
                ),
                to_file=True,
            )
            return result
 
        except (
            ValueError,
            GXDLMSException,
            GXDLMSExceptionResponse,
            GXDLMSConfirmedServiceError,
        ) as ex:
            logger.error(
                "[{}] DLMS error on {}: {}".format(cls.PROFILE_NAME, meter_ip, ex),
                to_file=True,
            )
            logger.debug(traceback.format_exc(), to_file=True)
            return None
 
        except Exception as ex:
            logger.error(
                "[{}] Unexpected error on {}: {}".format(cls.PROFILE_NAME, meter_ip, ex),
                to_file=True,
            )
            logger.debug(traceback.format_exc(), to_file=True)
            return None
 
        finally:
            _safe_close(reader, settings)
            logger.info(
                "[{}] Connection closed — meter {}".format(cls.PROFILE_NAME, meter_ip),
                to_file=True,
            )


# COUNT BASED

class _CountProfileMixin:
    """
    Mixin for profiles that read the latest N rows by count.
    Subclasses set `OBIS` and optionally `DEFAULT_COUNT`.
    """
 
    OBIS = ""
    DEFAULT_COUNT = 10
 
    @classmethod
    def main(cls, args, count=None):  # type: (List[Any], Optional[int]) -> Optional[List[Dict[str, Any]]]
        cls._count = count if count is not None else cls.DEFAULT_COUNT
        return MeterReader.main.__func__(cls, args)  # type: ignore[attr-defined]
 
    @classmethod
    def _read_data(cls, reader, settings, sn):
        obj = settings.client.objects.findByLN(ObjectType.PROFILE_GENERIC, cls.OBIS)
        if obj is None:
            raise ValueError("Object not found: {}".format(cls.OBIS))
 
        headers = _extract_headers(reader.read(obj, 3))
        rows = reader.read(obj, 2)
        selected = rows[: cls._count]
 
        logger.debug(
            "[{}] {} rows available, returning first {}".format(cls.PROFILE_NAME, len(rows), len(selected)),
            to_file=True,
        )
        return _rows_to_records(selected, headers, str(sn), cls.OBIS)
    
# RANGE BASED

class _RangeProfileMixin:
    """
    Mixin for profiles that read rows within a datetime range.
    Subclasses set `OBIS`.
    """
 
    OBIS = ""
 
    @classmethod
    def main(
        cls,
        args,
        start,
        end,
    ):
        # type: (List[Any], datetime, datetime) -> Optional[List[Dict[str, Any]]]
        cls._start = start
        cls._end = end
        return MeterReader.main.__func__(cls, args) 
 
    @classmethod
    def _read_data(cls, reader, settings, sn):
        obj = settings.client.objects.findByLN(ObjectType.PROFILE_GENERIC, cls.OBIS)
        if obj is None:
            raise ValueError("Object not found: {}".format(cls.OBIS))
 
        headers = _extract_headers(reader.read(obj, 3))
        rows = reader.readRowsByRange(obj, cls._start, cls._end)
        # logger.debug("[{}] ROWS RECEIVED : {}".format(cls.PROFILE_NAME, rows))
 
        logger.debug(
            "[{}] Range {} → {}: {} rows".format(cls.PROFILE_NAME, cls._start, cls._end, len(rows)),
            to_file=True,
        )
        return _rows_to_records(rows, headers, str(sn), cls.OBIS)


class nameplate_profile(_CountProfileMixin, MeterReader):
    PROFILE_NAME = "nameplate"
    OBIS = "0.0.94.91.10.255"
    DEFAULT_COUNT = 1
 
 
class instantaneous_profile(_CountProfileMixin, MeterReader):
    PROFILE_NAME = "instantaneous"
    OBIS = "1.0.94.91.0.255"
    DEFAULT_COUNT = 1
 
 
class block_load_profile(_RangeProfileMixin, MeterReader):
    """Load survey / LSD """
    PROFILE_NAME = "block_load"
    OBIS = "1.0.99.1.0.255"
 
 
class daily_load_profile(_RangeProfileMixin, MeterReader):
    """Midnight / daily load profile."""
    PROFILE_NAME = "daily_load"
    OBIS = "1.0.99.2.0.255"
 
 
class billing_profile(_CountProfileMixin, MeterReader):
    """
    Billing profile — returns the last N complete billing cycles.
    """
    PROFILE_NAME = "billing"
    OBIS = "1.0.98.1.0.255"
    DEFAULT_COUNT = 6
 
    @classmethod
    def _read_data(cls, reader, settings, sn):
        obj = settings.client.objects.findByLN(ObjectType.PROFILE_GENERIC, cls.OBIS)
        if obj is None:
            raise ValueError("Object not found: {}".format(cls.OBIS))
 
        headers = _extract_headers(reader.read(obj, 3))
        rows = reader.read(obj, 2)
        sortMethod = reader.read(obj, 5)
        entryInUse = reader.read(obj, 7)
        
        if sortMethod == SortMethod.LIFO:
            selected = rows[:1]
            logger.info("Sorting method LIFO in billing")
        elif sortMethod == SortMethod.FIFO:
            selected = rows[-1:]
            logger.info("Sorting method FIFO in billing")
 
        logger.debug(
            "[billing] {} total rows, returning {} closed cycles".format(len(rows), len(selected)),
            to_file=True,
        )
        return _rows_to_records(selected, headers, str(sn), cls.OBIS)
    
class scalar_instantaneous_profile(_CountProfileMixin, MeterReader):
    """Scalar/unit descriptor for the instantaneous profile."""
    PROFILE_NAME = "scalar_instantaneous"
    OBIS = "1.0.94.91.3.255"
    DEFAULT_COUNT = 1
 
 
class scalar_block_load_profile(_CountProfileMixin, MeterReader):
    """Scalar/unit descriptor for the block load (LSD) profile."""
    PROFILE_NAME = "scalar_block_load"
    OBIS = "1.0.94.91.4.255"
    DEFAULT_COUNT = 1
 
 
class scalar_daily_load_profile(_CountProfileMixin, MeterReader):
    """Scalar/unit descriptor for the daily load (midnight) profile."""
    PROFILE_NAME = "scalar_daily_load"
    OBIS = "1.0.94.91.5.255"
    DEFAULT_COUNT = 1
 
 
class scalar_billing_profile(_CountProfileMixin, MeterReader):
    """Scalar/unit descriptor for the billing profile."""
    PROFILE_NAME = "scalar_billing"
    OBIS = "1.0.94.91.6.255"
    DEFAULT_COUNT = 1
 
 
class scalar_event_profile(_CountProfileMixin, MeterReader):
    """Scalar/unit descriptor for the event log profile."""
    PROFILE_NAME = "scalar_event"
    OBIS = "1.0.94.91.7.255"
    DEFAULT_COUNT = 1
 
 
class voltage_event_profile(_CountProfileMixin, MeterReader):
    """Voltage-related event log — most recent N events."""
    PROFILE_NAME = "voltage_event"
    OBIS = "0.0.99.98.0.255"
    DEFAULT_COUNT = 50
 
    @classmethod
    def _read_data(cls, reader, settings, sn):
        obj = settings.client.objects.findByLN(ObjectType.PROFILE_GENERIC, cls.OBIS)
        if obj is None:
            raise ValueError("Object not found: {}".format(cls.OBIS))
 
        headers = _extract_headers(reader.read(obj, 3))
        rows = reader.read(obj, 2)
        sortMethod = reader.read(obj, 5)
        entryInUse = reader.read(obj, 7)
 
        count = getattr(cls, "_count", cls.DEFAULT_COUNT)

        if sortMethod == SortMethod.LIFO:
            selected = rows[1:11]  # most-recent N
        elif sortMethod == SortMethod.FIFO:
            selected = rows[-10:]
 
        logger.debug(
            "[voltage_event] {} total, returning last {}".format(len(rows), len(selected)),
            to_file=True,
        )
        return _rows_to_records(selected, headers, str(sn), cls.OBIS)
 
 

# Write utilities 
 
def write_pcp_dip(
    reader,
    settings,
    pip = 1800,
    obis_code = "1.0.0.8.0.255",
):
    """Write a demand integration period (DIP) or profile capture period (PCP)."""
    try:
        obj = GXDLMSData(obis_code)
        obj.setDataType(2, DataType.UINT32)
        obj.value = GXUInt32(pip)
        reader.write(obj, 2)
        logger.info("write_pcp_dip: wrote {} to {}".format(pip, obis_code), to_file=True)
        return True
    except Exception as ex:
        logger.error("write_pcp_dip error ({}): {}".format(obis_code, ex), to_file=True)
        return False
 
 
def write_meter_time(reader):
    """Sync meter clock to system time."""
    try:
        now = datetime.now()
        clock = GXDLMSClock()
        clock.time = GXDateTime(now)
        reader.write(clock, 2)
        logger.info("write_meter_time: synced to {}".format(now.isoformat()), to_file=True)
        return True
    except Exception as ex:
        logger.error("write_meter_time error: {}".format(ex), to_file=True)
        return False
 
 
def read_meter_time(args):  # type: (List[Any]) -> Optional[datetime]
    """Read current clock from meter. Returns datetime or None."""
    meter_ip = args[2] if len(args) > 2 else "unknown"
    reader = None
    settings = GXSettings()
    try:
        if settings.getParameters(args) != 0:
            return None
        if not isinstance(settings.media, (GXSerial, GXNet)):
            raise ValueError("Unsupported media type")
 
        reader = GXDLMSReader(
            settings.client, settings.media, settings.trace, settings.invocationCounter
        )
        settings.media.open()
        reader.initializeConnection()
        reader.getAssociationView()
 
        clock_obj = settings.client.objects.findByLN(ObjectType.CLOCK, "0.0.1.0.0.255")
        result = reader.read(clock_obj, 2)
        logger.info("read_meter_time: {} → {}".format(meter_ip, result), to_file=True)
        return result
 
    except Exception as ex:
        logger.error("read_meter_time error ({}): {}".format(meter_ip, ex), to_file=True)
        return None
 
    finally:
        _safe_close(reader, settings)


