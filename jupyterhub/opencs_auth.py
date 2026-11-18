"""JupyterHub authenticator for OpenCS Labs single sign-on.

The React frontend logs a student in against the FastAPI backend, which issues a
short-lived HS256 JWT and sets it as an HttpOnly cookie on the shared browser
origin. JupyterHub runs behind the same origin, so the browser already holds the
credential when it arrives at ``/hub/login``; no second login prompt exists.

    browser --POST /api/v1/auth/login--> backend      (issues JWT, sets cookie)
    browser --GET  /hub/login----------> JupyterHub   (this module)
                                        | validate JWT, self.login_user()
                                        v
                                       KubeSpawner pod + /lab

Trust model
-----------
This module only *verifies* tokens. It never mints them: the signing key
(``OPENCE_JWT_SECRET``) is shared with the backend, and the backend is the only
issuer. The claims contract matches ``backend/app/core/security.py``:
``iss``, ``sub`` (OpenCS user id), ``hub`` (JupyterHub username), ``iat``,
``nbf``, ``exp``, and optionally ``role``/``email``/``name``.

The JWT is accepted from, in order: the ``Authorization: Bearer`` header, the
OpenCS session cookie, or a ``?token=`` query parameter. The header is the
programmatic path (the backend can hand a token to an API client); the cookie is
the browser path; the query parameter exists so a redirect from the app can
carry the token when cookies are blocked, and is only honoured for this
authenticator's own login handler.
"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

import jwt
from jupyterhub.auth import Authenticator
from jupyterhub.handlers import BaseHandler
from jupyterhub.utils import url_path_join
from tornado.log import app_log

#: Cookie the FastAPI backend sets. Must match OPENCE_SESSION_COOKIE there.
SESSION_COOKIE = os.environ.get("OPENCE_SESSION_COOKIE", "opencs_session")

#: Shared HS256 signing key. Same value as the backend's OPENCE_JWT_SECRET.
JWT_SECRET = os.environ.get("OPENCE_JWT_SECRET", "")

#: Expected ``iss`` claim.
JWT_ISSUER = os.environ.get("OPENCE_JWT_ISSUER", "opencs")

#: Only HS256 is accepted: it is what the backend signs with, and it avoids the
#: `alg=none` / algorithm-confusion class of bugs entirely.
JWT_ALGORITHMS = ("HS256",)

#: Where to send a browser that has no valid session.
PUBLIC_ORIGIN = os.environ.get("OPENCE_PUBLIC_ORIGIN", "http://localhost:5173").rstrip("/")
LOGIN_PATH = os.environ.get("OPENCE_LOGIN_PATH", "/login")

#: Refresh users no more often than this. The access token is short-lived, but
#: the Hub session outlives it, so a stale claim must not log anyone out early.
REFRESH_INTERVAL_SECONDS = 60


def login_redirect_url() -> str:
    """The frontend login page, used when the browser has no usable session."""
    path = LOGIN_PATH if LOGIN_PATH.startswith("/") else f"/{LOGIN_PATH}"
    return f"{PUBLIC_ORIGIN}{path}"


def safe_next_url(candidate: str | None) -> str | None:
    """Accept only same-origin, absolute-path redirect targets.

    Rejects ``//evil.example``, ``https://evil.example``, backslash tricks and
    anything that is not a plain path, so ``?next=`` cannot be used as an open
    redirect.
    """
    if not candidate or not isinstance(candidate, str):
        return None
    candidate = candidate.strip()
    if "\\" in candidate or "\n" in candidate or "\r" in candidate:
        return None
    if not candidate.startswith("/") or candidate.startswith("//"):
        return None
    parsed = urlparse(candidate)
    if parsed.scheme or parsed.netloc:
        return None
    return candidate


def extract_token(handler) -> str | None:  # noqa: ANN001 - tornado RequestHandler
    """Read the OpenCS session JWT from the current request.

    Order matters: an explicit ``Authorization`` header beats a cookie so that a
    programmatic client is never confused by a stale browser session, and the
    query parameter is the last resort for cookie-less redirects.
    """
    header = handler.request.headers.get("Authorization", "")
    if header:
        parts = header.split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "bearer" and parts[1].strip():
            return parts[1].strip()
        if len(parts) == 1 and parts[0].lower() == "bearer":
            return None

    cookie = handler.get_cookie(SESSION_COOKIE, None)
    if cookie:
        return cookie.strip() or None

    query_token = handler.get_argument("token", None)
    if query_token:
        return query_token.strip() or None
    return None


def verify_token(token: str) -> dict[str, Any]:
    """Decode and validate a session JWT.

    Raises:
        jwt.PyJWTError: the token is malformed, expired, wrongly signed or
            missing a required claim.
    """
    return jwt.decode(
        token,
        JWT_SECRET,
        algorithms=list(JWT_ALGORITHMS),
        issuer=JWT_ISSUER,
        # `exp`/`iat`/`nbf` are validated automatically when present; requiring
        # them here means a hand-rolled token without a lifetime is refused.
        options={"require": ["exp", "iat", "sub", "hub", "iss"]},
    )


class OpenCSLoginHandler(BaseHandler):
    """Complete Hub login from the OpenCS session JWT.

    Registered at ``/hub/login`` (see ``OpenCSAuthenticator.get_handlers``), so
    it replaces the username/password form entirely -- there is nothing to type.
    """

    def get_login_url(self) -> str:  # pragma: no cover - provided for clarity
        return self.hub.base_url + "login"

    async def get(self):  # noqa: D401 - tornado handler
        # Already signed in: refresh the Hub cookie and continue. This is what
        # makes /hub/login idempotent and safe to link to directly.
        user = self.current_user
        if user:
            self.set_login_cookie(user)
            self.redirect(self._target(), permanent=False)
            return

        token = extract_token(self)
        if not token:
            self.log.info("OpenCS login: no session token presented")
            self.redirect(self._to_frontend(), permanent=False)
            return

        try:
            payload = verify_token(token)
        except jwt.ExpiredSignatureError:
            self.log.info("OpenCS login: session token expired")
            self.redirect(self._to_frontend(), permanent=False)
            return
        except jwt.PyJWTError as exc:
            # Do not echo the token or the reason verbatim into the URL.
            self.log.warning("OpenCS login: rejected session token (%s)", type(exc).__name__)
            self.redirect(self._to_frontend(), permanent=False)
            return
        except Exception as exc:  # noqa: BLE001 - never 500 on a bad credential
            self.log.exception("OpenCS login: unexpected token error (%s)", type(exc).__name__)
            self.redirect(self._to_frontend(), permanent=False)
            return

        username = payload.get("hub")
        if not isinstance(username, str) or not username:
            self.log.warning("OpenCS login: token has no usable 'hub' claim")
            self.redirect(self._to_frontend(), permanent=False)
            return

        # `login_user` runs the authenticator's `authenticate`, which re-reads
        # and re-verifies the token from this same request, then creates or
        # updates the Hub user and sets the login cookie.
        user = await self.login_user()
        if user is None:
            self.log.warning("OpenCS login: authenticator rejected user %r", username)
            self.redirect(self._to_frontend(), permanent=False)
            return

        self.log.info("OpenCS login: %s authenticated via session token", user.name)
        self.redirect(self._target(), permanent=False)

    def _target(self) -> str:
        """Honour a safe ``?next=``, otherwise go to the user's own server."""
        # hub.base_url carries the shard prefix (e.g. /nb/0/hub/).
        return safe_next_url(self.get_argument("next", None)) or url_path_join(
            self.hub.base_url, "home"
        )

    def _to_frontend(self) -> str:
        return login_redirect_url()


