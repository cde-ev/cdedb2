import functools
import pathlib
from typing import Any, Callable


def is_docker():
    return pathlib.Path("/CONTAINER").is_file()


def is_vm():
    return not is_docker()


def sanity_check(fun) -> Callable[..., None]:
    """Decorator for invasive actions which are forbidden on protected instances."""

    @functools.wraps(fun)
    def new_fun(*args: Any, **kwargs: Any) -> None:
        if pathlib.Path("/PRODUCTIONVM").is_file():
            raise RuntimeError("Refusing to touch live instance!")
        if pathlib.Path("/OFFLINEVM").is_file():
            raise RuntimeError("Refusing to touch orga instance!")
        return fun(*args, **kwargs)

    return new_fun
