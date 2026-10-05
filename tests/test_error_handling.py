import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

from app.error_handling import configure_error_handling
from app.errors import AppError


class Payload(BaseModel):
    count: int


def make_app() -> FastAPI:
    app = FastAPI()
    configure_error_handling(app)

    @app.post("/payload")
    async def accept_payload(payload: Payload):
        return payload

    @app.get("/application-error")
    async def application_error():
        raise AppError("APPOINTMENT_SLOT_BOOKED")

    @app.get("/database-error")
    async def database_error():
        raise SQLAlchemyError("sensitive database details")

    @app.get("/internal-error")
    async def internal_error():
        raise RuntimeError("sensitive internal details")

    return app


class ErrorHandlingTests(unittest.TestCase):
    def test_application_error_has_contract_and_server_generated_request_id(self):
        with TestClient(make_app()) as client:
            response = client.get(
                "/application-error",
                headers={"X-Request-ID": "client-controlled-id"},
            )

        self.assertEqual(response.status_code, 409)
        body = response.json()["error"]
        self.assertEqual(body["code"], "APPOINTMENT_SLOT_BOOKED")
        self.assertEqual(body["details"], {})
        self.assertNotEqual(body["request_id"], "client-controlled-id")
        self.assertEqual(response.headers["x-request-id"], body["request_id"])

    def test_validation_error_does_not_echo_rejected_value_or_raw_message(self):
        with TestClient(make_app()) as client:
            response = client.post(
                "/payload", json={"count": "private-input-value"}
            )

        self.assertEqual(response.status_code, 422)
        body = response.json()["error"]
        self.assertEqual(body["code"], "COMMON_VALIDATION_ERROR")
        self.assertEqual(
            body["details"]["fields"],
            [{"field": "count", "reason": "invalid_format"}],
        )
        self.assertNotIn("private-input-value", response.text)
        self.assertEqual(body["request_id"], response.headers["x-request-id"])

    def test_unknown_path_uses_common_not_found_contract(self):
        with TestClient(make_app()) as client:
            response = client.get("/missing")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "COMMON_NOT_FOUND")
        self.assertEqual(
            response.json()["error"]["request_id"],
            response.headers["x-request-id"],
        )

    def test_database_error_is_generic_to_client_and_logged_with_request_id(self):
        with self.assertLogs("dental_agent.errors", level="ERROR") as captured:
            with TestClient(make_app(), raise_server_exceptions=False) as client:
                response = client.get("/database-error")

        self.assertEqual(response.status_code, 500)
        body = response.json()["error"]
        self.assertEqual(body["code"], "DATABASE_ERROR")
        self.assertNotIn("sensitive database details", response.text)
        self.assertEqual(response.headers["x-request-id"], body["request_id"])
        self.assertTrue(
            any(
                record.error_code == "DATABASE_ERROR"
                and record.request_id == body["request_id"]
                for record in captured.records
            )
        )

    def test_unhandled_error_is_generic_to_client_and_logged_with_request_id(self):
        with self.assertLogs("dental_agent.errors", level="ERROR") as captured:
            with TestClient(make_app(), raise_server_exceptions=False) as client:
                response = client.get("/internal-error")

        self.assertEqual(response.status_code, 500)
        body = response.json()["error"]
        self.assertEqual(body["code"], "INTERNAL_ERROR")
        self.assertNotIn("sensitive internal details", response.text)
        self.assertEqual(response.headers["x-request-id"], body["request_id"])
        self.assertTrue(
            any(
                record.error_code == "INTERNAL_ERROR"
                and record.request_id == body["request_id"]
                for record in captured.records
            )
        )
