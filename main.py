"""Publish separate today/yesterday ESPN football snapshots, local to Europe/Rome."""
import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from scrapers.espn import fetch_scoreboard

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
CONFIG = ROOT / "config.json"
LIVE_FILES = ("live-current.json", "live-yesterday.json")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def save_if_changed(path, payload):
    old = read_json(path)
    if old and {k: v for k, v in old.items() if k != "updatedAt"} == {
        k: v for k, v in payload.items() if k != "updatedAt"
    }:
        print(f"Unchanged: {path.relative_to(ROOT)}", flush=True)
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)
    print(f"Written: {path.relative_to(ROOT)}", flush=True)
    return True


def local_day(match, zone):
    return datetime.fromisoformat(match["date"].replace("Z", "+00:00")).astimezone(zone).date()


def doc(name, espn_id, date_value, matches):
    return {
        "competition": name,
        "espnId": espn_id,
        "date": date_value.isoformat(),
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "total": len(matches),
        "liveCount": sum(bool(m.get("isLive")) for m in matches),
        "matches": sorted(matches, key=lambda m: (m["date"], m["id"])),
    }


def existing_matches(folder):
    """Read both files: yesterday's matches may still be in yesterday's current file."""
    matches = {}
    for filename in LIVE_FILES:
        for match in (read_json(folder / filename) or {}).get("matches", []):
            matches[match["id"]] = match
    return matches


def merge(new_matches, old_matches, allowed_dates, zone):
    """Prefer fresh ESPN; preserve previous scores if a schedule response is less detailed."""
    merged = {mid: m for mid, m in old_matches.items() if local_day(m, zone) in allowed_dates}
    for match in new_matches:
        if local_day(match, zone) not in allowed_dates:
            continue
        previous = merged.get(match["id"])
        if previous and (previous.get("isFinished") or previous.get("isLive")) and match.get("status") == "SCHEDULED":
            continue
        merged[match["id"]] = match
    return list(merged.values())


def publish(folder, name, espn_id, matches, zone):
    today = datetime.now(zone).date()
    yesterday = today - timedelta(days=1)
    for filename, day in (("live-current.json", today), ("live-yesterday.json", yesterday)):
        selected = [m for m in matches if local_day(m, zone) == day]
        save_if_changed(folder / filename, doc(name, espn_id, day, selected))


def should_poll(matches, now, before_minutes, after_hours):
    """Monitor around kickoff; future improvements can incorporate terminal status."""
    for match in matches:
        if match.get("status") in ("POSTPONED", "CANCELLED", "FINISHED") or match.get("isFinished"):
            continue
        kickoff = datetime.fromisoformat(match["date"].replace("Z", "+00:00")).astimezone(timezone.utc)
        if kickoff - timedelta(minutes=before_minutes) <= now <= kickoff + timedelta(hours=after_hours):
            return True
    return False


def process(slug, comp, settings, mode):
    folder = DATA / slug
    zone = ZoneInfo(settings.get("timezone", "Europe/Rome"))
    today = datetime.now(zone).date()
    yesterday = today - timedelta(days=1)
    date_strings = [yesterday.strftime("%Y%m%d"), today.strftime("%Y%m%d")]

    if mode == "schedule":
        fetched = fetch_scoreboard(comp["espn_id"], date_strings, settings.get("request_timeout_seconds", 20))
        save_if_changed(folder / "schedule.json", doc(comp["name"], comp["espn_id"], today, fetched))
        return

    old = existing_matches(folder)
    allowed = {today, yesterday}
    snapshot = read_json(folder / "schedule.json")
    if snapshot is None:
        raise RuntimeError(f"Missing data/{slug}/schedule.json: run schedule workflow first")
    scheduled = [m for m in snapshot.get("matches", []) if local_day(m, zone) in allowed]
    candidates = merge(scheduled, old, allowed, zone)
    # Refresh filenames at midnight even if no live game needs an ESPN request.
    if should_poll(candidates, datetime.now(timezone.utc),
                   settings.get("live_minutes_before", 30),
                   settings.get("live_hours_after", 4)):
        fetched = fetch_scoreboard(comp["espn_id"], date_strings, settings.get("request_timeout_seconds", 20))
        if not fetched:
            raise RuntimeError(f"{slug}: no ESPN events during an active monitoring window")
        candidates = merge(fetched, {m["id"]: m for m in candidates}, allowed, zone)
    else:
        print(f"{slug}: outside live window; no ESPN request", flush=True)
    publish(folder, comp["name"], comp["espn_id"], candidates, zone)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("schedule", "live"))
    args = parser.parse_args()
    config = read_json(CONFIG)
    errors = []
    for slug, comp in config["competitions"].items():
        if not comp.get("enabled", False):
            continue
        try:
            print(f"{slug}: {args.mode}", flush=True)
            process(slug, comp, config.get("settings", {}), args.mode)
        except Exception as exc:
            errors.append(slug)
            print(f"ERROR {slug}: {exc}", file=sys.stderr, flush=True)
    if errors:
        raise SystemExit(f"Failed competitions: {', '.join(errors)}")


if __name__ == "__main__":
    main()
