#!/usr/bin/env python3

"""This provides config objects for the CdEDB, that is: default values and
a way to override them. Any hardcoded values should be found in
here. An exception are the default queries, which are defined in `query_defaults.py`.

Each config object takes into account the default values found in 'defaults.py'.
They can be overwritten with values in additional config files, whose paths are given
via the environment variable 'CDEDB_CONFIGPATHS'. By default an override config is read
from '/etc/cdedb/config.py'.
"""

import abc
import collections
import contextlib
import functools
import importlib.util
import logging
import os
import pathlib
from collections.abc import Iterator, Mapping, MutableMapping, Sequence
from types import ModuleType
from typing import Any, ClassVar, Final, Self

PathLike = pathlib.Path | str

_LOGGER = logging.getLogger(__name__)
_ROOT_LOGGER = logging.getLogger()


def set_log_level(level: int) -> None:
    _ROOT_LOGGER.setLevel(level)
    for handler in _ROOT_LOGGER.handlers:
        handler.setLevel(level)


def _import_from_file(path: PathLike | None) -> dict[str, Any]:
    """Import all variables from the given file and return them as dict."""
    if path is None:
        _LOGGER.warning("No file path provided")
        return {}
    path = pathlib.Path(path)
    if not path.is_file():
        _LOGGER.warning(f"Config file {path.as_posix()!r} does not exist.")
        return {}
    if not path.read_text(encoding="utf-8"):
        # _LOGGER.info(f"Config file {path.as_posix()!r} is empty.")
        return {}
    return _import_from_file_inner(str(path))


@functools.cache
def _import_from_file_inner(path_str: str) -> dict[str, Any]:
    spec = importlib.util.spec_from_file_location("override", path_str)
    if not spec or not spec.loader:
        raise ImportError(spec, spec.loader if spec else None)  # pragma: no cover
    override = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(override)
    return dict_from_module(override)


def dict_from_module(module: ModuleType) -> dict[str, Any]:
    return {key: getattr(module, key) for key in dir(module) if not key.startswith("_")}


_DEFAULTS = dict_from_module(importlib.import_module("cdedb.config.defaults"))
_SECRECTS_DEFAULTS = dict_from_module(
    importlib.import_module("cdedb.config.default_secrets")
)


class BaseConfig(Mapping[str, Any], abc.ABC):
    _instance: ClassVar[Self | None] = None
    _defaults: ClassVar[Mapping[str, Any]]

    _configchain: collections.ChainMap[str, Any]

    # Config file with specific overrides for the current machine.
    _local_config_path: pathlib.Path

    # Make this class a singleton.
    def __new__(cls) -> Self:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init_once()

        return cls._instance

    def _init_once(self) -> None:
        # Do not touch the configpath, etc. in '__init__', otherwise every
        #  'Config()' call will reset this.
        # Also do not reload in '__init__' to avoid recursion errors when setting up
        #  the 'SecretsConfig'
        self.reload()

    @abc.abstractmethod
    def reload(self, recurse: bool = True) -> None: ...

    def _filter_overrides(self, overrides: Mapping[str, Any]) -> dict[str, Any]:
        """Only allow override keys that are also in the defaults."""
        return {key: value for key, value in overrides.items() if key in self._defaults}

    # Delegate item acces to the configchain.
    def __getitem__(self, key: str) -> Any:
        self.reload(recurse=False)
        return self._configchain.__getitem__(key)

    # The following dunder methods are required to to inheriting from `Mapping`,
    #  even though we never actually use them.
    def __iter__(self) -> Iterator[str]:  # pragma: no cover
        return self._configchain.__iter__()

    def __len__(self) -> int:  # pragma: no cover
        return self._configchain.__len__()


