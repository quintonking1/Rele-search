"""Map complaints and changelog items into the unified record schema (PRD: Data sources)."""

import json
from pathlib import Path


def load_complaints(path: Path) -> list[dict]:
    data = json.loads(path.read_text())
    return [
        {
            "id": c["complaint_id"],
            "source_type": "complaint",
            "date": c["date"],
            "product_area": c["product_area"],
            "title": c["title"],
            "text": c["text"],
            "platforms": c["platforms"],
            "plan": [c["plan"]],
            "audience": [c["customer_role"]],
            "extra": {
                "channel": c["channel"],
                "severity": c["severity"],
                "customer_id": c["customer_id"],
            },
        }
        for c in data["complaints"]
    ]


def load_changelog(path: Path) -> list[dict]:
    data = json.loads(path.read_text())
    records = []
    for release in data["releases"]:
        for item in release["items"]:
            records.append(
                {
                    "id": item["item_id"],
                    "source_type": "changelog",
                    "date": release["release_date"],
                    "product_area": item["product_area"],
                    "title": item["title"],
                    "text": f"{release['release_title']}\n\n{item['description']}",
                    "platforms": item["platforms"],
                    "plan": item["plan_availability"],
                    "audience": item["audience"],
                    "extra": {
                        "version": release["version"],
                        "release_id": release["release_id"],
                        "change_type": item["change_type"],
                    },
                }
            )
    return records


def load_all(complaints_path: Path, changelog_path: Path) -> list[dict]:
    records = load_complaints(complaints_path) + load_changelog(changelog_path)
    ids = [r["id"] for r in records]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate record ids across datasets")
    return records
