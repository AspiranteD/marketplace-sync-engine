# Marketplace Sync Engine
> **Portfolio context:** Extracted from founder-led production systems — multi-marketplace inventory, orders, and warehouse execution. **[Full portfolio](https://github.com/AspiranteD/AspiranteD)** · [aspiranted.github.io](https://aspiranted.github.io)

Production-grade orchestration engine for multi-marketplace data synchronization. Manages extraction scheduling, feed generation with intelligent deduplication, and batch database writes across marketplace platforms.

## Architecture

```
src/
+-- scheduler/
¦   +-- scheduler.py          # Multi-job scheduler with watchdog
¦   +-- api.py                # REST API for scheduler control
+-- sync/
¦   +-- feed_sync.py          # DB -> CSV -> cloud sync pipeline
¦   +-- store_assignment.py   # Price-ranked store routing
+-- worker/
    +-- thread_manager.py     # Queue-based batch DB writer
```

## Key Technical Features

### Extraction Scheduler (`src/scheduler/scheduler.py`)

APScheduler-based multi-job orchestration with production safeguards:

- **5+ independent jobs** with configurable intervals (orders=30min, chats=4h, listings=4h, eBay relist=72h, dynamic pricing=24h)
- **Startup sequence**: validate accounts ? run startup jobs sequentially (orders ? chats ? listings)
- **Zombie detection watchdog**: every 5 min, detects extractions stuck in `running` state beyond per-type timeouts (orders=20min, chats=60min, listings=45min)
- **Account validation gating**: skip extraction if no valid accounts/cookies
- **Concurrency protection**: `max_instances=1` + `coalesce=True` prevents overlapping runs
- **Misfire grace time**: 300s for extractors, 3600s for relist (handles server restarts)
- **Runtime interval changes**: modify any job's schedule via API without restart
- **Job status tracking**: run_count, skip_count, last_status, last_error, last_skip_reason
- **Event listeners**: APScheduler job execution/error events ? status updates + DB persistence
- **Database-agnostic**: callbacks for account validation, running checks, zombie marking

### Scheduler REST API (`src/scheduler/api.py`)

Full control plane:
- `GET /scheduler/status` — scheduler state + all jobs status
- `POST /scheduler/start` / `POST /scheduler/stop`
- `POST /scheduler/jobs/{id}/run` — execute immediately
- `PUT /scheduler/jobs/{id}/interval` — change schedule at runtime
- `GET /scheduler/jobs` — list all with status

Validated inputs (no negative intervals, no zero, minutes 0-59).

### Feed Sync Pipeline (`src/sync/feed_sync.py`)

Full DB ? CSV ? cloud storage pipeline with 9-step processing:

1. **Price filtering**: minimum 2 EUR, motor category exempt
2. **Image normalization**: split mixed separators (comma/space/pipe), limit to 10
3. **Condition mapping**: `PERFECTO` ? `as_good_as_new`, `CON_TARA` ? `fair`, `PARA_PIEZAS` ? `has_given_it_all`
4. **Shipping rules**: shippable if weight = 30kg or unknown
5. **Free shipping**: weight < 5kg AND price > 70 EUR
6. **ASIN+condition deduplication** with stock accumulation:
   - `PERFECTO`: group by ASIN+condition only (operator notes like "PAOLA", "BN" are not defects)
   - `CON_TARA`/others: group by ASIN+condition+description (each defect has unique images)
   - Within group: stock = count, price = min
7. **ID randomization**: 2-letter suffix rotating every 54h (676 combinations, AA-ZZ)
8. **Store assignment**: post-dedup price ranking (motor=16, top 5100=17, rest=14)
9. **Text formatting**: title truncation (60 chars), description truncation (640 chars)

#### ID Randomization Algorithm

Replicates the production V2_5 algorithm for marketplace search positioning:
- Base date: 2026-01-21 07:00:00
- Period: 54 hours (~2.25 days)
- Offset: 102 (first suffix = "DY")
- 676 combinations cycling through AA-ZZ

### Store Assignment (`src/sync/store_assignment.py`)

Price-based routing with category priority:

| Store | ID | Rule |
|-------|-----|------|
| Motor | 16 | Category contains "motor" (case-insensitive) |
| Expensive | 17 | Top N most expensive non-motor items |
| Cheap | 14 | Remaining non-motor items |

- Configurable TOP_N threshold (default 5100)
- Batch recalculation with update tracking (updated vs unchanged)
- Zero/null price ? always cheap

### Thread Manager (`src/worker/thread_manager.py`)

Queue-based batch processing for database writes:

- **Typed message queue**: create, update, batch_create, batch_update, progress, stop
- **Buffer accumulation**: individual ops buffer until batch_size ? auto-flush
- **Dedicated writer thread**: non-daemon for graceful shutdown
- **Pluggable callbacks**: per-type handlers for database persistence
- **Named locks**: hashes, counter, state, cache for synchronized access
- **Passthrough mode**: when disabled, all operations are no-ops (zero-cost migration)
- **Graceful shutdown**: flush pending ? signal stop ? join with 30s timeout
- **Timeout-based polling**: 0.5s queue wait with periodic buffer checks

## Testing

```bash
pip install -r requirements.txt
python -m pytest tests/ -v
```

**160 tests** covering:
- Scheduler lifecycle (start/stop/double-start, job registration, interval changes)
- Account validation gating and skip tracking
- Startup sequence with error isolation
- Watchdog zombie detection
- REST API endpoints and input validation
- Feed sync full pipeline (filter ? normalize ? map ? dedup ? assign ? format)
- ASIN deduplication rules (PERFECTO vs CON_TARA grouping)
- ID randomization algorithm (period boundaries, determinism)
- Store assignment (motor routing, price ranking, boundary cases)
- Thread manager (passthrough, enabled, buffers, concurrent enqueue, graceful shutdown)

## Usage

```python
from src.scheduler.scheduler import ExtractionScheduler, JobConfig
from src.sync.feed_sync import FeedSyncService

# 1. Configure scheduler
scheduler = ExtractionScheduler(
    validate_accounts=my_validator,
    mark_zombie=my_zombie_detector,
)
scheduler.register_job(JobConfig(
    job_id="extract_orders", name="Orders",
    run_fn=my_order_extractor, interval_minutes=30,
))
scheduler.start()
scheduler.run_startup_sequence()

# 2. Configure feed sync
sync = FeedSyncService(
    load_feed=my_db_loader,
    upload_file=my_cloud_uploader,
    top_n_expensive=5100,
)
sync.sync()
```

See `examples/sync_demo.py` for a complete working example.
