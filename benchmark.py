
"""
AMR Benchmark — Threading vs Multiprocessing vs Sequential
===========================================================
Reads a configurable set of meters using all three concurrency modes,
measures per-profile timing and total cycle time, and writes a JSON
report you can compare across servers.

USAGE
-----
    python amr_benchmark.py

OUTPUT
------
    benchmark_results_<hostname>_<timestamp>.json

CONFIGURATION
-------------
    Edit the CONFIG block below — meters, profiles, worker counts.
"""

import os
import sys
import json
import time
import socket
import platform
import traceback
import multiprocessing
from copy import deepcopy
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed

try:
    import psutil
    _PSUTIL = True
except ImportError:
    _PSUTIL = False
    print("[WARN] psutil not found — resource stats disabled. pip install psutil")

# ---------------------------------------------------------------------------
# Resource tracking helpers
# ---------------------------------------------------------------------------

def _proc_rss_mb():
    """RSS memory of this process in MB."""
    if not _PSUTIL:
        return None
    return round(psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024, 2)

def _open_fds():
    """Number of open file descriptors for this process."""
    if not _PSUTIL:
        return None
    try:
        return psutil.Process(os.getpid()).num_fds()
    except Exception:
        return None

class ResourceMonitor:
    """
    Samples RSS memory and CPU% of this process at ~0.5s intervals
    in a background thread during a timed block.

    Usage:
        mon = ResourceMonitor()
        mon.start()
        ... do work ...
        stats = mon.stop()   # returns dict
    """
    def __init__(self):
        self._samples_rss  = []
        self._samples_cpu  = []
        self._running      = False
        self._thread       = None
        self._fds_before   = None
        self._fds_after    = None

    def start(self):
        import threading
        self._running    = True
        self._fds_before = _open_fds()
        proc             = psutil.Process(os.getpid()) if _PSUTIL else None

        def _sample():
            while self._running:
                if proc:
                    try:
                        self._samples_rss.append(
                            round(proc.memory_info().rss / 1024 / 1024, 2)
                        )
                        self._samples_cpu.append(proc.cpu_percent(interval=None))
                    except Exception:
                        pass
                time.sleep(0.5)

        if _PSUTIL:
            proc.cpu_percent(interval=None)          # prime the counter
            self._thread = threading.Thread(target=_sample, daemon=True)
            self._thread.start()

    def stop(self):
        self._running  = False
        if self._thread:
            self._thread.join(timeout=2)
        self._fds_after = _open_fds()

        rss = self._samples_rss
        cpu = self._samples_cpu
        return {
            "mem_start_mb":  rss[0]  if rss else None,
            "mem_peak_mb":   max(rss) if rss else None,
            "mem_end_mb":    rss[-1]  if rss else None,
            "mem_delta_mb":  round(rss[-1] - rss[0], 2) if len(rss) >= 2 else None,
            "cpu_avg_pct":   round(sum(cpu) / len(cpu), 1) if cpu else None,
            "cpu_peak_pct":  max(cpu) if cpu else None,
            "fds_before":    self._fds_before,
            "fds_after":     self._fds_after,
            "fd_delta":      (self._fds_after - self._fds_before)
                             if self._fds_before is not None and self._fds_after is not None
                             else None,
        }

# from Gurux import gurux_class_single_conn as gurux_class
# ---------------------------------------------------------------------------
# PATH SETUP — adjust so local gurux package imports work
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ---------------------------------------------------------------------------
# CONFIG — edit this block only
# ---------------------------------------------------------------------------

# Each meter: a dict with 'ip', 'port', 'serial' (serial is label-only)
# and any extra args your GXSettings.getParameters() needs.
# 'args' is the full list passed to MeterReader.read_multi / profile.main.
# Build it the same way your production code does.
def create_args(data):
    
    args = ['main.py','-h', '_', '-p', '_', '-i','_', '-c','_', '-a', '_', '-P', '_', '-g','0.0.94.91.10.255:7', '-d', 'India']
    i = 0
    j = 0
    while i < len(args) and j < len(data):
        if args[i] == "_":
            args[i] = data[j]
            j += 1
        i += 1
   
    
    return args

