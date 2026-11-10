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


class ConsumerTests(unittest.TestCase):
    def test_accepts_incidents_escalation_contract(self):
        data = {
            "incidente_id": "inc-acme-000001",
            "titulo": "VPN no conecta",
            "descripcion": "Falla intermitente",
            "categoria": "RED",
            "prioridad": "P2",
            "solicitante_id": "usr-acme-00042",
            "escalado_por": "usr-acme-00003",
            "motivo": "Falla recurrente",
        }
        with patch.object(events.TABLE, "put_item") as put_item:
            problem_id = events._problem_from_incident("acme", data)

        self.assertTrue(problem_id.startswith("prb-acme-evt"))
        item = put_item.call_args.kwargs["Item"]
        self.assertEqual(item["incidente_origen_id"], data["incidente_id"])
        self.assertEqual(item["titulo"], data["titulo"])
        self.assertEqual(item["descripcion"], data["descripcion"])
        self.assertEqual(item["prioridad"], data["prioridad"])
        self.assertEqual(item["responsable_id"], data["escalado_por"])

    def test_ignores_change_without_problem_id(self):
        record = {"messageId": "msg-1", "body": "{}"}
        message = {
            "tenant_id": "acme",
            "evento": "cambio.implementado",
            "data": {"cambio_id": "chg-acme-000001"},
        }
        with patch.object(events, "_unwrap", return_value=message), patch.object(
            events, "_resolve_problem"
        ) as resolve_problem:
            result = events.handler({"Records": [record]}, None)

        self.assertEqual(result, {"batchItemFailures": []})
        resolve_problem.assert_not_called()

    def test_ignores_change_with_null_problem_id(self):
        record = {"messageId": "msg-2", "body": "{}"}
        message = {
            "tenant_id": "acme",
            "evento": "cambio.implementado",
            "data": {"problema_id": None},
        }
        with patch.object(events, "_unwrap", return_value=message), patch.object(
            events, "_resolve_problem"
        ) as resolve_problem:
            result = events.handler({"Records": [record]}, None)

        self.assertEqual(result, {"batchItemFailures": []})
        resolve_problem.assert_not_called()

    def test_retries_publish_for_resolved_problem_with_pending_event(self):
        problem_id = "prb-acme-000001"
        with patch.object(
            events.TABLE,
            "get_item",
            return_value={
                "Item": {
                    "estado": "RESUELTO",
                    "evento_resuelto_pendiente": True,
                    "incidentes_ids": ["inc-acme-000010"],
                }
            },
        ):
            result = events._resolve_problem("acme", {"problema_id": problem_id})

        self.assertEqual(result, (problem_id, True, ["inc-acme-000010"]))


if __name__ == "__main__":
    unittest.main()
