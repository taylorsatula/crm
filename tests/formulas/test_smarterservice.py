import json
from datetime import date, datetime, timedelta, timezone

import pytest

import formulas.smarterservice as smarterservice
from formulas.smarterservice import (
    CandidateSlot,
    Location,
    ScoreParts,
    ScoredCandidate,
    DEFAULT_BASE_LOCATION,
    best_candidate_per_day,
    calendar_payload_from_events,
    candidate_score,
    evaluate_slot,
    generate_candidate_slots,
    get_calendar_events,
    group_appointments_by_day,
    parse_appointments,
    parse_duration_minutes,
    schedule_suggestions,
    score_parts,
)


TODAY = date(2026, 5, 9)


def appointment(day, start, end, latitude=0.0, longitude=0.0):
    return {
        "start": f"{day.isoformat()}T{start}:00-05:00",
        "end": f"{day.isoformat()}T{end}:00-05:00",
        "lat": latitude,
        "long": longitude,
    }


def calendar(*appointments):
    return {"appointments": list(appointments)}


def test_drive_decay_gives_existing_day_half_cluster_credit_at_22_minutes():
    parts = score_parts(
        incremental_drive_minutes=22,
        existing_day=True,
        days_out=1,
        jobs_after=2,
        gap_before=120,
        gap_after=120,
    )

    assert parts.cluster_score == pytest.approx(50)


def test_blank_days_keep_partial_cluster_credit_at_22_minutes():
    parts = score_parts(
        incremental_drive_minutes=22,
        existing_day=False,
        days_out=1,
        jobs_after=1,
        gap_before=120,
        gap_after=120,
    )

    assert parts.cluster_score == pytest.approx(30)


def test_blank_day_incremental_drive_discounts_return_leg_and_caps_penalty():
    slot = CandidateSlot(
        day=TODAY + timedelta(days=1),
        start_minute=11 * 60,
        end_minute=(11 * 60) + 60,
        prev=None,
        next=None,
        jobs_before=0,
    )
    new_location = Location(latitude=0.0, longitude=0.0, label="job")

    def drive_time(_origin, _destination):
        return smarterservice.DriveLeg(minutes=40, source="estimated")

    candidate = evaluate_slot(
        slot,
        new_location,
        TODAY,
        drive_time,
        DEFAULT_BASE_LOCATION,
    )

    assert candidate is not None
    assert candidate.incremental_drive_minutes == pytest.approx(45)


def test_final_score_uses_variant_4_weights():
    parts = score_parts(
        incremental_drive_minutes=0,
        existing_day=True,
        days_out=0,
        jobs_after=1,
        gap_before=120,
        gap_after=120,
    )

    assert candidate_score(parts) == pytest.approx(100)


def test_parse_duration_accepts_human_hour_minute_shape():
    assert parse_duration_minutes("3h5m") == 185
    assert parse_duration_minutes("3h 5m") == 185


def test_candidate_generation_rejects_days_that_already_have_four_jobs():
    target_day = TODAY + timedelta(days=1)
    payload = calendar(
        appointment(target_day, "09:00", "10:00"),
        appointment(target_day, "10:00", "11:00"),
        appointment(target_day, "11:00", "12:00"),
        appointment(target_day, "12:00", "13:00"),
    )
    appointments_by_day = group_appointments_by_day(parse_appointments(payload))

    slots = generate_candidate_slots(
        appointments_by_day,
        parse_duration_minutes("01:00"),
        TODAY,
        horizon_days=1,
    )

    assert [slot for slot in slots if slot.day == target_day] == []


def test_candidate_generation_uses_real_free_gaps_and_9_to_5_boundaries():
    target_day = TODAY + timedelta(days=1)
    payload = calendar(appointment(target_day, "10:00", "12:00"))
    appointments_by_day = group_appointments_by_day(parse_appointments(payload))

    slots = generate_candidate_slots(
        appointments_by_day,
        parse_duration_minutes("01:00"),
        TODAY,
        horizon_days=1,
    )
    starts = [slot.start_minute for slot in slots]

    assert min(starts) >= 9 * 60
    assert max(slot.end_minute for slot in slots) <= 17 * 60
    assert 10 * 60 not in starts
    assert (11 * 60) + 30 not in starts
    assert 12 * 60 in starts


