"""ESPN scoreboard JSON adapter (unofficial endpoint; subject to change)."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"


def game_status(status):
    info = status.get("type") or {}
    name = info.get("name", "")
    state = info.get("state", "")
    special = {
        "STATUS_HALFTIME": "HALF_TIME",
        "STATUS_POSTPONED": "POSTPONED",
        "STATUS_CANCELED": "CANCELLED",
        "STATUS_CANCELLED": "CANCELLED",
        "STATUS_SUSPENDED": "SUSPENDED",
        "STATUS_FULL_TIME": "FINISHED",
        "STATUS_FINAL": "FINISHED",
    }
    if name in special:
        return special[name]
    if state == "pre":
        return "SCHEDULED"
    if state == "post":
        return "FINISHED"
    if state == "in":
        return {1: "FIRST_HALF", 2: "SECOND_HALF", 3: "EXTRA_TIME", 4: "EXTRA_TIME", 5: "PENALTIES"}.get(status.get("period"), "LIVE")
    return name or "UNKNOWN"


def score(value):
    if isinstance(value, dict):
        value = value.get("value", value.get("displayValue"))
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def parse_event(event):
    competitions = event.get("competitions") or []
    if not competitions:
        return None
    game = competitions[0]
    competitors = game.get("competitors") or []
    home = next((x for x in competitors if x.get("homeAway") == "home"), None)
    away = next((x for x in competitors if x.get("homeAway") == "away"), None)
    if not home or not away or not event.get("id") or not event.get("date"):
        return None
    raw_status = event.get("status") or game.get("status") or {}
    info = raw_status.get("type") or {}
    state = info.get("state")
    venue = game.get("venue") or {}
    return {
        "id": str(event["id"]),
        "date": event["date"],
        "homeTeam": (home.get("team") or {}).get("displayName"),
        "awayTeam": (away.get("team") or {}).get("displayName"),
        "homeScore": score(home.get("score")),
        "awayScore": score(away.get("score")),
        "status": game_status(raw_status),
        "espnStatus": info.get("name"),
        "statusDetail": info.get("detail"),
        "state": state,
        "elapsed": raw_status.get("displayClock"),
        "period": raw_status.get("period"),
        "isLive": state == "in",
        "isFinished": state == "post",
        "venue": venue.get("fullName") if isinstance(venue, dict) else None,
    }


def dates_for_window(timezone_name, before, after):
    today = datetime.now(ZoneInfo(timezone_name)).date()
    return [(today + timedelta(days=delta)).strftime("%Y%m%d") for delta in range(-before, after + 1)]


def fetch_scoreboard(espn_id, dates, timeout=20):
    matches = {}
    with requests.Session() as session:
        session.headers.update({"Accept": "application/json", "User-Agent": "FootballLiveSync/1.0"})
        for day in sorted(set(dates)):
            response = session.get(f"{BASE}/{espn_id}/scoreboard", params={"dates": day, "limit": 200}, timeout=timeout)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
                raise ValueError(f"{espn_id} / {day}: unexpected ESPN response")
            for event in payload["events"]:
                parsed = parse_event(event)
                if parsed:
                    matches[parsed["id"]] = parsed
            print(f"{espn_id} / {day}: {len(payload['events'])} events", flush=True)
    return sorted(matches.values(), key=lambda x: (x["date"], x["id"]))
