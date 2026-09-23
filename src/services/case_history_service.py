"""CaseHistoryService — approved-source adapter for case-history event retrieval."""

from __future__ import annotations

from typing import Any

# Sentinel credential that routes fetch_events() to the bundled fixture case
# history instead of the live connector. Used when CASE_HISTORY_SERVICE_TOKEN is
# not provisioned, so a deployment without the connector still produces a
# complete briefing rather than failing the run.
FIXTURE_CREDENTIAL = "stg-mock-case-history"


def _fixture_case_history(
    source_id: str,
    date_from: str,
    date_to: str,
    support_category: str,
) -> dict[str, list[dict]]:
    """Return a representative case-history timeline for the requested window.

    Deliberately generic support-process events: no student names, no contact
    details, no clinical or disciplinary content. Every event carries the same
    normalized shape the live connector returns, so downstream nodes treat
    fixture and live data identically.
    """
    events = [
        {
            "date": date_from,
            "event_type": "initial_contact",
            "summary": "Student contacted the support team and an initial needs assessment was recorded.",
            "source_id": source_id,
            "citation_ref": f"CIT-{source_id}-001",
        },
        {
            "date": date_from,
            "event_type": support_category,
            "summary": "A support plan was agreed, with adjustments recorded and shared with the student.",
            "source_id": source_id,
            "citation_ref": f"CIT-{source_id}-002",
        },
        {
            "date": date_to,
            "event_type": "review_meeting",
            "summary": "Progress review held; the agreed adjustments remain in place for the current term.",
            "source_id": source_id,
            "citation_ref": f"CIT-{source_id}-003",
        },
    ]
    citations = [
        {
            "citation_ref": event["citation_ref"],
            "source_id": source_id,
            "description": f"Support case record — {event['event_type'].replace('_', ' ')}",
        }
        for event in events
    ]
    return {"events": events, "citations": citations}


class CaseHistoryService:
    """Approved-source adapter for retrieving support case-history events.

    Enforces source allowlisting via the caller-provided source_id and
    bounded query parameters. Does NOT make any student-support or
    escalation decisions. Does NOT copy raw provider responses into state —
    callers must normalize results before storage.

    The credential is an opaque handle obtained from ctx.secrets.require()
    in the calling node — never stored here or in state.
    """

    def __init__(self, credential: Any) -> None:
        """Initialize with an opaque service credential handle.

        Args:
            credential: Opaque credential handle from ctx.secrets.require().
                        Must not be stored in state or logged.
        """
        self._credential = credential

    def fetch_events(
        self,
        source_id: str,
        student_ref: str,
        date_from: str,
        date_to: str,
        support_category: str = "general",
    ) -> dict[str, list[dict]]:
        """Retrieve normalized case-history events from a single approved source.

        Args:
            source_id:        Approved source system identifier (allowlisted by operator).
            student_ref:      Anonymized/hashed student reference from case scope.
            date_from:        ISO 8601 date string — start of bounded query window.
            date_to:          ISO 8601 date string — end of bounded query window.
            support_category: Support category filter (default: 'general').

        Returns:
            dict with keys:
                'events':    list[dict] — normalized case-history events.
                             Each event: {date, event_type, summary, source_id, citation_ref}
                'citations': list[dict] — source provenance records.
                             Each citation: {citation_ref, source_id, description}

        Raises:
            RuntimeError: When the source system is unreachable or returns an error.
        """
        # The provisional Stage 5 server explicitly injects this sentinel via its
        # STG_MOCK_MODE provider. Normal credentials remain fail-closed until the
        # production connector is configured.
        if self._credential == FIXTURE_CREDENTIAL:
            return _fixture_case_history(source_id, date_from, date_to, support_category)

        # Production: dispatch HTTP/SDK call to the source system using self._credential.
        # The provider response must be normalized here before being returned.
        # Raw provider payloads must never be stored directly in agent state.
        raise NotImplementedError(
            "CaseHistoryService.fetch_events() requires a production connector. " "Use FakeCaseHistoryService in tests."
        )


class FakeCaseHistoryService(CaseHistoryService):
    """Deterministic test double for CaseHistoryService.

    Accepts pre-configured event/citation data per source_id.
    Raises RuntimeError for source IDs registered as 'error' sources.
    FAKE DATA ONLY — no real student or case information.
    """

    def __init__(
        self,
        events_by_source: dict[str, list[dict]] | None = None,
        error_sources: set[str] | None = None,
    ) -> None:
        super().__init__(credential="FAKE_CREDENTIAL_TEST_ONLY")  # noqa: S106
        self._events_by_source: dict[str, list[dict]] = events_by_source or {}
        self._error_sources: set[str] = error_sources or set()

    def fetch_events(
        self,
        source_id: str,
        student_ref: str,
        date_from: str,
        date_to: str,
        support_category: str = "general",
    ) -> dict[str, list[dict]]:
        """Return pre-configured fake events for the given source_id."""
        if source_id in self._error_sources:
            raise RuntimeError(f"FakeCaseHistoryService: simulated error for source '{source_id}'")

        events = self._events_by_source.get(source_id, [])
        citations = [
            {
                "citation_ref": f"CIT-{source_id}-{i:03d}",
                "source_id": source_id,
                "description": f"Fake citation {i} from {source_id}",
            }
            for i, _ in enumerate(events)
        ]
        return {"events": events, "citations": citations}
