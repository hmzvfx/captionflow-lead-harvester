from __future__ import annotations

import json
from collections import Counter
from typing import Any

from ..models import LEAD_HEADERS, LeadRecord

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SHEETS = ["LEADS", "HOT LEADS", "NO EMAIL", "STATS", "SYSTEM_STATE"]
HOT_HEADERS = ["Name", "Email", "Profile URL", "Website", "Niche", "Score", "Language", "Country", "Email Status", "Source"]
NO_EMAIL_HEADERS = ["Name", "Profile URL", "Website", "Niche", "Score", "Language", "Country", "Source", "Why Qualified"]
STATUS_VALUES = ["NEW", "REVIEWED", "CONTACTED", "REPLIED", "INTERESTED", "CUSTOMER", "NOT_RELEVANT"]


def _column_letter(number: int) -> str:
    result = ""
    value = max(1, number)
    while value:
        value, remainder = divmod(value - 1, 26)
        result = chr(65 + remainder) + result
    return result


def lead_to_row(lead: LeadRecord) -> list[Any]:
    return [
        lead.lead_id, lead.discovered_at, lead.last_checked, lead.source, lead.name, lead.username,
        lead.platform, lead.profile_url, lead.website, lead.email, lead.email_status, lead.email_source_url,
        lead.niche, lead.country, lead.language, lead.followers if lead.followers is not None else "",
        lead.recent_activity, lead.content_type, lead.caption_opportunity, lead.captionflow_score,
        lead.classification, lead.why_qualified, lead.status,
        lead.instagram_url, lead.instagram_status, lead.instagram_search_query,
        lead.outreach_status, lead.email_subject, lead.sent_at, lead.gmail_message_id,
        lead.outreach_error, lead.outreach_attempts,
    ]


def row_to_dict(row: list[Any]) -> dict[str, Any]:
    padded = list(row) + [""] * max(0, len(LEAD_HEADERS) - len(row))
    return dict(zip(LEAD_HEADERS, padded[: len(LEAD_HEADERS)]))


class GoogleSheetsClient:
    def __init__(self, spreadsheet_id: str, service=None) -> None:
        self.spreadsheet_id = spreadsheet_id
        if service is None:
            try:
                import google.auth
                from googleapiclient.discovery import build
            except ImportError as exc:
                raise RuntimeError("Google Sheets dependencies are not installed; run pip install -e .") from exc
            credentials, _ = google.auth.default(scopes=SCOPES)
            service = build("sheets", "v4", credentials=credentials, cache_discovery=False)
        self.service = service

    def metadata(self) -> dict:
        return self.service.spreadsheets().get(spreadsheetId=self.spreadsheet_id).execute()

    def values_get(self, range_name: str) -> list[list[Any]]:
        result = self.service.spreadsheets().values().get(spreadsheetId=self.spreadsheet_id, range=range_name).execute()
        return result.get("values", [])

    def values_update(self, range_name: str, values: list[list[Any]]) -> None:
        self.service.spreadsheets().values().update(
            spreadsheetId=self.spreadsheet_id,
            range=range_name,
            valueInputOption="USER_ENTERED",
            body={"values": values},
        ).execute()

    def values_clear(self, range_name: str) -> None:
        self.service.spreadsheets().values().clear(spreadsheetId=self.spreadsheet_id, range=range_name, body={}).execute()

    def batch_update(self, requests: list[dict]) -> None:
        if requests:
            self.service.spreadsheets().batchUpdate(spreadsheetId=self.spreadsheet_id, body={"requests": requests}).execute()


