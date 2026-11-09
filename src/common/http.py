import json
from decimal import Decimal


class JsonEncoder(json.JSONEncoder):
    def default(self, value):
        if isinstance(value, Decimal):
            return int(value) if value % 1 == 0 else float(value)
        return super().default(value)


def response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Authorization,Content-Type",
            "Access-Control-Allow-Methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS",
        },
        "body": json.dumps(body, cls=JsonEncoder),
    }


def error(status_code, code, message):
    return response(status_code, {"error": {"codigo": code, "mensaje": message}})
