import hashlib
import json
import logging
import os
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

from src.common.events import publish


TABLE = boto3.resource("dynamodb").Table(os.environ["PROBLEMAS_TABLE"])
LOGGER = logging.getLogger(__name__)


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _problem_from_incident(tenant_id, data):
    incident_id = data.get("incidente_id")
    if not isinstance(incident_id, str) or not incident_id.startswith(f"inc-{tenant_id}-"):
        raise ValueError("El evento no contiene un incidente_id válido para su tenant")
    title = data.get("titulo") or f"Problema originado por {incident_id}"
    priority = data.get("prioridad", "P3")
    responsable_id = data.get("responsable_id", "")
    if not isinstance(title, str) or priority not in {"P1", "P2", "P3", "P4"}:
        raise ValueError("El evento contiene título o prioridad inválidos")
    if responsable_id and (
        not isinstance(responsable_id, str)
        or not responsable_id.startswith(f"usr-{tenant_id}-")
    ):
        raise ValueError("El responsable del evento no pertenece al tenant")

    digest = hashlib.sha256(incident_id.encode("utf-8")).hexdigest()[:12]
    problem_id = f"prb-{tenant_id}-evt{digest}"
    now = _now()
    item = {
        "tenant_id": tenant_id,
        "problema_id": problem_id,
        "titulo": title,
        "descripcion": str(data.get("descripcion", "")),
        "prioridad": priority,
        "estado": "NUEVO",
        "estado_creado_en": f"NUEVO#{now}",
        "causa_raiz": None,
        "workaround": None,
        "incidentes_ids": [incident_id],
        "incidente_origen_id": incident_id,
        "cambio_id": None,
        "responsable_id": responsable_id,
        "creado_en": now,
        "actualizado_en": now,
    }
    try:
        TABLE.put_item(
            Item=item,
            ConditionExpression="attribute_not_exists(tenant_id) AND attribute_not_exists(problema_id)",
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
            raise
    return problem_id


def _resolve_problem(tenant_id, data):
    problem_id = data.get("problema_id")
    if not isinstance(problem_id, str) or not problem_id.startswith(f"prb-{tenant_id}-"):
        raise ValueError("El evento no contiene un problema_id válido para su tenant")
    result = TABLE.get_item(Key={"tenant_id": tenant_id, "problema_id": problem_id})
    item = result.get("Item")
    if not item:
        raise ValueError(f"No existe el problema {problem_id} del evento")
    if item["estado"] in {"RESUELTO", "CERRADO"}:
        return problem_id, bool(item.get("evento_resuelto_pendiente"))
    now = _now()
    TABLE.update_item(
        Key={"tenant_id": tenant_id, "problema_id": problem_id},
        UpdateExpression=(
            "SET #state = :resolved, estado_creado_en = :sort, "
            "actualizado_en = :now, evento_resuelto_pendiente = :pending"
        ),
        ExpressionAttributeNames={"#state": "estado"},
        ExpressionAttributeValues={
            ":resolved": "RESUELTO",
            ":sort": f"RESUELTO#{now}",
            ":now": now,
            ":pending": True,
            ":old": item["estado"],
        },
        ConditionExpression="#state = :old",
    )
    return problem_id, True


def _acknowledge_resolved_event(tenant_id, problem_id):
    TABLE.update_item(
        Key={"tenant_id": tenant_id, "problema_id": problem_id},
        UpdateExpression="REMOVE evento_resuelto_pendiente",
        ConditionExpression="evento_resuelto_pendiente = :pending",
        ExpressionAttributeValues={":pending": True},
    )


def _unwrap(record):
    raw = record["body"]
    body = json.loads(raw)
    if not isinstance(body, dict):
        raise ValueError("El evento debe ser un objeto JSON")
    if body.get("Type") == "Notification":
        body = json.loads(body["Message"])
    if not isinstance(body, dict) or not isinstance(body.get("data"), dict):
        raise ValueError("El evento debe ser un objeto con data como objeto")
    return body


def handler(event, _context):
    failures = []
    for record in event.get("Records", []):
        try:
            message = _unwrap(record)
            tenant_id = message["tenant_id"]
            event_name = message["evento"]
            data = message["data"]
            if not isinstance(tenant_id, str) or not tenant_id:
                raise ValueError("El evento no contiene tenant_id")
            if event_name == "incidente.escalado_a_problema":
                _problem_from_incident(tenant_id, data)
            elif event_name == "cambio.implementado":
                if data.get("problema_id") is None:
                    LOGGER.info(
                        "Se ignora cambio.implementado sin problema_id: %s",
                        record["messageId"],
                    )
                    continue
                problem_id, changed = _resolve_problem(tenant_id, data)
                if changed:
                    publish("problema.resuelto", tenant_id, {"problema_id": problem_id})
                    _acknowledge_resolved_event(tenant_id, problem_id)
            else:
                raise ValueError(f"Evento no soportado por q-problemas: {event_name}")
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            LOGGER.exception("Evento inválido %s; se reintentará y podrá llegar a la DLQ", record["messageId"])
            failures.append({"itemIdentifier": record["messageId"]})
        except ClientError:
            LOGGER.exception("Error de AWS al procesar el mensaje %s; se reintentará", record["messageId"])
            failures.append({"itemIdentifier": record["messageId"]})
    return {"batchItemFailures": failures}
