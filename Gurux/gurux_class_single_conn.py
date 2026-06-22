#
#  --------------------------------------------------------------------------
#   Gurux Ltd
#
#  Copyright (c) Gurux Ltd
#  GNU General Public License v2 — http://www.gnu.org/licenses/gpl-2.0.txt
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
from typing import List, Dict, Optional, Any, Tuple
from gurux_dlms.GXDateTime import GXDateTime
from gurux_dlms.GXUInt32 import GXUInt32

from .GXSettings import GXSettings
from .GXDLMSReader import GXDLMSReader
from logger import logger
from .utils import _extract_headers, _rows_to_records, _safe_close
import traceback
import signal
from datetime import datetime

try:
    import pkg_resources
except Exception:
    print("pkg_resources not found")


CONNECT_TIMEOUT_MS = 10_000   # GXNet media timeout in milliseconds
CONNECT_TIMEOUT_S  = 10       # GXSerial media timeout in seconds
READ_TIMEOUT_S     = 30       # per-profile SIGALRM budget


class _ReadTimeout(Exception):
    """Raised by SIGALRM when a single profile read takes too long."""


def _alarm_handler(signum, frame):
    raise _ReadTimeout("Read exceeded {} seconds".format(READ_TIMEOUT_S))


def _set_read_timeout():
    """Arm SIGALRM for READ_TIMEOUT_S seconds."""
    signal.signal(signal.SIGALRM, _alarm_handler)
    signal.alarm(READ_TIMEOUT_S)


def _clear_read_timeout():
    """Disarm SIGALRM."""
    signal.alarm(0)