METERS = [
    {"serial": "IEM00000717", "ip": "10.10.12.14",  "args": create_args(["10.10.12.14",  "4059", "WRAPPER", "32", "Low", "lnt1"])},
    {"serial": "IEM00000372", "ip": "10.10.127.16", "args": create_args(["10.10.127.16", "4059", "WRAPPER", "32", "Low", "lnt1"])},
    {"serial": "IEM00000349", "ip": "10.10.128.11", "args": create_args(["10.10.128.11", "4059", "WRAPPER", "32", "Low", "lnt1"])},
    {"serial": "IEM00000258", "ip": "10.10.180.14", "args": create_args(["10.10.180.14", "4059", "WRAPPER", "32", "Low", "lnt1"])},
    {"serial": "IEM00001255", "ip": "10.10.54.11",  "args": create_args(["10.10.54.11",  "4059", "WRAPPER", "32", "Low", "lnt1"])},
    {"serial": "IEM00001235", "ip": "10.10.70.12",  "args": create_args(["10.10.70.12",  "4059", "WRAPPER", "32", "Low", "lnt1"])},
    {"serial": "IEM00000501", "ip": "10.10.95.13",  "args": create_args(["10.10.95.13",  "4059", "WRAPPER", "32", "Low", "lnt1"])},
    {"serial": "IEM00000648", "ip": "10.11.2.12",   "args": create_args(["10.11.2.12",   "4059", "WRAPPER", "32", "Low", "lnt1"])},
    {"serial": "IEM00001454", "ip": "10.11.55.14",  "args": create_args(["10.11.55.14",  "4059", "WRAPPER", "32", "Low", "lnt1"])},
    {"serial": "IEM00000799", "ip": "10.11.65.16",  "args": create_args(["10.11.65.16",  "4059", "WRAPPER", "32", "Low", "lnt1"])},
]


# Profiles to read for EVERY meter.
# Each entry: (profile_class_name_string, kwargs_dict)
# Using strings here so this config block works before imports resolve.
# 'block_load'  → _RangeProfileMixin: needs start + end (auto-set below)
# 'daily_load'  → _RangeProfileMixin: needs start + end (auto-set below)
# 'instantaneous' → _CountProfileMixin: needs count
# 'billing'       → _CountProfileMixin: needs count
PROFILE_CONFIG = [
    ("block_load",    {}),   # range: today 00:00 → now  (auto-set below)
    ("daily_load",    {}),   # range: 30 days ago → now  (auto-set below)
    ("instantaneous", {"count": 1}),
    # ("billing",     {"count": 3}),   # uncomment to add
    # ("voltage_event", {"count": 50}),
]


def _build_datetime_ranges():
    """
    Returns (block_start, block_end, daily_start, daily_end).
    block_load : today 00:00:00 → now
    daily_load : 30 days ago 00:00:00 → now
    """
    now = datetime.now()
    block_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    daily_start = (now - timedelta(days=30)).replace(hour=0, minute=0, second=0, microsecond=0)
    return block_start, now, daily_start, now


def _resolve_profiles(profile_config):
    """
    Turns string-keyed PROFILE_CONFIG into actual (class, kwargs) tuples.
    Import here so multiprocessing workers also resolve cleanly.
    """
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
    CLASS_MAP = {
        "block_load":             block_load_profile,
        "daily_load":             daily_load_profile,
        "instantaneous":          instantaneous_profile,
        "billing":                billing_profile,
        "nameplate":              nameplate_profile,
        "voltage_event":          voltage_event_profile,
        "scalar_instantaneous":   scalar_instantaneous_profile,
        "scalar_block_load":      scalar_block_load_profile,
        "scalar_daily_load":      scalar_daily_load_profile,
        "scalar_billing":         scalar_billing_profile,
        "scalar_event":           scalar_event_profile,
    }

    block_start, block_end, daily_start, daily_end = _build_datetime_ranges()

    profiles = []
    for name, kwargs in profile_config:
        cls = CLASS_MAP[name]
        kw = dict(kwargs)
        if name == "block_load":
            kw.setdefault("start", block_start)
            kw.setdefault("end",   block_end)
        elif name == "daily_load":
            kw.setdefault("start", daily_start)
            kw.setdefault("end",   daily_end)
        profiles.append((cls, kw))
    return profiles


# ---------------------------------------------------------------------------
# Core per-meter read — used by all three modes
# ---------------------------------------------------------------------------