class Config(BaseConfig):
    _defaults = _DEFAULTS
    _config_paths_env_name = "CDEDB_CONFIGPATHS"
    _default_config_paths: Final = [pathlib.Path("/etc/cdedb/config.py")]

    # List of paths to read config overrides from.
    _config_paths: list[pathlib.Path]
    # Ephemeral config overrides provided via context manager.
    _context_manager_overrides: MutableMapping[str, Any]
    # Final constructed configs.
    _configs: dict[str, dict[str, Any]]
    _config_chain: collections.ChainMap[str, Any]

    def _init_once(self) -> None:
        self._config_paths = self.read_configpaths()
        self._context_manager_overrides = {}
        super()._init_once()

    @staticmethod
    def parse_paths(paths: Sequence[PathLike | None]) -> list[pathlib.Path]:
        return [pathlib.Path(path).resolve() for path in paths if path]

    @classmethod
    def read_configpaths(cls) -> list[pathlib.Path]:
        """Helper to get the config path from the environment."""
        if cls._config_paths_env_name in os.environ:
            return cls.parse_paths(os.environ[cls._config_paths_env_name].split(":"))
        return cls._default_config_paths

    @classmethod
    def get_config_env(cls) -> dict[str, str]:
        return {cls._config_paths_env_name: ":".join(map(str, cls.get_config_paths()))}

    @classmethod
    def get_config_paths(cls) -> list[pathlib.Path]:
        return cls()._config_paths

    @classmethod
    def set_config_paths(cls, *paths: PathLike) -> None:
        cls()._config_paths = cls.parse_paths(paths)
        cls().reload()

    @classmethod
    def clear_config_cache(cls) -> None:
        _import_from_file_inner.cache_clear()
        cls().reload()

    def reload(self, recurse: bool = True) -> None:
        self._configs = {
            "cm": self._filter_overrides(self._context_manager_overrides),
            **{
                f"_{path}": self._filter_overrides(_import_from_file(path))
                for path in self._config_paths
            },
        }

        self._configchain = collections.ChainMap(
            *self._configs.values(),
            self._defaults,
        )

        if recurse:
            SecretsConfig().reload()
            set_log_level(self._configchain["LOG_LEVEL"])

    @contextlib.contextmanager
    def with_overrides(
        self,
        *,
        config_paths: Sequence[PathLike | None] | None = None,
        **kwargs: Any,
    ) -> Iterator[None]:
        """Allow temporarily overriding config values via context manager."""

        _LOGGER.debug(f"Starting config override with {config_paths=} and {kwargs=}.")
        real_config_paths = self._config_paths
        real_context_manager_overrides = self._context_manager_overrides

        if config_paths is not None:
            self._config_paths = self.parse_paths(config_paths)
        # Do not filter the kwargs here, so the NewSecretsConfig can use them too.
        self._context_manager_overrides = collections.ChainMap(
            kwargs, real_context_manager_overrides
        )

        self.reload()

        _LOGGER.debug(repr(self))

        try:
            yield

        finally:
            _LOGGER.debug(
                f"Resetting after config override to {real_config_paths=} and {real_context_manager_overrides=}."
            )

            self._config_paths = real_config_paths
            self._context_manager_overrides = real_context_manager_overrides

            self.reload()

            _LOGGER.debug(repr(self))

    # The repr is only relevant for debugging.
    def __repr__(self) -> str:  # pragma: no cover
        name = self.__class__.__qualname__
        configs = [
            (repr(k[1:]) if k.startswith("_") else k) + "=" + repr(v)
            for k, v in self._configs.items()
        ]
        return f"{name}({' '.join(configs)})"


class SecretsConfig(BaseConfig):
    _defaults = _SECRECTS_DEFAULTS
    _config_path_key = "SECRETS_CONFIGPATH"

    def _init_once(self) -> None:
        self._config = Config()

    def reload(self, recurse: bool = True) -> None:
        local_config = self._filter_overrides(
            _import_from_file(self._config[self._config_path_key])
        )

        # for security reasons, do not use the _SECRETS_DEFAULT in production
        if pathlib.Path("/PRODUCTIONVM").is_file():
            defaults = {}
        else:
            defaults = self._defaults

        self._configchain = collections.ChainMap(
            self._filter_overrides(self._config._context_manager_overrides),
            local_config,
            defaults,
        )

    # The repr is only relevant for debugging.
    def __repr__(self) -> str:  # pragma: no cover
        name = self.__class__.__qualname__
        local_config = {k: '***' for k in self._configchain.maps[1]}
        return f"{name}(cm={self._configchain.maps[0]!r} local={local_config!r})"
