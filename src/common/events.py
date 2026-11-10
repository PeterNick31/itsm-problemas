import json
import os
from datetime import datetime, timezone

import boto3


def publish(event_name, tenant_id, data):
    if os.environ.get("EVENTS_ENABLED", "false").lower() != "true":
        return None

    topic_arn = os.environ.get("EVENTS_TOPIC_ARN")
    if not topic_arn:
        raise RuntimeError("EVENTS_TOPIC_ARN no está configurado")

    envelope = {
        "evento": event_name,
        "version": "1.0",
        "tenant_id": tenant_id,
        "origen": "problemas",
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "data": data,
    }
    boto3.client("sns").publish(
        TopicArn=topic_arn,
        Message=json.dumps(envelope),
        MessageAttributes={
            "evento": {"DataType": "String", "StringValue": event_name},
            "tenant_id": {"DataType": "String", "StringValue": tenant_id},
        },
    )
    return envelope