def read_one_meter(meter_dict, profile_config):
    """
    Reads all configured profiles for a single meter.
    Returns a result dict with per-profile timings and row counts.
    Designed to be picklable (profile_config is plain data, not class refs).
    """
    from Gurux.gurux_class_single_conn import MeterReader

    serial   = meter_dict["serial"]
    args     = meter_dict["args"]
    profiles = _resolve_profiles(profile_config)

    meter_result = {
        "serial":           serial,
        "ip":               meter_dict["ip"],
        "profiles":         {},
        "total_duration_s": None,
        "success":          False,
        "error":            None,
        "mem_start_mb":     None,
        "mem_peak_mb":      None,
        "mem_end_mb":       None,
        "mem_delta_mb":     None,
        "fd_delta":         None,
    }

    meter_start = time.perf_counter()
    meter_result["mem_start_mb"] = _proc_rss_mb()
    fds_before = _open_fds()

    try:
        # --- connect once, read all profiles ---
        from Gurux.gurux_class_single_conn import MeterReader as _MR

        # We need per-profile timing, so we patch read_multi to time each profile.
        # Instead of calling read_multi directly, we replicate its logic with timers.
        from Gurux.gurux_class_single_conn import MeterReader
        from gurux_dlms.enums import ObjectType
        from gurux_net import GXNet
        from gurux_serial import GXSerial

        reader, settings = MeterReader._open_connection(args)

        try:
            sn_obj = settings.client.objects.findByLN(ObjectType.DATA, "0.0.96.1.0.255")
            sn = reader.read(sn_obj, 2) if sn_obj else "UNKNOWN_SN"

            for profile_cls, kwargs in profiles:
                name = profile_cls.PROFILE_NAME
                p_start = time.perf_counter()
                status = "ok"
                rows   = 0
                error  = None

                try:
                    import signal

                    def _handler(s, f):
                        raise TimeoutError("Read timeout")
                    signal.signal(signal.SIGALRM, _handler)
                    signal.alarm(30)
                    try:
                        result = profile_cls._read_data(reader, settings, sn, **kwargs)
                        rows = len(result) if result else 0
                    finally:
                        signal.alarm(0)

                except TimeoutError as ex:
                    status = "timeout"
                    error  = str(ex)
                except Exception as ex:
                    status = "error"
                    error  = str(ex)

                p_elapsed = round(time.perf_counter() - p_start, 3)
                meter_result["profiles"][name] = {
                    "status":      status,
                    "rows":        rows,
                    "duration_s":  p_elapsed,
                    "error":       error,
                }

            meter_result["success"] = True

        finally:
            from Gurux.gurux_class_single_conn import _safe_close
            _safe_close(reader, settings)

    except Exception as ex:
        meter_result["error"] = "{}: {}".format(type(ex).__name__, str(ex))
        meter_result["traceback"] = traceback.format_exc()

    meter_result["total_duration_s"] = round(time.perf_counter() - meter_start, 3)

    mem_end = _proc_rss_mb()
    fds_after = _open_fds()
    meter_result["mem_end_mb"]   = mem_end
    meter_result["mem_peak_mb"]  = mem_end  # per-meter peak approximation; batch peak from monitor
    meter_result["mem_delta_mb"] = round(mem_end - meter_result["mem_start_mb"], 2) \
                                   if mem_end is not None and meter_result["mem_start_mb"] is not None \
                                   else None
    meter_result["fd_delta"]     = (fds_after - fds_before) \
                                   if fds_before is not None and fds_after is not None \
                                   else None

    return meter_result


# ---------------------------------------------------------------------------
# Three execution modes
# ---------------------------------------------------------------------------

def run_sequential(meters, profile_config):
    mon = ResourceMonitor()
    mon.start()
    results = []
    for m in meters:
        results.append(read_one_meter(m, profile_config))
    resource_stats = mon.stop()
    return results, resource_stats


def run_threaded(meters, profile_config, max_workers):
    mon = ResourceMonitor()
    mon.start()
    results = [None] * len(meters)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(read_one_meter, m, profile_config): i
            for i, m in enumerate(meters)
        }
        for fut in as_completed(futures):
            idx = futures[fut]
            try:
                results[idx] = fut.result()
            except Exception as ex:
                results[idx] = {
                    "serial":           meters[idx]["serial"],
                    "ip":               meters[idx]["ip"],
                    "profiles":         {},
                    "total_duration_s": None,
                    "success":          False,
                    "error":            str(ex),
                }
    resource_stats = mon.stop()
    return results, resource_stats


