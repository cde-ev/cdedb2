#!/usr/bin/env python3

"""This provides config objects for the CdEDB, that is: default values and
a way to override them. Any hardcoded values should be found in
here. An exception are the default queries, which are defined in `query_defaults.py`.

Each config object takes into account the default values found in here. They can
be overwritten with values in an additional config file, where the path to this
file has to be present as environment variable CDEDB_CONFIGPATH.
"""

import abc
import collections
import contextlib
import importlib.util
import logging
import os
import pathlib
from collections.abc import Iterator, Mapping, MutableMapping
from typing import Any, ClassVar, Self

from cdedb.config.defaults import DEFAULT_LOG_LEVEL  # noqa: F401

PathLike = pathlib.Path | str


# The default path were a configuration file is expected. It is easier to hardcode this
# at some places where the configpath environment variable is unfeasible (like in
# wsgi.py, the entry point of apache2). This reflects also the configpath were the
# autobuild, docker-compose and production expect the config per default.
DEFAULT_CONFIGPATH = pathlib.Path("/etc/cdedb/config.py")

_LOGGER = logging.getLogger(__name__)
_ROOT_LOGGER = logging.getLogger()


_DEFAULTS = vars(importlib.import_module("cdedb.config.defaults"))
_SECRECTS_DEFAULTS = vars(importlib.import_module("cdedb.config.default_secrets"))


def set_log_level(level: int) -> None:
    _ROOT_LOGGER.setLevel(level)
    for handler in _ROOT_LOGGER.handlers:
        handler.setLevel(level)


def _import_from_file(path: PathLike | None) -> MutableMapping[str, Any]:
    """Import all variables from the given file and return them as dict."""
    if path is None:
        _LOGGER.warning("No file path provided")
        return {}
    path = pathlib.Path(path)
    if not path.is_file():
        _LOGGER.warning(f"Config file {path.as_posix()!r} does not exist.")
        return {}
    if not path.read_text(encoding="utf-8"):
        _LOGGER.warning(f"Config file {path.as_posix()!r} is empty.")
        return {}
    spec = importlib.util.spec_from_file_location("override", str(path))
    if not spec or not spec.loader:
        raise ImportError(spec, spec.loader if spec else None)  # pragma: no cover
    override = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(override)
    return {key: getattr(override, key) for key in dir(override)}


class NewBaseConfig(Mapping[str, Any], abc.ABC):
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


class NewConfig(NewBaseConfig):
    _defaults = _DEFAULTS

    # Config file with persistent adjustments to those overrides.
    _temp_config_path: pathlib.Path | None
    _temp_config_key = "TEMP_CONFIG_PATH"
    # Ephemeral config overrides provided via context manager.
    _context_manager_overrides: dict[str, Any]

    def _init_once(self) -> None:
        self._local_config_path = self.read_configpath()
        self._temp_config_path = None
        self._context_manager_overrides = {}
        super()._init_once()

    @classmethod
    def read_configpath(cls) -> pathlib.Path:
        """Helper to get the config path from the environment."""
        if path := os.environ.get("CDEDB_CONFIGPATH"):
            return pathlib.Path(path)
        return DEFAULT_CONFIGPATH

    @classmethod
    def get_configpath(cls) -> pathlib.Path:
        return cls()._local_config_path

    @classmethod
    def set_config_path(cls, local_config_path: PathLike) -> None:
        cls()._local_config_path = pathlib.Path(local_config_path)
        cls().reload()

    def reload(self, recurse: bool = True) -> None:
        local_config = self._filter_overrides(
            _import_from_file(self._local_config_path)
        )

        # Temporarily create a configchain without the temp config in order to figure
        #  out where to locate the temp config.
        _fake_config_chain = collections.ChainMap(
            self._filter_overrides(self._context_manager_overrides),
            local_config,
            self._defaults,
        )

        temp_config = {}
        _temp_config_path = _fake_config_chain[self._temp_config_key]
        if _temp_config_path is not None:
            self._temp_config_path = pathlib.Path(_temp_config_path)
            temp_config = self._filter_overrides(
                _import_from_file(self._temp_config_path)
            )
            if self._temp_config_key in temp_config:
                if temp_config[self._temp_config_key] != self._temp_config_path:
                    raise RuntimeError(
                        f'May not set differing "{self._temp_config_key}" in temp config.'
                    )

        self._configchain = collections.ChainMap(
            self._filter_overrides(self._context_manager_overrides),
            temp_config,
            local_config,
            self._defaults,
        )

        if recurse:
            NewSecretsConfig().reload()
            set_log_level(self._configchain["LOG_LEVEL"])

    @contextlib.contextmanager
    def with_overrides(
        self,
        *,
        local_config_path: PathLike | None = None,
        **kwargs: Any,
    ) -> Iterator[None]:
        """Allow temporarily overriding config values via context manager."""

        _LOGGER.debug(
            f"Starting config override with {local_config_path=} and {kwargs=}."
        )
        _real_local_config_path = self._local_config_path
        _real_context_manager_overrides = self._context_manager_overrides

        if local_config_path:
            self._local_config_path = pathlib.Path(local_config_path)
        if kwargs:
            # Do not filter the kwargs here, so the NewSecretsConfig can use them too.
            self._context_manager_overrides = kwargs

        self.reload()

        _LOGGER.debug(repr(self))

        yield

        _LOGGER.debug(
            f"Resetting after config override to {_real_local_config_path=} and {_real_context_manager_overrides=}."
        )

        self._local_config_path = _real_local_config_path
        self._context_manager_overrides = _real_context_manager_overrides

        self.reload()

        _LOGGER.debug(repr(self))

    # The repr is only relevant for debugging.
    def __repr__(self) -> str:  # pragma: no cover
        name = self.__class__.__qualname__
        return f"{name}(cm={self._configchain.maps[0]!r} temp={self._configchain.maps[1]!r} local={self._configchain.maps[2]!r})"


class NewSecretsConfig(NewBaseConfig):
    _defaults = _SECRECTS_DEFAULTS
    _local_config_key = "SECRETS_CONFIGPATH"

    def _init_once(self) -> None:
        self._config = NewConfig()

    def reload(self, recurse: bool = True) -> None:
        local_config = self._filter_overrides(
            _import_from_file(self._config[self._local_config_key])
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


Config = NewConfig
TestConfig = NewConfig
SecretsConfig = NewSecretsConfig

get_configpath = NewConfig.get_configpath
set_configpath = NewConfig.set_config_path
