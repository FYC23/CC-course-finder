from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from .config import ARTIFACT_DIR
from .http import AssistHttpClient
from .models import AgreementRef


class ArtifactFetcher:
    def __init__(self, client: AssistHttpClient, artifact_dir: Path | None = None) -> None:
        self.client = client
        self.artifact_dir = artifact_dir or ARTIFACT_DIR
        self.artifact_dir.mkdir(parents=True, exist_ok=True)

    def artifact_path(self, ref: AgreementRef) -> Path:
        safe_agreement_id = "".join(
            ch if ch.isalnum() or ch in ("-", "_") else "_"
            for ch in ref.agreement_id
        )
        filename = (
            f"report_{ref.target_school_id}_{ref.cc_id}_{safe_agreement_id}.pdf"
        )
        return self.artifact_dir / filename

    def fetch_artifact(self, ref: AgreementRef, force: bool = False) -> Path:
        path = self.artifact_path(ref)
        if path.exists() and not force:
            return path
        artifact_url = self._encoded_artifact_url(ref.artifact_url)
        payload = self.client.get_bytes(artifact_url, accept_pdf=True)
        path.write_bytes(payload)
        return path

    @staticmethod
    def _encoded_artifact_url(url: str) -> str:
        if "/artifacts/" not in url:
            return url
        prefix, key = url.split("/artifacts/", 1)
        # Keep path separators in key-like identifiers while encoding spaces and
        # other unsafe characters.
        return f"{prefix}/artifacts/{quote(key, safe='/')}"

