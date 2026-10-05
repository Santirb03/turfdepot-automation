# TurfDepot Sales & Quote Automation Platform

Backend de cotizaciones con FastAPI, SQLAlchemy y PostgreSQL. Incluye PDF
personalizado y numeración comercial desde 11001.

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

El catálogo ahora contiene ocho modelos aprobados a partir de Cotizacion 10162.
En `.env`, `GARDEN_PRICES` es un objeto JSON de tipo de jardín a tarifa final por m²,
con IVA incluido. `.env.example` contiene los ocho modelos; conserva el catálogo
completo para generar el PDF con todas las opciones. Ejemplo de un modelo:

```dotenv
GARDEN_PRICES={"san_mateo_20":"348.00"}
```

Después de cambiarlo ejecuta `docker compose up -d --build`.
Sin catálogo, POST devuelve 503; con un tipo desconocido, devuelve 422.
Las tarifas son finales en MXN: no se les vuelve a añadir IVA. La ubicación es
informativa y no cambia el precio. Se aplican las mismas tarifas para cualquier
área, conforme a la confirmación del usuario. La preparación de base conserva
$150/m² finales y se muestra como propuesta separada en la tercera página,
sin sumarse a los totales de pasto. La API conserva extras del Milestone 1 por
compatibilidad; para el flujo PDF usa `extras=[]`.

## Probar los endpoints

```powershell
Invoke-RestMethod http://localhost:8000/health
$body = @{
    customer_name = 'Juan Perez'
    customer_phone = '4421234567'
    customer_location = 'Juriquilla, Queretaro'
    square_meters = 45
    garden_type = 'san_mateo_20'
    extras = @()
} | ConvertTo-Json -Depth 4
$quote = Invoke-RestMethod http://localhost:8000/quotes -Method Post -ContentType 'application/json' -Body $body
$quote
Invoke-RestMethod "http://localhost:8000/quotes/$($quote.id)"
Invoke-WebRequest "http://localhost:8000/quotes/$($quote.id)/pdf" -OutFile "Cotizacion-$($quote.quote_number).pdf"
```

Con 45 m² de San Mateo 20: subtotal 15660.00, extras 0.00, total 15660.00.
POST devuelve 201 y GET devuelve 200, o 404 si no existe el ID.
Se devuelve `id`, `quote_number`, `customer_id`, `square_meters`, `garden_type`, `subtotal`,
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
    schema.py              # Actualización aditiva para folio y tarifas del PDF
  schemas/quote.py         # Contratos de entrada y salida Pydantic
  services/
    pricing.py             # Catálogo, subtotal, extras y total sin DB
    quote_service.py       # Coordina cálculo y transacción de guardado
    catalog.py             # Ocho modelos y tarifas finales aprobadas
    pdf_service.py         # Personaliza la plantilla con valores guardados
  assets/
    quote-template.pdf     # Diseño original sin los datos del cliente anterior
    fonts/                 # Calibri privada local (ignorada por Git)
tests/
  conftest.py              # PostgreSQL aislado por esquema temporal
  test_pricing.py          # Diez pruebas originales conservadas
  test_quote_pricing.py    # Extras, redondeo, valores inválidos y catálogo
  test_quotes.py           # API, persistencia, rollback y health
  test_config.py           # Validación de configuración
  test_pdf.py              # PDF, cálculos, fotos idénticas y precios históricos
  test_quote_numbers.py    # Folios, concurrencia, reinicios y esquema anterior
scripts/prepare_pdf_template.py # Regenera el fondo desde la referencia original
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
Al iniciar se crean tablas faltantes y se ejecuta una actualización aditiva
específica para folios y tarifas del PDF. No es un sistema general de migraciones;
cambios futuros del esquema requerirán actualizaciones adicionales. La aplicación
permanece sin bot, WhatsApp, AWS ni frontend.

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

## Validación histórica del Milestone 1

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
imágenes ni configuración. En aquella etapa el catálogo estaba vacío; el precio
300 se utiliza exclusivamente en las pruebas originales.

## Etapa PDF: funcionamiento y tarifas aprobadas

| garden_type | Modelo | MXN/m² con IVA incluido |
|---|---|---:|
| san_mateo_20 | San Mateo 20 | 348.00 |
| san_mateo_30 | San Mateo 30 | 382.80 |
| santa_fe_20 | Santa Fe 20 | 382.80 |
| v_lawn_27 | V Lawn 27 | 429.20 |
| san_mateo_40 | San Mateo 40 | 475.60 |
| santa_fe_30 | Santa Fe 30 | 487.20 |
| v_lawn_30 | V Lawn 30 | 475.60 |
| v_lawn_37 | V Lawn 37 | 510.40 |

