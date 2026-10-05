# Prueba con WhatsApp oficial de Meta

La integración está deshabilitada por defecto. Primero configura el número de
prueba; no hace falta migrar el número del negocio en esta etapa.

## 1. Crear la app y el número de prueba

Abre https://developers.facebook.com/apps/ con tu cuenta de Meta. Regístrate
como desarrollador si el portal lo solicita. Crea una app para conectar con
clientes mediante WhatsApp y sigue el asistente del producto WhatsApp. Los nombres
de menús pueden variar según el panel de Meta.

En la configuración/API setup de WhatsApp, obtén el número de prueba y añade
tu teléfono como destinatario de prueba, completando su verificación. Ejecuta
el mensaje de prueba que ofrece Meta para confirmar que tu teléfono lo recibe.
El asistente puede solicitar asociar o crear un portfolio empresarial.

## 2. Configurar secretos localmente

Edita `.env` local, nunca `.env.example`. No publiques ni pegues los tokens en
chat, capturas, GitHub o comandos que queden en el historial.

| Variable | Valor |
| --- | --- |
| WHATSAPP_ENABLED | true, cuando todos los valores siguientes estén completos |
| WHATSAPP_PHONE_NUMBER_ID | ID del número de prueba, no el teléfono ni el WABA ID |
| WHATSAPP_API_VERSION | Versión Graph soportada que aparece en el ejemplo del panel de Meta |
| WHATSAPP_ACCESS_TOKEN | Token de acceso del panel de WhatsApp para esta prueba |
| WHATSAPP_APP_SECRET | App secret en la configuración básica de la app |
| WHATSAPP_VERIFY_TOKEN | Cadena aleatoria que defines tú; también se configura en el webhook de Meta |
| INTERNAL_API_KEY | Otra cadena aleatoria, distinta; protege las rutas internas al activar WhatsApp |

El token temporal sirve para pruebas; revisa su caducidad en Meta. Antes de
producción, configura un token apropiado de usuario de sistema y su rotación.
El verify token y el app secret son valores diferentes. Para generar los dos
valores aleatorios, ejecuta localmente `python -c "import secrets; print(secrets.token_urlsafe(32))"`
una vez por valor y cópialos directamente a `.env`.

Calibri debe estar disponible en `src/turfdepot/assets/fonts/` como hasta ahora.
No uses las fuentes de CI para el PDF real.

## 3. Iniciar API y worker

```powershell
docker compose --profile whatsapp up --build -d
docker compose ps
```

El worker toma trabajos guardados en PostgreSQL. La API confirma inmediatamente
la recepción después de guardarlos; generar el PDF o enviar mensajes no demora
el webhook. No se usan Redis, Celery ni otro servicio de almacenamiento.

## 4. Configurar una URL HTTPS pública

Meta necesita alcanzar el webhook por HTTPS; `localhost` no es suficiente.
Para la prueba, utiliza un túnel temporal hacia el puerto 8000, por ejemplo
`ngrok http 8000` si ngrok ya está instalado y configurado. Este proyecto no
instala, configura ni abre el túnel automáticamente.

Registra en la configuración de webhooks de WhatsApp:

- Callback URL: `https://TU-HOST/webhooks/whatsapp` (sin barra final).
- Verify token: el valor de `WHATSAPP_VERIFY_TOKEN` de tu `.env`.
- Suscripción al campo `messages` de la cuenta WhatsApp Business.

Meta hará una petición GET para verificar el endpoint. Los POST siguientes deben
tener `X-Hub-Signature-256` calculada con el app secret; no se aceptan POST sin
firma. Solo se procesan eventos del `WHATSAPP_PHONE_NUMBER_ID` configurado.

Al habilitar WhatsApp, `/quotes`, `/conversations`, `/docs` y `/openapi.json`
requieren `Authorization: Bearer <INTERNAL_API_KEY>`. `/health` y el webhook
son accesibles sin esa clave; el webhook valida su propio token/firma.
Los PDFs se suben a Meta por `/media` y se envían por ID como documentos; no se
publican enlaces anónimos a las cotizaciones.

## 5. Hacer la prueba completa

