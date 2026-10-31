"""Schedule discovery every 6 hours; live polling only near scheduled kickoffs."""
import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from scrapers.espn import dates_for_window, fetch_scoreboard

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
CONFIG = ROOT / "config.json"


def read_json(path):
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_if_changed(path, content):
    old = read_json(path)
    if old and all(old.get(key) == value for key, value in content.items() if key != "updatedAt"):
        print(f"No changes: {path.relative_to(ROOT)}", flush=True)
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(content, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)
    print(f"Updated: {path.relative_to(ROOT)}", flush=True)
    return True


def document(competition, espn_id, matches):
    return {
        "competition": competition,
        "espnId": espn_id,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "total": len(matches),
        "liveCount": sum(bool(m.get("isLive")) for m in matches),
        "matches": matches,
    }


def parse_utc(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def active_matches(schedule, now, minutes_before, hours_after):
    result = []
    for match in schedule:
        if match.get("status") in ("POSTPONED", "CANCELLED"):
            continue
        kickoff = parse_utc(match["date"])
        if kickoff - timedelta(minutes=minutes_before) <= now <= kickoff + timedelta(hours=hours_after):
            result.append(match)
    return result


def update_schedule(slug, config, settings):
    dates = dates_for_window(
        settings.get("timezone", "Europe/Rome"),
        settings.get("schedule_days_before", 1),
        settings.get("schedule_days_after", 7),
    )
    matches = fetch_scoreboard(config["espn_id"], dates, settings.get("request_timeout_seconds", 20))
    # ESPN may legitimately return [] for a league with no fixtures in this window.
    changed = write_if_changed(DATA / slug / "schedule.json", document(config["name"], config["espn_id"], matches))
    # Expose an initial empty live endpoint even before the first match begins.
    live_file = DATA / slug / "live.json"
    if not live_file.exists():
        write_if_changed(live_file, document(config["name"], config["espn_id"], []))
    return changed


def update_live(slug, config, settings):
    schedule_data = read_json(DATA / slug / "schedule.json")
    if schedule_data is None:
        raise RuntimeError(f"Missing data/{slug}/schedule.json. Run 'python main.py schedule' first.")
    now = datetime.now(timezone.utc)
    active = active_matches(
        schedule_data.get("matches", []), now,
        settings.get("live_minutes_before", 30),
        settings.get("live_hours_after", 4),
    )
    if not active:
        print(f"{slug}: no matches in polling window; skip ESPN", flush=True)
        return False

    zone = ZoneInfo(settings.get("timezone", "Europe/Rome"))
    # Include adjacent local dates if games cross midnight; ESPN dates are calendar filters.
    dates = set()
    for m in active:
        local = parse_utc(m["date"]).astimezone(zone).date()
        for delta in (-1, 0, 1):
            dates.add((local + timedelta(days=delta)).strftime("%Y%m%d"))
    fetched = fetch_scoreboard(config["espn_id"], dates, settings.get("request_timeout_seconds", 20))
    if not fetched:
        raise RuntimeError(f"{slug}: ESPN returned no events during an active polling window; preserving previous live JSON")

    # Preserve earlier matches in the current schedule window; replace with latest ESPN values.
    prev = read_json(DATA / slug / "live.json") or {}
    scheduled_ids = {m["id"] for m in schedule_data.get("matches", [])}
    merged = {m["id"]: m for m in prev.get("matches", []) if m["id"] in scheduled_ids}
    merged.update({m["id"]: m for m in fetched if m["id"] in scheduled_ids})
    for match in active:
        if match["id"] not in merged:
            raise RuntimeError(f"{slug}: active match {match['id']} missing from ESPN response")
    matches = sorted(merged.values(), key=lambda m: (m["date"], m["id"]))
    return write_if_changed(DATA / slug / "live.json", document(config["name"], config["espn_id"], matches))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["schedule", "live"])
    args = parser.parse_args()
    config = read_json(CONFIG)
    settings = config.get("settings", {})
    errors = []
    for slug, comp in config["competitions"].items():
        if not comp.get("enabled", False):
            print(f"Skip disabled: {slug}")
            continue
        try:
            print(f"Processing {slug}: {args.mode}", flush=True)
            if args.mode == "schedule":
                update_schedule(slug, comp, settings)
            else:
                update_live(slug, comp, settings)
        except Exception as exc:
            print(f"ERROR {slug}: {exc}", file=sys.stderr, flush=True)
            errors.append(slug)
    if errors:
        raise SystemExit(f"Failed: {', '.join(errors)}")


if __name__ == "__main__":
    main()
