"""Tests for api/base.py - Unified API response format."""

from datetime import timezone

from api.base import (
    success_response,
    error_response,
    ErrorCodes,
)


class TestSuccessResponse:
    """Tests for success_response()."""

    def test_structure(self):
        resp = success_response({"foo": "bar"})
        assert resp.success is True
        assert resp.data == {"foo": "bar"}
        assert resp.error is None

    def test_request_id_generated(self):
        resp = success_response({})
        assert resp.meta.request_id is not None
        assert len(resp.meta.request_id) > 0

    def test_timestamp_is_utc(self):
        resp = success_response({})
        assert resp.meta.timestamp.tzinfo == timezone.utc


class TestErrorResponse:
    """Tests for error_response()."""

    def test_structure(self):
        resp = error_response("TEST_ERROR", "Something went wrong")
        assert resp.success is False
        assert resp.data is None
        assert resp.error.code == "TEST_ERROR"
        assert resp.error.message == "Something went wrong"

    def test_request_id_generated(self):
        resp = error_response("ERR", "msg")
        assert resp.meta.request_id is not None
        assert len(resp.meta.request_id) > 0

    def test_timestamp_is_utc(self):
        resp = error_response("ERR", "msg")
        assert resp.meta.timestamp.tzinfo == timezone.utc


class TestErrorCodes:
    """Tests that ErrorCodes contains required codes from ERROR_CODES.md."""

    def test_has_internal_error(self):
        assert ErrorCodes.INTERNAL_ERROR == "INTERNAL_ERROR"

    def test_has_not_found(self):
        assert ErrorCodes.NOT_FOUND == "NOT_FOUND"

    def test_has_validation_error(self):
        assert ErrorCodes.VALIDATION_ERROR == "VALIDATION_ERROR"

    def test_has_not_authenticated(self):
        assert ErrorCodes.NOT_AUTHENTICATED == "NOT_AUTHENTICATED"

    def test_has_rate_limited(self):
        assert ErrorCodes.RATE_LIMITED == "RATE_LIMITED"

    def test_has_service_unavailable(self):
        assert ErrorCodes.SERVICE_UNAVAILABLE == "SERVICE_UNAVAILABLE"