def run_multiprocess(meters, profile_config, max_workers):
    mon = ResourceMonitor()
    mon.start()
    results = [None] * len(meters)
    with ProcessPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(read_one_meter, m, profile_config): i
            for i, m in enumerate(meters)
        }
        for fut in as_completed(futures):
            idx = futures[fut]
            try:
                results[idx] = fut.result()
            except Exception as ex:
                results[idx] = {
                    "serial":           meters[idx]["serial"],
                    "ip":               meters[idx]["ip"],
                    "profiles":         {},
                    "total_duration_s": None,
                    "success":          False,
                    "error":            str(ex),
                }
    resource_stats = mon.stop()
    return results, resource_stats


# ---------------------------------------------------------------------------
# Stats summariser
# ---------------------------------------------------------------------------

def summarise(meter_results, mode, workers, wall_time_s, resource_stats=None):
    """
    Computes per-profile stats and overall summary across all meters.
    """
    profile_stats = {}  # name → {durations, rows, timeouts, errors}

    for mr in meter_results:
        for pname, pd in mr.get("profiles", {}).items():
            if pname not in profile_stats:
                profile_stats[pname] = {"durations": [], "rows": [], "timeouts": 0, "errors": 0}
            ps = profile_stats[pname]
            if pd["status"] == "ok":
                ps["durations"].append(pd["duration_s"])
                ps["rows"].append(pd["rows"])
            elif pd["status"] == "timeout":
                ps["timeouts"] += 1
            else:
                ps["errors"] += 1

    profile_summary = {}
    for pname, ps in profile_stats.items():
        durations = ps["durations"]
        rows      = ps["rows"]
        profile_summary[pname] = {
            "attempts":    len(durations) + ps["timeouts"] + ps["errors"],
            "ok":          len(durations),
            "timeouts":    ps["timeouts"],
            "errors":      ps["errors"],
            "min_s":       round(min(durations), 3)  if durations else None,
            "max_s":       round(max(durations), 3)  if durations else None,
            "avg_s":       round(sum(durations) / len(durations), 3) if durations else None,
            "total_rows":  sum(rows),
            "avg_rows":    round(sum(rows) / len(rows), 1) if rows else None,
        }

    meter_durations = [
        mr["total_duration_s"] for mr in meter_results
        if mr.get("total_duration_s") is not None
    ]
    success_count = sum(1 for mr in meter_results if mr.get("success"))

    # per-meter resource summary
    mem_peaks  = [mr["mem_peak_mb"]  for mr in meter_results if mr.get("mem_peak_mb")  is not None]
    mem_deltas = [mr["mem_delta_mb"] for mr in meter_results if mr.get("mem_delta_mb") is not None]
    fd_deltas  = [mr["fd_delta"]     for mr in meter_results if mr.get("fd_delta")      is not None]

    return {
        "mode":              mode,
        "workers":           workers,
        "wall_time_s":       round(wall_time_s, 3),
        "meters_total":      len(meter_results),
        "meters_success":    success_count,
        "meters_failed":     len(meter_results) - success_count,
        "avg_meter_s":       round(sum(meter_durations) / len(meter_durations), 3) if meter_durations else None,
        "max_meter_s":       round(max(meter_durations), 3) if meter_durations else None,
        "min_meter_s":       round(min(meter_durations), 3) if meter_durations else None,
        "profiles":          profile_summary,
        # batch-level resource (from ResourceMonitor sampling the main process)
        "batch_resources":   resource_stats or {},
        # per-meter resource aggregates
        "meter_mem_peak_max_mb":  round(max(mem_peaks),  2) if mem_peaks  else None,
        "meter_mem_delta_avg_mb": round(sum(mem_deltas) / len(mem_deltas), 2) if mem_deltas else None,
        "meter_fd_delta_max":     max(fd_deltas) if fd_deltas else None,
        "meter_detail":      meter_results,
    }


# ---------------------------------------------------------------------------
# Pretty printer for the terminal
# ---------------------------------------------------------------------------

RESET  = "\033[0m"
BOLD   = "\033[1m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
RED    = "\033[31m"
CYAN   = "\033[36m"
DIM    = "\033[2m"