Base: $150/m² finales. Se conserva como propuesta separada, igual que en la referencia.

`POST /quotes` sigue guardando el modelo seleccionado y su total. Además guarda
el catálogo de los ocho modelos y la tarifa de base para generar las tres páginas.
`GET /quotes/{id}/pdf` recibe el **ID interno**, no el folio comercial, y descarga
`Cotizacion-11001.pdf` (o el folio correspondiente). El PDF muestra todos los modelos.
Sus importes provienen del catálogo guardado en esa cotización: cambiar tarifas
posteriormente no modifica PDFs anteriores.

Los folios se asignan en PostgreSQL desde 11001 con una secuencia y unicidad, incluso
con solicitudes concurrentes. Reiniciar la API no reinicia la secuencia. Puede
haber saltos si una transacción falla: los números consumidos no se reutilizan.
El PDF toma su fecha de `created_at` convertido a America/Mexico_City; descargarlo
otro día no cambia su fecha.

Cotizaciones anteriores sin catálogo histórico, tipos ajenos a los ocho modelos,
o cotizaciones con extras adicionales devuelven 409 al solicitar PDF. No se les
asignan precios actuales por suposición y no se omiten cargos silenciosamente.

El fondo conserva imágenes, logo y geometría originales. Los textos del cliente
anterior se eliminaron físicamente del contenido; no están ocultos bajo rectángulos.
ReportLab añade los datos variables con Calibri. Se mantienen ocho modelos y la
página de base, con precios finales sin renglón de IVA. Se corrigió el encabezado
accidental `#¡NOMBRE?` por `IMAGEN`.

Las fuentes Calibri.ttf y Calibri-Bold.ttf están en `src/turfdepot/assets/fonts/`
como recursos privados locales ignorados por Git. Antes de desplegar en otro
equipo, suministra esas fuentes con su licencia. Docker las copia desde el
directorio de trabajo. Si faltan, el endpoint responde 409 con el archivo requerido.
Textos que no caben se rechazan explícitamente, sin truncarlos.

El PDF se genera en memoria al descargarlo: no se acumulan archivos en PostgreSQL.
`output/pdf/Cotizacion-11001-demo.pdf` es una vista previa con datos de prueba;
no registra clientes ni consume el folio real. `scripts/prepare_pdf_template.py`
permite regenerar el fondo desde el documento original:

```powershell
.venv/Scripts/python.exe scripts/prepare_pdf_template.py 'ruta/al/original.pdf' src/turfdepot/assets/quote-template.pdf
```

Pruebas nuevas: imágenes idénticas a las de la plantilla, ocho modelos y base,
cálculos, datos personalizados, descarga, tarifas históricas, folios concurrentes,
reinicios y actualización del esquema antiguo sin perder sus filas.

Validación de esta etapa: 58 pruebas aprobadas contra PostgreSQL real dentro de
Docker; tres páginas del ejemplo renderizadas y revisadas visualmente. Un aviso
de deprecación de TestClient/httpx permanece en las dependencias de pruebas.
`pip check`, compilación de módulos y `git diff --check` sin errores. Los cambios
se organizan en commits locales con autorización del usuario; el push queda pendiente.

## Conversación del bot (prueba local)

`POST /conversations/messages` recibe un mensaje y devuelve `reply`, `state`,
`quote_id`, `quote_number` y `pdf_url`. Guarda el estado en PostgreSQL. Todavía
no recibe ni envía mensajes de WhatsApp: es el flujo interno que usará la integración.

En http://localhost:8000/docs abre ese endpoint y usa **Try it out**:

```json
{
  "contact_phone": "524421234567",
  "message_id": "ejercicio-1",
  "text": "hola"
}
```

Repite con el mismo `contact_phone`, cambiando `message_id` para cada mensaje:

| message_id | text | Resultado |
| --- | --- | --- |
| ejercicio-1 | hola | Pide nombre |
| ejercicio-2 | Santiago Rodriguez | Pide superficie o medidas |
| ejercicio-3 | es de 30 x 22 | Calcula 660 m² y pide confirmación |
| ejercicio-4 | sí | Pide ubicación |
| ejercicio-5 | Corregidora | Guarda cotización y devuelve enlace al PDF |

Abre `http://localhost:8000` seguido del `pdf_url` devuelto para descargarla.
Esta prueba **sí guarda un cliente y consume un folio**. El PDF del ejercicio
generado directamente en chat no consumió ningún folio de la base de datos.

