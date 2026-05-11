#!/usr/bin/env python3
"""
Donut Intel Platform — CLI (F73)
Usage: python cli.py <command> [options]
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def _setup():
    from backend.database.db import init_db
    init_db()


# ---------------------------------------------------------------------------
# Source scan
# ---------------------------------------------------------------------------

def cmd_scan(args):
    _setup()
    from backend.database.db import session_scope
    from backend.database.models import ScanSession
    from backend.scrapers.source_scraper import run_source_scan
    from datetime import datetime, timezone

    with session_scope() as db:
        sess = ScanSession(
            name=f"CLI Scan {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}",
            session_type="source",
            target=args.site or "all_sources",
            status="pending",
        )
        db.add(sess)
        db.flush()
        session_id = sess.id

    def progress(event, data):
        if event == "product_progress":
            print(f"\r  [{data.get('site','')}] {data.get('current',0)}/{data.get('total',0)} products", end="", flush=True)
        elif event in ("site_start", "site_complete", "urls_found"):
            print(f"\n  {event}: {data}")

    print(f"Starting scan (session #{session_id})...")
    asyncio.run(run_source_scan(
        scan_session_id=session_id,
        site_filter=args.site,
        progress_callbacks=[lambda event, data: progress(event, data)],
    ))
    print("\n\nSource scan complete.")


# ---------------------------------------------------------------------------
# Competitor scan
# ---------------------------------------------------------------------------

def cmd_competitor_scan(args):
    _setup()
    from backend.competitor.scraper import run_competitor_scan
    from backend.database.db import session_scope
    from backend.database.models import Competitor
    from datetime import datetime, timezone

    with session_scope() as db:
        if args.domain:
            comp = db.query(Competitor).filter(Competitor.domain == args.domain).first()
            if not comp:
                print(f"Competitor '{args.domain}' not found. Add it first.")
                sys.exit(1)
            competitor_ids = [comp.id]
        else:
            competitor_ids = [c.id for c in db.query(Competitor).filter(Competitor.is_active == True).all()]

    if not competitor_ids:
        print("No competitors found. Discover or import competitors first.")
        sys.exit(1)

    session_name = args.session or f"CLI Scan {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}"
    for cid in competitor_ids:
        print(f"Scanning competitor {cid}...")
        result = asyncio.run(run_competitor_scan(
            competitor_id=cid,
            session_name=session_name,
            find_similar=args.similar,
        ))
        print(f"  → {result.get('competitor')}: {result.get('matches_found')} matches")


# ---------------------------------------------------------------------------
# Competitor import
# ---------------------------------------------------------------------------

def cmd_import(args):
    _setup()
    from backend.competitor.discovery import bulk_import_competitors
    from backend.database.db import session_scope
    from backend.database.models import Competitor
    from datetime import datetime, timezone

    domains = []
    if args.file:
        with open(args.file) as f:
            domains = [line.strip() for line in f if line.strip()]
    elif args.domains:
        domains = args.domains

    if not domains:
        print("Provide --file or --domains")
        sys.exit(1)

    parsed = asyncio.run(bulk_import_competitors(domains))
    added = 0
    with session_scope() as db:
        for d in parsed:
            if not db.query(Competitor).filter(Competitor.domain == d["domain"]).first():
                db.add(Competitor(
                    domain=d["domain"], name=d["name"], base_url=d["base_url"],
                    scan_session_name=args.session or f"CLI Import {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
                ))
                added += 1
    print(f"Imported {added}/{len(parsed)} new competitors.")


# ---------------------------------------------------------------------------
# Dedup
# ---------------------------------------------------------------------------

def cmd_dedup(args):
    _setup()
    from backend.database.db import session_scope
    from backend.dedup.engine import DeduplicationEngine

    print("Running deduplication...")
    with session_scope() as db:
        engine = DeduplicationEngine()
        stats = engine.run(db)
    print(f"Deduplication complete: {json.dumps(stats, indent=2)}")


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

def cmd_stats(args):
    _setup()
    from backend.database.db import session_scope, db_health_check
    from backend.database.models import Product, ProductSource, DuplicateCandidate, ScanSession, Competitor, CompetitorProductMatch
    from sqlalchemy import func

    with session_scope() as db:
        total = db.query(func.count(Product.id)).filter(Product.is_active == True).scalar()
        sources = db.query(func.count(ProductSource.id)).filter(ProductSource.is_active == True).scalar()
        pending_dups = db.query(func.count(DuplicateCandidate.id)).filter(DuplicateCandidate.status == "pending").scalar()
        total_competitors = db.query(func.count(Competitor.id)).filter(Competitor.is_active == True).scalar()
        total_matches = db.query(func.count(CompetitorProductMatch.id)).filter(CompetitorProductMatch.is_active == True).scalar()
        last_scan = db.query(ScanSession).order_by(ScanSession.started_at.desc()).first()
        last_scan_status = last_scan.status if last_scan else None
        last_scan_started = last_scan.started_at.isoformat() if last_scan and last_scan.started_at else None
        site_counts = (
            db.query(ProductSource.source_site, func.count(ProductSource.id))
            .filter(ProductSource.is_active == True)
            .group_by(ProductSource.source_site).all()
        )

    health = db_health_check()
    print(f"\n{'='*50}")
    print(f"  Donut Intel Platform — Catalog Stats")
    print(f"{'='*50}")
    print(f"  Total Products:         {total}")
    print(f"  Source Listings:        {sources}")
    print(f"  Pending Duplicates:     {pending_dups}")
    print(f"  Competitors Tracked:    {total_competitors}")
    print(f"  Competitor Matches:     {total_matches}")
    print(f"\n  Products by Site:")
    for site, count in site_counts:
        print(f"    {site:<30} {count}")
    print(f"\n  Last Scan: {last_scan_status or 'None'} {('(' + last_scan_started + ')') if last_scan_started else ''}")
    print(f"\n  DB Path:   {health['path']}")
    print(f"  DB Size:   {health['size_mb']} MB")
    print(f"  WAL Mode:  {health['wal_mode']}")
    print(f"{'='*50}\n")


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def cmd_export(args):
    _setup()
    from backend.export.exporter import export_products_csv, export_products_xlsx, export_products_txt

    fmt = args.format or "csv"
    if fmt == "xlsx":
        data, filename = export_products_xlsx(triggered_by="cli")
    elif fmt == "txt":
        data, filename = export_products_txt(triggered_by="cli")
    else:
        data, filename = export_products_csv(triggered_by="cli")

    out = Path(args.output) if args.output else Path("./exports") / filename
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    print(f"Exported {fmt.upper()} to {out}")


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def cmd_report(args):
    _setup()
    from backend.reports.reporter import price_disparity_report, summary_report, competitor_report, price_comparison_report

    if args.type == "summary":
        html = summary_report(args.days or 7)
    elif args.type == "disparity":
        html = price_disparity_report(args.threshold or 5.0)
    elif args.type == "competitor" and args.id:
        html = competitor_report(args.id)
    elif args.type == "price" and args.id:
        html = price_comparison_report(args.id)
    else:
        print("Specify --type summary|disparity|competitor|price and --id if needed.")
        sys.exit(1)

    out = Path(args.output) if args.output else Path(f"./exports/report_{args.type}.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"Report saved to {out}")


# ---------------------------------------------------------------------------
# DB path
# ---------------------------------------------------------------------------

def cmd_dbpath(args):
    _setup()
    from backend.config import config

    if args.set:
        config.set("database", "path", args.set)
        print(f"Database path updated to: {args.set}")
        print("Restart the server for this to take effect.")
    else:
        path = config.db_path()
        print(f"Database path: {path}")
        print(f"Exists: {path.exists()}")
        if path.exists():
            print(f"Size: {path.stat().st_size / 1024 / 1024:.2f} MB")


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

def cmd_schedule(args):
    _setup()
    from backend.scheduler.scheduler import create_job, list_jobs, delete_job, run_job_now

    if args.action == "list":
        jobs = list_jobs()
        if not jobs:
            print("No scheduled jobs.")
            return
        for j in jobs:
            print(f"[{j['id']}] {j['name']} ({j['job_type']}) — {j['schedule_type']}:{j['schedule_value']} next={j.get('next_run_at','?')}")

    elif args.action == "create":
        result = create_job(
            name=args.name,
            job_type=args.job_type,
            target=args.target,
            schedule_type=args.schedule_type,
            schedule_value=args.schedule_value,
        )
        print(f"Created job #{result['id']}: {args.name}")

    elif args.action == "delete":
        delete_job(args.id)
        print(f"Deleted job #{args.id}")

    elif args.action == "run":
        run_job_now(args.id)
        print(f"Queued job #{args.id} to run immediately")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(prog="donut-intel", description="Donut Intel Platform CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    # scan
    p = sub.add_parser("scan", help="Scrape source sites")
    p.add_argument("--site", default=None, help="Specific site domain")
    p.set_defaults(func=cmd_scan)

    # competitor-scan
    p = sub.add_parser("competitor-scan", help="Scan competitor sites")
    p.add_argument("--domain", default=None, help="Specific competitor domain")
    p.add_argument("--session", default=None, help="Session name")
    p.add_argument("--similar", action="store_true", help="Also find similar products")
    p.set_defaults(func=cmd_competitor_scan)

    # import
    p = sub.add_parser("import-competitors", help="Bulk import competitor domains")
    p.add_argument("--file", default=None, help="File with one domain per line")
    p.add_argument("--domains", nargs="+", default=None, help="Domains to import")
    p.add_argument("--session", default=None, help="Session name")
    p.set_defaults(func=cmd_import)

    # dedup
    p = sub.add_parser("dedup", help="Run deduplication")
    p.set_defaults(func=cmd_dedup)

    # stats
    p = sub.add_parser("stats", help="Show catalog statistics")
    p.set_defaults(func=cmd_stats)

    # export
    p = sub.add_parser("export", help="Export data")
    p.add_argument("--format", choices=["csv", "xlsx", "txt"], default="csv")
    p.add_argument("--output", default=None, help="Output file path")
    p.set_defaults(func=cmd_export)

    # report
    p = sub.add_parser("report", help="Generate an HTML report")
    p.add_argument("--type", choices=["summary", "disparity", "competitor", "price"], default="summary")
    p.add_argument("--id", type=int, default=None, help="Competitor or product ID")
    p.add_argument("--days", type=int, default=7)
    p.add_argument("--threshold", type=float, default=5.0)
    p.add_argument("--output", default=None, help="Output file path")
    p.set_defaults(func=cmd_report)

    # dbpath
    p = sub.add_parser("dbpath", help="Show or set database path")
    p.add_argument("--set", default=None, help="Set new database path")
    p.set_defaults(func=cmd_dbpath)

    # schedule
    p = sub.add_parser("schedule", help="Manage scheduled jobs")
    p.add_argument("action", choices=["list", "create", "delete", "run"])
    p.add_argument("--name", default=None)
    p.add_argument("--job-type", default="source_scan", dest="job_type")
    p.add_argument("--target", default=None)
    p.add_argument("--schedule-type", default="daily", dest="schedule_type")
    p.add_argument("--schedule-value", default="09:00", dest="schedule_value")
    p.add_argument("--id", type=int, default=None)
    p.set_defaults(func=cmd_schedule)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