def test_low_drive_existing_day_cluster_wins_against_far_blank_day(monkeypatch):
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    existing_day = TODAY + timedelta(days=1)
    payload = calendar(
        appointment(existing_day, "09:00", "12:00", latitude=1.0, longitude=1.0),
        appointment(existing_day, "13:00", "17:00", latitude=1.0, longitude=1.0),
    )

    response = schedule_suggestions(
        calendar_payload=payload,
        new_latitude=1.0,
        new_longitude=1.0,
        duration="01:00",
        today=TODAY,
        use_google=False,
        base_location=Location(latitude=0.0, longitude=0.0),
        horizon_days=3,
    )

    assert response["suggestions"][0]["date"] == existing_day.isoformat()


def test_blank_day_can_win_when_existing_day_drive_fit_is_poor(monkeypatch):
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    existing_day = TODAY + timedelta(days=1)
    blank_day = TODAY + timedelta(days=2)
    payload = calendar(
        appointment(existing_day, "09:00", "12:00", latitude=10.0, longitude=10.0),
        appointment(existing_day, "13:00", "17:00", latitude=10.0, longitude=11.0),
    )

    response = schedule_suggestions(
        calendar_payload=payload,
        new_latitude=0.0,
        new_longitude=0.0,
        duration="01:00",
        today=TODAY,
        use_google=False,
        base_location=Location(latitude=0.0, longitude=0.0),
        horizon_days=3,
    )

    assert response["suggestions"][0]["date"] == blank_day.isoformat()


def test_final_scoring_only_queries_google_for_top_estimated_candidates():
    start_day = TODAY + timedelta(days=1)
    payload = calendar(
        *[
            item
            for offset in range(5)
            for item in (
                appointment(
                    start_day + timedelta(days=offset),
                    "09:00",
                    "10:00",
                    latitude=0.01 + offset,
                    longitude=0.01,
                ),
                appointment(
                    start_day + timedelta(days=offset),
                    "13:00",
                    "17:00",
                    latitude=0.01 + offset,
                    longitude=0.02,
                ),
            )
        ]
    )
    calls = []

    def provider(origin, destination):
        calls.append((origin.cache_key(), destination.cache_key()))
        return 0

    schedule_suggestions(
        calendar_payload=payload,
        new_latitude=0.0,
        new_longitude=0.0,
        duration="01:00",
        today=TODAY,
        drive_time_provider=provider,
        base_location=Location(latitude=0.0, longitude=0.0),
        horizon_days=5,
        google_candidate_limit=1,
    )

    assert len(calls) == 3


def test_google_drive_time_reuses_per_request_leg_cache():
    target_day = TODAY + timedelta(days=1)
    payload = calendar(
        appointment(target_day, "09:00", "10:00", latitude=0.01, longitude=0.01),
        appointment(target_day, "15:00", "17:00", latitude=0.02, longitude=0.02),
    )
    calls = []

    def provider(origin, destination):
        calls.append((origin.cache_key(), destination.cache_key()))
        return 1

    schedule_suggestions(
        calendar_payload=payload,
        new_latitude=0.0,
        new_longitude=0.0,
        duration="01:00",
        today=TODAY,
        drive_time_provider=provider,
        base_location=Location(latitude=0.0, longitude=0.0),
        horizon_days=1,
        google_candidate_limit=2,
    )

    assert len(calls) == 3


def test_google_shortlist_uses_best_slot_per_day_before_cap():
    start_day = TODAY + timedelta(days=1)

    def scored(day, start_minute, score):
        return ScoredCandidate(
            slot=CandidateSlot(
                day=day,
                start_minute=start_minute,
                end_minute=start_minute + 60,
                prev=None,
                next=None,
                jobs_before=0,
            ),
            score=score,
            incremental_drive_minutes=10,
            drive_minutes_source="estimated",
            gap_before=120,
            gap_after=120,
            parts=ScoreParts(0, 0, 0, 0, 0, 0),
        )

    shortlist = best_candidate_per_day(
        [
            scored(start_day, 600, 90),
            scored(start_day, 630, 85),
            scored(start_day + timedelta(days=1), 600, 80),
            scored(start_day + timedelta(days=1), 630, 75),
        ]
    )[:2]
    shortlisted_days = [candidate.day.isoformat() for candidate in shortlist]
    assert shortlisted_days == [
        start_day.isoformat(),
        (start_day + timedelta(days=1)).isoformat(),
    ]


