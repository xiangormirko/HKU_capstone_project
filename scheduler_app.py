"""
Product Scout recurring-refresh scheduler (app-integrated).

Runs the app's data refreshes on a recurring cadence (mirroring the production
pipeline in scheduler/main_scheduler.py) by calling refresh_manager, which keeps
the data-freshness store the UI reads up to date.

  social  → every 12h   amazon → every 24h
  trends  → weekly       trade  → weekly

Run standalone:           python scheduler_app.py
Or start inside the app:  set env PS_ENABLE_SCHEDULER=1 before launching server.py

Uses APScheduler if installed; otherwise falls back to a lightweight stdlib
thread loop (no extra dependency required).
"""

import logging
import threading
import time

import refresh_manager as rm

logging.basicConfig(level=logging.INFO,
                    format="[%(asctime)s] %(levelname)s [scheduler] %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S")
log = logging.getLogger("ps-scheduler")


def _job(source):
    log.info("refresh %s (est ~%ss) ...", source, rm.estimate_seconds(source))
    st = rm.run_blocking(source)
    log.info("refresh %s -> %s%s", source, st["last_status"],
             f" ({st['note']})" if st.get("note") else "")


# ───────────────────────── APScheduler path ─────────────────────────
def _start_apscheduler(blocking):
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.schedulers.blocking import BlockingScheduler
    except Exception:
        return None
    sched = (BlockingScheduler if blocking else BackgroundScheduler)()
    sched.add_job(lambda: _job("social"), "interval", hours=12, id="social", max_instances=1)
    sched.add_job(lambda: _job("amazon"), "interval", hours=24, id="amazon", max_instances=1)
    sched.add_job(lambda: _job("trends"), "cron", day_of_week="mon", hour=0, id="trends")
    sched.add_job(lambda: _job("trade"),  "cron", day_of_week="sun", hour=0, id="trade")
    sched.start()
    log.info("APScheduler started (%s).", "blocking" if blocking else "background")
    return sched


# ───────────────────────── stdlib fallback ─────────────────────────
def _fallback_loop(stop_event):
    """Every minute, refresh any source whose interval has elapsed (uses the
    freshness store's due_now flag)."""
    log.info("APScheduler not available — using stdlib interval loop.")
    while not stop_event.is_set():
        for s in rm.ORDER:
            st = rm.status_for(s)
            if st and st["due_now"] and not st["running"]:
                try:
                    _job(s)
                except Exception as e:  # noqa: BLE001
                    log.error("job %s failed: %s", s, e)
        stop_event.wait(60)


def start_in_app():
    """Non-blocking: start the scheduler in a daemon thread for use inside the
    Flask server (guarded by PS_ENABLE_SCHEDULER)."""
    if _start_apscheduler(blocking=False):
        return
    stop = threading.Event()
    threading.Thread(target=_fallback_loop, args=(stop,), daemon=True).start()


if __name__ == "__main__":
    log.info("Starting Product Scout refresh scheduler. Ctrl+C to stop.")
    if _start_apscheduler(blocking=True):
        pass
    else:
        try:
            _fallback_loop(threading.Event())
        except (KeyboardInterrupt, SystemExit):
            log.info("Scheduler stopped.")
