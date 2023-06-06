"""
Manages loading and storing per-game configuration data.
"""

import dataclasses
import itertools
import os
from dataclasses import dataclass, field
from typing import Any, ClassVar, Dict, List, Optional, Union

import yaml

from .lib import SETTINGS_DIR


class ConfigFlags:
    _defaults: ClassVar[Dict[str, bool]] = {
        "use_gpu": False,
        "fallback": True,
        "use_primus": True,
        "vsync": True,
        "is_64_bit": True,
    }

    def __init__(self, **kwargs: bool):
        self._lookup: Dict[str, bool] = {}
        for key in self._defaults:
            if key in kwargs:
                self._lookup[key] = kwargs.pop(key)
        if kwargs:
            raise TypeError(
                "ConfigFlags.__init__() got an unexpected keyword argument {!r}".format(
                    next(iter(kwargs))
                )
            )

    def asdict(self) -> Dict[str, bool]:
        return self._lookup

    def __bool__(self) -> bool:
        return bool(self._lookup)

    @property
    def fields(self) -> List[str]:
        return list(self._defaults.keys())

    def __getattr__(self, name: str) -> Any:
        # this only gets called if `name` isn't an existing instance attribute
        return self._lookup.get(name, self._defaults[name])

    def __setattr__(self, name: str, value: bool) -> None:
        if name in self._defaults:
            self._lookup[name] = value
        else:
            super().__setattr__(name, value)

    def __delattr__(self, name: str) -> None:
        if name in self._defaults:
            del self._lookup[name]
        else:
            super().__delattr__(name)

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, ConfigFlags):
            return NotImplemented
        return self._lookup == other._lookup

    def __repr__(self) -> str:
        return (
            "ConfigFlags("
            + ",".join(
                f"{k}={self._lookup[k]}" for k in self._defaults if k in self._lookup
            )
            + ")"
        )

    def copy(self) -> "ConfigFlags":
        return ConfigFlags(**self._lookup)


@dataclass
class Config:
    game: str
    command: List[str] = field(default_factory=list)
    flags: ConfigFlags = field(default_factory=ConfigFlags)
    process_name: str = ""
    window_title: str = ""
    window_class: str = ""
    hooks: List[str] = field(default_factory=list)

    @classmethod
    def load(cls, game: str) -> "Config":
        path = SETTINGS_DIR / f"{game}.yaml"
        with open(path) as f:
            data = yaml.safe_load(f)

        if "flags" in data:
            data["flags"] = ConfigFlags(**data["flags"])
        return cls(game, **data)

    def check(self) -> Optional[str]:
        """Checks if this configuration is valid.

        Returns None if it is valid, or an error message if not.
        """
        # a command is required
        if not self.command:
            return "No command specified"

        # the command must be a valid executable
        program = self.command[0]
        if not os.path.isfile(program):
            if os.sep not in program:
                return f'The file "{program}" specified for command does not exist (it should be a full path).'
            return f'The file "{program}" specified for command does not exist.'
        if not os.access(program, os.X_OK):
            return f'The file "{program}" specified for command is not executable.'

        return None

    def asdict(self) -> Dict[str, Union[str, List[str], ConfigFlags]]:
        """Returns a dict representing this configuration, excluding default values."""
        d: Dict[str, Union[str, List[str], ConfigFlags]] = {}
        for fld in dataclasses.fields(self):
            if fld.name == "game":
                continue
            val = getattr(self, fld.name)
            if not val:
                continue
            if isinstance(val, ConfigFlags):
                val = val.asdict()
            d[fld.name] = val
        return d

    def save(self) -> None:
        path = SETTINGS_DIR / f"{self.game}.yaml"
        with open(path, "w") as f:
            yaml.dump(
                self.asdict(),
                f,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False,
            )

    def copy(self) -> "Config":
        return Config(
            self.game,
            self.command.copy(),
            self.flags.copy(),
            self.process_name,
            self.window_title,
            self.window_class,
            self.hooks.copy(),
        )

    def pretty(self) -> str:
        """Pretty-formats this Config object."""
        out = []
        option_width = (
            max(
                len(fld)
                for fld in itertools.chain(
                    (x.name for x in dataclasses.fields(self)),
                    self.flags.fields,
                )
            )
            + 1
        )

        def fmt(name: str, value: Any) -> str:
            return "{:<{width}s} {}".format(name + ":", value, width=option_width)

        for fld in dataclasses.fields(self):
            val = getattr(self, fld.name)
            if isinstance(val, ConfigFlags):
                for flag_name in self.flags.fields:
                    flag_val = getattr(self.flags, flag_name)
                    out.append(fmt(flag_name, flag_val))
            else:
                out.append(fmt(fld.name, val))
        return "\n".join(out)
