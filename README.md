# TurfDepot Sales & Quote Automation Platform

Milestone 1: backend de cotizaciones con FastAPI, SQLAlchemy y PostgreSQL.

## Ejecutar desde cero (PowerShell)

Requisitos: Docker Desktop con motor Linux iniciado. Para ejecutar Python fuera de
Docker, Python 3.13.

```powershell
Copy-Item .env.example .env
# Edita .env: elige POSTGRES_PASSWORD y actualiza DATABASE_URL con la misma clave.
docker compose up --build
```

La API queda en http://localhost:8000 y Swagger en http://localhost:8000/docs.
Compose espera a que PostgreSQL esté saludable antes de arrancar FastAPI.
Los puertos se publican solo en localhost; este MVP aún no tiene autenticación.
Si 5432 está ocupado, configura `POSTGRES_PORT=55432` y cambia también el puerto
de `DATABASE_URL` a 55432. Esto ya se hizo en el `.env` local de esta máquina para
evitar interferir con otro proyecto; la plantilla conserva el puerto estándar.

El catálogo inicialmente está vacío. En `.env`, configura `GARDEN_PRICES` como
objeto JSON cuyas claves son tipos de jardín y cuyos valores son tarifas por m².
Ejemplo **exclusivamente de prueba**, no tarifa comercial:

```dotenv
GARDEN_PRICES={"jardin_plus":"300.00"}
```

Después de cambiarlo ejecuta `docker compose up -d --build`.
Sin catálogo, POST devuelve 503; con un tipo desconocido, devuelve 422.
Necesitamos del negocio: identificadores de tipos, tarifa final por m², moneda y
confirmación de si esas tarifas ya incluyen IVA. En este milestone no se añade IVA:
`total = subtotal + extras_total`. No hay descuentos, escalas ni mínimos implícitos.
Los precios de extras provienen de quien llama a la API.

## Probar los endpoints

```powershell
Invoke-RestMethod http://localhost:8000/health
$body = @{
    customer_name = 'Juan Perez'
    customer_phone = '4421234567'
    customer_location = 'Juriquilla, Queretaro'
    square_meters = 45
    garden_type = 'jardin_plus'
    extras = @(@{ name = 'base'; price = 2500 })
} | ConvertTo-Json -Depth 4
$quote = Invoke-RestMethod http://localhost:8000/quotes -Method Post -ContentType 'application/json' -Body $body
$quote
Invoke-RestMethod "http://localhost:8000/quotes/$($quote.id)"
```

Con la tarifa ficticia anterior: subtotal 13500.00, extras 2500.00, total 16000.00.
POST devuelve 201 y GET devuelve 200, o 404 si no existe el ID.
Se devuelve `id`, `customer_id`, `square_meters`, `garden_type`, `subtotal`,
`extras_total`, `total`, `status` y `created_at` (UTC).
Los decimales se serializan como cadenas JSON (`"16000.00"`) para preservar precisión.
Pydantic admite números o cadenas decimales como entrada. Rechaza importes negativos,
valores no finitos, más de dos decimales, campos desconocidos y texto vacío.
El área debe ser mayor que cero y como máximo 1,000,000 m²; se admiten hasta 100 extras.

## Estructura y responsabilidades

```text
src/turfdepot/
  __init__.py
  main.py                  # Factory, inicio, sesiones, routers y errores DB
  models.py                # Dataclasses originales: GrassProduct, QuoteItem
  pricing.py               # Funciones originales y cálculo decimal compartido
  api/routes/
    health.py              # GET /health: consulta SELECT 1
    quotes.py              # POST /quotes y GET /quotes/{id}
  core/config.py           # Variables de entorno y catálogo validado
  db/
    database.py            # Una sesión SQLAlchemy por solicitud
    models.py              # Tablas Customer, Quote, QuoteExtra y relaciones
  schemas/quote.py         # Contratos de entrada y salida Pydantic
  services/
    pricing.py             # Catálogo, subtotal, extras y total sin DB
    quote_service.py       # Coordina cálculo y transacción de guardado
tests/
  conftest.py              # PostgreSQL aislado por esquema temporal
  test_pricing.py          # Diez pruebas originales conservadas
  test_quote_pricing.py    # Extras, redondeo, valores inválidos y catálogo
  test_quotes.py           # API, persistencia, rollback y health
  test_config.py           # Validación de configuración
.env.example               # Plantilla sin credenciales reales
Dockerfile                 # Imagen Python, dependencias y Uvicorn
docker-compose.yml         # API, PostgreSQL, red, healthchecks y volumen
requirements.txt           # Dependencias de ejecución
requirements-dev.txt       # pytest y cliente HTTP
pyproject.toml             # Configuración de pytest para src/
```

Cada subpaquete contiene un `__init__.py` vacío. `.gitignore` conserva las exclusiones
originales y `.dockerignore` evita copiar entornos, secretos y cachés a la imagen.

## Recorrido de una solicitud

1. FastAPI selecciona la ruta y Pydantic valida el JSON antes de ejecutar su función.
2. La ruta llama a `quote_service.create_quote` con una sesión y el catálogo.
3. `price_quote` consulta la tarifa y reutiliza `decimal_subtotal`; suma los extras.
4. El servicio construye Customer, Quote y QuoteExtra mediante relaciones ORM.
5. `session.begin()` confirma todo junto; ante una excepción revierte la transacción.
6. SQLAlchemy genera INSERT para PostgreSQL usando el driver psycopg.
7. `QuoteRead` selecciona los campos y serializa la respuesta.

