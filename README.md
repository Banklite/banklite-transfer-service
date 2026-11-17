# Transfer Service — BankLite

Transferencias internas, a bancos externos (ACH/SWIFT/Stellar testnet) y programadas; validacion de fondos y de fraude; pago de servicios y QR.

Parte del proyecto **BankLite** (banca digital con microservicios) de *Arquitectura y Modelamiento de Software*, Universidad Cooperativa de Colombia. Cada microservicio tiene su propio repositorio y su propia base de datos (`transfer_db`).

## Responsabilidad en la arquitectura

Transferencias internas, a bancos externos (ACH/SWIFT/Stellar testnet) y programadas; validacion de fondos y de fraude; pago de servicios y QR. Se comunica con los demas servicios por **REST** (operaciones que necesitan respuesta inmediata) y por **eventos** en RabbitMQ (exchange `banklite.events`, tipo topic).

| Eventos publicados | Eventos consumidos |
|---|---|
| `transfer.completed` | — |

## Tecnologias

FastAPI, SQLAlchemy, PostgreSQL, APScheduler, RabbitMQ (pika), Stellar SDK (testnet). Python 3.12, Docker.

## Despliegue

- URL publica: <https://banklite-transfer-service.onrender.com>
- Salud: <https://banklite-transfer-service.onrender.com/health>
- Documentacion interactiva (Swagger): <https://banklite-transfer-service.onrender.com/docs>

Desplegado en Render (plan gratuito: tarda hasta ~1 minuto en responder si estuvo inactivo). Las credenciales se configuran como variables de entorno en la plataforma, no en el codigo.

## Endpoints principales

| Metodo | Ruta | Descripcion |
|---|---|---|
| `POST` | `/transfers` | Crea una transferencia (valida cuenta, fraude y ledger) |
| `GET` | `/transfers` | Lista transferencias |
| `GET` | `/transfers/{id}` | Detalle de una transferencia |
| `GET` | `/transfers/{id}/schedule` | Programacion de una transferencia recurrente |
| `POST` | `/beneficiaries` | Crea un beneficiario |
| `GET` | `/payment-rails` | Rieles de pago disponibles |
| `POST` | `/transfers/qr/pagar` | Pago por QR |
| `GET` | `/transfers/trm` | Tasa de cambio |
| `GET` | `/health` | Estado del servicio |
| `GET` | `/stats` | Contadores del servicio |

La lista completa esta en `/docs`.

## Variables de entorno

Copia `.env.example` a `.env` y completa los valores.

| Variable | Descripcion |
|---|---|
| `DATABASE_URL` | Conexion PostgreSQL |
| `ACCOUNT_SERVICE_URL` | URL de account-service |
| `LEDGER_SERVICE_URL` | URL de ledger-service |
| `FRAUD_SERVICE_URL` | URL de fraud-service |
| `NOTIFICATION_SERVICE_URL` | URL de notification-service (respaldo REST) |
| `IDENTITY_SERVICE_URL` | URL de identity-service |
| `STELLAR_TREASURY_SECRET` | Llave secreta de la tesoreria Stellar (testnet) |
| `STELLAR_NETWORK` | Red Stellar |
| `STELLAR_HORIZON_URL` | Horizon de la red |
| `RABBITMQ_URL` | URL del bus de eventos |
| `ENABLE_EVENTS` | Publicar eventos |

## Base de datos

Motor: PostgreSQL. Base: `transfer_db`.

- `db/schema.sql`: creacion de tablas, indices y restricciones.
- `db/seed.sql`: datos de ejemplo.

El servicio tambien crea las tablas solo al arrancar (`create_all`). Para restaurar a mano:

```bash
createdb transfer_db
psql -d transfer_db -f db/schema.sql
psql -d transfer_db -f db/seed.sql
```

Respaldo completo (para entregar o restaurar): `pg_dump -Fc transfer_db > transfer_db.dump` y `pg_restore -d transfer_db transfer_db.dump`.

## Instalacion y ejecucion

Con Docker:

```bash
docker build -t banklite-transfer-service .
docker run --env-file .env -p 8004:8004 -e PORT=8004 banklite-transfer-service
```

Sin Docker:

```bash
python -m venv .venv && source .venv/bin/activate   # en Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8004
```

Prueba: abre <http://localhost:8004/docs>.

## Pruebas automatizadas

```bash
pip install -r requirements-dev.txt
python -m pytest tests -v --cov=app --cov-report=term-missing --cov-report=html
```

No necesitan PostgreSQL, RabbitMQ ni los otros microservicios: la base es SQLite en memoria y las dependencias externas se reemplazan con mocks (`unittest.mock`). El reporte navegable queda en `htmlcov/index.html`.

| Tipo | Archivo | Que verifica |
|---|---|---|
| Unitaria (mocks) | `tests/unit/test_clientes_rest.py` | Clientes REST hacia fraud-service (fail-open) y ledger-service (partida doble, rechazo vs. caida) con `httpx` simulado. |
| Unitaria (mocks) | `tests/unit/test_qr_aviso.py` | El pago por QR publica `transfer.completed`; si el bus no esta, avisa por REST. |
| Integracion | `tests/integration/test_transfers_api.py` | La SAGA de `POST /transfers` completa: catalogo en la base -> account -> saldo -> antifraude -> partida doble -> evento. Fallos a mitad de camino dejan la transferencia `rechazada`; idempotencia. |
| Integracion | `tests/integration/test_qr_y_servicios_api.py` | Cobro y pago con QR y pago de servicios publicos contra la cuenta puente. |

Resultado actual: **40 pruebas** (9 unitarias y 31 de integracion), todas aprobadas, con **74 % de cobertura** de `app/`.

En GitHub Actions las pruebas corren en cada `push` y `pull request`. Si una falla, la imagen no se construye y no se despliega. El reporte de cobertura queda en el resumen de la ejecucion y como artefacto descargable `coverage-banklite-transfer-service`.

## Repositorios del proyecto

`banklite-identity-service`, `banklite-account-service`, `banklite-ledger-service`, `banklite-transfer-service`, `banklite-card-service`, `banklite-fraud-service`, `banklite-notification-service`, `banklite-compliance-service`. Panel web: `services/web-panel` en el repositorio `banklite-microservicios`.
