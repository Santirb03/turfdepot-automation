"""Personalize the original PDF; preserve its photos, logo and page geometry."""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from threading import Lock
from zoneinfo import ZoneInfo

from pypdf import PdfReader, PdfWriter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

from turfdepot.db.models import Quote
from turfdepot.pricing import decimal_subtotal
from turfdepot.services.catalog import MODELS

ASSETS = Path(__file__).resolve().parents[1] / "assets"
FONT_LOCK = Lock()


class PdfUnavailable(ValueError):
    pass


@dataclass(frozen=True)
class PdfQuote:
    number: int
    customer_name: str
    location: str
    square_meters: Decimal
    issued_on: date
    prices: dict[str, str]
    base_price: Decimal


def quote_pdf(quote: Quote) -> bytes:
    if quote.extras_total:
        raise PdfUnavailable("Esta plantilla no admite extras adicionales a la propuesta de base.")
    if quote.garden_type not in {key for key, _, _ in MODELS}:
        raise PdfUnavailable("El modelo seleccionado no corresponde a la plantilla de ocho modelos.")
    if not quote.pdf_prices or len(quote.pdf_prices) != len(MODELS) or quote.base_price_per_m2 is None:
        raise PdfUnavailable("La cotización no tiene guardadas las tarifas de los ocho modelos para PDF.")
    return render_pdf(PdfQuote(
        number=quote.quote_number, customer_name=quote.customer.name,
        location=quote.customer.location, square_meters=quote.square_meters,
        issued_on=quote.created_at.astimezone(ZoneInfo("America/Mexico_City")).date(),
        prices=quote.pdf_prices, base_price=quote.base_price_per_m2,
    ))


def money(amount: Decimal) -> str:
    return format(amount, ",.2f").translate(str.maketrans({",": ".", ".": ","}))


def spanish_date(value: date) -> str:
    days = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
    months = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
              "septiembre", "octubre", "noviembre", "diciembre")
    return f"{days[value.weekday()]} {value.day} de {months[value.month - 1]} de {value.year}"


def register_fonts() -> None:
    with FONT_LOCK:
        for name, filename in (("TurfCalibri", "Calibri.ttf"), ("TurfCalibriBold", "Calibri-Bold.ttf")):
            if name not in pdfmetrics.getRegisteredFontNames():
                path = ASSETS / "fonts" / filename
                if not path.is_file():
                    raise PdfUnavailable(f"Falta la fuente privada {filename} en assets/fonts.")
                pdfmetrics.registerFont(TTFont(name, str(path)))


def draw_text(canvas: Canvas, value: str, x: float, baseline: float,
              width: float, size: float = 8.3841, bold: bool = False,
              align: str = "left") -> None:
    font = "TurfCalibriBold" if bold else "TurfCalibri"
    face = pdfmetrics.getFont(font).face
    if any(ord(character) not in face.charToGlyph for character in value):
        raise PdfUnavailable("El texto contiene caracteres que Calibri no puede representar.")
    measured = pdfmetrics.stringWidth(value, font, size)
    if measured > width:
        size *= width / measured
    if size < 6:
        raise PdfUnavailable("El nombre o ubicación es demasiado largo para el espacio de la plantilla.")
    canvas.setFillColorRGB(0, 0, 0)
    canvas.setFont(font, size)
    y = 792 - baseline
    if align == "right":
        canvas.drawRightString(x + width, y, value)
    elif align == "center":
        canvas.drawCentredString(x + width / 2, y, value)
    else:
        canvas.drawString(x, y, value)


def draw_price_row(canvas: Canvas, top: float, label: str, value: str,
                   bold: bool = False, shaded: bool = False) -> None:
    x, split, right, height = 403.2, 473.76, 544.44, 13.68
    canvas.setFillColorRGB(1, 1, 1)
    canvas.rect(x, 792-top-height, right-x, height, stroke=0, fill=1)
    if shaded:
        canvas.setFillColorRGB(0.647059, 0.647059, 0.647059)
        canvas.rect(split, 792-top-height, right-split, height, stroke=0, fill=1)
    canvas.setStrokeColorRGB(0, 0, 0)
    canvas.setLineWidth(0.6)
    canvas.rect(x, 792-top-height, right-x, height, stroke=1, fill=0)
    canvas.line(split, 792-top, split, 792-top-height)
    draw_text(canvas, label, x+2, top+9.5, split-x-4, size=8.38 if shaded else 6.8)
    draw_text(canvas, "$", split+4, top+10.2, 8, size=10.18 if bold else 8.38, bold=bold)
    draw_text(canvas, value, split+13, top+10.2, right-split-16,
              size=10.18 if bold else 8.38, bold=bold, align="right")


