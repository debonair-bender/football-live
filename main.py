import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from scrapers.espn import fetch_matches

ROOT = Path(__file__).resolve().parent
CONFIG_FILE = ROOT / "config.json"
DATA_DIR = ROOT / "data"


def update_competition(slug, config, settings):
    name = config.get("name", slug)
    espn_id = config["espn_id"]

    print(f"\n=== Updating {name} ===", flush=True)

    matches = fetch_matches(
        espn_id=espn_id,
        timezone=settings.get("timezone", "Europe/Rome"),
        days_offset=settings.get(
            "days_offset", [-1, 0, 1]
        ),
        timeout=settings.get("timeout", 20)
    )

    output_file = DATA_DIR / slug / "live.json"

    # Automatically create directories
    output_file.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    if output_file.exists():
        previous = json.loads(
            output_file.read_text(encoding="utf-8")
        )

        if previous.get("matches") == matches:
            print(f"{slug}: no changes")
            return False

    result = {
        "competition": name,
        "espnId": espn_id,
        "updatedAt": datetime.now(
            timezone.utc
        ).isoformat(),
        "total": len(matches),
        "liveCount": sum(
            1 for match in matches if match["isLive"]
        ),
        "matches": matches
    }

    # Write safely using a temporary file
    temp_file = output_file.with_suffix(".json.tmp")

    temp_file.write_text(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False
        ),
        encoding="utf-8"
    )

    temp_file.replace(output_file)

    print(
        f"{slug}: saved {len(matches)} matches",
        flush=True
    )

    return True


def main():
    config = json.loads(
        CONFIG_FILE.read_text(encoding="utf-8")
    )

    settings = config.get("settings", {})
    competitions = config["competitions"]

    errors = []
    updated = 0

    for slug, competition in competitions.items():
        if not competition.get("enabled", False):
            print(f"SKIP: {slug} disabled")
            continue

        try:
            if update_competition(
                slug,
                competition,
                settings
            ):
                updated += 1

        except Exception as error:
            print(
                f"ERROR {slug}: {error}",
                file=sys.stderr,
                flush=True
            )
            errors.append(slug)

    print(f"\nUpdated competitions: {updated}")

    if errors:
        print(
            f"Failed competitions: {', '.join(errors)}",
            file=sys.stderr
        )
        sys.exit(1)

    print("All competitions processed successfully")


if __name__ == "__main__":
    main()
