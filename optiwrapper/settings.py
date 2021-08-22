"""
Manages loading and storing per-game configuration data.
"""

import configparser
import dataclasses
import itertools
import os
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, Dict, List, Literal, Optional, Tuple, TypedDict, Union

import yaml

from .lib import CONFIG_DIR, SETTINGS_DIR, logger


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
        d = dict()
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
            return True
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
        if not path.exists() and (CONFIG_DIR / f"{game}.cfg").exists():
            # try old config
            logger.warning("Loading from old config file")
            return cls.load_legacy(game)
        with open(path) as f:
            data = yaml.safe_load(f)

        if "flags" in data:
            data["flags"] = ConfigFlags(**data["flags"])
        return cls(game, **data)

    @classmethod
    def load_legacy(cls, game: str) -> "Config":
        path = CONFIG_DIR / f"{game}.cfg"
        with open(path) as f:
            config_data = f.read()
        old = parse_config_file(config_data)

        is_64_bit: Optional[bool] = None
        if "is_32_bit" in old:
            is_64_bit = not old["is_32_bit"]
        flags = ConfigFlags(
            use_gpu=old.get("use_gpu", None),
            fallback=old.get("fallback", None),
            use_primus=old.get("use_primus", None),
            vsync=old.get("force_vsync", None),
            is_64_bit=is_64_bit,
        )

        kwargs: Dict[str, Union[str, List[str], ConfigFlags]] = dict()
        if "cmd" in old:
            kwargs["command"] = old["cmd"]
        if "proc_name" in old:
            kwargs["process_name"] = old["proc_name"]
        if "window_title" in old:
            kwargs["window_title"] = old["window_title"]
        if "window_class" in old:
            kwargs["window_class"] = old["window_class"]
        if flags:
            kwargs["flags"] = flags
        if "hooks" in old:
            kwargs["hooks"] = old["hooks"]

        config = cls(game, **kwargs)  # type: ignore
        # save to the new format
        config.save()
        return config

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
        d: Dict[str, Union[str, List[str], ConfigFlags]] = dict()
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


### OLD CONFIG HANDLING BELOW ###


class ConfigDict(TypedDict, total=False):
    cmd: List[str]
    game: str
    use_gpu: bool
    fallback: bool
    use_primus: bool
    force_vsync: bool
    is_32_bit: bool
    proc_name: str
    window_title: str
    window_class: str
    hooks: List[str]


ConfigKeys = Literal[
    "cmd",
    "game",
    "use_gpu",
    "fallback",
    "use_primus",
    "force_vsync",
    "is_32_bit",
    "proc_name",
    "window_title",
    "window_class",
    "hooks",
]


CONFIG_TYPES = ConfigDict.__annotations__  # pylint: disable=no-member


class ConfigException(Exception):
    """
    An error caused by an invalid configuration file.
    """


def parse_config_file(data: str) -> Dict[str, Any]:
    """
    Parses the contents of a configuration file.
    """

    def parse_option(option: str, value: Any) -> Tuple[str, Any]:
        if option.lower() not in CONFIG_TYPES:
            raise ConfigException("Invalid option: {}".format(option))
        dest = option.lower()
        type_ = CONFIG_TYPES[dest]

        if type_ is str:
            vals = shlex.split(value)
            if len(vals) == 1:
                # strip quotes if there's only one string
                return dest, vals[0]
            return dest, value
        if type_ is List[str]:
            if not (value and value[0] == "(" and value[-1] == ")"):
                raise ConfigException(
                    "{} must be an array, surrounded by parens".format(option)
                )
            return dest, shlex.split(value[1:-1])
        if type_ is bool:
            if value not in ("y", "n"):
                raise ConfigException('{} must be "y" or "n"'.format(option))
            return dest, value == "y"
        if type_ is Path:
            return dest, Path(value).expanduser().absolute()
        raise ConfigException("Internal error: argument type not found for " + option)

    config_p = configparser.ConfigParser()
    config_p.optionxform = str  # type: ignore
    config_p.read_string("[section]\n" + data)
    config = dict()
    for opt, val in config_p.items("section"):
        dest, value = parse_option(opt, val)
        config[dest] = value

    return config
