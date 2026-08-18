from __future__ import annotations

import asyncio
import json
import sys

from .config import Config
from .models import LEAD_HEADERS
from .persistence.sheets import SheetRepository, _column_letter
from .pipeline import run_harvest
from .providers.youtube import YOUTUBE_API, YouTubeProvider, _extract_links, _official_website
from .runtime.logging import configure_logging
from .runtime.network import NetworkError

_ORIGINAL_YOUTUBE_DISCOVER = YouTubeProvider.discover
_ORIGINAL_UPSERT_LEADS = SheetRepository.upsert_leads


def _is_verified_email_lead(lead) -> bool:
    return bool(
        getattr(lead, "email", "")
        and getattr(lead, "email_status", "") == "VERIFIED_PUBLIC_SOURCE"
    )


async def _youtube_discover_with_video_descriptions(self):
    """Augment channel metadata with public descriptions from recently discovered videos."""
    candidates = await _ORIGINAL_YOUTUBE_DISCOVER(self)
    if not candidates:
        return candidates

    video_ids: list[str] = []
    for candidate in candidates:
        for video_id in candidate.metadata.get("video_ids", [])[:4]:
            if video_id and video_id not in video_ids:
                video_ids.append(video_id)

    descriptions_by_channel: dict[str, list[str]] = {}
    for start in range(0, len(video_ids), 50):
        batch = video_ids[start : start + 50]
        if not batch:
            continue
        try:
            data = await self.context.http.get_json(
                f"{YOUTUBE_API}/videos",
                params={
                    "part": "snippet",
                    "id": ",".join(batch),
                    "maxResults": 50,
                    "key": self.context.config.youtube_api_key,
                },
            )
        except NetworkError:
            continue

        for item in data.get("items", []):
            snippet = item.get("snippet", {})
            channel_id = snippet.get("channelId", "")
            description = snippet.get("description", "") or ""
            if channel_id and description:
                descriptions_by_channel.setdefault(channel_id, []).append(description)

    for candidate in candidates:
        extra_descriptions = descriptions_by_channel.get(candidate.provider_id, [])
        if not extra_descriptions:
            continue

        pieces = [candidate.raw_text or candidate.description or "", *extra_descriptions]
        candidate.raw_text = "\n\n".join(piece for piece in pieces if piece)

        links = list(candidate.raw_links)
        for description in extra_descriptions:
            for link in _extract_links(description):
                if link not in links:
                    links.append(link)
        candidate.raw_links = links

        website = _official_website(links)
        if website:
            candidate.website = website

        candidate.metadata["video_descriptions_checked"] = len(extra_descriptions)

    return candidates


def _email_only_upsert(self, leads):
    """Keep LEADS strictly usable: verified public emails only, while preserving outreach tracking."""
    verified_leads = [lead for lead in leads if _is_verified_email_lead(lead)]
    end_col = _column_letter(len(LEAD_HEADERS))
    existing_rows = self.client.values_get(f"'LEADS'!A2:{end_col}")
    verified_existing = [
        row
        for row in existing_rows
        if len(row) > 10
        and str(row[9]).strip()
        and str(row[10]).strip() == "VERIFIED_PUBLIC_SOURCE"
    ]
    if len(verified_existing) != len(existing_rows):
        self.client.values_clear(f"'LEADS'!A2:{end_col}")
        if verified_existing:
            self.client.values_update("'LEADS'!A2", verified_existing)

    return _ORIGINAL_UPSERT_LEADS(self, verified_leads)


def install_email_first_mode() -> None:
    YouTubeProvider.discover = _youtube_discover_with_video_descriptions
    SheetRepository.upsert_leads = _email_only_upsert


def main() -> int:
    configure_logging()
    try:
        config = Config.from_env()
        if not config.has_public_sources:
            raise ValueError("Configure YOUTUBE_API_KEY and/or PUBLIC_* sources before harvesting")
        install_email_first_mode()
        report = asyncio.run(run_harvest(config))
        report["mode"] = "EMAIL_FIRST_VERIFIED_ONLY"
        report["run_status"] = "SUCCESS_WITH_WARNINGS" if report.get("errors", 0) else "SUCCESS"
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
