"""FretCase card module: layout, offline stylisation and thermal printing.

Interface (see docs/milestone-1.md, "Card module"):

    CardInput, CardImages, Style, render_card(card) -> CardImages, Printer, PrinterError
"""

from .printer import Printer, PrinterError
from .render import CardImages, CardInput, Style, render_card

__all__ = ["CardImages", "CardInput", "Printer", "PrinterError", "Style", "render_card"]
__version__ = "0.1.0"
