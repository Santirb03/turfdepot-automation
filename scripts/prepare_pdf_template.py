"""Build a sanitized background from the business-owned reference PDF."""
import argparse
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.generic import ContentStream, NameObject


def prepare_template(source: Path, destination: Path) -> None:
    reader = PdfReader(source)
    if len(reader.pages) != 3:
        raise ValueError("Expected the three-page Cotizacion 10162 layout")
    writer = PdfWriter()
    for index, page in enumerate(reader.pages):
        stream = ContentStream(page.get_contents(), reader)
        position = (0.0, 0.0)
        operations = []
        for operands, operator in stream.operations:
            if operator == b"Tm":
                position = (float(operands[4]), float(operands[5]))
            x, y = position
            if index < 2:
                remove = (
                    (abs(x - 163.36) < 1 and any(abs(y - value) < 1 for value in (97.6, 111.84, 144.16)))
                    or (550 < x < 730 and abs(y - 97.6) < 1)
                    or (600 < x < 730 and abs(y - 144.16) < 1)
                    or (530 <= x <= 730 and 200 < y < 790)
                    or abs(y - 190.24) < 1
                )
            else:
                remove = 490 <= x <= 730 and 390 < y < 455
            if remove and operator in (b"Tj", b"TJ", b"'", b'"'):
                continue
            operations.append((operands, operator))
        stream.operations = operations
        page[NameObject("/Contents")] = stream
        writer.add_page(page)
    writer.add_metadata({"/Title": "TurfDepot - plantilla de cotizacion", "/Author": "TurfDepot"})
    destination.parent.mkdir(parents=True, exist_ok=True)
    writer.write(destination)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    arguments = parser.parse_args()
    prepare_template(arguments.source, arguments.destination)
