"""
Example: configuring and running the full sync engine.

Shows how to:
  1. Register extraction jobs with custom intervals
  2. Use callbacks for account validation and zombie detection
  3. Run the startup sequence
  4. Configure feed sync with deduplication and store assignment
  5. Use ThreadManager for batch DB writes
"""
from src.scheduler.scheduler import ExtractionScheduler, JobConfig
from src.scheduler.api import SchedulerAPI, IntervalUpdateRequest
from src.sync.feed_sync import FeedSyncService
from src.worker.thread_manager import ThreadManager


def demo_scheduler():
    """Configure and control the extraction scheduler."""

    def validate_accounts():
        return {"all_valid": True, "results": [{"valid": True}]}

    def check_running(ext_type):
        return False

    def mark_zombie(ext_type, timeout_min):
        return []

    scheduler = ExtractionScheduler(
        validate_accounts=validate_accounts,
        check_running=check_running,
        mark_zombie=mark_zombie,
    )

    scheduler.register_job(JobConfig(
        job_id="extract_orders", name="Orders",
        run_fn=lambda: print("Extracting orders..."),
        interval_minutes=30,
        requires_valid_accounts=True,
        run_on_startup=True,
    ))

    scheduler.register_job(JobConfig(
        job_id="extract_chats", name="Chats",
        run_fn=lambda: print("Extracting chats..."),
        interval_hours=4,
        requires_valid_accounts=True,
        run_on_startup=True,
    ))

    scheduler.register_job(JobConfig(
        job_id="ebay_relist", name="eBay Relist",
        run_fn=lambda: print("Running eBay relist..."),
        interval_hours=72,
        misfire_grace_time=3600,
        requires_valid_accounts=False,
        run_on_startup=False,
    ))

    # REST API wrapper
    api = SchedulerAPI(scheduler)

    print("Status:", api.get_status())
    print("Start:", api.start())
    print("Run job:", api.run_job("extract_orders"))
    print("Set interval:", api.set_interval(
        "extract_orders", IntervalUpdateRequest(hours=1, minutes=0),
    ))
    print("Jobs:", api.list_jobs())
    print("Stop:", api.stop())

    # Startup sequence (validates accounts, runs startup jobs)
    scheduler.start()
    scheduler.run_startup_sequence()

    # Watchdog (detects zombies)
    scheduler.run_watchdog()


def demo_feed_sync():
    """Configure and run feed sync with deduplication."""

    def load_feed():
        return [
            {
                "id_base": "LPNWE001",
                "asin": "B08N5WRWNW",
                "price": 45.99,
                "external_category": "Electronics",
                "condition_code": "PERFECTO",
                "condition_description": "PAOLA",
                "images_raw": "https://img1.jpg, https://img2.jpg",
                "shipping_weight_kg": 2.5,
                "title": "Wireless Headphones",
            },
            {
                "id_base": "LPNWE002",
                "asin": "B08N5WRWNW",
                "price": 42.50,
                "external_category": "Electronics",
                "condition_code": "PERFECTO",
                "condition_description": "BN",
                "images_raw": "https://img3.jpg",
                "shipping_weight_kg": 2.5,
                "title": "Wireless Headphones",
            },
            {
                "id_base": "LPNWE003",
                "asin": "B08N5WRWNW",
                "price": 30.00,
                "external_category": "Electronics",
                "condition_code": "CON_TARA",
                "condition_description": "Scratched left ear cup",
                "images_raw": "https://img4.jpg",
                "shipping_weight_kg": 2.5,
                "title": "Wireless Headphones (defect)",
            },
        ]

    uploaded_data = []

    def upload_file(filename, items):
        uploaded_data.extend(items)
        print(f"Uploaded {filename}: {len(items)} items")

    svc = FeedSyncService(
        load_feed=load_feed,
        upload_file=upload_file,
        top_n_expensive=2,
    )

    result = svc.sync()
    print(f"Sync result: {result}")

    for item in uploaded_data:
        print(f"  {item['id']}: stock={item.get('stock', 1)}, "
              f"price={item.get('price')}, store={item.get('store')}")


def demo_thread_manager():
    """Configure batch writer with passthrough and active modes."""

    # Passthrough mode (default) - no-op
    tm_passive = ThreadManager(enabled=False)
    tm_passive.enqueue("create", {"id": 1})
    print("Passthrough: queue empty =", tm_passive.task_queue.empty())

    # Active mode with batch processing
    results = []
    tm = ThreadManager(batch_size=2, enabled=True)
    tm.set_callback("batch_create", lambda items: results.extend(items))
    tm.start_writer()

    for i in range(5):
        tm.enqueue("create", {"id": i}, use_buffer=True)

    tm.stop_writer()
    print(f"Batch processed: {len(results)} items")


if __name__ == "__main__":
    print("=" * 60)
    print("Scheduler Demo")
    print("=" * 60)
    demo_scheduler()

    print("\n" + "=" * 60)
    print("Feed Sync Demo")
    print("=" * 60)
    demo_feed_sync()

    print("\n" + "=" * 60)
    print("Thread Manager Demo")
    print("=" * 60)
    demo_thread_manager()
