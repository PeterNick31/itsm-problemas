import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_EC2_METADATA_DISABLED", "true")
os.environ.setdefault("PROBLEMAS_TABLE", "test-problemas")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.handlers import problemas


def api_event(method, resource, role="ADMIN", query=None):
    return {
        "httpMethod": method,
        "resource": resource,
        "queryStringParameters": query or {},
        "pathParameters": {"id": "prb-acme-000001"},
        "requestContext": {
            "authorizer": {
                "tenant_id": "acme",
                "usuario_id": "usr-acme-00001",
                "rol": role,
            }
        },
    }


class HandlerTests(unittest.TestCase):
    def test_agent_cannot_delete_problem(self):
        with patch.object(problemas.TABLE, "delete_item") as delete_item:
            result = problemas.handler(
                api_event("DELETE", "/problemas/{id}", role="AGENTE"),
                None,
            )

        self.assertEqual(result["statusCode"], 403)
        delete_item.assert_not_called()

    def test_list_applies_priority_and_assignee_filters(self):
        with patch.object(
            problemas.TABLE,
            "query",
            return_value={"Items": [], "LastEvaluatedKey": None},
        ) as query:
            result = problemas.handler(
                api_event(
                    "GET",
                    "/problemas",
                    query={"prioridad": "P1", "responsable_id": "usr-acme-00003"},
                ),
                None,
            )

        self.assertEqual(result["statusCode"], 200)
        self.assertIn("FilterExpression", query.call_args.kwargs)
        self.assertEqual(json.loads(result["body"])["data"], [])

    def test_resolving_problem_publishes_linked_incident_ids(self):
        event = api_event("PATCH", "/problemas/{id}/estado")
        event["body"] = json.dumps({"estado": "RESUELTO"})
        item = {
            "problema_id": "prb-acme-000001",
            "estado": "RESUELTO",
            "incidentes_ids": ["inc-acme-000007"],
        }
        with (
            patch.object(problemas, "_update_state", return_value="RESUELTO"),
            patch.object(problemas, "_get_problem", return_value=item),
            patch.object(problemas, "publish") as publish,
        ):
            result = problemas.handler(event, None)

        self.assertEqual(result["statusCode"], 200)
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