El teléfono es metadata del contacto, no una pregunta al cliente. Se normaliza
el prefijo `+`. Solo se pide una ubicación y no afecta al precio. Las superficies
directas (por ejemplo `40 m²`) pasan a ubicación; las dimensiones requieren sí/no.
Un `no` permite corregir las medidas. Entradas inválidas conservan el paso actual.

La cotización ofrece los ocho modelos y base opcional con las tarifas guardadas.
Por compatibilidad con el esquema anterior, `garden_type` y `total` guardan la
referencia interna SAN MATEO 20; **no representan una elección del cliente** ni
un total conjunto de las ocho opciones. El documento muestra cada opción separada.

Reenviar el mismo `message_id` y texto devuelve la respuesta original. Reutilizarlo
con otro texto devuelve 409. Un bloqueo por contacto evita duplicados entre workers.
La creación de cotización, el estado final y la respuesta se guardan juntos; si el
catálogo está incompleto o el PDF falla, se revierte y se puede reintentar el mismo
mensaje. PostgreSQL puede dejar huecos en folios de transacciones fallidas.

Al completar, los siguientes mensajes devuelven el enlace existente. Esta etapa
admite una cotización por contacto; todavía no implementa nuevas cotizaciones para
el mismo contacto, correcciones posteriores, extracción libre de varios datos en
un mensaje ni transferencia real a un asesor. El primer mensaje inicia el saludo.
Las tablas `conversations` y `conversation_messages` se crean de forma aditiva al
arrancar. Las respuestas e identificadores se conservan para evitar reprocesamiento.

Verificación: **81 pruebas pasan** en Docker con PostgreSQL, usando esquemas
aislados, incluyendo el flujo completo, descarga del PDF, mensajes concurrentes,
reintentos, validación y compatibilidad con las cotizaciones anteriores.

## GitHub Actions

`.github/workflows/ci.yml` ejecuta las pruebas en cada push a `main`, pull request
destinado a `main`, o ejecución manual desde Actions. Usa Ubuntu 24.04, Python
3.13 y un servicio PostgreSQL 17 efímero con credenciales exclusivas de pruebas.
No necesita secrets, AWS ni acceso a la base de datos del negocio.

Instala las dependencias, ejecuta `pip check` y la suite completa. Las acciones
están fijadas por commit, tienen permisos de lectura y cancelan ejecuciones
anteriores de la misma rama. No realiza despliegues ni envíos por WhatsApp.

CI usa **Carlito solo dentro de pytest**, mediante `--pdf-test-fonts=carlito`.
Sus archivos y licencia SIL OFL están en `tests/assets/carlito`. El código de
producción conserva Calibri y exige que se proporcione al desplegar. CI verifica
datos, imágenes y cálculos del PDF; la fidelidad visual exacta se revisa con
Calibri localmente. Ninguna prueba se omite por la ausencia de fuentes privadas.

Para reproducir la suite de CI localmente:

```powershell
docker compose up -d db
docker compose build api
docker compose run --rm api python -m pip check
docker compose run --rm api python -m pytest -q --pdf-test-fonts=carlito
```

El chequeo aparecerá en GitHub después de subir este workflow. Configurar una
regla que exija ese chequeo para fusionar PRs es un paso separado; este archivo
por sí solo no impide pushes directos a `main`.

## WhatsApp Cloud API (número de prueba)

La integración oficial está preparada pero deshabilitada por defecto.
Consulta [docs/whatsapp-setup.md](docs/whatsapp-setup.md) para crear la app de Meta,
configurar `.env`, iniciar el worker y registrar el webhook HTTPS.

El webhook `GET/POST /webhooks/whatsapp` verifica token/firma y guarda mensajes
en PostgreSQL sin llamar a Meta dentro de la petición. El worker de Compose
(perfil `whatsapp`) procesa la conversación y envía texto o PDF como documento.
Al activarlo se exige una clave interna para acceder al resto de la API.
La prueba automatizada no utiliza credenciales reales ni envía mensajes.

Validación de esta etapa: **101 pruebas pasan** en Docker con PostgreSQL y fuentes
de CI, incluyendo firma y verificación, protección de rutas, mensajes duplicados,
cola persistente, ejercicio completo con PDF, errores de Meta y envíos inciertos.
También se completó una prueba real con el número de prueba de Meta: recepción
de datos del cliente, cálculo y envío automático del PDF por WhatsApp. Las
credenciales y la URL del túnel se configuran por entorno, fuera del repositorio.