def _color_status(ok, total):
    if ok == total:
        return GREEN + str(ok) + RESET
    elif ok == 0:
        return RED + str(ok) + RESET
    return YELLOW + str(ok) + RESET

def print_summary(s):
    mode_label = "{} (workers={})".format(s["mode"].upper(), s["workers"])
    print("\n" + BOLD + CYAN + "━" * 60 + RESET)
    print(BOLD + "  {}".format(mode_label) + RESET)
    print(BOLD + CYAN + "━" * 60 + RESET)
    print("  Wall time     : {}s".format(s["wall_time_s"]))
    print("  Meters        : {}/{} ok".format(
        _color_status(s["meters_success"], s["meters_total"]),
        s["meters_total"]
    ))
    print("  Per-meter avg : {}s  min {}s  max {}s".format(
        s["avg_meter_s"], s["min_meter_s"], s["max_meter_s"]
    ))
    print()
    print("  {:<26} {:>6} {:>7} {:>7} {:>7} {:>9}".format(
        "Profile", "ok", "avg_s", "min_s", "max_s", "avg_rows"
    ))
    print("  " + DIM + "-" * 58 + RESET)
    for pname, ps in s["profiles"].items():
        ok_str = _color_status(ps["ok"], ps["attempts"])
        print("  {:<26} {:>6} {:>7} {:>7} {:>7} {:>9}".format(
            pname,
            ok_str,
            ps["avg_s"]  if ps["avg_s"]  is not None else "-",
            ps["min_s"]  if ps["min_s"]  is not None else "-",
            ps["max_s"]  if ps["max_s"]  is not None else "-",
            ps["avg_rows"] if ps["avg_rows"] is not None else "-",
        ))

    # Resource stats
    br = s.get("batch_resources", {})
    if br:
        print()
        print("  Resources (batch)")
        print("    Memory : start={} MB  peak={} MB  end={} MB  delta={} MB".format(
            br.get("mem_start_mb"), br.get("mem_peak_mb"),
            br.get("mem_end_mb"),   br.get("mem_delta_mb"),
        ))
        print("    CPU    : avg={}%  peak={}%".format(
            br.get("cpu_avg_pct"), br.get("cpu_peak_pct"),
        ))
        print("    FDs    : before={}  after={}  delta={}  {}".format(
            br.get("fds_before"), br.get("fds_after"), br.get("fd_delta"),
            RED + "← LEAK?" + RESET if (br.get("fd_delta") or 0) > 0 else GREEN + "✓ clean" + RESET,
        ))
    per_peak = s.get("meter_mem_peak_max_mb")
    per_delta = s.get("meter_mem_delta_avg_mb")
    if per_peak is not None:
        print("  Resources (per-meter)  peak_max={} MB  delta_avg={} MB  fd_delta_max={}".format(
            per_peak, per_delta, s.get("meter_fd_delta_max"),
        ))

    # Meter-level failures
    failed = [mr for mr in s["meter_detail"] if not mr.get("success")]
    if failed:
        print()
        print("  " + RED + "Failed meters:" + RESET)
        for mr in failed:
            print("    {} ({}) — {}".format(mr["serial"], mr["ip"], mr.get("error", "unknown")))


def print_comparison(summaries):
    """Side-by-side wall time comparison across modes."""
    print("\n" + BOLD + "=" * 60 + RESET)
    print(BOLD + "  COMPARISON" + RESET)
    print(BOLD + "=" * 60 + RESET)
    baseline = summaries[0]["wall_time_s"]
    for s in summaries:
        speedup = round(baseline / s["wall_time_s"], 2) if s["wall_time_s"] else "-"
        bar_len = int((s["wall_time_s"] / baseline) * 30) if baseline else 0
        bar     = "█" * bar_len
        label   = "{:<28}".format("{} w={}".format(s["mode"], s["workers"]))
        print("  {}  {}s  {}x  {}".format(
            label, s["wall_time_s"], speedup, CYAN + bar + RESET
        ))
    print()



