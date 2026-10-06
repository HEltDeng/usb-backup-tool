from __future__ import annotations

import base64
import hashlib
import logging
from pathlib import Path, PurePosixPath
import random
import time
from typing import Any

import requests

from .config import Settings
from .errors import UploadError


class AliDriveClient:
    """Minimal legacy AliDrive multipart client isolated from the local backup path."""

    def __init__(self, settings: Settings, logger: logging.Logger, session: requests.Session | None = None) -> None:
        if not settings.refresh_token:
            raise UploadError("未配置 ALIDRIVE_REFRESH_TOKEN")
        self.settings = settings
        self.logger = logger
        self.session = session or requests.Session()
        self.access_token = ""
        self.drive_id = ""

    def _sleep(self, attempt: int) -> None:
        time.sleep(min(8.0, (2 ** attempt) + random.random() * 0.2))

    def _request(self, method: str, url: str, *, auth: bool = True, **kwargs: Any) -> requests.Response:
        headers = dict(kwargs.pop("headers", {}))
        if auth:
            if not self.access_token:
                self.authenticate()
            headers["Authorization"] = f"Bearer {self.access_token}"
        last: Exception | None = None
        for attempt in range(self.settings.max_retries):
            try:
                response = self.session.request(method, url, headers=headers, timeout=self.settings.timeout_seconds, **kwargs)
                if response.status_code == 401 and auth and attempt == 0:
                    self.authenticate()
                    headers["Authorization"] = f"Bearer {self.access_token}"
                    continue
                if response.status_code == 429 or response.status_code >= 500:
                    raise requests.HTTPError(f"HTTP {response.status_code}", response=response)
                response.raise_for_status()
                return response
            except (requests.Timeout, requests.ConnectionError, requests.HTTPError) as exc:
                last = exc
                if attempt + 1 >= self.settings.max_retries:
                    break
                self.logger.warning("阿里云盘请求失败，第 %d/%d 次，稍后重试: %s", attempt + 1, self.settings.max_retries, type(exc).__name__)
                self._sleep(attempt)
        raise UploadError(f"网络/API 请求失败: {type(last).__name__}: {last}")

    def authenticate(self) -> None:
        response = self._request(
            "POST",
            f"{self.settings.auth_base}/v2/account/token",
            auth=False,
            json={"grant_type": "refresh_token", "refresh_token": self.settings.refresh_token},
        )
        data = response.json()
        token = str(data.get("access_token", ""))
        drive_id = str(data.get("default_drive_id") or data.get("drive_id") or "")
        if not token or not drive_id:
            raise UploadError("鉴权响应缺少 access_token/default_drive_id；请确认令牌类型")
        self.access_token = token
        self.drive_id = drive_id

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", f"{self.settings.api_base}{path}", json=payload).json()

    def ensure_remote_folder(self, remote_path: str) -> str:
        parent = "root"
        for component in PurePosixPath("/" + remote_path.strip("/")).parts:
            if component == "/":
                continue
            listing = self._post(
                "/adrive/v3/file/list",
                {"drive_id": self.drive_id, "parent_file_id": parent, "limit": 100, "all": False},
            )
            match = next((item for item in listing.get("items", []) if item.get("type") == "folder" and item.get("name") == component), None)
            if match:
                parent = str(match["file_id"])
                continue
            created = self._post(
                "/adrive/v2/file/createWithFolders",
                {"drive_id": self.drive_id, "parent_file_id": parent, "name": component, "type": "folder", "check_name_mode": "refuse"},
            )
            parent = str(created.get("file_id", ""))
            if not parent:
                raise UploadError(f"无法创建云端目录: {component}")
        return parent

    def _proof_code(self, file: Path) -> str:
        size = file.stat().st_size
        digest = hashlib.sha1(self.access_token.encode("utf-8")).hexdigest()
        offset = int(digest[:16], 16) % size if size else 0
        with file.open("rb") as stream:
            stream.seek(offset)
            return base64.b64encode(stream.read(8)).decode("ascii")

    def upload(self, file: Path) -> None:
        if not self.drive_id:
            self.authenticate()
        parent = self.ensure_remote_folder(self.settings.remote_root)
        size = file.stat().st_size
        count = max(1, (size + self.settings.part_size - 1) // self.settings.part_size)
        created = self._post(
            "/v2/file/create_with_proof",
            {
                "drive_id": self.drive_id,
                "parent_file_id": parent,
                "name": file.name,
                "type": "file",
                "check_name_mode": "auto_rename",
                "size": size,
                "proof_code": self._proof_code(file),
                "proof_version": "v1",
                "part_info_list": [{"part_number": number} for number in range(1, count + 1)],
            },
        )
        if created.get("rapid_upload"):
            self.logger.info("阿里云盘秒传成功: %s", file.name)
            return
        upload_id = str(created.get("upload_id", ""))
        file_id = str(created.get("file_id", ""))
        parts = created.get("part_info_list") or []
        if not upload_id or not file_id or len(parts) != count:
            raise UploadError("创建分片上传任务响应不完整")
        with file.open("rb") as stream:
            for index, part in enumerate(parts, start=1):
                payload = stream.read(self.settings.part_size)
                url = str(part.get("upload_url", ""))
                if not url:
                    raise UploadError(f"第 {index} 片缺少 upload_url")
                self._request("PUT", url, auth=False, data=payload)
                self.logger.info("上传分片成功: %d/%d | 字节=%d", index, count, len(payload))
        self._post("/v2/file/complete", {"drive_id": self.drive_id, "file_id": file_id, "upload_id": upload_id})
        self.logger.info("阿里云盘上传完成: %s", file.name)