class OpenCSLogoutHandler(BaseHandler):
    """Log out and return the browser to the OpenCS frontend.

    The OpenCS session cookie belongs to the backend and is deliberately left
    alone: logging out of the notebook must not sign the student out of the
    course app.
    """

    async def get(self):
        user = self.current_user
        if user:
            self.log.info("OpenCS logout: %s", user.name)
        self.clear_login_cookie()
        self._jupyterhub_user = None
        self.redirect(login_redirect_url(), permanent=False)


class OpenCSAuthenticator(Authenticator):
    """Trust the OpenCS backend's session JWT instead of asking for a password."""

    #: There is no login form to render, so JupyterHub must not try to show one.
    auto_login = True

    #: Missing username/password form data is expected, not an error.
    login_service = "OpenCS"

    async def authenticate(self, handler, data=None):  # noqa: ANN001, ARG002
        """Return the Hub user described by the request's session token.

        Returns ``None`` when no valid token is present, which is the normal
        case for an unauthenticated request: JupyterHub then redirects to
        ``/hub/login``, which is this module's own handler.

        ``data`` is ignored on purpose. These credentials never arrive in a
        form body; accepting one would create a second, weaker auth path.
        """
        if handler is None:  # pragma: no cover - defensive
            return None

        token = extract_token(handler)
        if not token:
            return None

        try:
            payload = verify_token(token)
        except jwt.PyJWTError as exc:
            self.log.debug("OpenCS auth: invalid session token (%s)", type(exc).__name__)
            return None

        username = payload.get("hub")
        if not isinstance(username, str) or not username.strip():
            self.log.warning("OpenCS auth: token is missing a 'hub' claim")
            return None
        username = username.strip()

        # auth_state is persisted by JupyterHub when `enable_auth_state` is on.
        # It carries the OpenCS identity so the backend can correlate a Hub user
        # with its own records without trusting anything from the browser.
        return {
            "name": username,
            "auth_state": {
                "user_id": payload.get("sub"),
                "role": payload.get("role"),
                "email": payload.get("email"),
                "name": payload.get("name"),
            },
        }

    async def refresh_user(self, user, handler=None):  # noqa: ANN001
        """Keep the Hub session, refresh claims only when a token is on hand.

        The Hub cookie outlives the short-lived OpenCS JWT. Refreshing must not
        log an active student out just because their API token expired, so this
        returns ``True`` (no change needed) unless a *valid* replacement token
        is present, in which case the auth_state is updated.
        """
        if handler is None:
            return True
        token = extract_token(handler)
        if not token:
            return True
        try:
            payload = verify_token(token)
        except jwt.PyJWTError:
            # An expired or bogus token on an ordinary request is not a logout.
            return True
        if payload.get("hub") != user.name:
            # A different identity than the logged-in one: ignore rather than
            # silently switching accounts mid-session.
            return True
        return {
            "name": user.name,
            "auth_state": {
                "user_id": payload.get("sub"),
                "role": payload.get("role"),
                "email": payload.get("email"),
                "name": payload.get("name"),
            },
        }

    def pre_spawn_start(self, user, spawner):  # noqa: ANN001
        """No-op hook, kept explicit.

        Resource limits and identity are applied by KubeSpawner's pod manifest
        (see ``jupyterhub_config.py``); there is no PAM session or token store
        to prepare here.
        """

    def post_spawn_stop(self, user, spawner):  # noqa: ANN001
        """No-op hook, kept explicit. See :meth:`pre_spawn_start`."""

    def login_url(self, base_url: str) -> str:
        """``/hub/login`` -- the handler registered below lives there."""
        return url_path_join(base_url, "login")

    def logout_url(self, base_url: str) -> str:
        return url_path_join(base_url, "logout")

    def get_handlers(self, app):  # noqa: ANN001
        """Register the token-accepting login handler and a frontend-aware logout."""
        return [
            (r"/login", OpenCSLoginHandler),
            (r"/logout", OpenCSLogoutHandler),
        ]


def _warn_on_configuration() -> None:
    """Fail loudly at import time rather than at the first login."""
    if not JWT_SECRET:
        app_log.warning(
            "OPENCE_JWT_SECRET is empty: every OpenCS session token will fail "
            "verification and no student can reach a notebook."
        )


_warn_on_configuration()
