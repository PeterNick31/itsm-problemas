import argparse
import os
import random
from datetime import datetime, timedelta, timezone

import boto3


TENANTS = ("acme", "globex", "initech")
TITLES = (
    "Caídas recurrentes del servidor de correo",
    "Intermitencia en la conexión VPN",
    "Errores al procesar pagos",
    "Lentitud en el portal de clientes",
    "Fallas de autenticación en la aplicación",
    "Desconexión de impresoras de red",
)
DESCRIPTIONS = (
    "Se reproduce de forma intermitente durante las horas de mayor uso.",
    "El equipo de soporte detectó varios incidentes relacionados.",
    "El comportamiento comenzó después de una actualización reciente.",
    "Los usuarios reportan el problema desde distintas áreas.",
)


def seed(tenant_id, count, table_name, seed_value):
    table = boto3.resource("dynamodb").Table(table_name)
    randomizer = random.Random(seed_value)
    states = ("NUEVO", "EN_ANALISIS", "ERROR_CONOCIDO", "RESUELTO", "CERRADO")
    today = datetime.now(timezone.utc).date()
    for batch_start in range(1, count + 1, 25):
        with table.batch_writer(overwrite_by_pkeys=["tenant_id", "problema_id"]) as writer:
            batch_end = min(batch_start + 25, count + 1)
            for number in range(batch_start, batch_end):
                state = states[number % len(states)]
                created_date = today - timedelta(days=number % 365)
                timestamp = f"{created_date.isoformat()}T12:00:00Z"
                item = {
                    "tenant_id": tenant_id,
                    "problema_id": f"prb-{tenant_id}-{number:06d}",
                    "titulo": randomizer.choice(TITLES),
                    "descripcion": randomizer.choice(DESCRIPTIONS),
                    "prioridad": randomizer.choice(("P1", "P2", "P3", "P4")),
                    "estado": state,
                    "estado_creado_en": f"{state}#{timestamp}",
                    "causa_raiz": "Configuración inconsistente entre nodos." if state in states[2:] else None,
                    "workaround": "Reiniciar el servicio afectado." if state in states[2:] else None,
                    "incidentes_ids": [f"inc-{tenant_id}-{number:06d}"],
                    "cambio_id": None,
                    "responsable_id": f"usr-{tenant_id}-{(number % 10000) + 1:05d}",
                    "creado_en": timestamp,
                    "actualizado_en": timestamp,
                }
                writer.put_item(Item=item)
        print(f"{tenant_id}: {min(batch_start + 24, count)}/{count} registros listos")


def main():
    parser = argparse.ArgumentParser(description="Carga problemas ficticios en DynamoDB.")
    parser.add_argument("--table", default=os.environ.get("PROBLEMAS_TABLE"))
    parser.add_argument("--tenant", choices=TENANTS + ("todos",), default="todos")
    parser.add_argument("--count", type=int, default=10_000, help="Cantidad por tenant (máximo sugerido: 10000).")
    parser.add_argument("--seed", type=int, default=2032)
    args = parser.parse_args()
    if not args.table:
        parser.error("Indica --table o configura PROBLEMAS_TABLE.")
    if not 1 <= args.count <= 10_000:
        parser.error("--count debe estar entre 1 y 10000 por tenant.")
    tenants = TENANTS if args.tenant == "todos" else (args.tenant,)
    for tenant_id in tenants:
        seed(tenant_id, args.count, args.table, args.seed + TENANTS.index(tenant_id))


if __name__ == "__main__":
    main()
