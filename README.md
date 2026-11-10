# itsm-problemas

Microservicio de análisis de causa raíz de incidentes. En el avance actual despliega el CRUD, API Gateway, Lambda y su tabla DynamoDB. La integración con SNS/SQS y sus consumidores queda conservada en el código, pero aplazada y excluida del despliegue actual.

## Requisitos

- Python 3.12
- AWS CLI configurado y Serverless Framework 3
- `LabRole` con permisos para Lambda, API Gateway, DynamoDB y lectura del parámetro SSM del authorizer
- `itsm-auth` desplegado en la misma cuenta AWS, región `us-east-1` y stage

## Despliegue

Antes de desplegar, confirma que existe `/itsm/dev/authorizer-arn` en SSM en la misma cuenta y región. Las rutas de negocio usan el Lambda Authorizer compartido con caché desactivada durante la integración.

```powershell
serverless deploy --stage dev --region us-east-1
```

Inicia sesión con `itsm-auth` y envía el JWT como `Authorization: Bearer <token>`. El authorizer debe exponer `tenant_id`, `usuario_id` y `rol`. El tenant de cada lectura y escritura se obtiene exclusivamente de ese contexto.

## Endpoints

Todos los endpoints requieren rol `ADMIN` o `AGENTE`; eliminar está limitado a `ADMIN` y problemas en estado `NUEVO`.

| Método | Ruta | Uso |
|---|---|---|
| POST | `/problemas` | Crear problema |
| GET | `/problemas?limite=20&siguiente=...&estado=NUEVO&prioridad=P1&responsable_id=usr-acme-00001` | Listar y filtrar problemas |
| GET | `/problemas/resumen` | Conteo por estado |
| GET | `/problemas/{id}` | Obtener detalle del tenant autenticado |
| PUT | `/problemas/{id}` | Editar título, descripción, prioridad o responsable |
| PATCH | `/problemas/{id}/estado` | Cambiar estado respetando transiciones |
| POST | `/problemas/{id}/causa-raiz` | Registrar causa y workaround |
| POST | `/problemas/{id}/incidentes` | Vincular incidentes del mismo tenant |
| DELETE | `/problemas/{id}` | Eliminar problema NUEVO (ADMIN) |

Las respuestas siguen `{ "data": ... }` y `{ "error": { "codigo": "...", "mensaje": "..." } }`. Las listas usan DynamoDB `Query`, cursores codificados en base64 y un máximo de 100 elementos por página.

## Modelo y seed

La tabla principal es `itsm-problemas-{stage}-problemas`, con `tenant_id` como partition key, `problema_id` como sort key y el índice `estado-index` sobre `tenant_id` + `estado_creado_en`.

El seed genera IDs reproducibles `prb-{tenant}-{n:06d}` y referencias de incidente `inc-{tenant}-{n:06d}`:

```powershell
python -m pip install -r requirements.txt
python seed/seed_problemas.py --table itsm-problemas-dev-problemas --tenant acme --count 10000
python seed/seed_problemas.py --table itsm-problemas-dev-problemas --tenant todos --count 10000
```

`todos` carga 10,000 registros por tenant (`acme`, `globex`, `initech`), 30,000 en total.

## Eventos pospuestos

La fase actual no depende de SNS/SQS, no resuelve sus ARN de SSM y no despliega triggers ni consumidores. `src/consumers/events.py` se conserva como código futuro y `src/consumers/` se excluye del paquete Lambda.

El publicador se conserva para la futura fase de eventos, pero no-op cuando `EVENTS_ENABLED=false` (valor predeterminado). Cuando se autorice la fase EDA, se habilitarán los ARN reales y los contratos acordados. El contrato previsto para `problema.resuelto.data` incluye `problema_id` e `incidentes_ids`.

## Pruebas

```powershell
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

Las pruebas unitarias no requieren acceso a AWS. No ejecutes `serverless remove`: podría borrar recursos y datos.
