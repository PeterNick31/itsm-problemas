import base64
import json
import os
import re
import uuid
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

from src.common.events import publish
from src.common.http import error, response


TABLE = boto3.resource("dynamodb").Table(os.environ["PROBLEMAS_TABLE"])
ROLES = {"ADMIN", "AGENTE"}
STATES = {"NUEVO", "EN_ANALISIS", "ERROR_CONOCIDO", "RESUELTO", "CERRADO"}
TRANSITIONS = {
    "NUEVO": {"EN_ANALISIS"},
    "EN_ANALISIS": set(),
    "ERROR_CONOCIDO": {"RESUELTO"},
    "RESUELTO": {"CERRADO"},
    "CERRADO": set(),
}
EDITABLE_FIELDS = {"titulo", "descripcion", "prioridad", "responsable_id"}
TENANT_PATTERN = re.compile(r"^[a-z0-9-]{2,40}$")


class RequestError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status = status
        self.code = code


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _claims(event):
    authorizer = event.get("requestContext", {}).get("authorizer", {})
    claims = authorizer.get("tenant_id") and authorizer or authorizer.get("lambda", {})
    if not claims.get("tenant_id") or not claims.get("usuario_id") or not claims.get("rol"):
        raise RequestError(401, "NO_AUTORIZADO", "No se encontró el contexto del usuario.")
    if claims["rol"] not in ROLES:
        raise RequestError(403, "ROL_NO_PERMITIDO", "Se requiere rol ADMIN o AGENTE.")
    if not TENANT_PATTERN.fullmatch(str(claims["tenant_id"])):
        raise RequestError(403, "TENANT_INVALIDO", "El tenant del token no es válido.")
    if not str(claims["usuario_id"]).startswith(f"usr-{claims['tenant_id']}-"):
        raise RequestError(403, "USUARIO_INVALIDO", "El usuario no pertenece al tenant autenticado.")
    return claims


def _body(event):
    try:
        value = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError as exc:
        raise RequestError(400, "JSON_INVALIDO", "El cuerpo debe ser JSON válido.") from exc
    if not isinstance(value, dict):
        raise RequestError(400, "JSON_INVALIDO", "El cuerpo debe ser un objeto JSON.")
    return value


def _path_problem_id(event):
    value = event.get("pathParameters", {}).get("id")
    if not value:
        raise RequestError(400, "ID_REQUERIDO", "Falta el identificador del problema.")
    return value


def _get_problem(tenant_id, problem_id):
    result = TABLE.get_item(Key={"tenant_id": tenant_id, "problema_id": problem_id})
    item = result.get("Item")
    if not item:
        raise RequestError(404, "NO_ENCONTRADO", "No existe un problema con ese ID en este tenant.")
    return item


def _token_decode(value):
    try:
        key = json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RequestError(400, "TOKEN_INVALIDO", "El cursor de paginación no es válido.") from exc
    if not isinstance(key, dict) or not key.get("tenant_id") or not key.get("problema_id"):
        raise RequestError(400, "TOKEN_INVALIDO", "El cursor de paginación no es válido.")
    return key


def _list(event, tenant_id):
    query = event.get("queryStringParameters") or {}
    try:
        limit = int(query.get("limite", "20"))
    except (TypeError, ValueError) as exc:
        raise RequestError(400, "LIMITE_INVALIDO", "limite debe ser un entero entre 1 y 100.") from exc
    if not 1 <= limit <= 100:
        raise RequestError(400, "LIMITE_INVALIDO", "limite debe ser un entero entre 1 y 100.")

    priority = query.get("prioridad")
    if priority and priority not in {"P1", "P2", "P3", "P4"}:
        raise RequestError(400, "PRIORIDAD_INVALIDA", "El filtro prioridad debe ser P1, P2, P3 o P4.")
    assignee = query.get("responsable_id")
    if assignee and not assignee.startswith(f"usr-{tenant_id}-"):
        raise RequestError(400, "RESPONSABLE_INVALIDO", "El responsable debe pertenecer al tenant autenticado.")

    params = {"Limit": limit}
    if query.get("estado"):
        state = query["estado"]
        if state not in STATES:
            raise RequestError(400, "ESTADO_INVALIDO", "El filtro estado no es válido.")
        params.update({
            "IndexName": "estado-index",
            "KeyConditionExpression": Key("tenant_id").eq(tenant_id)
            & Key("estado_creado_en").begins_with(f"{state}#"),
            "ScanIndexForward": False,
        })
    else:
        params["KeyConditionExpression"] = Key("tenant_id").eq(tenant_id)
        params["ScanIndexForward"] = False
    filters = []
    if priority:
        filters.append(Attr("prioridad").eq(priority))
    if assignee:
        filters.append(Attr("responsable_id").eq(assignee))
    if filters:
        filter_expression = filters[0]
        for condition in filters[1:]:
            filter_expression &= condition
        params["FilterExpression"] = filter_expression
    if query.get("siguiente"):
        start_key = _token_decode(query["siguiente"])
        if start_key["tenant_id"] != tenant_id:
            raise RequestError(400, "TOKEN_INVALIDO", "El cursor no pertenece al tenant autenticado.")
        params["ExclusiveStartKey"] = start_key

    result = TABLE.query(**params)
    next_key = result.get("LastEvaluatedKey")
    next_token = (
        base64.urlsafe_b64encode(json.dumps(next_key).encode("utf-8"))
        .decode("ascii")
        .rstrip("=")
        if next_key
        else None
    )
    return response(200, {
        "data": result.get("Items", []),
        "paginacion": {"limite": limit, "siguiente": next_token},
    })


