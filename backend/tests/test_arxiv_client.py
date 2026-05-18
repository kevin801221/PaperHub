import io
import tarfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import arxiv
import httpx
import respx

from paperhub.pipelines.arxiv_client import (
    ArxivResult,
    download_arxiv_source,
    search_arxiv,
)


def test_arxiv_module_has_expected_api_shape() -> None:
    """Contract test against the installed arxiv module — fails fast on
    API drift across major version bumps."""
    assert hasattr(arxiv, "Client")
    assert hasattr(arxiv, "Search")
    assert hasattr(arxiv, "Result")
    client = arxiv.Client()
    assert callable(getattr(client, "results", None)), (
        "arxiv.Client.results missing — search_arxiv needs rewrite"
    )
    # Result.source_url() exists in the installed arxiv library.
    # download_arxiv_source no longer DEPENDS on it (we build the URL
    # directly), but we still assert its presence to catch major API
    # drift early.
    assert callable(getattr(arxiv.Result, "source_url", None)), (
        "arxiv.Result.source_url missing — if re-adding metadata query, needs rewrite"
    )


def test_search_arxiv_returns_typed_results() -> None:
    fake_result = MagicMock()
    fake_result.entry_id = "http://arxiv.org/abs/2403.01234v1"
    fake_result.title = "A Test Paper"
    fake_result.authors = [MagicMock(name="Author One"), MagicMock(name="Author Two")]
    fake_result.authors[0].name = "Author One"
    fake_result.authors[1].name = "Author Two"
    fake_result.summary = "An abstract."
    fake_result.published.year = 2024

    with patch(
        "paperhub.pipelines.arxiv_client._client"
    ) as mock_client:
        mock_client.results.return_value = iter([fake_result])
        results = search_arxiv("mixture of experts", max_results=1)

    assert len(results) == 1
    r = results[0]
    assert isinstance(r, ArxivResult)
    assert r.arxiv_id == "2403.01234"
    assert r.title == "A Test Paper"
    assert r.authors == ["Author One", "Author Two"]
    assert r.year == 2024
    assert r.abstract == "An abstract."


@respx.mock
def test_download_arxiv_source_writes_to_cache(tmp_path: Path) -> None:
    """download_arxiv_source fetches the tarball via httpx and unpacks it.

    The arxiv metadata API (_client.results) must NOT be called — the source
    URL is built deterministically from the arxiv_id (fix for 429 bug).
    """
    # Build an in-memory tarball with a single main.tex.
    src_text = r"\documentclass{article}\begin{document}Hi\end{document}"
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo(name="main.tex")
        info.size = len(src_text)
        tar.addfile(info, io.BytesIO(src_text.encode("utf-8")))
    tarball_bytes = buf.getvalue()

    # Mock only the HTTP GET for the source URL — no arxiv API mock needed.
    respx.get("https://arxiv.org/src/2403.01234").mock(
        return_value=httpx.Response(200, content=tarball_bytes),
    )

    # Verify _client.results is NOT called during download.
    with patch(
        "paperhub.pipelines.arxiv_client._client.results",
        side_effect=AssertionError("_client.results must not be called by download_arxiv_source"),
    ):
        source_dir = download_arxiv_source("2403.01234", cache_root=tmp_path / "cache")

    assert source_dir.exists()
    assert (source_dir / "main.tex").exists()
    assert source_dir.parent.name == "2403.01234"


@respx.mock
def test_download_arxiv_source_builds_src_url_without_arxiv_metadata_query(
    tmp_path: Path,
) -> None:
    """download_arxiv_source must build the source URL from the arxiv_id
    directly, without calling _client.results at all."""
    src_text = r"\documentclass{article}\begin{document}Test\end{document}"
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo(name="paper.tex")
        info.size = len(src_text)
        tar.addfile(info, io.BytesIO(src_text.encode("utf-8")))
    tarball_bytes = buf.getvalue()

    respx.get("https://arxiv.org/src/1234.56789").mock(
        return_value=httpx.Response(200, content=tarball_bytes),
    )

    mock_results = MagicMock(
        side_effect=AssertionError("_client.results called — no metadata query allowed"),
    )
    with patch("paperhub.pipelines.arxiv_client._client.results", mock_results):
        source_dir = download_arxiv_source("1234.56789", cache_root=tmp_path / "cache")

    mock_results.assert_not_called()
    assert (source_dir / "paper.tex").exists()