class MeterReader:
    """
    Shared lifecycle for single-profile reads.

    Subclasses override `_read_data(reader, settings, sn, **kwargs)` and must
    return list[dict] or raise.

    For reading multiple profiles in one connection use `MeterReader.read_multi`.
    """

    PROFILE_NAME = "base"

    # ------------------------------------------------------------------
    # Internal: open connection with timeout applied to media
    # ------------------------------------------------------------------

    @staticmethod
    def _open_connection(args):
        # type: (List[Any]) -> Tuple[GXDLMSReader, GXSettings]
        """
        Parse args, apply media timeouts, open media, handshake.
        Returns (reader, settings) on success, raises on failure.
        Caller is responsible for closing via _safe_close.
        """
        settings = GXSettings()
        if settings.getParameters(args) != 0:
            raise ValueError("Failed to parse args")

        if not isinstance(settings.media, (GXSerial, GXNet)):
            raise ValueError("Unsupported media type: {}".format(type(settings.media)))

        if isinstance(settings.media, GXNet):
            settings.media.timeout = CONNECT_TIMEOUT_MS
        else:
            settings.media.timeout = CONNECT_TIMEOUT_S

        reader = GXDLMSReader(
            settings.client,
            settings.media,
            settings.trace,
            settings.invocationCounter,
        )

        settings.media.open()          # raises on connect failure/timeout
        reader.initializeConnection()  # DLMS handshake
        reader.getAssociationView()    # fetch object catalog

        return reader, settings

    # ------------------------------------------------------------------
    # Single-profile entry point (backward-compatible with Task.execute)
    # ------------------------------------------------------------------

    @classmethod
    def main(cls, args, **kwargs):
        # type: (List[Any], Any) -> Optional[List[Dict[str, Any]]]
        """
        Entry point for a single profile read.
        kwargs are forwarded to _read_data (count / start+end).
        """
        meter_ip = args[2] if len(args) > 2 else "unknown"
        logger.info(
            "[{}] Reading started — meter {}".format(cls.PROFILE_NAME, meter_ip),
            to_file=True,
        )

        reader = None
        settings = None

        try:
            reader, settings = MeterReader._open_connection(args)

            if not settings.readObjects:
                logger.warning(
                    "[{}] No readObjects configured for {}".format(cls.PROFILE_NAME, meter_ip),
                    to_file=True,
                )
                return None

            sn_obj = settings.client.objects.findByLN(ObjectType.DATA, "0.0.96.1.0.255")
            sn = reader.read(sn_obj, 2) if sn_obj else "UNKNOWN_SN"

            _set_read_timeout()
            try:
                result = cls._read_data(reader, settings, sn, **kwargs)
            finally:
                _clear_read_timeout()

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

        except _ReadTimeout as ex:
            logger.error(
                "[{}] Read timeout on {}: {}".format(cls.PROFILE_NAME, meter_ip, ex),
                to_file=True,
            )
            return None

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


    @staticmethod
    def read_multi(args, profiles):
        # type: (List[Any], List[Tuple[type, Dict[str, Any]]]) -> Dict[str, Optional[List[Dict[str, Any]]]]
        """
        Connect once to a meter and read multiple profiles.

        profiles is a list of (profile_class, kwargs) tuples, e.g.:

            results = MeterReader.read_multi(args, [
                (block_load_profile,  {"start": t1, "end": t2}),
                (daily_load_profile,  {"start": t1, "end": t2}),
                (billing_profile,     {"count": 3}),
                (instantaneous_profile, {"count": 1}),
            ])

        Returns dict keyed by PROFILE_NAME.
        Each value is list[dict] on success, None if that profile failed.
        Returns None entirely if the connection itself fails.
        """
        meter_ip = args[2] if len(args) > 2 else "unknown"
        logger.info(
            "[read_multi] Starting {} profiles — meter {}".format(len(profiles), meter_ip),
            to_file=True,
        )

        reader = None
        settings = None
        results = {}

        try:
            reader, settings = MeterReader._open_connection(args)

            if not settings.readObjects:
                logger.warning(
                    "[read_multi] No readObjects configured for {}".format(meter_ip),
                    to_file=True,
                )
                return None

            sn_obj = settings.client.objects.findByLN(ObjectType.DATA, "0.0.96.1.0.255")
            sn = reader.read(sn_obj, 2) if sn_obj else "UNKNOWN_SN"

            for profile_cls, kwargs in profiles:
                name = profile_cls.PROFILE_NAME
                logger.info(
                    "[read_multi] Reading {} — meter {}".format(name, meter_ip),
                    to_file=True,
                )
                _set_read_timeout()
                try:
                    results[name] = profile_cls._read_data(reader, settings, sn, **kwargs)
                    logger.info(
                        "[read_multi] {} done — {} records".format(
                            name, len(results[name]) if results[name] else 0
                        ),
                        to_file=True,
                    )
                except _ReadTimeout as ex:
                    logger.error(
                        "[read_multi] Timeout on {} for {}: {}".format(name, meter_ip, ex),
                        to_file=True,
                    )
                    results[name] = None
                except (
                    GXDLMSException,
                    GXDLMSExceptionResponse,
                    GXDLMSConfirmedServiceError,
                    ValueError,
                ) as ex:
                    logger.error(
                        "[read_multi] DLMS error on {} for {}: {}".format(name, meter_ip, ex),
                        to_file=True,
                    )
                    logger.debug(traceback.format_exc(), to_file=True)
                    results[name] = None
                except Exception as ex:
                    logger.error(
                        "[read_multi] Unexpected error on {} for {}: {}".format(name, meter_ip, ex),
                        to_file=True,
                    )
                    logger.debug(traceback.format_exc(), to_file=True)
                    results[name] = None
                finally:
                    _clear_read_timeout()

            if settings.outputFile:
                settings.client.objects.save(settings.outputFile)

        except Exception as ex:
            logger.error(
                "[read_multi] Connection failed for {}: {}".format(meter_ip, ex),
                to_file=True,
            )
            logger.debug(traceback.format_exc(), to_file=True)
            return None

        finally:
            _safe_close(reader, settings)
            logger.info(
                "[read_multi] Connection closed — meter {}".format(meter_ip),
                to_file=True,
            )

        return results



class _CountProfileMixin:
    """
    Mixin for profiles that read the latest N rows by count.
    Subclasses set OBIS and optionally DEFAULT_COUNT.
    """

    OBIS = ""
    DEFAULT_COUNT = 10

    @classmethod
    def main(cls, args, count=None):
        # type: (List[Any], Optional[int]) -> Optional[List[Dict[str, Any]]]
        return MeterReader.main.__func__(cls, args, count=count)  # type: ignore[attr-defined]

    @classmethod
    def _read_data(cls, reader, settings, sn, count=None, **_ignored):
        count = count if count is not None else cls.DEFAULT_COUNT
        obj = settings.client.objects.findByLN(ObjectType.PROFILE_GENERIC, cls.OBIS)
        if obj is None:
            raise ValueError("Object not found: {}".format(cls.OBIS))

        headers = _extract_headers(reader.read(obj, 3))
        rows = reader.read(obj, 2)
        selected = rows[:count]

        logger.debug(
            "[{}] {} rows available, returning first {}".format(
                cls.PROFILE_NAME, len(rows), len(selected)
            ),
            to_file=True,
        )
        return _rows_to_records(selected, headers, str(sn), cls.OBIS)



