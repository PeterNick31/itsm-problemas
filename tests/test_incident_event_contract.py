import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_EC2_METADATA_DISABLED", "true")
os.environ.setdefault("PROBLEMAS_TABLE", "test-problemas")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.consumers import events


class IncidentEventContractTests(unittest.TestCase):
    def test_change_resolution_publishes_linked_incident_ids(self):
        record = {"messageId": "msg-1", "body": "{}"}
        message = {
            "tenant_id": "acme",
            "evento": "cambio.implementado",
            "data": {"problema_id": "prb-acme-000001"},
        }
        with (
            patch.object(events, "_unwrap", return_value=message),
            patch.object(
                events,
                "_resolve_problem",
                return_value=("prb-acme-000001", True, ["inc-acme-000007"]),
            ),
            patch.object(events, "publish") as publish,
            patch.object(events, "_acknowledge_resolved_event"),
        ):
            result = events.handler({"Records": [record]}, None)

        self.assertEqual(result, {"batchItemFailures": []})
        publish.assert_called_once_with(
            "problema.resuelto",
            "acme",
            {
                "problema_id": "prb-acme-000001",
                "incidentes_ids": ["inc-acme-000007"],
            },
        )


if __name__ == "__main__":
    unittest.main()