def main():
    cpu_count = multiprocessing.cpu_count()
    # Workers: 1 baseline + up to cpu_count, capped at meter count
    # Typical useful set: 1, half-cpu, full-cpu, meter-count
    n_meters  = len(METERS)
    candidate_workers = sorted(set([
        1,
        max(1, cpu_count // 2),
        cpu_count,
        min(n_meters, cpu_count * 2),
        n_meters,
    ]))
    # Remove duplicates and anything > meter count
    worker_counts = [w for w in sorted(set(candidate_workers)) if w <= n_meters]

    hostname  = socket.gethostname()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    outfile   = "benchmark_results_{}_{}.json".format(hostname, timestamp)

    print(BOLD + "\nAMR Benchmark" + RESET)
    print("  Host    : {} ({})".format(hostname, platform.node()))
    print("  CPUs    : {}".format(cpu_count))
    print("  Meters  : {}".format(n_meters))
    print("  Workers : {}".format(worker_counts))
    print("  Profiles: {}".format([p[0] for p in PROFILE_CONFIG]))
    block_start, block_end, daily_start, daily_end = _build_datetime_ranges()
    print("  block_load range : {} → {}".format(block_start, block_end))
    print("  daily_load range : {} → {}".format(daily_start, daily_end))
    print()

    all_summaries = []
    all_raw       = []

    # ── Sequential baseline ──────────────────────────────────────────────
    print(BOLD + "[1/{}] Sequential (baseline)...".format(
        1 + 2 * (len(worker_counts) - 1)  # total runs
    ) + RESET, flush=True)
    t0 = time.perf_counter()
    seq_results, seq_res = run_sequential(METERS, PROFILE_CONFIG)
    seq_wall    = time.perf_counter() - t0
    seq_summary = summarise(seq_results, "sequential", 1, seq_wall, seq_res)
    all_summaries.append(seq_summary)
    all_raw.append({"mode": "sequential", "workers": 1, "meter_results": seq_results})
    print_summary(seq_summary)

    run_idx = 2

    # ── Threading ────────────────────────────────────────────────────────
    for w in worker_counts:
        if w == 1:
            continue   # sequential already covers this
        print(BOLD + "\n[{}/...] Threading  workers={}...".format(run_idx, w) + RESET, flush=True)
        t0 = time.perf_counter()
        thr_results, thr_res = run_threaded(METERS, PROFILE_CONFIG, max_workers=w)
        thr_wall    = time.perf_counter() - t0
        thr_summary = summarise(thr_results, "threading", w, thr_wall, thr_res)
        all_summaries.append(thr_summary)
        all_raw.append({"mode": "threading", "workers": w, "meter_results": thr_results})
        print_summary(thr_summary)
        run_idx += 1

    # ── Multiprocessing ──────────────────────────────────────────────────
    for w in worker_counts:
        if w == 1:
            continue
        print(BOLD + "\n[{}/...] Multiprocessing  workers={}...".format(run_idx, w) + RESET, flush=True)
        t0 = time.perf_counter()
        mp_results, mp_res  = run_multiprocess(METERS, PROFILE_CONFIG, max_workers=w)
        mp_wall     = time.perf_counter() - t0
        mp_summary  = summarise(mp_results, "multiprocessing", w, mp_wall, mp_res)
        all_summaries.append(mp_summary)
        all_raw.append({"mode": "multiprocessing", "workers": w, "meter_results": mp_results})
        print_summary(mp_summary)
        run_idx += 1

    # ── Comparison ───────────────────────────────────────────────────────
    print_comparison(all_summaries)

    # ── JSON output ──────────────────────────────────────────────────────
    report = {
        "meta": {
            "hostname":     hostname,
            "platform":     platform.platform(),
            "cpu_count":    cpu_count,
            "python":       platform.python_version(),
            "timestamp":    timestamp,
            "meters":       [{"serial": m["serial"], "ip": m["ip"]} for m in METERS],
            "profiles":     [p[0] for p in PROFILE_CONFIG],
            "block_range":  [str(block_start), str(block_end)],
            "daily_range":  [str(daily_start), str(daily_end)],
        },
        "summaries": [
            {k: v for k, v in s.items() if k != "meter_detail"}
            for s in all_summaries
        ],
        "raw": all_raw,
    }

    # Datetime objects aren't JSON serialisable — convert
    def _default(obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        raise TypeError(type(obj))

    with open(outfile, "w") as f:
        json.dump(report, f, indent=2, default=_default)

    print("  Report saved → " + BOLD + outfile + RESET)
    print("  Copy to your other server and run there for comparison.\n")


if __name__ == "__main__":
    # Multiprocessing on Linux uses fork by default (fine).
    # On macOS/Windows it uses spawn — the guard below is required.
    multiprocessing.freeze_support()
    main()