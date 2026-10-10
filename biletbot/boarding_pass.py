from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .messages import baggage_text, duration_text, human_date, price_text, transfer_text


def boarding_pass(search, ticket):
    """Render an informational ticket card; it is not a check-in document."""
    image = Image.new("RGB", (1400, 760), "#1454A3")
    draw = ImageDraw.Draw(image)
    blue = "white"

    def font(size, bold=False):
        path = Path(__file__).parent / "fonts" / "Unbounded.ttf"
        result = ImageFont.truetype(str(path), size)
        result.set_variation_by_axes([700 if bold else 400])
        return result

    def city(x, value):
        size = 68
        while size > 28 and draw.textlength(value, font=font(size, True)) > 580:
            size -= 2
        text(x, 165, value, size, True, 580)

    def text(x, y, value, size=28, bold=False, width=1250):
        f = font(size, bold)
        lines, line = [], ""
        for word in value.split():
            candidate = (line + " " + word).strip()
            if draw.textlength(candidate, font=f) > width and line:
                lines.append(line)
                line = word
            else:
                line = candidate
        lines.append(line)
        for line in lines:
            draw.text((x, y), line, font=f, fill=blue)
            y += size + 12
        return y

    draw.rounded_rectangle((20, 20, 1380, 740), radius=30, outline=blue, width=3)
    text(60, 50, "BILET BOT / АВИАБИЛЕТ", 30, True)
    text(1000, 50, price_text(ticket), 32, True, 330)
    draw.line((60, 115, 1340, 115), fill=blue, width=2)
    text(60, 140, "ОТКУДА", 20)
    text(760, 140, "КУДА", 20)
    city(60, search.origin_name)
    city(760, search.destination_name)
    text(60, 260, search.origin, 26, width=600)
    text(760, 260, search.destination, 26, width=600)
    for x in range(60, 1340, 24):
        draw.line((x, 320, x + 12, 320), fill=blue, width=2)
    dates = human_date(ticket["departure_at"])
    if ticket.get("return_at"):
        dates += " — " + human_date(ticket["return_at"])
    y = text(60, 350, dates, 32, True)
    y = text(60, y + 16, baggage_text(ticket.get("baggage_code")))
    y = text(60, y + 12, "В пути: " + duration_text(ticket))
    text(60, y + 12, transfer_text(ticket), 26)
    draw.line((60, 675, 1340, 675), fill=blue, width=2)
    text(60, 700, "Найдено в @bilet_bot / сайт biletbot.ru", 20, width=1050)
    assets = Path(__file__).parent / "assets"
    for x, name in ((1220, "robot.png"), (1290, "airplane.png")):
        with Image.open(assets / name) as emoji:
            icon = emoji.convert("RGBA").resize((48, 48), Image.Resampling.LANCZOS)
            image.paste(icon, (x, 687), icon)
    output = BytesIO()
    image.save(output, format="PNG")
    output.seek(0)
    output.name = "ticket.png"
    return output
