from turfdepot.models import GrassProduct, QuoteItem


DEFAULT_VAT_RATE = 0.16


def calculate_subtotal(
    square_meters: float,
    price_per_m2: float,
) -> float:
    if square_meters <= 0:
        raise ValueError("Los metros cuadrados deben ser mayores que cero.")

    if price_per_m2 < 0:
        raise ValueError("El precio por metro cuadrado no puede ser negativo.")

    return round(square_meters * price_per_m2, 2)


def calculate_vat(
    subtotal: float,
    vat_rate: float = DEFAULT_VAT_RATE,
) -> float:
    if subtotal < 0:
        raise ValueError("El subtotal no puede ser negativo.")

    if not 0 <= vat_rate <= 1:
        raise ValueError("La tasa de IVA debe estar entre 0 y 1.")

    return round(subtotal * vat_rate, 2)


def calculate_total(
    subtotal: float,
    vat: float,
) -> float:
    if subtotal < 0:
        raise ValueError("El subtotal no puede ser negativo.")

    if vat < 0:
        raise ValueError("El IVA no puede ser negativo.")

    return round(subtotal + vat, 2)


def create_quote_item(
    product: GrassProduct,
    square_meters: float,
    vat_rate: float = DEFAULT_VAT_RATE,
) -> QuoteItem:
    subtotal = calculate_subtotal(
        square_meters=square_meters,
        price_per_m2=product.price_per_m2,
    )

    vat = calculate_vat(
        subtotal=subtotal,
        vat_rate=vat_rate,
    )

    total = calculate_total(
        subtotal=subtotal,
        vat=vat,
    )

    return QuoteItem(
        product=product,
        square_meters=square_meters,
        subtotal=subtotal,
        vat=vat,
        total=total,
    )