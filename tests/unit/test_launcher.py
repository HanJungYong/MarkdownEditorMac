from pathlib import Path


def test_windows_launcher_uses_crlf_utf8_and_project_local_paths() -> None:
    launcher = Path(__file__).resolve().parents[2] / "run_markdowneditor.bat"
    raw = launcher.read_bytes()

    assert not raw.startswith(b"\xef\xbb\xbf")
    assert b"\r\n" in raw
    without_crlf = raw.replace(b"\r\n", b"")
    assert b"\n" not in without_crlf
    assert b"\r" not in without_crlf

    text = raw.decode("utf-8")
    assert 'pushd "%~dp0"' in text
    assert 'set "UV_CACHE_DIR=%PROJECT_ROOT%\\.uv-cache"' in text
    assert "uv.exe sync --locked --no-dev" in text
    assert "uv.exe run --locked --no-dev markdowneditor %*" in text
