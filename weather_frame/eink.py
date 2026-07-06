"""Spectra-6 conversion used by Weather Frame previews and signatures.

The matching palette and saturation blend mirror Pimoroni's 13.3-inch
``inky_el133uf1`` driver. The final RGB colors approximate the reflective inks
on a monitor; real appearance still varies with panel and ambient light.
"""
from __future__ import annotations

from PIL import Image, ImageChops

# Palette order used by the Inky EL133UF1 driver:
# black, white, yellow, red, blue, green.
DRIVER_DESATURATED_PALETTE = (
    (0, 0, 0),
    (255, 255, 255),
    (255, 255, 0),
    (255, 0, 0),
    (0, 0, 255),
    (0, 255, 0),
)

DRIVER_SATURATED_PALETTE = (
    (0, 0, 0),
    (161, 164, 165),
    (208, 190, 71),
    (156, 72, 75),
    (61, 59, 94),
    (58, 91, 70),
)

# Monitor approximation of the physical Spectra-6 inks, in driver order.
DISPLAY_APPEARANCE_PALETTE = (
    (26, 26, 28),
    (236, 234, 223),
    (198, 176, 74),
    (165, 60, 56),
    (49, 71, 130),
    (58, 110, 72),
)


def driver_matching_palette(saturation: float) -> tuple[tuple[int, int, int], ...]:
    """Return the RGB palette the Inky driver uses to assign source pixels."""
    saturation = float(saturation)
    if not 0 <= saturation <= 1:
        raise ValueError("saturation must be between 0 and 1")
    return tuple(
        tuple(
            int(saturated[channel] * saturation + desaturated[channel] * (1 - saturation))
            for channel in range(3)
        )
        for saturated, desaturated in zip(
            DRIVER_SATURATED_PALETTE, DRIVER_DESATURATED_PALETTE
        )
    )


def _palette_image(colors: tuple[tuple[int, int, int], ...]) -> Image.Image:
    palette = Image.new("P", (1, 1))
    palette.putpalette([channel for color in colors for channel in color])
    return palette


def _blue_hue_weight(value: int) -> int:
    """Weight cyan through indigo hues, with soft boundaries."""
    if 115 <= value <= 195:
        return 255
    if 100 < value < 115:
        return round((value - 100) / 15 * 255)
    if 195 < value < 215:
        return round((215 - value) / 20 * 255)
    return 0


def apply_blue_bias(
    image: Image.Image,
    amount: float = 0.0,
    saturation: float = 0.5,
) -> Image.Image:
    """Pull blue-family pixels toward the driver's blue matching point.

    ``amount`` is deliberately selective: neutral paper, red rocks, yellows,
    and greens remain unchanged. Adjust in 0.05 increments; 1.0 is primarily a
    diagnostic extreme.
    """
    amount = float(amount)
    if not 0 <= amount <= 1:
        raise ValueError("blue_bias must be between 0 and 1")
    rgb = image.convert("RGB")
    if amount == 0:
        return rgb

    hue, colorfulness, _value = rgb.convert("HSV").split()
    hue_mask = hue.point([_blue_hue_weight(value) for value in range(256)])
    color_mask = colorfulness.point(
        [min(255, value * 3) for value in range(256)]
    )
    mask = ImageChops.multiply(hue_mask, color_mask).point(
        [round(value * amount) for value in range(256)]
    )
    blue_point = driver_matching_palette(saturation)[4]
    target = Image.new("RGB", rgb.size, blue_point)
    return Image.composite(target, rgb, mask)


def quantize_spectra6(image: Image.Image, saturation: float = 0.5) -> Image.Image:
    """Dither RGB artwork as the Inky driver would, then show ink-like colors."""
    matching = _palette_image(driver_matching_palette(saturation))
    indexed = image.convert("RGB").quantize(
        palette=matching,
        dither=Image.Dither.FLOYDSTEINBERG,
    )
    indexed.putpalette(
        [channel for color in DISPLAY_APPEARANCE_PALETTE for channel in color]
    )
    return indexed.convert("RGB")
