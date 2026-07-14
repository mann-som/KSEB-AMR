# AMR Pipeline System Design

## 1. Purpose

This project is an AMR (Automated Meter Reading) data pipeline that:

1. discovers meters from a central source system,
2. builds a per-meter read plan,
3. opens a DLMS connection to each meter,
4. reads one or more meter profiles,
5. transforms the raw profile data into a structured result,
6. logs the outcome and updates meter status.

The current focus is to make the pipeline work reliably end-to-end. The later phase will add persistence of fetched data and richer status updates.

---

## 2. Goals

### Primary goals
- Keep the current flow simple and reliable.
- Separate responsibilities clearly so each layer has one job.
- Make date-range and profile planning explicit in the task layer.
- Keep ETL orchestration focused on orchestration, not low-level meter logic.

### Non-goals for the first iteration
- Full DB persistence of every fetched profile payload.
- Advanced queueing, retry policies, or parallel scheduling.
- Complex analytics or reporting.

---

## 3. Current architecture (as implemented)

### 3.1 Entry points
- [main.py](main.py): orchestrates the ETL run for a meter group.
- [test.py](test.py): smoke tests the DB access, meter discovery, and ETL path.
- [initialize.py](initialize.py): prepares local SQLite state and schema.

### 3.2 Core modules
- [DataGetter/DataGetter.py](DataGetter/DataGetter.py): reads meter metadata from the production system.
- [Entity/meter.py](Entity/meter.py): represents a single meter and builds the DLMS argument list.
- [Task/Task.py](Task/Task.py): decides which profiles to read and builds the read execution plan.
- [Profile/Profiles.py](Profile/Profiles.py): defines profile metadata and mapping to Gurux classes.
- [Gurux/gurux_class_single_conn.py](Gurux/gurux_class_single_conn.py): wraps DLMS read logic and profile execution.
- [Gurux/GXDLMSReader.py](Gurux/GXDLMSReader.py): performs low-level communication and retry handling.
- [DataBase/DataBase.py](DataBase/DataBase.py): abstract DB access layer for SQLite/MySQL.
- [DataSetter/DataSetter.py](DataSetter/DataSetter.py): writes status and timeout information.
- [logger/logger.py](logger/logger.py): logging and observability.

---

## 4. Target architecture (recommended MVP)

The target design should follow a clean pipeline pattern:

1. Discovery Layer
2. Meter Domain Layer
3. Task Planning Layer
4. Device Communication Layer
5. Transformation Layer
6. Persistence/Status Layer
7. Observability Layer

### 4.1 Layer responsibilities

#### A. Discovery Layer
Responsible for finding meters that need to be processed.

Current module:
- [DataGetter/DataGetter.py](DataGetter/DataGetter.py)

Responsibilities:
- query the production master tables,
- filter meters by group,
- return a list of meter descriptors.

#### B. Meter Domain Layer
Responsible for representing one meter as a runnable unit.

Current module:
- [Entity/meter.py](Entity/meter.py)

Responsibilities:
- normalize raw meter metadata,
- build the connection argument list,
- resolve per-meter timeout,
- expose methods for later status updates and data persistence.

#### C. Task Planning Layer
Responsible for deciding what should be read from a meter and when.

Current module:
- [Task/Task.py](Task/Task.py)

Responsibilities:
- build the read plan for one meter,
- decide which profiles should be included,
- compute the time window for range-based profiles,
- decide whether scalar profiles are needed,
- convert the plan into a list of read jobs.

This is where the daily date-range logic should move.

#### D. Device Communication Layer
Responsible for actual meter communication over DLMS/Gurux.

Current modules:
- [Gurux/gurux_class_single_conn.py](Gurux/gurux_class_single_conn.py)
- [Gurux/GXDLMSReader.py](Gurux/GXDLMSReader.py)

Responsibilities:
- open connection,
- authenticate and initialize,
- read one or more profiles,
- return raw profile rows,
- surface communication errors and timeouts.

#### E. Transformation Layer
Responsible for converting raw profile payloads into the structure expected by the rest of the system.

Current module:
- [main.py](main.py)

Responsibilities:
- normalize read output,
- attach profile counts,
- build a structured ETL result for one meter.

#### F. Persistence/Status Layer
Responsible for storing results and updating processing status.

Current modules:
- [DataSetter/DataSetter.py](DataSetter/DataSetter.py)
- [DataBase/DataBase.py](DataBase/DataBase.py)

Responsibilities:
- write timeout values,
- later write fetched data to persistent storage,
- update meter reading status.

For the current MVP, this layer can stay minimal and only update status where already supported.

#### G. Observability Layer
Responsible for tracing, logging, and metrics.

Current module:
- [logger/logger.py](logger/logger.py)