def _create(event, tenant_id, user_id):
    body = _body(event)
    if not isinstance(body.get("titulo"), str) or not body["titulo"].strip():
        raise RequestError(400, "TITULO_REQUERIDO", "titulo es obligatorio.")
    priority = body.get("prioridad", "P3")
    if priority not in {"P1", "P2", "P3", "P4"}:
        raise RequestError(400, "PRIORIDAD_INVALIDA", "prioridad debe ser P1, P2, P3 o P4.")

    now = _now()
    item = {
        "tenant_id": tenant_id,
        "problema_id": f"prb-{tenant_id}-{uuid.uuid4().hex[:12]}",
        "titulo": body["titulo"].strip(),
        "descripcion": str(body.get("descripcion", "")),
        "prioridad": priority,
        "estado": "NUEVO",
        "estado_creado_en": f"NUEVO#{now}",
        "causa_raiz": None,
        "workaround": None,
        "incidentes_ids": [],
        "cambio_id": None,
        "responsable_id": body.get("responsable_id", user_id),
        "creado_en": now,
        "actualizado_en": now,
    }
    if not str(item["responsable_id"]).startswith(f"usr-{tenant_id}-"):
        raise RequestError(400, "RESPONSABLE_INVALIDO", "El responsable debe pertenecer al tenant autenticado.")
    TABLE.put_item(
        Item=item,
        ConditionExpression="attribute_not_exists(tenant_id) AND attribute_not_exists(problema_id)",
    )
    return response(201, {"data": item})


def _update_state(tenant_id, problem_id, new_state, expected_states=None):
    if new_state not in STATES:
        raise RequestError(400, "ESTADO_INVALIDO", "El estado indicado no es válido.")
    item = _get_problem(tenant_id, problem_id)
    current = item["estado"]
    if expected_states is not None and current not in expected_states:
        raise RequestError(409, "TRANSICION_INVALIDA", f"No se puede registrar causa raíz desde {current}.")
    is_cause_root_transition = expected_states == {"EN_ANALISIS"} and new_state == "ERROR_CONOCIDO"
    if new_state not in TRANSITIONS[current] and not is_cause_root_transition:
        raise RequestError(409, "TRANSICION_INVALIDA", f"No se permite pasar de {current} a {new_state}.")
    now = _now()
    TABLE.update_item(
        Key={"tenant_id": tenant_id, "problema_id": problem_id},
        UpdateExpression="SET #state = :state, estado_creado_en = :sort, actualizado_en = :now",
        ExpressionAttributeNames={"#state": "estado"},
        ExpressionAttributeValues={
            ":state": new_state,
            ":sort": f"{new_state}#{now}",
            ":now": now,
            ":old": current,
        },
        ConditionExpression="#state = :old",
    )
    return new_state


def _summary(tenant_id):
    counts = {state: 0 for state in sorted(STATES)}
    for state in STATES:
        params = {
            "IndexName": "estado-index",
            "KeyConditionExpression": Key("tenant_id").eq(tenant_id)
            & Key("estado_creado_en").begins_with(f"{state}#"),
            "Select": "COUNT",
        }
        while True:
            result = TABLE.query(**params)
            counts[state] += result["Count"]
            last_key = result.get("LastEvaluatedKey")
            if not last_key:
                break
            params["ExclusiveStartKey"] = last_key
    return response(200, {"data": {"por_estado": counts, "total": sum(counts.values())}})