class _RangeProfileMixin:
    """
    Mixin for profiles that read rows within a datetime range.
    Subclasses set OBIS.
    """

    OBIS = ""

    @classmethod
    def main(cls, args, start, end):
        # type: (List[Any], datetime, datetime) -> Optional[List[Dict[str, Any]]]
        return MeterReader.main.__func__(cls, args, start=start, end=end)  # type: ignore[attr-defined]

    @classmethod
    def _read_data(cls, reader, settings, sn, start=None, end=None, **_ignored):
        if start is None or end is None:
            raise ValueError("[{}] start and end are required".format(cls.PROFILE_NAME))

        obj = settings.client.objects.findByLN(ObjectType.PROFILE_GENERIC, cls.OBIS)
        if obj is None:
            raise ValueError("Object not found: {}".format(cls.OBIS))

        headers = _extract_headers(reader.read(obj, 3))
        rows = reader.readRowsByRange(obj, start, end)

        logger.debug(
            "[{}] Range {} → {}: {} rows".format(cls.PROFILE_NAME, start, end, len(rows)),
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
    """Load survey / LSD"""
    PROFILE_NAME = "block_load"
    OBIS = "1.0.99.1.0.255"


class daily_load_profile(_RangeProfileMixin, MeterReader):
    """Midnight / daily load profile."""
    PROFILE_NAME = "daily_load"
    OBIS = "1.0.99.2.0.255"


class billing_profile(_CountProfileMixin, MeterReader):
    """Billing profile — returns the last N complete billing cycles."""
    PROFILE_NAME = "billing"
    OBIS = "1.0.98.1.0.255"
    DEFAULT_COUNT = 6

    @classmethod
    def _read_data(cls, reader, settings, sn, count=None, **_ignored):
        count = count if count is not None else cls.DEFAULT_COUNT
        obj = settings.client.objects.findByLN(ObjectType.PROFILE_GENERIC, cls.OBIS)
        if obj is None:
            raise ValueError("Object not found: {}".format(cls.OBIS))

        headers  = _extract_headers(reader.read(obj, 3))
        rows     = reader.read(obj, 2)
        sort_method = reader.read(obj, 5)
        # entryInUse = reader.read(obj, 7)  # reserved for future use

        if sort_method == SortMethod.LIFO:
            selected = rows[:count]
            logger.info("[billing] Sort: LIFO, selected first {}".format(len(selected)), to_file=True)
        elif sort_method == SortMethod.FIFO:
            selected = rows[-count:]
            logger.info("[billing] Sort: FIFO, selected last {}".format(len(selected)), to_file=True)
        else:
            # Unknown sort order — fall back to last N rows
            selected = rows[-count:]
            logger.warning(
                "[billing] Unknown sort method {}, falling back to last {}".format(
                    sort_method, len(selected)
                ),
                to_file=True,
            )

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
    def _read_data(cls, reader, settings, sn, count=None, **_ignored):
        count = count if count is not None else cls.DEFAULT_COUNT
        obj = settings.client.objects.findByLN(ObjectType.PROFILE_GENERIC, cls.OBIS)
        if obj is None:
            raise ValueError("Object not found: {}".format(cls.OBIS))

        headers = _extract_headers(reader.read(obj, 3))
        rows = reader.read(obj, 2)
        sort_method = reader.read(obj, 5)
        # entryInUse = reader.read(obj, 7)  # reserved for future use

        if sort_method == SortMethod.LIFO:
            selected = rows[:count]
        elif sort_method == SortMethod.FIFO:
            selected = rows[-count:]
        else:
            selected = rows[-count:]
            logger.warning(
                "[voltage_event] Unknown sort method {}, falling back to last {}".format(
                    sort_method, count
                ),
                to_file=True,
            )

        logger.debug(
            "[voltage_event] {} total, returning last {}".format(len(rows), len(selected)),
            to_file=True,
        )
        return _rows_to_records(selected, headers, str(sn), cls.OBIS)


# ---------------------------------------------------------------------------
# WRITE UTILITIES
# (unchanged — these receive an already-open reader from the caller)
# ---------------------------------------------------------------------------

def write_pcp_dip(reader, settings, pip=1800, obis_code="1.0.0.8.0.255"):
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
    settings = None
    try:
        reader, settings = MeterReader._open_connection(args)
        clock_obj = settings.client.objects.findByLN(ObjectType.CLOCK, "0.0.1.0.0.255")
        result = reader.read(clock_obj, 2)
        logger.info("read_meter_time: {} → {}".format(meter_ip, result), to_file=True)
        return result
    except Exception as ex:
        logger.error("read_meter_time error ({}): {}".format(meter_ip, ex), to_file=True)
        return None
    finally:
        _safe_close(reader, settings)