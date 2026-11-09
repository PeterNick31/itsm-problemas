# itsm-problemas

Microservicio de análisis de causa raíz de incidentes. El stack crea la tabla DynamoDB y consume/publica eventos mediante el bus SNS y la cola SQS compartidos de `itsm-infra`.

## Requisitos

- Python 3.12
- Node.js 20 y npm
- AWS CLI configurado; `LabRole` con permisos para Lambda, API Gateway, DynamoDB, lectura de SSM, publicación SNS y consumo SQS
- Serverless Framework 3: `npm install --global serverless@3`

## Archivos principales

- `serverless.yml`: API, tabla, autorización y referencias SSM a la infraestructura compartida.
- `src/handlers/problemas.py`: endpoints CRUD y flujos de estado.
- `src/consumers/events.py`: reacciones a escalamiento de incidentes e implementación de cambios.
- `seed/seed_problemas.py`: datos ficticios repetibles por tenant.
- `docs/modelo.json`: esquema para el informe.

## Requisitos para desplegar

Antes de desplegar, `itsm-infra` debe estar desplegado en la **misma cuenta AWS** y en `us-east-1` para el stage elegido. El stack lee los parámetros `/itsm/{stage}/sns-eventos-arn` y `/itsm/{stage}/q-problemas-arn` que Infra publica. El rol `LabRole` debe poder leer esos parámetros, publicar al tópico y consumir de la cola.

El JWT se valida con el secreto compartido guardado como SecureString en `/itsm/{stage}/jwt-secret`. Este debe ser el mismo secreto que usa el servicio de autenticación. Para una prueba completamente aislada, se puede usar `JWT_SECRET` del entorno como alternativa, pero el stack sigue necesitando el bus SNS/SQS compartido. No guardes secretos en Git:

```powershell
$env:JWT_SECRET = "reemplaza-por-un-secreto-local-largo"
serverless deploy --stage dev
```

El authorizer de este repositorio valida JWT HS256 y requiere `tenant_id`, `sub`, `rol` y `exp`. Para pruebas manuales genera un token:

```powershell
$env:JWT_SECRET = "el-mismo-secreto-del-despliegue"
python scripts/generate_dev_token.py --tenant acme --user usr-acme-00001 --role ADMIN
```

Envía el resultado como `Authorization: Bearer <token>`. Este generador es solo una herramienta local; no es un sistema de login para producción.

## Endpoints

Todos requieren JWT con rol `ADMIN` o `AGENTE`. La eliminación (`DELETE /problemas/{id}`) es exclusiva de `ADMIN`.

| Método | Ruta | Uso |
|---|---|---|
| POST | `/problemas` | Crear problema manual |
| GET | `/problemas?limite=20&siguiente=...&estado=NUEVO&prioridad=P1&responsable_id=usr-acme-00001` | Lista paginada y filtros opcionales |
| GET | `/problemas/{id}` | Detalle del tenant autenticado |
| PUT | `/problemas/{id}` | Editar título, descripción, prioridad o responsable |
| PATCH | `/problemas/{id}/estado` | Cambiar estado respetando transiciones |
| POST | `/problemas/{id}/causa-raiz` | Registrar causa y workaround; publica evento |
| POST | `/problemas/{id}/incidentes` | Vincular IDs del mismo tenant |
| DELETE | `/problemas/{id}` | Eliminar solo si está `NUEVO` |
| GET | `/problemas/resumen` | Conteo por estado para el dashboard |

El tenant siempre se obtiene del contexto del token; el body no puede elegir el tenant. Las respuestas siguen `{"data": ...}` y `{"error": {"codigo": "...", "mensaje": "..."}}`.

## Eventos incluidos

El consumidor escucha la cola compartida `q-problemas`, que Infra suscribe al tópico común con filtro por el atributo SNS `evento`. El productor publica al tópico común e incluye ese atributo. Infra configura `RawMessageDelivery: true`; por eso el consumidor acepta directamente el sobre JSON del evento y también el sobre SNS estándar. Los eventos procesados son:

- `incidente.escalado_a_problema`: crea idempotentemente un problema vinculado al incidente.
- `cambio.implementado`: marca el problema como `RESUELTO` y publica `problema.resuelto`. Si el evento no incluye `problema_id` (por ejemplo, un cambio originado desde Solicitudes), se ignora.

Al resolver desde el consumidor, el registro conserva una marca pendiente hasta que SNS confirma la publicación; un reintento puede volver a publicar el evento, por lo que los consumidores deben tolerar duplicados.

La cola compartida tiene su DLQ y política de reintentos gestionadas por Infra. Los consumidores deben ser idempotentes porque SQS ofrece entrega al menos una vez.

## Datos ficticios

Después del despliegue:

```powershell
python -m pip install -r requirements.txt
python seed/seed_problemas.py --table itsm-problemas-dev-problemas --tenant acme --count 10000
python seed/seed_problemas.py --table itsm-problemas-dev-problemas --tenant todos --count 10000
```

La opción `todos` carga 10,000 registros en cada tenant (`acme`, `globex`, `initech`), 30,000 en total. El script usa claves deterministas, vincula un ID de incidente por problema y asigna fechas pasadas; se puede repetir.

## Pruebas y ejecución local

```powershell
python -m unittest discover -s tests -v
```

Las pruebas unitarias no requieren acceso a AWS. Para probar endpoints y eventos desplegados, primero debe estar disponible `itsm-infra` en la misma cuenta y región, y deben existir el secreto JWT y los permisos necesarios.

## Integración con el grupo

1. Verificar que Infra esté desplegada en la misma cuenta AWS, región `us-east-1` y stage `dev`, y que existan sus dos parámetros SSM de SNS/SQS.
2. Confirmar con el integrante 5 el formato del JWT y que `/itsm/dev/jwt-secret` sea el secreto compartido. El authorizer local del microservicio puede sustituirse al acordar el ARN del authorizer común.
3. Confirmar con Incidentes el contenido de `incidente.escalado_a_problema` y con Cambios que `cambio.implementado` incluya `tenant_id` y `problema_id`.
4. Compartir IDs de prueba con Cambios y la URL de API con el responsable del frontend.

No subas credenciales reales ni despliegues el microservicio antes de que Infra publique los parámetros requeridos.
