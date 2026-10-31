from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

BASE_URL = (
    "https://site.api.espn.com/apis/site/v2/"
    "sports/soccer"
)


def get_match_status(status):
    status_type = status.get("type", {})
    state = status_type.get("state")
    name = status_type.get("name", "")
    detail = status_type.get("detail", "")

    if name == "STATUS_HALFTIME":
        return "HALF_TIME"

    if name == "STATUS_POSTPONED":
        return "POSTPONED"

    if name == "STATUS_CANCELED":
        return "CANCELLED"

    if name == "STATUS_SUSPENDED":
        return "SUSPENDED"

    if state == "pre":
        return "SCHEDULED"

    if state == "post":
        return "FINISHED"

    if state == "in":
        period = status.get("period")

        if period == 1:
            return "FIRST_HALF"
        if period == 2:
            return "SECOND_HALF"
        if period in (3, 4):
            return "EXTRA_TIME"
        if period == 5:
            return "PENALTIES"

        return "LIVE"

    return name or detail or "UNKNOWN"


def parse_score(value):
    if value is None or value == "":
        return None

    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def parse_event(event):
    competitions = event.get("competitions") or []

    if not competitions:
        return None

    competition = competitions[0]
    competitors = competition.get("competitors", [])

    home = next(
        (t for t in competitors if t.get("homeAway") == "home"),
        None
    )
    away = next(
        (t for t in competitors if t.get("homeAway") == "away"),
        None
    )

    if not home or not away:
        return None

    status = event.get("status", {})
    status_type = status.get("type", {})

    match_status = get_match_status(status)

    home_team = home.get("team", {})
    away_team = away.get("team", {})

    return {
        "id": str(event.get("id")),
        "date": event.get("date"),
        "homeTeam": home_team.get("displayName"),
        "awayTeam": away_team.get("displayName"),
        "homeTeamId": home_team.get("id"),
        "awayTeamId": away_team.get("id"),
        "homeScore": parse_score(home.get("score")),
        "awayScore": parse_score(away.get("score")),
        "status": match_status,
        "espnStatus": status_type.get("name"),
        "statusDetail": status_type.get("detail"),
        "state": status_type.get("state"),
        "elapsed": status.get("displayClock"),
        "period": status.get("period"),
        "isLive": status_type.get("state") == "in",
        "isFinished": status_type.get("state") == "post",
        "venue": (
            competition.get("venue", {}).get("fullName")
            if isinstance(competition.get("venue"), dict)
            else None
        )
    }


def fetch_matches(
    espn_id,
    timezone="Europe/Rome",
    days_offset=None,
    timeout=20
):
    if days_offset is None:
        days_offset = [-1, 0, 1]

    now = datetime.now(ZoneInfo(timezone))
    matches = {}

    session = requests.Session()
    session.headers.update({
        "Accept": "application/json",
        "User-Agent": "FootballLiveSync/1.0"
    })

    for offset in days_offset:
        date = (
            now + timedelta(days=offset)
        ).strftime("%Y%m%d")

        url = f"{BASE_URL}/{espn_id}/scoreboard"

        response = session.get(
            url,
            params={"dates": date, "limit": 200},
            timeout=timeout
        )

        response.raise_for_status()
        payload = response.json()

        if not isinstance(payload.get("events"), list):
            raise ValueError(
                f"{espn_id}: invalid ESPN response for {date}"
            )

        events = payload["events"]

        print(
            f"{espn_id} | {date} | "
            f"{len(events)} events",
            flush=True
        )

        for event in events:
            match = parse_event(event)

            if match is not None:
                matches[match["id"]] = match

    return sorted(
        matches.values(),
        key=lambda m: (m["date"] or "", m["id"])
    )