class SheetRepository:
    def __init__(self, spreadsheet_id: str, service=None) -> None:
        if not spreadsheet_id:
            raise ValueError("GOOGLE_SPREADSHEET_ID is required")
        self.client = GoogleSheetsClient(spreadsheet_id, service=service)

    @property
    def leads_end_column(self) -> str:
        return _column_letter(len(LEAD_HEADERS))

    def bootstrap(self) -> None:
        meta = self.client.metadata()
        existing = {s["properties"]["title"]: s["properties"] for s in meta.get("sheets", [])}
        add_requests = [{"addSheet": {"properties": {"title": title}}} for title in SHEETS if title not in existing]
        self.client.batch_update(add_requests)
        if add_requests:
            meta = self.client.metadata()
            existing = {s["properties"]["title"]: s["properties"] for s in meta.get("sheets", [])}

        expected = {
            "LEADS": LEAD_HEADERS,
            "HOT LEADS": HOT_HEADERS,
            "NO EMAIL": NO_EMAIL_HEADERS,
            "STATS": ["Metric", "Value"],
            "SYSTEM_STATE": ["Key", "JSON Value"],
        }
        for title, headers in expected.items():
            current = self.client.values_get(f"'{title}'!1:1")
            if not current or not any(str(x).strip() for x in current[0]):
                self.client.values_update(f"'{title}'!A1", [headers])
                continue

            actual = [str(x) for x in current[0]]
            if actual == headers:
                continue

            if title == "LEADS" and actual == headers[: len(actual)] and len(actual) < len(headers):
                start_col = _column_letter(len(actual) + 1)
                self.client.values_update(f"'{title}'!{start_col}1", [headers[len(actual):]])
                continue

            raise RuntimeError(f"Sheet '{title}' exists with incompatible headers; no destructive reset was performed")

        requests: list[dict] = []
        for title in ("LEADS", "HOT LEADS", "NO EMAIL", "STATS"):
            props = existing[title]
            end_index = len(LEAD_HEADERS) if title == "LEADS" else 10
            requests.extend([
                {"updateSheetProperties": {"properties": {"sheetId": props["sheetId"], "gridProperties": {"frozenRowCount": 1}}, "fields": "gridProperties.frozenRowCount"}},
                {"repeatCell": {"range": {"sheetId": props["sheetId"], "startRowIndex": 0, "endRowIndex": 1}, "cell": {"userEnteredFormat": {"backgroundColor": {"red": 0.08, "green": 0.09, "blue": 0.12}, "textFormat": {"foregroundColor": {"red": 1, "green": 1, "blue": 1}, "bold": True}}}, "fields": "userEnteredFormat(backgroundColor,textFormat)"}},
                {"autoResizeDimensions": {"dimensions": {"sheetId": props["sheetId"], "dimension": "COLUMNS", "startIndex": 0, "endIndex": end_index}}},
            ])
        system_props = existing["SYSTEM_STATE"]
        requests.append({"updateSheetProperties": {"properties": {"sheetId": system_props["sheetId"], "hidden": True}, "fields": "hidden"}})

        leads_id = existing["LEADS"]["sheetId"]
        if not existing["LEADS"].get("basicFilter"):
            requests.append({"setBasicFilter": {"filter": {"range": {"sheetId": leads_id, "startRowIndex": 0, "startColumnIndex": 0, "endColumnIndex": len(LEAD_HEADERS)}}}})
        requests.append({
            "setDataValidation": {
                "range": {"sheetId": leads_id, "startRowIndex": 1, "startColumnIndex": 22, "endColumnIndex": 23},
                "rule": {"condition": {"type": "ONE_OF_LIST", "values": [{"userEnteredValue": v} for v in STATUS_VALUES]}, "strict": False, "showCustomUi": True},
            }
        })
        self.client.batch_update(requests)
        self._initialize_state_defaults()

    def _initialize_state_defaults(self) -> None:
        state = self.load_state()
        defaults = {
            "processed_queries": [], "query_cursors": {}, "channel_checked_at": {}, "website_checked_at": {},
            "email_checked_at": {}, "instagram_lookup_cache": {}, "processed_video_ids": [], "provider_state": {},
            "failed_jobs": {}, "retry_queue": [], "dead_letter_queue": [], "youtube_query_offset": 0,
            "youtube_query_tokens": {}, "youtube_query_done_at": {}, "youtube_known_channel_ids": [],
        }
        changed = False
        for key, value in defaults.items():
            if key not in state:
                state[key] = value
                changed = True
        if changed:
            self.save_state(state)

    def load_state(self) -> dict[str, Any]:
        rows = self.client.values_get("'SYSTEM_STATE'!A2:B")
        state: dict[str, Any] = {}
        for row in rows:
            if len(row) < 2 or not row[0]:
                continue
            try:
                state[str(row[0])] = json.loads(str(row[1]))
            except json.JSONDecodeError:
                continue
        return state

    def save_state(self, state: dict[str, Any]) -> None:
        rows = [[key, json.dumps(value, ensure_ascii=False, separators=(",", ":"))] for key, value in sorted(state.items())]
        self.client.values_clear("'SYSTEM_STATE'!A2:B")
        if rows:
            self.client.values_update("'SYSTEM_STATE'!A2", rows)

    def upsert_leads(self, leads: list[LeadRecord]) -> tuple[int, int, list[list[Any]]]:
        leads_range = f"'LEADS'!A2:{self.leads_end_column}"
        existing_rows = self.client.values_get(leads_range)
        by_id: dict[str, list[Any]] = {str(r[0]): list(r) for r in existing_rows if r and r[0]}
        new_count = 0
        updated_count = 0
        for lead in leads:
            row = lead_to_row(lead)
            existing = by_id.get(lead.lead_id)
            if existing:
                existing_padded = existing + [""] * (len(LEAD_HEADERS) - len(existing))
                row[1] = existing_padded[1] or row[1]
                row[22] = existing_padded[22] or row[22]
                if existing_padded[23] and not row[23]:
                    row[23] = existing_padded[23]
                    row[24] = existing_padded[24] or row[24]
                    row[25] = existing_padded[25] or row[25]
                # Outreach is managed independently by the Gmail automation and must never
                # be erased or reset by a discovery/enrichment harvest.
                for index in range(26, len(LEAD_HEADERS)):
                    if existing_padded[index] not in (None, ""):
                        row[index] = existing_padded[index]
                updated_count += 1
            else:
                new_count += 1
            by_id[lead.lead_id] = row
        all_rows = list(by_id.values())
        all_rows.sort(key=lambda r: str((r + [""] * len(LEAD_HEADERS))[1]), reverse=True)
        self.client.values_clear(leads_range)
        if all_rows:
            self.client.values_update("'LEADS'!A2", all_rows)
        self.refresh_views(all_rows)
        return new_count, updated_count, all_rows

    def refresh_views(self, all_rows: list[list[Any]]) -> None:
        padded_rows = [r + [""] * (len(LEAD_HEADERS) - len(r)) for r in all_rows]
        hot_rows = [r for r in padded_rows if str(r[20]).upper() == "HOT"]
        hot_rows.sort(key=lambda r: (str(r[10]) == "VERIFIED_PUBLIC_SOURCE", int(r[19] or 0)), reverse=True)
        hot_values = [[r[4], r[9], r[7], r[8], r[12], r[19], r[14], r[13], r[10], r[3]] for r in hot_rows]
        no_email_rows = [r for r in padded_rows if not str(r[9]).strip()]
        no_email_rows.sort(key=lambda r: int(r[19] or 0), reverse=True)
        no_email_values = [[r[4], r[7], r[8], r[12], r[19], r[14], r[13], r[3], r[21]] for r in no_email_rows]

        self.client.values_clear("'HOT LEADS'!A2:J")
        self.client.values_clear("'NO EMAIL'!A2:I")
        if hot_values:
            self.client.values_update("'HOT LEADS'!A2", hot_values)
        if no_email_values:
            self.client.values_update("'NO EMAIL'!A2", no_email_values)

    def update_stats(self, all_rows: list[list[Any]], metrics: dict[str, Any]) -> None:
        padded = [r + [""] * (len(LEAD_HEADERS) - len(r)) for r in all_rows]
        total = len(padded)
        hot = sum(1 for r in padded if str(r[20]).upper() == "HOT")
        emails = sum(1 for r in padded if str(r[9]).strip())
        verified = sum(1 for r in padded if str(r[10]) == "VERIFIED_PUBLIC_SOURCE")
        instagram = sum(1 for r in padded if str(r[23]).strip())
        contacted = sum(1 for r in padded if str(r[22]).upper() == "CONTACTED")
        sent = sum(1 for r in padded if str(r[26]).upper() == "SENT")
        no_email = total - emails
        today = str(metrics.get("started_at", ""))[:10]
        new_today = sum(1 for r in padded if str(r[1])[:10] == today)
        rows: list[list[Any]] = [
            ["TOTAL LEADS", total], ["NEW TODAY", new_today], ["HOT LEADS", hot], ["EMAILS FOUND", emails],
            ["VERIFIED EMAILS", verified], ["INSTAGRAM FOUND", instagram], ["CONTACTED", contacted], ["OUTREACH SENT", sent], ["NO EMAIL", no_email],
            ["LAST RUN", metrics.get("finished_at", "")], ["LAST RUN DURATION", metrics.get("duration", 0)],
            ["LEADS DISCOVERED LAST RUN", metrics.get("candidates_found", 0)], ["NEW LEADS LAST RUN", metrics.get("new_leads", 0)],
            ["DUPLICATES PREVENTED", metrics.get("duplicates_prevented", 0)], ["WEBSITES CRAWLED", metrics.get("websites_crawled", 0)],
            ["YOUTUBE REQUESTS", metrics.get("youtube_requests", 0)], ["YOUTUBE SEARCH REQUESTS", metrics.get("youtube_search_requests", 0)],
            ["INSTAGRAM LOOKUPS", metrics.get("instagram_lookups", 0)], ["INSTAGRAM FOUND LAST RUN", metrics.get("instagram_found", 0)],
            ["ERRORS", metrics.get("errors", 0)],
        ]
        dimensions = [
            ("LEADS BY SOURCE", 3), ("LEADS BY NICHE", 12), ("LEADS BY LANGUAGE", 14), ("LEADS BY COUNTRY", 13),
        ]
        for title, index in dimensions:
            rows.append([title, ""])
            counter = Counter(str(r[index] or "UNKNOWN") for r in padded)
            rows.extend([[f"  {key}", value] for key, value in counter.most_common(15)])
        self.client.values_clear("'STATS'!A2:B")
        if rows:
            self.client.values_update("'STATS'!A2", rows)


class SheetStateStore:
    def __init__(self, repository: SheetRepository) -> None:
        self.repository = repository
        self.data = repository.load_state()

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value

    def flush(self) -> None:
        self.repository.save_state(self.data)
