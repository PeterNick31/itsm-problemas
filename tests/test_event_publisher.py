import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common.events import publish


class EventPublisherTests(unittest.TestCase):
    def test_publishes_infra_event_attribute_and_envelope(self):
        sns_client = Mock()
        with patch("src.common.events.boto3.client", return_value=sns_client):
            with patch.dict(os.environ, {"EVENTS_TOPIC_ARN": "arn:aws:sns:us-east-1:123456789012:topic"}):
                result = publish(
                    "problema.causa_raiz_identificada",
                    "acme",
                    {"problema_id": "prb-acme-000001"},
                )

        self.assertEqual(result["evento"], "problema.causa_raiz_identificada")
        self.assertEqual(result["tenant_id"], "acme")
        sns_client.publish.assert_called_once()
        message = json.loads(sns_client.publish.call_args.kwargs["Message"])
        self.assertEqual(message, result)
        self.assertEqual(
            sns_client.publish.call_args.kwargs["MessageAttributes"]["evento"],
            {
                "DataType": "String",
                "StringValue": "problema.causa_raiz_identificada",
            },
        )


if __name__ == "__main__":
    unittest.main()
