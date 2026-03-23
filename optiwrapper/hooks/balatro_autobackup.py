import asyncio
import getpass
import os
import socket
from pathlib import Path

from optiwrapper.hooks import WrapperHook
from optiwrapper.lib import clean_ld_preload


class Hook(WrapperHook):
    """Starts and stops a terminal running my Balatro autobackup script."""

    def __init__(self) -> None:
        # pylint doesn't like asyncio.subprocess.Process
        self.process: "asyncio.subprocess.Process | None" = None  # noqa: UP037

    async def on_start(self) -> None:
        env = {**os.environ, **clean_ld_preload(is_64_bit=True)}
        self.process = await asyncio.create_subprocess_exec(
            "terminator",
            "--title",
            f"{getpass.getuser()}@{socket.gethostname()}: ~/Games/Balatro/autobackup.lua",
            "--execute",
            "bash",
            "-c",
            "while true; do echo 'starting autobackup.lua'; ./autobackup.lua; done",
            cwd=Path.home() / "Games/Balatro",
            env=env,
        )

    async def on_stop(self) -> None:
        if self.process is not None:
            if self.process.returncode is None:
                # process is still running
                self.process.terminate()
            await self.process.wait()
            self.process = None
