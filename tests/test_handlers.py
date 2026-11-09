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


if __name__ == "__main__":
    unittest.main()