def render_pdf(data: PdfQuote) -> bytes:
    register_fonts()
    if set(data.prices) != {key for key, _, _ in MODELS}:
        raise PdfUnavailable("Se requieren las tarifas de los ocho modelos.")
    reader = PdfReader(ASSETS / "quote-template.pdf")
    writer = PdfWriter(clone_from=reader)
    meters = format(data.square_meters, "f").rstrip("0").rstrip(".") if "." in str(data.square_meters) else str(data.square_meters)
    for index, page in enumerate(writer.pages):
        buffer = BytesIO()
        canvas = Canvas(buffer, pagesize=(612, 792))
        if index < 2:
            draw_text(canvas, data.customer_name, 122.52, 73.2, 190)
            draw_text(canvas, meters, 122.52, 83.88, 190)
            draw_text(canvas, data.location, 122.52, 108.12, 190)
            draw_text(canvas, spanish_date(data.issued_on), 373, 73.2, 170, align="right")
            draw_text(canvas, str(data.number), 403.2, 108.12, 141.24, align="center")
            # Replace the spreadsheet's accidental #¡NOMBRE? header, using the original green strip.
            canvas.setFillColorRGB(1, 1, 1)
            canvas.setFont("TurfCalibriBold", 10.18)
            for label, x in (("IMAGEN", 119), ("DESCRIPCION", 296), ("INVERSION", 475)):
                canvas.drawCentredString(x, 792-142.68, label)
            for row, (key, _, _) in enumerate(MODELS[index*4:(index+1)*4]):
                top = 186.72 + row*109.08
                # Clear the original investment cells and their obsolete IVA/subtotal borders.
                canvas.setFillColorRGB(1, 1, 1)
                canvas.rect(402.8, 792-(top+69.2), 142.2, 83.5, stroke=0, fill=1)
                price = Decimal(data.prices[key])
                total = decimal_subtotal(data.square_meters, price)
                draw_price_row(canvas, top, "PRECIO M2 EN PESOS", money(price), bold=True)
                draw_price_row(canvas, top+54.84, "INVERSION TOTAL", money(total), bold=True, shaded=True)
        else:
            # Same original table geometry; all variable text was removed from the background.
            x, split, right, top, height = 366.6, 436.8, 508.8, 298.2, 13.56
            canvas.setFillColorRGB(1, 1, 1)
            canvas.rect(x-0.5, 792-top-height*3-0.5, right-x+1, height*3+1, stroke=0, fill=1)
            canvas.setStrokeColorRGB(0, 0, 0)
            canvas.setLineWidth(0.6)
            canvas.rect(x, 792-top-height*3, right-x, height*3, stroke=1, fill=0)
            canvas.line(split, 792-top, split, 792-top-height*3)
            rows = (("COSTO UNITARIO", money(data.base_price)), ("METROS CUADRADOS", meters),
                    ("COSTO DE BASE", money(decimal_subtotal(data.square_meters, data.base_price))))
            for row, (label, value) in enumerate(rows):
                row_top = top + row*height
                if row:
                    canvas.line(x, 792-row_top, right, 792-row_top)
                draw_text(canvas, label, x+2, row_top+9.84, split-x-4, size=8.38)
                if row != 1:
                    draw_text(canvas, "$", split+4, row_top+9.84, 8, bold=row==2)
                draw_text(canvas, value, split+13, row_top+9.84, right-split-16,
                          bold=row==2, align="right")
        canvas.save()
        page.merge_page(PdfReader(buffer).pages[0])
    writer.add_metadata({"/Title": f"Cotización {data.number} - TurfDepot", "/Author": "TurfDepot"})
    output = BytesIO()
    writer.write(output)
    return output.getvalue()