def test_fallback_warning_and_estimated_source_when_google_provider_fails():
    class ProviderFailure(RuntimeError):
        pass

    def provider(_origin, _destination):
        raise ProviderFailure("distance matrix down")

    response = schedule_suggestions(
        calendar_payload=calendar(),
        new_latitude=0.0,
        new_longitude=0.0,
        duration="01:00",
        today=TODAY,
        drive_time_provider=provider,
        base_location=Location(latitude=0.0, longitude=0.0),
        horizon_days=1,
    )

    assert response["warnings"] == [
        "Google drive-time unavailable; used estimated drive minutes."
    ]
    assert response["suggestions"][0]["drive_minutes_source"] == "estimated"


def test_calendar_payload_from_events_geocodes_and_updates_cache():
    class FakeGeocoder:
        def __init__(self):
            self.calls = []

        def geocode(self, address):
            self.calls.append(address)
            return 3.0, 4.0

    events = [
        {
            "id": "cached",
            "summary": "Cached job",
            "start": {"dateTime": "2026-05-10T09:00:00-05:00"},
            "end": {"dateTime": "2026-05-10T10:00:00-05:00"},
            "location": "Cached Address",
        },
        {
            "id": "new",
            "summary": "New job",
            "start": {"dateTime": "2026-05-11T11:00:00-05:00"},
            "end": {"dateTime": "2026-05-11T12:00:00-05:00"},
            "location": "New Address",
        },
        {
            "id": "missing-location",
            "start": {"dateTime": "2026-05-12T11:00:00-05:00"},
            "end": {"dateTime": "2026-05-12T12:00:00-05:00"},
        },
        {
            "id": "punctuation-location",
            "start": {"dateTime": "2026-05-13T11:00:00-05:00"},
            "end": {"dateTime": "2026-05-13T12:00:00-05:00"},
            "location": ",  ",
        },
    ]
    cache = {"Cached Address": [1.0, 2.0]}
    geocoder = FakeGeocoder()

    payload = calendar_payload_from_events(events, cache, geocoder)

    assert payload == {
        "appointments": [
            {
                "start": "2026-05-10T09:00:00-05:00",
                "end": "2026-05-10T10:00:00-05:00",
                "lat": 1.0,
                "long": 2.0,
            },
            {
                "start": "2026-05-11T11:00:00-05:00",
                "end": "2026-05-11T12:00:00-05:00",
                "lat": 3.0,
                "long": 4.0,
            },
        ]
    }
    assert geocoder.calls == ["New Address"]
    assert cache["New Address"] == [3.0, 4.0]


def test_get_calendar_events_uses_calendar_id_and_horizon():
    class FakeEvents:
        def __init__(self):
            self.kwargs = None

        def list(self, **kwargs):
            self.kwargs = kwargs
            return self

        def execute(self):
            return {"items": [{"id": "event-1"}]}

    class FakeService:
        def __init__(self):
            self.events_resource = FakeEvents()

        def events(self):
            return self.events_resource

    service = FakeService()

    events = get_calendar_events(
        service,
        calendar_id="calendar@example.com",
        now=datetime(2026, 5, 9, 12, 0, tzinfo=timezone.utc),
        horizon_days=45,
    )

    assert events == [{"id": "event-1"}]
    assert service.events_resource.kwargs == {
        "calendarId": "calendar@example.com",
        "timeMin": "2026-05-09T12:00:00Z",
        "timeMax": "2026-06-23T12:00:00Z",
        "singleEvents": True,
        "orderBy": "startTime",
    }


def test_smarterservice_cloudfunction_returns_scored_suggestions(monkeypatch):
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    payload = calendar()
    monkeypatch.setattr(
        smarterservice,
        "fetch_google_calendar_payload",
        lambda logger=None: payload,
    )

    class FakeRequest:
        args = {"lat": "34.5912", "long": "-86.4866", "duration": "01:00"}

    body, status, headers = smarterservice.smarterservice_cloudfunction(FakeRequest())
    parsed = json.loads(body)

    assert status == 200
    assert headers == {"Content-Type": "application/json"}
    assert parsed["suggestions"][0]["rank"] == 1
    assert parsed["warnings"] == [
        "Google drive-time unavailable; used estimated drive minutes."
    ]


def test_smarterservice_cloudfunction_can_return_appointments_only(monkeypatch):
    payload = calendar(appointment(TODAY + timedelta(days=1), "09:00", "10:00"))
    monkeypatch.setattr(
        smarterservice,
        "fetch_google_calendar_payload",
        lambda logger=None: payload,
    )

    class FakeRequest:
        args = {"appointments_only": "1"}

    body, status, _headers = smarterservice.smarterservice_cloudfunction(FakeRequest())

    assert status == 200
    assert json.loads(body) == payload
