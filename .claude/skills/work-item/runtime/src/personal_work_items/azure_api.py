from __future__ import annotations

import base64
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class APIError(RuntimeError):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class Response(Protocol):
    def read(self) -> bytes: ...

    def close(self) -> None: ...


class Opener(Protocol):
    def open(self, request: Request, timeout: float = ...) -> Response: ...


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self,
        request: Request,
        fp: object,
        code: int,
        message: str,
        headers: object,
        new_url: str,
    ) -> Request | None:
        return None


@dataclass(frozen=True)
class Client:
    config: Mapping[str, object]
    token: str = field(repr=False)
    opener: Opener | Callable[[Request, float], Response] | None = None
    timeout: float = 15.0

    def __post_init__(self) -> None:
        organization = self.config.get("organization")
        project = self.config.get("project")
        if not isinstance(organization, str) or not re.fullmatch(
            r"[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?", organization
        ):
            raise APIError("Azure DevOps organization is invalid")
        if (
            not isinstance(project, str)
            or not project.strip()
            or project != project.strip()
            or any(character in project for character in "/\\?#")
            or any(ord(character) < 32 for character in project)
        ):
            raise APIError("Azure DevOps project is invalid")
        if not isinstance(self.token, str) or not self.token:
            raise APIError("personal Azure DevOps credentials are unavailable")

    @property
    def organization(self) -> str:
        organization = self.config["organization"]
        assert isinstance(organization, str)
        return organization

    @property
    def project(self) -> str:
        project = self.config["project"]
        assert isinstance(project, str)
        return project

    @property
    def base_url(self) -> str:
        return (
            f"https://dev.azure.com/{self.organization}/"
            f"{quote(self.project, safe='')}/_apis/wit"
        )

    def request(
        self,
        method: str,
        suffix: str,
        payload: Mapping[str, object] | Sequence[Mapping[str, object]] | None = None,
        content_type: str = "application/json",
    ) -> object:
        url = self._url(suffix)
        encoded_payload = None
        headers = {
            "Accept": "application/json",
            "Authorization": "Basic "
            + base64.b64encode(f"personal:{self.token}".encode()).decode(),
            "User-Agent": "tj-agents-personal-work-items/1",
        }
        if payload is not None:
            encoded_payload = json.dumps(
                payload, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
            headers["Content-Type"] = content_type
        request = Request(url, data=encoded_payload, headers=headers, method=method)
        try:
            response = self._open(request)
            try:
                body = response.read()
            finally:
                response.close()
        except HTTPError as error:
            raise APIError(
                f"Azure DevOps {method} failed (HTTP {error.code})", error.code
            ) from error
        except (OSError, URLError, TimeoutError) as error:
            raise APIError(
                "Azure DevOps transport is unavailable; "
                "a write outcome may be uncertain"
            ) from error
        if not body:
            return None
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise APIError(
                "Azure DevOps returned an invalid response; "
                "a write outcome may be uncertain"
            ) from error

    def _open(self, request: Request) -> Response:
        if self.opener is None:
            return cast(
                Response, build_opener(NoRedirect()).open(request, timeout=self.timeout)
            )
        if callable(self.opener):
            return self.opener(request, self.timeout)
        return self.opener.open(request, timeout=self.timeout)

    def _url(self, suffix: str) -> str:
        parsed = urlsplit(suffix)
        if (
            not suffix
            or parsed.scheme
            or parsed.netloc
            or parsed.fragment
            or parsed.path.startswith("/")
            or "\\" in parsed.path
            or ".." in parsed.path.split("/")
        ):
            raise APIError("Azure DevOps endpoint is invalid")
        query = parse_qsl(parsed.query, keep_blank_values=True)
        query.append(("api-version", "7.1"))
        return urlunsplit(
            (
                "https",
                "dev.azure.com",
                urlsplit(self.base_url).path + "/" + parsed.path,
                urlencode(query),
                "",
            )
        )
