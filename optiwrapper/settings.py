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
    _fields: ClassVar[List[str]] = [
        "use_gpu",
        "fallback",
        "use_primus",
        "vsync",
        "is_64_bit",
    ]

    def __init__(
        self,
        use_gpu: Optional[bool] = None,
        fallback: Optional[bool] = None,
        use_primus: Optional[bool] = None,
        vsync: Optional[bool] = None,
        is_64_bit: Optional[bool] = None,
    ):
        # pylint: disable=too-many-arguments
        self._use_gpu = use_gpu
        self._fallback = fallback
        self._use_primus = use_primus
        self._vsync = vsync
        self._is_64_bit = is_64_bit

    def asdict(self) -> Dict[str, bool]:
        d = {}
        for name in self._fields:
            val = getattr(self, f"_{name}")
            if val is not None:
                d[name] = val
        return d

    def __bool__(self) -> bool:
        return bool(self.asdict())

    @property
    def fields(self) -> List[str]:
        return self._fields

    @property
    def use_gpu(self) -> bool:
        if self._use_gpu is None:
            return False
        return self._use_gpu

    @use_gpu.setter
    def use_gpu(self, value: bool) -> None:
        self._use_gpu = value

    @property
    def fallback(self) -> bool:
        if self._fallback is None:
            return True
        return self._fallback

    @property
    def use_primus(self) -> bool:
        if self._use_primus is None:
            return True
        return self._use_primus

    @property
    def vsync(self) -> bool:
        if self._vsync is None:
            return True
        return self._vsync

    @property
    def is_64_bit(self) -> bool:
        if self._is_64_bit is None:
            return True
        return self._is_64_bit


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