Desde el teléfono de destinatario verificado, escribe al número de prueba:
`hola`, `Santiago Rodriguez`, `30 x 22`, `sí`, `Corregidora`, esperando la
respuesta del bot antes de cada mensaje. Debes recibir el PDF con 660 m² y
la ubicación. Esta prueba guarda un cliente y consume un folio real.

Se completó esta prueba contra Meta con el número de prueba, credenciales locales
y un túnel HTTPS: el cliente confirmó la recepción del PDF. Al configurar otro
entorno deben repetirse estos pasos. Las pruebas automatizadas simulan las
respuestas HTTP, sin enviar mensajes reales.

## Operación y límites de esta etapa

Un mensaje entrante se guarda una sola vez por su ID de Meta. Un worker procesa
los trabajos en orden de recepción; si se ejecutan varios, un bloqueo PostgreSQL
deja solo uno activo. El orden de eventos atrasados de Meta no se reconstruye.
La respuesta calculada se guarda antes de enviar, permitiendo reintentar fallos
sin avanzar otra vez la conversación ni crear otra cotización.

En la prueba se observó que Meta entrega algunos números mexicanos como `521`
pero los autoriza para envío como `52`. Solo ante un rechazo explícito 131030 de
un número `521` de 13 dígitos, el cliente prueba una vez el mismo destinatario
sin ese `1`. La identidad guardada de la conversación no cambia. No aplica ante
timeouts, errores de servidor ni otros rechazos. Los errores guardan únicamente
el estado HTTP y los códigos numéricos, sin cuerpos con datos privados.

`done` significa que Meta aceptó la petición, no que el cliente leyó o recibió
el mensaje. Los eventos de estado se confirman pero todavía no se guardan.
Audios, imágenes y textos vacíos o mayores a 1.000 caracteres reciben una
petición de texto y no avanzan el formulario. No hay transcripción automática.

Solo se responde a mensajes recientes: se dejan expirar trabajos de más de
23 horas y 50 minutos como margen antes de la ventana de atención de 24 horas.
No se implementan plantillas para seguimiento fuera de esa ventana.

Si falla el procesamiento, la subida de media o Meta rechaza expresamente el
envío, el trabajo queda `failed` y espera revisión. No se reintenta en bucle.
Si hay timeout, un error 5xx durante el envío o un reinicio después de iniciarlo,
queda `uncertain`: no es posible saber automáticamente si Meta aceptó el mensaje.
Los siguientes trabajos de ese contacto esperan; otros contactos continúan.

Consulta IDs y estados, sin imprimir tokens o datos del cliente:

```powershell
docker compose --profile whatsapp run --rm whatsapp-worker python -m turfdepot.whatsapp_worker --list
```

Después de corregir un error (por ejemplo, token vencido o fuentes ausentes),
reintenta un trabajo `failed`, reemplazando `123` por su ID:

```powershell
docker compose --profile whatsapp run --rm whatsapp-worker python -m turfdepot.whatsapp_worker --retry 123
```

Un trabajo `uncertain` requiere comprobar manualmente qué ocurrió. Después de
resolver la entrega con el cliente, `--resolve 123` lo marca resuelto y desbloquea
el contacto; **no envía ni reenvía ningún mensaje**. No hay garantía de entrega
exactamente una vez entre PostgreSQL y un servicio externo.

El formulario sigue admitiendo una cotización por contacto. Después de enviar el
PDF, el bot deja de responder a ese contacto y el negocio continúa manualmente la
conversación. El silencio se conserva al reiniciar el servicio. La asignación de
asesores, el seguimiento comercial y nuevas cotizaciones son etapas posteriores.

## Fuentes oficiales

- Cloud API y configuración de activos/tokens, colección mantenida por Meta:
  https://www.postman.com/meta/whatsapp-business-platform/documentation/wlk6lh4/whatsapp-cloud-api
- Media y mensajes:
  https://www.postman.com/meta/whatsapp-business-platform/folder/13382743-ecb27be5-4d27-4763-bbee-6a8002c04bf3
  https://www.postman.com/meta/whatsapp-business-platform/folder/13382743-ba8d099d-007e-4b52-b9f2-3cf3c60e4fbc
- HTTPS público y recepción de webhooks (documentación del SDK oficial archivado;
  el proyecto no usa ese SDK): https://whatsapp.github.io/WhatsApp-Nodejs-SDK/receivingMessages/
