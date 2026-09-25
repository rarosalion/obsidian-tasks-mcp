import json
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import quote

import httpx

from . import frontmatter

_MAP = {"Accept": "application/vnd.olrapi.document-map+json"}
_JSON = {"Content-Type": "application/json"}
_MARKDOWN = {"Content-Type": "text/markdown"}
_JSONLOGIC = {"Content-Type": "application/vnd.olrapi.jsonlogic+json"}


class VaultError(Exception):
    pass


class NotFoundError(VaultError):
    pass


class ConflictError(VaultError):
    """The file changed between the read and the write, so nothing was written."""


class ExistsError(VaultError):
    pass


@dataclass(frozen=True)
class Document:
    path: str
    text: str
    version: str


class Vault(Protocol):
    def read(self, path: str, consistent: bool = True) -> Document: ...

    def write(self, doc: Document, new_text: str) -> None: ...

    def create(self, path: str, text: str) -> None: ...

    def exists(self, path: str) -> bool: ...

    def list_folder(self, folder: str) -> list[str]: ...

    def find_boards(self) -> list[str]: ...

    def find_by_name(self, name: str) -> list[str]: ...


class RestVault:
    """Vault access through the Obsidian Local REST API plugin."""

    def __init__(self, base_url: str, api_key: str, timeout: float = 20.0):
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )

    @staticmethod
    def _url(path: str) -> str:
        return "/vault/" + quote(path.strip("/"), safe="/")

    def _version(self, path: str) -> str:
        response = self._http.get(self._url(path), headers=_MAP)
        if response.status_code == 404:
            raise NotFoundError(path)
        response.raise_for_status()
        return response.json()["version"]

    def read(self, path: str, consistent: bool = True) -> Document:
        if not consistent:
            response = self._http.get(self._url(path))
            if response.status_code == 404:
                raise NotFoundError(path)
            response.raise_for_status()
            return Document(path, response.text, "")
        for _ in range(3):
            before = self._version(path)
            response = self._http.get(self._url(path))
            if response.status_code == 404:
                raise NotFoundError(path)
            response.raise_for_status()
            if self._version(path) == before:
                return Document(path, response.text, before)
        raise ConflictError(f"{path} kept changing while being read")

    def write(self, doc: Document, new_text: str) -> None:
        if new_text == doc.text:
            return
        old_front, _ = frontmatter.split(doc.text)
        new_front, new_body = frontmatter.split(new_text)
        if old_front == new_front:
            self._patch_body(doc, new_body)
            return
        if self._version(doc.path) != doc.version:
            raise ConflictError(doc.path)
        self._put(doc.path, new_text)

    def _patch_body(self, doc: Document, body: str) -> None:
        instruction = {
            "targetType": "heading",
            "target": None,
            "operation": "replace",
            "content": body,
            "ifMatch": doc.version,
        }
        response = self._http.patch(
            self._url(doc.path), content=json.dumps(instruction), headers=_JSON
        )
        if response.status_code == 412:
            raise ConflictError(doc.path)
        response.raise_for_status()

    def _put(self, path: str, text: str) -> None:
        response = self._http.put(self._url(path), content=text.encode(), headers=_MARKDOWN)
        response.raise_for_status()

    def create(self, path: str, text: str) -> None:
        if self.exists(path):
            raise ExistsError(path)
        self._put(path, text)

    def exists(self, path: str) -> bool:
        response = self._http.get(self._url(path), headers=_MAP)
        if response.status_code == 404:
            return False
        response.raise_for_status()
        return True

    def list_folder(self, folder: str) -> list[str]:
        response = self._http.get(self._url(folder) + "/")
        if response.status_code == 404:
            return []
        response.raise_for_status()
        prefix = folder.strip("/")
        return [f"{prefix}/{name}" for name in response.json()["files"] if name.endswith(".md")]

    def _search(self, query: dict) -> list[str]:
        response = self._http.post("/search/", content=json.dumps(query), headers=_JSONLOGIC)
        response.raise_for_status()
        return [hit["filename"] for hit in response.json()]

    def find_boards(self) -> list[str]:
        return self._search({"==": [{"var": "frontmatter.kanban-plugin"}, "board"]})

    def find_by_name(self, name: str) -> list[str]:
        suffix = f"{name}.md"
        return self._search(
            {
                "or": [
                    {"==": [{"var": "path"}, suffix]},
                    {"regexp": ["(^|/)" + _escape(suffix) + "$", {"var": "path"}]},
                ]
            }
        )


def _escape(text: str) -> str:
    return "".join("\\" + c if c in r".^$*+?()[]{}|\\" else c for c in text)
