"""Host-process spawner for the no-Docker, no-systemd deployment.

JupyterHub's stock ``LocalProcessSpawner`` calls ``pwd.getpwnam(user.name)``
when building a server's environment and home directory. That assumes one OS
account per Hub user, which the 12-endpoint tmux targets do not have: accounts
like ``student1`` do not exist there, so every spawn fails with ``KeyError``.

``OpenCSLocalSpawner`` keeps LocalProcessSpawner's process model (a single-user
server process, started and stopped by the Hub) but resolves the home directory
from configuration instead of passwd. Every user therefore shares one OS account
and one home tree, which is exactly what the deployment documents: there is no
per-user OS isolation here, only per-user directory separation.
"""

from __future__ import annotations

import os
import pwd
from typing import Any

from jupyterhub.spawner import LocalProcessSpawner


class OpenCSLocalSpawner(LocalProcessSpawner):
    """LocalProcessSpawner that never looks a Hub user up in passwd."""

    #: OS account that owns the spawned servers.
    service_user: str = ""
    #: Root directory holding one subdirectory per Hub user.
    home_root: str = ""

    def _service_pw(self) -> pwd.struct_passwd:
        name = self.service_user or pwd.getpwuid(os.getuid()).pw_name
        return pwd.getpwnam(name)

    def user_env(self, env: dict[str, str]) -> dict[str, str]:
        """Build the child environment without a passwd lookup for the user.

        Mirrors the stock implementation's contract (HOME/USER/LOGNAME/SHELL and
        the PATH fallback) while sourcing the identity from the service account.
        """
        pw = self._service_pw()
        env.setdefault("HOME", self._home())
        env.setdefault("USER", self.user.name)
        env.setdefault("LOGNAME", self.user.name)
        env.setdefault("SHELL", pw.pw_shell or "/bin/sh")
        env.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin")
        return env

    def _home(self) -> str:
        if self.home_root:
            home = os.path.join(self.home_root, self.user.name)
        else:
            home = os.path.join(self._service_pw().pw_dir, "opencs-runtime", "notebooks", self.user.name)
        os.makedirs(home, exist_ok=True)
        return home

    def get_state(self) -> dict[str, Any]:
        state = super().get_state()
        state.setdefault("home_root", self.home_root)
        return state

    def start(self) -> tuple[str, str]:
        self.home_dir = self._home()
        return super().start()