Cada POST registra un cliente nuevo, aunque repita teléfono. No deduplicamos por
teléfono sin una regla de negocio. Las cotizaciones guardan sus importes calculados:
GET no recalcula con precios nuevos. La sesión se cierra al terminar la solicitud.
Errores de DB devuelven 503 sin exponer SQL ni datos del cliente.

Se conservan las dataclasses, funciones públicas y pruebas originales. El subtotal
ahora comparte un cálculo `Decimal` con redondeo `ROUND_HALF_UP`; la función antigua
sigue devolviendo float por compatibilidad. Los helpers originales de IVA siguen
disponibles pero no participan en POST. La ruta nueva mantiene Decimal de extremo
a extremo y columnas NUMERIC en la DB.

## Docker y conexión con PostgreSQL

Dockerfile instala Python y dependencias, copia código y tests, y ejecuta Uvicorn
como usuario sin privilegios. Incluye pytest para poder validar la misma imagen;
una imagen de despliegue futura podrá separar esas dependencias.

Compose crea una red donde `db` resuelve al contenedor PostgreSQL. La API construye
su conexión desde DB_HOST/DB_USER/DB_PASSWORD/DB_NAME; esto permite claves con
caracteres especiales sin interpolarlas en una URL. Fuera de Docker se usa
DATABASE_URL con localhost, puerto publicado y contraseña codificada para URL
si contiene caracteres reservados. DATABASE_URL tiene prioridad sobre DB_*.

El volumen `postgres_data` conserva datos al recrear contenedores.
`docker compose down` detiene y elimina contenedores, pero conserva ese volumen.
Cambiar POSTGRES_PASSWORD en `.env` no cambia la contraseña de una DB ya inicializada.
Al iniciar, `create_all` crea las tablas faltantes; **no realiza migraciones** de
tablas existentes. Es suficiente para esta primera versión, no para evolucionar
un esquema con datos en producción. No se han añadido tecnologías de milestones futuros.

## Python local y tests

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
docker compose up -d db
$env:PYTHONPATH = 'src'
.venv/Scripts/python.exe -m uvicorn turfdepot.main:create_app --factory --reload
```

En otra terminal, desde la raíz:

```powershell
.venv/Scripts/python.exe -m pytest -q
```

O todo dentro de Docker:

```powershell
docker compose run --rm api python -m pytest -q -p no:cacheprovider
```

Las pruebas de API usan PostgreSQL real, nunca SQLite. Cada prueba crea un esquema
`test_<uuid>` y lo elimina al terminar. Necesitan un usuario con permiso CREATE SCHEMA;
por defecto usan la DB de desarrollo. Puedes dirigirlas a otra DB con
TEST_DATABASE_URL. No borran tablas de la aplicación. El catálogo 300.00 se inyecta
solo en tests. `TestClient` ejecuta el lifespan dentro de un contexto `with`.
Se comprueban creación, consulta, importes, relaciones, timestamps, entradas
inválidas, persistencia desde una sesión independiente, rollback y caída de DB.
No había linter configurado en el repositorio.

Solo pruebas unitarias, sin PostgreSQL:

```powershell
.venv/Scripts/python.exe -m pytest tests/test_pricing.py tests/test_quote_pricing.py tests/test_config.py -q
```

## Cinco partes para estudiar

1. `schemas/quote.py`: cómo los tipos y límites rechazan entradas antes del servicio.
2. `services/pricing.py` y `pricing.py`: por qué Decimal, dónde se redondea y cómo se
   separan tarifa, área y extras.
3. `services/quote_service.py`: qué garantizan begin, flush, commit y rollback.
4. `db/models.py`: claves foráneas, relaciones Python y restricciones SQL.
5. `main.py` y `db/database.py`: engine compartido, sesión por solicitud y lifespan;
   sigue también cómo `tests/conftest.py` conecta ese flujo con PostgreSQL aislado.

Referencias oficiales: [transacciones SQLAlchemy](https://docs.sqlalchemy.org/en/20/orm/session_transaction.html)
y [tests del lifespan de FastAPI](https://fastapi.tiangolo.com/advanced/testing-events/).

## Validación de esta entrega

- `docker compose up --build -d`: imagen construida y ambos servicios saludables.
- `docker compose run --rm api python -m pytest -q -p no:cacheprovider`: 49 pruebas
  aprobadas contra PostgreSQL real, incluidas las diez originales.
- `.venv/Scripts/python.exe -m pytest -q`: las mismas 49 pruebas aprobadas desde
  Windows (229.65 s; dentro de Docker, 2.05 s en esta ejecución).
- `/health` comprobado por HTTP desde Windows; Uvicorn también arrancó localmente.
- `pip check`, compilación de módulos y `git diff --check`: sin errores.
- Dos avisos de deprecación vienen de Starlette/TestClient y AnyIO; no son fallos
  de la aplicación. No se ocultaron.

Para iniciar Docker en esta máquina fue necesario apartar carpetas de sockets
temporales averiados, conservándolas en `%LOCALAPPDATA%/Docker/run.turfdepot-backup*`
y `%LOCALAPPDATA%/docker-secrets-engine.turfdepot-backup*`. No se borraron volúmenes,
imágenes ni configuración. La aplicación queda con catálogo vacío hasta que
proporciones tarifas reales; el precio 300 se utiliza exclusivamente en pruebas.