def _handle(event):
    claims = _claims(event)
    tenant_id = claims["tenant_id"]
    user_id = claims["usuario_id"]
    method = event.get("httpMethod", "").upper()
    path = event.get("resource", "")

    if method == "GET" and path == "/problemas/resumen":
        return _summary(tenant_id)
    if method == "GET" and path == "/problemas":
        return _list(event, tenant_id)
    if method == "POST" and path == "/problemas":
        return _create(event, tenant_id, user_id)

    problem_id = _path_problem_id(event)
    if method == "GET" and path == "/problemas/{id}":
        return response(200, {"data": _get_problem(tenant_id, problem_id)})

    if method == "PUT" and path == "/problemas/{id}":
        body = _body(event)
        unknown_fields = set(body) - EDITABLE_FIELDS
        if unknown_fields:
            raise RequestError(400, "CAMPOS_NO_PERMITIDOS", "El body contiene campos que no se pueden editar.")
        updates = {key: value for key, value in body.items() if key in EDITABLE_FIELDS}
        if not updates:
            raise RequestError(400, "SIN_CAMPOS", "Indica al menos un campo editable.")
        if "titulo" in updates and (not isinstance(updates["titulo"], str) or not updates["titulo"].strip()):
            raise RequestError(400, "TITULO_INVALIDO", "titulo no puede estar vacío.")
        if "prioridad" in updates and updates["prioridad"] not in {"P1", "P2", "P3", "P4"}:
            raise RequestError(400, "PRIORIDAD_INVALIDA", "prioridad debe ser P1, P2, P3 o P4.")
        if "responsable_id" in updates and not str(updates["responsable_id"]).startswith(f"usr-{tenant_id}-"):
            raise RequestError(400, "RESPONSABLE_INVALIDO", "El responsable debe pertenecer al tenant autenticado.")
        if "titulo" in updates:
            updates["titulo"] = updates["titulo"].strip()
        _get_problem(tenant_id, problem_id)
        fields = ["#field" + str(index) for index in range(len(updates))]
        values = {":value" + str(index): value for index, value in enumerate(updates.values())}
        names = {fields[index]: key for index, key in enumerate(updates)}
        assignments = [f"{fields[index]} = :value{index}" for index in range(len(updates))]
        assignments.extend(["actualizado_en = :now"])
        values[":now"] = _now()
        TABLE.update_item(
            Key={"tenant_id": tenant_id, "problema_id": problem_id},
            UpdateExpression="SET " + ", ".join(assignments),
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )
        return response(200, {"data": _get_problem(tenant_id, problem_id)})

    if method == "PATCH" and path == "/problemas/{id}/estado":
        state = _body(event).get("estado")
        new_state = _update_state(tenant_id, problem_id, state)
        if new_state == "RESUELTO":
            publish("problema.resuelto", tenant_id, {"problema_id": problem_id})
        return response(200, {"data": _get_problem(tenant_id, problem_id)})

    if method == "POST" and path == "/problemas/{id}/causa-raiz":
        body = _body(event)
        cause = body.get("causa_raiz")
        workaround = body.get("workaround")
        if not isinstance(cause, str) or not cause.strip():
            raise RequestError(400, "CAUSA_REQUERIDA", "causa_raiz es obligatoria.")
        if not isinstance(workaround, str) or not workaround.strip():
            raise RequestError(400, "WORKAROUND_REQUERIDO", "workaround es obligatorio.")
        _update_state(tenant_id, problem_id, "ERROR_CONOCIDO", {"EN_ANALISIS"})
        now = _now()
        TABLE.update_item(
            Key={"tenant_id": tenant_id, "problema_id": problem_id},
            UpdateExpression="SET causa_raiz = :cause, workaround = :workaround, actualizado_en = :now",
            ExpressionAttributeValues={":cause": cause.strip(), ":workaround": workaround.strip(), ":now": now},
        )
        event_data = {
            "problema_id": problem_id,
            "causa_raiz": cause.strip(),
            "workaround": workaround.strip(),
        }
        publish("problema.causa_raiz_identificada", tenant_id, event_data)
        return response(200, {"data": _get_problem(tenant_id, problem_id)})

    if method == "POST" and path == "/problemas/{id}/incidentes":
        body = _body(event)
        ids = body.get("incidentes_ids")
        if not isinstance(ids, list) or not all(isinstance(value, str) for value in ids):
            raise RequestError(400, "INCIDENTES_INVALIDOS", "incidentes_ids debe ser una lista de IDs.")
        if len(set(ids)) != len(ids) or any(not value.startswith(f"inc-{tenant_id}-") for value in ids):
            raise RequestError(400, "INCIDENTES_INVALIDOS", "Los IDs deben ser únicos y pertenecer al tenant.")
        item = _get_problem(tenant_id, problem_id)
        merged = sorted(set(item.get("incidentes_ids", [])) | set(ids))
        TABLE.update_item(
            Key={"tenant_id": tenant_id, "problema_id": problem_id},
            UpdateExpression="SET incidentes_ids = :ids, actualizado_en = :now",
            ExpressionAttributeValues={":ids": merged, ":now": _now()},
        )
        return response(200, {"data": _get_problem(tenant_id, problem_id)})

    if method == "DELETE" and path == "/problemas/{id}":
        if claims["rol"] != "ADMIN":
            raise RequestError(403, "ROL_NO_PERMITIDO", "Se requiere rol ADMIN para eliminar problemas.")
        item = _get_problem(tenant_id, problem_id)
        if item["estado"] != "NUEVO":
            raise RequestError(409, "ESTADO_INVALIDO", "Solo se pueden eliminar problemas en estado NUEVO.")
        TABLE.delete_item(
            Key={"tenant_id": tenant_id, "problema_id": problem_id},
            ConditionExpression="#state = :new",
            ExpressionAttributeNames={"#state": "estado"},
            ExpressionAttributeValues={":new": "NUEVO"},
        )
        return response(200, {"data": {"problema_id": problem_id, "eliminado": True}})

    raise RequestError(404, "RUTA_NO_ENCONTRADA", "La ruta solicitada no existe.")


def handler(event, _context):
    try:
        return _handle(event)
    except RequestError as exc:
        return error(exc.status, exc.code, str(exc))
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return error(409, "CONFLICTO", "El registro cambió; vuelve a consultar e intenta otra vez.")
        raise
