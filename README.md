# itsm-problemas

Microservicio independiente para el análisis de causa raíz de incidentes. Esta primera versión se puede desarrollar y probar sin esperar al resto del equipo: crea su DynamoDB, su tópico SNS, su cola SQS y su DLQ. Al integrar el proyecto grupal se conecta al tópico/cola compartidos y al authorizer del integrante 5.

## Requisitos

- Python 3.12
- Node.js 20 y npm
- AWS CLI configurado y permisos para desplegar Lambda, API Gateway, DynamoDB, SNS y SQS
- Serverless Framework 3: `npm install --global serverless@3`

## Archivos principales

- `serverless.yml`: API, tabla, autorización local y recursos de eventos.
- `src/handlers/problemas.py`: endpoints CRUD y flujos de estado.
- `src/consumers/events.py`: reacciones a escalamiento de incidentes e implementación de cambios.
- `seed/seed_problemas.py`: datos ficticios repetibles por tenant.
- `docs/modelo.json`: esquema para el informe.

## Configuración y despliegue aislado

En integración, el stack lee el secreto compartido desde el parámetro SSM SecureString `/itsm/{stage}/jwt-secret`, que debe contener el mismo secreto usado para firmar los JWT. El despliegue aislado permite usar `JWT_SECRET` del entorno como alternativa si el parámetro todavía no está creado. No guardes el secreto en Git:

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

El tópico y la cola locales permiten desarrollar sin `itsm-infra`. El consumidor procesa:

- `incidente.escalado_a_problema`: crea idempotentemente un problema vinculado al incidente.
- `cambio.implementado`: marca el problema como `RESUELTO` y publica `problema.resuelto`. Si el evento no incluye `problema_id` (por ejemplo, un cambio originado desde Solicitudes), se ignora.

Al resolver desde el consumidor, el registro conserva una marca pendiente hasta que SNS confirma la publicación; un reintento puede volver a publicar el evento, por lo que los consumidores deben tolerar duplicados.

Estos recursos son locales para desarrollo aislado. Antes de integrar:

1. Pide al integrante 1 los parámetros `/itsm/{stage}/sns-eventos-arn` y `/itsm/{stage}/q-problemas-arn`, además de los permisos para publicar en SNS y consumir de SQS. Sustituye `ProblemasEventsTopic`, `ProblemasDLQ`, `ProblemasQueue`, `ProblemasQueuePolicy` y `ProblemasSubscription` por esos recursos compartidos; no elimines los recursos locales antes de tener los ARN y coordinar el despliegue.
2. Pide al integrante 5 que publique el JWT compartido como SecureString en `/itsm/{stage}/jwt-secret`, con permisos de lectura para el rol de despliegue.

No conectes tópicos de producción duplicados ni sustituyas los recursos locales hasta tener esos datos.

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

Las pruebas unitarias del JWT no requieren AWS ni paquetes externos. Para probar los endpoints, despliega el stack aislado en una cuenta AWS de desarrollo y usa el token local indicado arriba.

## Integración con el grupo

1. Reemplazar el authorizer local por el ARN acordado en `/itsm/{stage}/authorizer-arn`.
2. Configurar el tópico SNS y la cola SQS compartidos desde los parámetros SSM del proyecto.
3. Confirmar con Incidentes el contenido de `incidente.escalado_a_problema`, y con Cambios que `cambio.implementado` incluya `tenant_id` y `problema_id`.
4. Compartir IDs de prueba con Cambios y la URL de API con el responsable del frontend.

La base de desarrollo no incluye credenciales reales ni necesita que esas integraciones estén disponibles.
