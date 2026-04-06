"""Scheduler for quarterly data refresh pipeline."""

import argparse
import sys

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from db import setup_logging

logger = setup_logging("scheduler")


def run_pipeline():
    """Run the full pipeline: collect -> classify -> analyze."""
    logger.info("Starting quarterly pipeline run")

    try:
        from collect import run_collection
        logger.info("Step 1/3: Data collection")
        run_collection()
    except Exception as e:
        logger.error("Collection failed: %s", e)
        return

    try:
        from classify import run_classification
        logger.info("Step 2/3: Chain classification")
        run_classification()
    except Exception as e:
        logger.error("Classification failed: %s", e)
        return

    try:
        from analyze import run_analysis
        logger.info("Step 3/3: Quarterly analysis")
        run_analysis()
    except Exception as e:
        logger.error("Analysis failed: %s", e)
        return

    logger.info("Pipeline complete")


def main():
    parser = argparse.ArgumentParser(description="Gym intelligence quarterly scheduler")
    parser.add_argument(
        "--now", action="store_true", help="Run the pipeline immediately instead of scheduling"
    )
    args = parser.parse_args()

    if args.now:
        logger.info("Running pipeline immediately (--now flag)")
        run_pipeline()
        return

    logger.info("Starting scheduler — pipeline will run on the first Monday of each quarter")

    scheduler = BlockingScheduler()

    # First Monday of January, April, July, October at 06:00 UTC
    scheduler.add_job(
        run_pipeline,
        CronTrigger(month="1,4,7,10", day="1-7", day_of_week="mon", hour=6, minute=0),
        id="quarterly_refresh",
        name="Quarterly gym data refresh",
    )

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped")


if __name__ == "__main__":
    main()