Responsibilities:
- log progress,
- write errors and meter-level events,
- record counts of processed/succeeded/failed meters.

---

## 5. Proposed data structures

### 5.1 Meter
Represents a single meter and its connection metadata.

Fields:
- meter_id
- meter_serial_number
- static_ip
- port
- interface
- client_address
- authentication
- password
- timeout
- group

### 5.2 ProfilePlan
Represents one profile read job.

Fields:
- profile_name
- profile_enum
- read_type (count/range)
- kwargs
- scalar_hint
- priority

### 5.3 MeterReadPlan
Represents the full plan for one meter.

Fields:
- meter_id
- meter_serial_number
- profiles: list[ProfilePlan]
- start_time
- end_time
- read_window

### 5.4 ReadResult
Represents the outcome of reading one profile.

Fields:
- profile_name
- rows: list[dict] | None
- status: success/failed/timeout
- error_message

### 5.5 ETLResult
Represents the output of one meter ETL run.

Fields:
- meter_id
- loaded
- profiles
- profile_counts
- errors

---

## 6. Proposed control flow

### 6.1 High-level sequence

```text
main.py
  -> DataGetter.get_meters(group)
  -> build Meter objects
  -> for each meter:
       ETL.run(meter)
         -> MeterTask.from_meter(meter)
         -> task builds MeterReadPlan
         -> MeterReader.read_multi(args, plan)
         -> transform raw data
         -> load/update status (later phase)
```

### 6.2 What each phase does

#### Discovery
- fetch meters from production tables.

#### Planning
- decide which profiles to read.
- compute start/end range for range-based profiles.

#### Execution
- open one DLMS connection.
- run profile reads.

#### Transformation
- normalize raw fields and counts.

#### Loading
- for MVP: update status or log result.
- later: persist raw/transformed data and update status in DB.

---

## 7. Refactor recommendation for the current code

### 7.1 Move date-range logic out of ETL

Today, [main.py](main.py) creates the time window via `build_time_window()` in the ETL class.

Recommended change:
- move the time window creation into the task/planning layer.
- `MeterTask` or a new planner class should own:
  - start/end window,
  - profile-specific read windows,
  - default profile selection rules.

This keeps ETL focused on orchestration only.

### 7.2 Keep ETL.load() lightweight for now

Current behavior:
- ETL.load() basically updates meter status and returns success/failure.

Recommended MVP behavior:
- ETL.load() should only do the minimum required for now:
  - optionally update status,
  - log the result,
  - return a structured outcome.

Later, ETL.load() can be expanded to:
- insert raw profile rows into persistence tables,
- store transformed records,
- update status with richer metadata.

### 7.3 Introduce a small planner abstraction

A good first refactor is to introduce a planner class such as:
- `MeterReadPlanner`

Responsibilities:
- inspect meter state,
- decide profiles,
- decide date range,
- return `MeterReadPlan`.

Then `MeterTask.from_meter()` becomes a thin wrapper that uses the planner.

---

## 8. Error handling strategy

The system should treat each step as a separate concern:

### Connection errors
- raised by Gurux when the meter is unreachable or handshake fails.

### Profile errors
- per-profile timeouts or DLMS exceptions.

### Planning errors
- missing metadata or invalid meter arguments.

### Persistence errors
- later-phase concern; should not block the core read if the MVP only needs to log and continue.

### Recommended behavior
- log everything,
- capture a structured error message,
- continue to the next meter where possible,
- mark the current meter as partial/failed.

---

## 9. Logging and observability

Each major step should produce structured logs:
- meter discovery success/failure,
- meter plan creation,
- connection opened/closed,
- profile read start/end,
- profile timeout/error,
- ETL result summary.

This is already partially implemented in [logger/logger.py](logger/logger.py).

---

## 10. Suggested phased roadmap

### Phase 1 — Make it work
- keep ETL simple,
- move date window planning into task layer,
- make run result explicit and easy to inspect,
- preserve current success/failure semantics.

### Phase 2 — Add persistence
- define storage schema for raw and transformed data,
- make ETL.load() persist results,
- update status and timestamps based on successful reads.

### Phase 3 — Make it scalable
- add concurrency control,
- add retries and backoff,
- add batch scheduling and reporting.

---

## 11. Recommended implementation direction

For the next iteration, implement this minimal refactor:

1. Create a `MeterReadPlanner` or move planning logic from ETL to `MeterTask`.
2. Make `MeterTask` own the read window and profile selection.
3. Keep ETL as:
   - build meter object,
   - create task,
   - execute task,
   - transform result,
   - log result.
4. Leave storage/persistence as a later feature.

This gives you a cleaner architecture without overcomplicating the first working version.
