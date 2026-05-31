"""Variant 4 scheduler port for the legacy quote-v2 smarterservice.php flow.

The legacy PHP endpoint accepted ``lat``, ``long``, and ``duration`` and loaded a
calendar payload shaped like ``{"appointments": [...]}``. This module keeps that
surface as an importable Python scheduler and adds the deterministic Variant 4
scoring model.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlencode
from urllib.request import Request, urlopen


CALENDAR_URL = "https://smarterservice-cloudfunction-3cpovdjmcq-uc.a.run.app"
SMARTERSERVICE_CALENDAR_ID = "a8hin9meea2nnatan6f87837ig@group.calendar.google.com"
GEOCODE_CACHE_BUCKET = "smarterservice_cache"
GEOCODE_CACHE_BLOB_NAME = "geocode_cache.json"
BASE_ADDRESS = "136 Southeast Catherine Drive, Owens Cross Roads, AL, 35763"
CALENDAR_SCOPES = ("https://www.googleapis.com/auth/calendar.readonly",)

WORKDAY_START_MINUTE = 9 * 60
WORKDAY_END_MINUTE = 17 * 60
ANCHOR_MINUTES = 30
HORIZON_DAYS = 45
MAX_JOBS_PER_DAY = 4
GOOGLE_CANDIDATE_LIMIT = 10
MINIMUM_USEFUL_GAP_MINUTES = 120
DRIVE_DECAY_MIDPOINT_MINUTES = 22
ROUTE_EFFICIENCY_ZERO_MINUTES = 60
BLANK_DAY_RETURN_WEIGHT = 0.5
BLANK_DAY_INCREMENTAL_DRIVE_CAP_MINUTES = 45


class DriveTimeUnavailable(RuntimeError):
    """Raised when a real drive-time provider cannot return a usable duration."""


class GoogleClientUnavailable(RuntimeError):
    """Raised when optional Google dependencies or credentials are unavailable."""


@dataclass(frozen=True)
class Location:
    latitude: float | None = None
    longitude: float | None = None
    address: str | None = None
    label: str = ""

    def require_coordinates(self) -> tuple[float, float]:
        if self.latitude is None or self.longitude is None:
            raise ValueError(f"Location {self.label or self.address!r} has no coordinates")
        return self.latitude, self.longitude

    def google_query_value(self) -> str:
        if self.address:
            return self.address
        latitude, longitude = self.require_coordinates()
        return f"{latitude},{longitude}"

    def cache_key(self) -> tuple[str, str | float | None, float | None]:
        if self.address and self.latitude is None and self.longitude is None:
            return ("address", self.address, None)
        return (
            "coords",
            round(self.latitude or 0.0, 6),
            round(self.longitude or 0.0, 6),
        )


# The address is the durable operating default. The coordinates are only used for
# fallback estimates when Google drive time is unavailable.
DEFAULT_BASE_LOCATION = Location(
    latitude=34.5912,
    longitude=-86.4866,
    address=BASE_ADDRESS,
    label="base",
)


@dataclass(frozen=True)
class Appointment:
    start: datetime
    end: datetime
    location: Location

    @property
    def day(self) -> date:
        return self.start.date()

    @property
    def start_minute(self) -> int:
        return self.start.hour * 60 + self.start.minute

    @property
    def end_minute(self) -> int:
        return self.end.hour * 60 + self.end.minute


@dataclass(frozen=True)
class CandidateSlot:
    day: date
    start_minute: int
    end_minute: int
    prev: Appointment | None
    next: Appointment | None
    jobs_before: int


@dataclass(frozen=True)
class DriveLeg:
    minutes: float
    source: str


@dataclass(frozen=True)
class ScoreParts:
    cluster_score: float
    route_efficiency_score: float
    soonness_score: float
    gap_quality_score: float
    capacity_score: float
    buffer_score: float


@dataclass(frozen=True)
class ScoredCandidate:
    slot: CandidateSlot
    score: float
    incremental_drive_minutes: float
    drive_minutes_source: str
    gap_before: float
    gap_after: float
    parts: ScoreParts

    @property
    def day(self) -> date:
        return self.slot.day

    @property
    def start_minute(self) -> int:
        return self.slot.start_minute

    @property
    def end_minute(self) -> int:
        return self.slot.end_minute


DriveTimeProvider = Callable[[Location, Location], float]
DriveTimeResolver = Callable[[Location, Location], DriveLeg]


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def parse_duration_minutes(duration: str | int | float) -> int:
    if isinstance(duration, int):
        minutes = duration
    elif isinstance(duration, float):
        minutes = int(round(duration))
    else:
        value = duration.strip().lower()
        human_match = re.fullmatch(r"(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?", value)
        if human_match and any(human_match.groups()):
            hours = int(human_match.group(1) or 0)
            trailing_minutes = int(human_match.group(2) or 0)
            minutes = hours * 60 + trailing_minutes
        else:
            parts = value.split(":")
            if len(parts) != 2:
                raise ValueError("duration must use HH:MM or 3h5m format")
            minutes = int(parts[0]) * 60 + int(parts[1])

    if minutes <= 0:
        raise ValueError("duration must be greater than zero minutes")
    return minutes


def minutes_to_hhmm(minutes: int) -> str:
    hour, minute = divmod(minutes, 60)
    return f"{hour:02d}:{minute:02d}"


def parse_appointment_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def parse_appointments(calendar_payload: Mapping[str, Any]) -> list[Appointment]:
    appointments = []

    for item in calendar_payload.get("appointments", []):
        longitude = item.get("long", item.get("lon", item.get("longitude")))
        appointments.append(
            Appointment(
                start=parse_appointment_datetime(str(item["start"])),
                end=parse_appointment_datetime(str(item["end"])),
                location=Location(
                    latitude=float(item["lat"]),
                    longitude=float(longitude),
                    label=str(item.get("summary", item.get("id", "appointment"))),
                ),
            )
        )

    appointments.sort(key=lambda appointment: (appointment.start, appointment.end))
    return appointments


def group_appointments_by_day(
    appointments: Sequence[Appointment],
) -> dict[date, list[Appointment]]:
    grouped: dict[date, list[Appointment]] = {}
    for appointment in appointments:
        grouped.setdefault(appointment.day, []).append(appointment)

    for day_appointments in grouped.values():
        day_appointments.sort(key=lambda appointment: (appointment.start, appointment.end))

    return grouped


def normalize_excluded_dates(excluded_dates: Sequence[date | str] | None) -> set[date]:
    if not excluded_dates:
        return set()

    normalized = set()
    for value in excluded_dates:
        if isinstance(value, date):
            normalized.add(value)
        else:
            normalized.add(date.fromisoformat(value.strip()))
    return normalized


def parse_excluded_dates(value: str | None) -> set[date]:
    if not value:
        return set()
    return normalize_excluded_dates(
        [part.strip() for part in value.split(",") if part.strip()]
    )


def candidate_dates(
    today: date,
    horizon_days: int = HORIZON_DAYS,
    excluded_dates: Sequence[date | str] | None = None,
) -> list[date]:
    excluded = normalize_excluded_dates(excluded_dates)
    return [
        today + timedelta(days=offset)
        for offset in range(1, horizon_days + 1)
        if (today + timedelta(days=offset)).weekday() < 5
        and today + timedelta(days=offset) not in excluded
    ]


def round_up_to_anchor(minutes: int, anchor_minutes: int = ANCHOR_MINUTES) -> int:
    remainder = minutes % anchor_minutes
    if remainder == 0:
        return minutes
    return minutes + (anchor_minutes - remainder)


def generate_candidate_slots(
    appointments_by_day: Mapping[date, Sequence[Appointment]],
    duration_minutes: int,
    today: date,
    horizon_days: int = HORIZON_DAYS,
    workday_start_minute: int = WORKDAY_START_MINUTE,
    workday_end_minute: int = WORKDAY_END_MINUTE,
    anchor_minutes: int = ANCHOR_MINUTES,
    max_jobs_per_day: int = MAX_JOBS_PER_DAY,
    excluded_dates: Sequence[date | str] | None = None,
) -> list[CandidateSlot]:
    slots: list[CandidateSlot] = []

    for day in candidate_dates(today, horizon_days, excluded_dates):
        day_appointments = list(appointments_by_day.get(day, []))
        if len(day_appointments) >= max_jobs_per_day:
            continue

        gaps: list[tuple[int, int, Appointment | None, Appointment | None]] = []
        if day_appointments:
            first = day_appointments[0]
            gaps.append((workday_start_minute, first.start_minute, None, first))

            for previous, next_appointment in zip(day_appointments, day_appointments[1:]):
                gaps.append(
                    (
                        previous.end_minute,
                        next_appointment.start_minute,
                        previous,
                        next_appointment,
                    )
                )

            last = day_appointments[-1]
            gaps.append((last.end_minute, workday_end_minute, last, None))
        else:
            gaps.append((workday_start_minute, workday_end_minute, None, None))

        for gap_start, gap_end, previous, next_appointment in gaps:
            latest_start = gap_end - duration_minutes
            start_minute = round_up_to_anchor(gap_start, anchor_minutes)

            while start_minute <= latest_start:
                slots.append(
                    CandidateSlot(
                        day=day,
                        start_minute=start_minute,
                        end_minute=start_minute + duration_minutes,
                        prev=previous,
                        next=next_appointment,
                        jobs_before=len(day_appointments),
                    )
                )
                start_minute += anchor_minutes

    return slots


def haversine_miles(origin: Location, destination: Location) -> float:
    origin_lat, origin_long = origin.require_coordinates()
    destination_lat, destination_long = destination.require_coordinates()

    earth_radius_miles = 3958.0
    delta_lat = math.radians(destination_lat - origin_lat)
    delta_long = math.radians(destination_long - origin_long)

    value = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(math.radians(origin_lat))
        * math.cos(math.radians(destination_lat))
        * math.sin(delta_long / 2) ** 2
    )
    return earth_radius_miles * (2 * math.atan2(math.sqrt(value), math.sqrt(1 - value)))


def estimate_drive_minutes(
    origin: Location,
    destination: Location,
    average_mph: float = 30.0,
) -> float:
    if average_mph <= 0:
        raise ValueError("average_mph must be greater than zero")
    return (haversine_miles(origin, destination) / average_mph) * 60


class GoogleDistanceMatrixDriveTimeProvider:
    """Small Google Distance Matrix client used only for final candidate scoring."""

    def __init__(self, api_key: str | None = None, timeout_seconds: int = 5) -> None:
        self.api_key = api_key or os.getenv("GOOGLE_MAPS_API_KEY")
        self.timeout_seconds = timeout_seconds

    def __call__(self, origin: Location, destination: Location) -> float:
        if not self.api_key:
            raise DriveTimeUnavailable("GOOGLE_MAPS_API_KEY is not configured")

        query = urlencode(
            {
                "origins": origin.google_query_value(),
                "destinations": destination.google_query_value(),
                "key": self.api_key,
            }
        )
        request = Request(
            f"https://maps.googleapis.com/maps/api/distancematrix/json?{query}",
            headers={"User-Agent": "crm-smarterservice-python/1.0"},
        )

        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except OSError as exc:
            raise DriveTimeUnavailable(str(exc)) from exc

        if payload.get("status") != "OK":
            raise DriveTimeUnavailable(str(payload.get("error_message") or payload.get("status")))

        try:
            element = payload["rows"][0]["elements"][0]
        except (IndexError, KeyError, TypeError) as exc:
            raise DriveTimeUnavailable("Google response did not include a route") from exc

        if element.get("status") != "OK":
            raise DriveTimeUnavailable(str(element.get("status")))

        duration = element.get("duration_in_traffic") or element.get("duration")
        if not duration or "value" not in duration:
            raise DriveTimeUnavailable("Google response did not include duration")

        return float(duration["value"]) / 60


class GoogleMapsGeocoder:
    """Geocoder backed by the official googlemaps client."""

    def __init__(self, api_key: str | None = None) -> None:
        api_key = api_key or os.getenv("GOOGLE_MAPS_API_KEY")
        if not api_key:
            raise GoogleClientUnavailable("GOOGLE_MAPS_API_KEY is not configured")

        try:
            from googlemaps import Client as GoogleMapsClient
        except ImportError as exc:
            raise GoogleClientUnavailable("Install googlemaps to geocode calendar events") from exc

        self._client = GoogleMapsClient(api_key)

    def geocode(self, address: str) -> tuple[float, float]:
        results = self._client.geocode(address)
        if not results:
            raise GoogleClientUnavailable(f"No geocode result for address: {address}")

        location = results[0]["geometry"]["location"]
        return float(location["lat"]), float(location["lng"])


class GCSGeocodeCache:
    """JSON geocode cache stored in Google Cloud Storage."""

    def __init__(
        self,
        bucket_name: str = GEOCODE_CACHE_BUCKET,
        blob_name: str = GEOCODE_CACHE_BLOB_NAME,
    ) -> None:
        try:
            from google.cloud import storage
        except ImportError as exc:
            raise GoogleClientUnavailable(
                "Install google-cloud-storage to use the GCS geocode cache"
            ) from exc

        self._client = storage.Client()
        self._bucket = self._client.bucket(bucket_name)
        self._blob = self._bucket.blob(blob_name)

    def load(self) -> dict[str, list[float]]:
        if not self._blob.exists():
            return {}

        payload = json.loads(self._blob.download_as_text())
        cache = {}
        for address, coords in payload.items():
            latitude, longitude = normalize_geocode(coords)
            cache[str(address)] = [latitude, longitude]
        return cache

    def save(self, cache: Mapping[str, Sequence[float]]) -> None:
        self._blob.upload_from_string(
            json.dumps(cache, sort_keys=True),
            content_type="application/json",
        )


def normalize_geocode(value: Sequence[float] | Mapping[str, float]) -> tuple[float, float]:
    if isinstance(value, Mapping):
        longitude = value.get("lng", value.get("long", value.get("longitude")))
        return float(value["lat"]), float(longitude)

    return float(value[0]), float(value[1])


def get_geocode(
    address: str,
    cache: dict[str, Sequence[float] | Mapping[str, float]],
    geocoder: GoogleMapsGeocoder,
) -> tuple[float, float]:
    if address in cache:
        return normalize_geocode(cache[address])

    latitude, longitude = geocoder.geocode(address)
    cache[address] = [latitude, longitude]
    return latitude, longitude


def calendar_payload_from_events(
    events: Sequence[Mapping[str, Any]],
    cache: dict[str, Sequence[float] | Mapping[str, float]],
    geocoder: GoogleMapsGeocoder,
    logger: Any | None = None,
) -> dict[str, list[dict[str, Any]]]:
    appointments = []

    for event in events:
        location = event.get("location")
        if location is not None:
            location = str(location).strip()
        if not location or not any(character.isalnum() for character in location):
            if logger:
                logger.info("Skipping calendar event without a location: %s", event.get("id"))
            continue

        start = event.get("start", {}).get("dateTime") or event.get("start", {}).get("date")
        end = event.get("end", {}).get("dateTime") or event.get("end", {}).get("date")
        if not start or not end:
            if logger:
                logger.info("Skipping calendar event without start/end: %s", event.get("id"))
            continue

        try:
            latitude, longitude = get_geocode(location, cache, geocoder)
        except Exception as exc:
            if logger:
                logger.info(
                    "Skipping calendar event with ungeocodable location %r: %s",
                    location,
                    exc,
                )
            continue
        appointments.append(
            {
                "start": start,
                "end": end,
                "lat": latitude,
                "long": longitude,
            }
        )

        if logger:
            logger.info(
                "Calendar event %s starts at %s and ends at %s at %s",
                event.get("summary", event.get("id")),
                start,
                end,
                location,
            )

    return {"appointments": appointments}


def load_google_credentials(
    *,
    credentials_file: str | None = None,
    service_account_info: Mapping[str, Any] | None = None,
    scopes: Sequence[str] = CALENDAR_SCOPES,
) -> Any:
    try:
        from google.oauth2.service_account import Credentials
    except ImportError as exc:
        raise GoogleClientUnavailable("Install google-auth to load service account credentials") from exc

    if service_account_info is None and os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON"):
        service_account_info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])

    if service_account_info is not None:
        return Credentials.from_service_account_info(dict(service_account_info), scopes=list(scopes))

    credentials_file = (
        credentials_file
        or os.getenv("SMARTERSERVICE_SERVICE_ACCOUNT_FILE")
        or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    )
    if not credentials_file:
        raise GoogleClientUnavailable(
            "Set SMARTERSERVICE_SERVICE_ACCOUNT_FILE or GOOGLE_APPLICATION_CREDENTIALS"
        )

    return Credentials.from_service_account_file(credentials_file, scopes=list(scopes))


def build_calendar_service(credentials: Any) -> Any:
    try:
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise GoogleClientUnavailable(
            "Install google-api-python-client to read Google Calendar events"
        ) from exc

    return build("calendar", "v3", credentials=credentials, cache_discovery=False)


def get_calendar_events(
    service: Any,
    *,
    calendar_id: str = SMARTERSERVICE_CALENDAR_ID,
    now: datetime | None = None,
    horizon_days: int = HORIZON_DAYS,
) -> list[Mapping[str, Any]]:
    now = now or datetime.now(timezone.utc)
    future = now + timedelta(days=horizon_days)

    events_result = (
        service.events()
        .list(
            calendarId=calendar_id,
            timeMin=now.isoformat().replace("+00:00", "Z"),
            timeMax=future.isoformat().replace("+00:00", "Z"),
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )
    return list(events_result.get("items", []))


def fetch_google_calendar_payload(
    *,
    calendar_id: str = SMARTERSERVICE_CALENDAR_ID,
    horizon_days: int = HORIZON_DAYS,
    credentials_file: str | None = None,
    service_account_info: Mapping[str, Any] | None = None,
    service: Any | None = None,
    geocoder: GoogleMapsGeocoder | None = None,
    cache_store: GCSGeocodeCache | None = None,
    cache_bucket: str = GEOCODE_CACHE_BUCKET,
    cache_blob_name: str = GEOCODE_CACHE_BLOB_NAME,
    maps_api_key: str | None = None,
    now: datetime | None = None,
    logger: Any | None = None,
) -> dict[str, list[dict[str, Any]]]:
    if service is None:
        credentials = load_google_credentials(
            credentials_file=credentials_file,
            service_account_info=service_account_info,
        )
        service = build_calendar_service(credentials)

    geocoder = geocoder or GoogleMapsGeocoder(maps_api_key)
    cache_store = cache_store or GCSGeocodeCache(cache_bucket, cache_blob_name)

    cache = cache_store.load()
    events = get_calendar_events(
        service,
        calendar_id=calendar_id,
        now=now,
        horizon_days=horizon_days,
    )
    payload = calendar_payload_from_events(events, cache, geocoder, logger=logger)
    cache_store.save(cache)
    return payload


def estimated_drive_resolver(origin: Location, destination: Location) -> DriveLeg:
    return DriveLeg(estimate_drive_minutes(origin, destination), "estimated")


def google_then_estimated_drive_resolver(
    provider: DriveTimeProvider,
    warnings: list[str],
) -> DriveTimeResolver:
    cache: dict[tuple[tuple[str, str | float | None, float | None], tuple[str, str | float | None, float | None]], DriveLeg] = {}

    def resolve(origin: Location, destination: Location) -> DriveLeg:
        key = (origin.cache_key(), destination.cache_key())
        if key in cache:
            return cache[key]

        try:
            leg = DriveLeg(float(provider(origin, destination)), "google")
        except Exception as exc:
            warnings.append(
                f"Google drive-time unavailable; used estimated drive minutes. Detail: {exc}"
            )
            leg = estimated_drive_resolver(origin, destination)

        cache[key] = leg
        return leg

    return resolve


def unused_gap_penalty(gap_minutes: float) -> float:
    if gap_minutes <= 0:
        return 0.0
    if gap_minutes >= MINIMUM_USEFUL_GAP_MINUTES:
        return 0.0
    return 100 * (1 - gap_minutes / MINIMUM_USEFUL_GAP_MINUTES)


def score_parts(
    *,
    incremental_drive_minutes: float,
    existing_day: bool,
    days_out: int,
    jobs_after: int,
    gap_before: float,
    gap_after: float,
) -> ScoreParts:
    drive_decay = 1 / (
        1 + (incremental_drive_minutes / DRIVE_DECAY_MIDPOINT_MINUTES) ** 2
    )
    # Blank days should still keep meaningful credit when drive is reasonable.
    cluster_floor = 0.6 if not existing_day else 1.0
    cluster_score = 100 * cluster_floor * drive_decay
    route_efficiency_score = 100 * clamp01(
        1 - incremental_drive_minutes / ROUTE_EFFICIENCY_ZERO_MINUTES
    )
    soonness_score = 100 * math.exp(-days_out / 21)
    gap_quality_score = 100 - max(unused_gap_penalty(gap_before), unused_gap_penalty(gap_after))
    capacity_score = 100 * clamp01(1 - (jobs_after - 1) / 4)
    buffer_score = 100 * clamp01(min(gap_before, gap_after) / 30)

    return ScoreParts(
        cluster_score=cluster_score,
        route_efficiency_score=route_efficiency_score,
        soonness_score=soonness_score,
        gap_quality_score=gap_quality_score,
        capacity_score=capacity_score,
        buffer_score=buffer_score,
    )


def candidate_score(parts: ScoreParts) -> float:
    return (
        0.35 * parts.cluster_score
        + 0.20 * parts.route_efficiency_score
        + 0.20 * parts.soonness_score
        + 0.15 * parts.gap_quality_score
        + 0.05 * parts.capacity_score
        + 0.05 * parts.buffer_score
    )


def evaluate_slot(
    slot: CandidateSlot,
    new_location: Location,
    today: date,
    drive_time: DriveTimeResolver,
    base_location: Location = DEFAULT_BASE_LOCATION,
    workday_start_minute: int = WORKDAY_START_MINUTE,
    workday_end_minute: int = WORKDAY_END_MINUTE,
) -> ScoredCandidate | None:
    prev_location = slot.prev.location if slot.prev else base_location
    next_location = slot.next.location if slot.next else base_location

    prev_to_job = drive_time(prev_location, new_location)
    job_to_next = drive_time(new_location, next_location)

    if slot.jobs_before == 0:
        incremental_drive = prev_to_job.minutes + (
            BLANK_DAY_RETURN_WEIGHT * job_to_next.minutes
        )
        incremental_drive = min(
            incremental_drive,
            BLANK_DAY_INCREMENTAL_DRIVE_CAP_MINUTES,
        )
        sources = {prev_to_job.source, job_to_next.source}
    else:
        replaced_leg = drive_time(prev_location, next_location)
        incremental_drive = prev_to_job.minutes + job_to_next.minutes - replaced_leg.minutes
        sources = {prev_to_job.source, job_to_next.source, replaced_leg.source}

    prev_end_minute = slot.prev.end_minute if slot.prev else workday_start_minute
    next_start_minute = slot.next.start_minute if slot.next else workday_end_minute
    gap_before = slot.start_minute - (prev_end_minute + prev_to_job.minutes)
    gap_after = next_start_minute - (slot.end_minute + job_to_next.minutes)

    if gap_before < 0 or gap_after < 0:
        return None

    parts = score_parts(
        incremental_drive_minutes=max(0.0, incremental_drive),
        existing_day=slot.jobs_before > 0,
        days_out=(slot.day - today).days,
        jobs_after=slot.jobs_before + 1,
        gap_before=gap_before,
        gap_after=gap_after,
    )

    return ScoredCandidate(
        slot=slot,
        score=candidate_score(parts),
        incremental_drive_minutes=max(0.0, incremental_drive),
        drive_minutes_source="google" if sources == {"google"} else "estimated",
        gap_before=gap_before,
        gap_after=gap_after,
        parts=parts,
    )


def sort_candidates(candidates: Sequence[ScoredCandidate]) -> list[ScoredCandidate]:
    return sorted(
        candidates,
        key=lambda candidate: (
            -candidate.score,
            candidate.day,
            candidate.start_minute,
            candidate.incremental_drive_minutes,
        ),
    )


def best_candidate_per_day(candidates: Sequence[ScoredCandidate]) -> list[ScoredCandidate]:
    best_by_day: dict[date, ScoredCandidate] = {}

    for candidate in sort_candidates(candidates):
        best_by_day.setdefault(candidate.day, candidate)

    return sort_candidates(list(best_by_day.values()))


def get_geofence_area(latitude: float, longitude: float) -> str | None:
    geofences = {
        "North Madison": ((34.7535, 34.8377), (-86.7860, -86.6677)),
        "South Madison": ((34.5971, 34.7535), (-86.7860, -86.6677)),
        "North Huntsville": ((34.6988, 34.8377), (-86.6677, -86.5172)),
        "South Huntsville": ((34.5672, 34.6988), (-86.6677, -86.5172)),
    }

    for area, (lat_range, long_range) in geofences.items():
        if lat_range[0] <= latitude <= lat_range[1] and long_range[0] <= longitude <= long_range[1]:
            return area
    return None


def first_free_weekday(
    appointments: Sequence[Appointment],
    new_latitude: float,
    new_longitude: float,
    today: date,
    horizon_days: int = HORIZON_DAYS,
) -> str | None:
    appointment_dates = {appointment.day for appointment in appointments}
    area = get_geofence_area(new_latitude, new_longitude)

    target_weekday = {
        "South Madison": 0,
        "North Madison": 1,
        "South Huntsville": 3,
        "North Huntsville": 4,
    }.get(area, 2)

    for day in candidate_dates(today, horizon_days):
        if day.weekday() == target_weekday and day not in appointment_dates:
            return day.isoformat()
    return None


def deduplicate_warnings(warnings: Sequence[str]) -> list[str]:
    deduplicated = []
    seen = set()
    for warning in warnings:
        summary = warning.split(" Detail:", 1)[0]
        if summary not in seen:
            seen.add(summary)
            deduplicated.append(summary)
    return deduplicated


def score_standard_deviation(candidates: Sequence[ScoredCandidate]) -> float:
    if not candidates:
        return 0.0

    scores = [candidate.score for candidate in candidates]
    mean = sum(scores) / len(scores)
    variance = sum((score - mean) ** 2 for score in scores) / len(scores)
    return math.sqrt(variance)


def candidate_to_response(
    candidate: ScoredCandidate,
    rank: int,
    *,
    clear_winner: bool = False,
    score_gap_to_next: float | None = None,
    score_std_dev: float | None = None,
) -> dict[str, Any]:
    response = {
        "rank": rank,
        "date": candidate.day.isoformat(),
        "start": minutes_to_hhmm(candidate.start_minute),
        "end": minutes_to_hhmm(candidate.end_minute),
        "score": round(candidate.score, 2),
        "incremental_drive_minutes": round(candidate.incremental_drive_minutes),
        "drive_minutes_source": candidate.drive_minutes_source,
        "unbooked_day": candidate.slot.jobs_before == 0,
        "existing_jobs_on_day": candidate.slot.jobs_before,
        "clear_winner": clear_winner,
    }

    if score_gap_to_next is not None:
        response["score_gap_to_next"] = round(score_gap_to_next, 2)
    if score_std_dev is not None:
        response["score_std_dev"] = round(score_std_dev, 2)

    return response


def schedule_suggestions(
    *,
    calendar_payload: Mapping[str, Any],
    new_latitude: float | None = None,
    new_longitude: float | None = None,
    address: str | None = None,
    duration: str | int | float,
    today: date | None = None,
    drive_time_provider: DriveTimeProvider | None = None,
    use_google: bool = True,
    base_location: Location = DEFAULT_BASE_LOCATION,
    horizon_days: int = HORIZON_DAYS,
    google_candidate_limit: int = GOOGLE_CANDIDATE_LIMIT,
    excluded_dates: Sequence[date | str] | None = None,
) -> dict[str, Any]:
    today = today or date.today()
    duration_minutes = parse_duration_minutes(duration)
    appointments = parse_appointments(calendar_payload)
    appointments_by_day = group_appointments_by_day(appointments)

    if address is not None:
        if new_latitude is not None or new_longitude is not None:
            raise ValueError("Provide either address or coordinates (lat/long), not both")
        new_latitude, new_longitude = GoogleMapsGeocoder().geocode(address)
    elif new_latitude is None or new_longitude is None:
        raise ValueError("Must provide either address or both new_latitude and new_longitude")

    new_location = Location(
        latitude=float(new_latitude),
        longitude=float(new_longitude),
        label=address or "new appointment",
    )

    slots = generate_candidate_slots(
        appointments_by_day,
        duration_minutes,
        today,
        horizon_days=horizon_days,
        excluded_dates=excluded_dates,
    )

    cheap_candidates = [
        candidate
        for slot in slots
        if (candidate := evaluate_slot(slot, new_location, today, estimated_drive_resolver, base_location))
        is not None
    ]
    top_estimated_candidates = best_candidate_per_day(cheap_candidates)[:google_candidate_limit]

    warnings: list[str] = []
    provider = drive_time_provider
    if use_google and provider is None and os.getenv("GOOGLE_MAPS_API_KEY"):
        provider = GoogleDistanceMatrixDriveTimeProvider()

    if use_google and provider is not None:
        final_drive_resolver = google_then_estimated_drive_resolver(provider, warnings)
    else:
        final_drive_resolver = estimated_drive_resolver
        if use_google and top_estimated_candidates:
            warnings.append("Google drive-time unavailable; used estimated drive minutes.")

    final_candidates = [
        candidate
        for estimated_candidate in top_estimated_candidates
        if (
            candidate := evaluate_slot(
                estimated_candidate.slot,
                new_location,
                today,
                final_drive_resolver,
                base_location,
            )
        )
        is not None
    ]
    sorted_final_candidates = sort_candidates(final_candidates)
    ranked_candidates = sorted_final_candidates[:3]
    std_dev = score_standard_deviation(sorted_final_candidates)
    score_gap_to_next = (
        ranked_candidates[0].score - ranked_candidates[1].score
        if len(ranked_candidates) > 1
        else None
    )
    has_clear_winner = (
        score_gap_to_next is not None
        and std_dev > 0
        and score_gap_to_next >= std_dev
    )

    return {
        "suggestions": [
            candidate_to_response(
                candidate,
                rank,
                clear_winner=rank == 1 and has_clear_winner,
                score_gap_to_next=score_gap_to_next if rank == 1 else None,
                score_std_dev=std_dev if rank == 1 else None,
            )
            for rank, candidate in enumerate(ranked_candidates, start=1)
        ],
        "first_free_weekday": first_free_weekday(
            appointments,
            float(new_latitude),
            float(new_longitude),
            today,
            horizon_days,
        ),
        "excluded_dates": [
            excluded_date.isoformat()
            for excluded_date in sorted(normalize_excluded_dates(excluded_dates))
        ],
        "warnings": deduplicate_warnings(warnings),
    }


def fetch_calendar_payload(calendar_url: str = CALENDAR_URL) -> Mapping[str, Any]:
    request = Request(calendar_url, headers={"User-Agent": "crm-smarterservice-python/1.0"})
    with urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def load_calendar_payload(path: str) -> Mapping[str, Any]:
    with open(path, encoding="utf-8") as file:
        return json.load(file)


def request_arg(request: Any, name: str, default: Any = None) -> Any:
    args = getattr(request, "args", {}) or {}
    if hasattr(args, "get"):
        return args.get(name, default)
    return default


def json_http_response(payload: Mapping[str, Any]) -> tuple[str, int, dict[str, str]]:
    return json.dumps(payload), 200, {"Content-Type": "application/json"}


def smarterservice_cloudfunction(request: Any) -> tuple[str, int, dict[str, str]]:
    """Google Cloud Function entry point for direct scheduling suggestions.

    Query params are compatible with the legacy PHP caller:
    ``lat``, ``long``, and ``duration``. Passing ``appointments_only=1`` returns
    the raw ``{"appointments": [...]}`` payload for old callers that only need
    the calendar/geocode feed.
    """

    import logging

    logger = logging.getLogger(__name__)
    payload = fetch_google_calendar_payload(logger=logger)

    appointments_only = str(request_arg(request, "appointments_only", "")).lower()
    if appointments_only in {"1", "true", "yes"}:
        return json_http_response(payload)

    address = request_arg(request, "address")
    latitude = request_arg(request, "lat")
    longitude = request_arg(request, "long") or request_arg(request, "longitude")
    duration = request_arg(request, "duration", "02:00")
    excluded_dates = parse_excluded_dates(request_arg(request, "exclude_dates"))

    kwargs: dict[str, Any] = {
        "calendar_payload": payload,
        "duration": duration,
        "excluded_dates": excluded_dates,
    }
    if address:
        kwargs["address"] = str(address)
    elif latitude is not None and longitude is not None:
        kwargs["new_latitude"] = float(latitude)
        kwargs["new_longitude"] = float(longitude)
    else:
        return json_http_response({"error": "address or lat/long required"})

    return json_http_response(schedule_suggestions(**kwargs))


def main() -> None:
    parser = argparse.ArgumentParser(description="Return Variant 4 smarterservice suggestions.")
    parser.add_argument("--address", default=None, help="Geocode this address instead of --lat/--long")
    parser.add_argument("--lat", type=float, default=None)
    parser.add_argument("--long", dest="longitude", type=float, default=None)
    parser.add_argument("--duration", default="02:00")
    parser.add_argument("--calendar-file")
    parser.add_argument("--calendar-url", default=CALENDAR_URL)
    parser.add_argument("--google-calendar", action="store_true")
    parser.add_argument("--calendar-id", default=SMARTERSERVICE_CALENDAR_ID)
    parser.add_argument("--credentials-file")
    parser.add_argument("--cache-bucket", default=GEOCODE_CACHE_BUCKET)
    parser.add_argument("--cache-blob-name", default=GEOCODE_CACHE_BLOB_NAME)
    parser.add_argument("--no-google", action="store_true")
    parser.add_argument("--appointments-only", action="store_true")
    parser.add_argument("--exclude-dates", default="")
    args = parser.parse_args()

    if args.google_calendar:
        payload = fetch_google_calendar_payload(
            calendar_id=args.calendar_id,
            credentials_file=args.credentials_file,
            cache_bucket=args.cache_bucket,
            cache_blob_name=args.cache_blob_name,
        )
    elif args.calendar_file:
        payload = load_calendar_payload(args.calendar_file)
    else:
        payload = fetch_calendar_payload(args.calendar_url)

    if args.appointments_only:
        print(json.dumps(payload, indent=2))
        return

    schedule_kwargs: dict[str, Any] = {
        "calendar_payload": payload,
        "duration": args.duration,
        "use_google": not args.no_google,
        "excluded_dates": parse_excluded_dates(args.exclude_dates),
    }
    if args.address:
        schedule_kwargs["address"] = args.address
    elif args.lat is not None and args.longitude is not None:
        schedule_kwargs["new_latitude"] = args.lat
        schedule_kwargs["new_longitude"] = args.longitude
    else:
        parser.error("--address or --lat/--long required")

    response = schedule_suggestions(**schedule_kwargs)
    print(json.dumps(response, indent=2))


if __name__ == "__main__":
    main()
