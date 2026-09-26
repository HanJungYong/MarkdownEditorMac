from pathlib import Path

from markdowneditor.app import parse_arguments


def test_gui_parser_accepts_zero_one_or_many_files() -> None:
    # run_markdowneditor.bat forwards %*, so several dropped files must not be an error.
    assert parse_arguments([]).files == []
    assert parse_arguments(["a.md"]).files == ["a.md"]
    many = parse_arguments(["a.md", "한글 폴더\\b (1).md", "--disable-gpu", "c.markdown"])
    assert many.files == ["a.md", "한글 폴더\\b (1).md", "c.markdown"]
    assert many.disable_gpu is True


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
