# Plantilla de cotización

`quote-template.pdf` se deriva del PDF Cotizacion 10162 proporcionado por el usuario.
Conserva fotos, logo, tipografía y geometría originales. Se eliminaron físicamente
los valores del cliente anterior y los importes variables del contenido del PDF.
Las fotos de preparación y los términos permanecen como en la referencia.

Las fuentes completas Calibri.ttf y Calibri-Bold.ttf se suministran en `fonts/`
desde la instalación local de Windows. Son archivos privados ignorados por Git.
El despliegue debe aportar estas fuentes con su licencia; Docker las copia si
están presentes. No se sustituyen silenciosamente por otra tipografía.

Tarifas aprobadas: `services/catalog.py`; todos los importes incluyen IVA.
La preparación de base conserva $150/m² finales y se muestra como propuesta
separada, igual que en el documento original. No se suma a los totales de pasto.
