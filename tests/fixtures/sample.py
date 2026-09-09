"""Carrel sample source fixture — indexed as FileType.CODE.

Source files carry no signature, so detection is by extension alone. The
sentinel phrase for source-search tests is: cartulary shelfmark.
"""

SHELF_CAPACITY = 42


def catalogue(title: str, shelf: int = 1) -> dict[str, object]:
    """Return a catalogue record for one item on the desk."""
    return {"title": title, "shelf": shelf, "sentinel": "cartulary shelfmark"}


class ReadingRoom:
    """A room with a finite number of shelves."""

    def __init__(self, shelves: int = SHELF_CAPACITY) -> None:
        self.shelves = shelves

    def is_full(self, used: int) -> bool:
        return used >= self.shelves
