"""Append-only store for ``/btw`` aside prompts and responses."""

from threading import Lock
from typing import Iterator, List


class Aside(dict):
    """A single aside prompt and its response, usable as a mapping."""

    def __init__(self, prompt: str, response: str):
        super().__init__(prompt=prompt, response=response)

    @property
    def prompt(self) -> str:
        return self["prompt"]

    @property
    def response(self) -> str:
        return self["response"]


class Asides:
    """Thread-safe, append-only list of aside exchanges."""

    _instance = None
    _instance_lock = Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._items: List[Aside] = []
                    instance._items_lock = Lock()
                    cls._instance = instance

        return cls._instance

    @classmethod
    def get_instance(cls) -> "Asides":
        """Return the process-wide aside store."""
        return cls()

    def add(self, prompt: str, response: str) -> Aside:
        """Append an exchange and return it."""
        aside = Aside(prompt=prompt, response=response)

        with self._items_lock:
            self._items.append(aside)

        return aside

    def items(self) -> List[Aside]:
        """Return a snapshot of every stored exchange."""
        with self._items_lock:
            return list(self._items)

    def get(self, index: int) -> Aside | None:
        """Return the exchange at *index*, or None when out of range."""
        with self._items_lock:
            if -len(self._items) <= index < len(self._items):
                return self._items[index]

        return None

    def __len__(self) -> int:
        with self._items_lock:
            return len(self._items)

    def __iter__(self) -> Iterator[Aside]:
        return iter(self.items())


_asides = Asides()


def add_aside(prompt: str, response: str) -> Aside:
    """Append a prompt/response pair to the shared aside store."""
    return _asides.add(prompt, response)


def get_asides() -> List[Aside]:
    """Return a snapshot of every stored aside exchange."""
    return _asides.items()


def get_aside(index: int) -> Aside | None:
    """Return the aside exchange at *index*, or None when out of range."""
    return _asides.get(index)
