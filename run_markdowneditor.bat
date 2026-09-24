@echo off
setlocal EnableExtensions
chcp 65001 >nul
pushd "%~dp0" || (
  echo [오류] 프로젝트 폴더로 이동할 수 없습니다: %~dp0
  exit /b 1
)
set "PROJECT_ROOT=%CD%"
set "UV_CACHE_DIR=%PROJECT_ROOT%\.uv-cache"
set "UV_PYTHON_INSTALL_DIR=%PROJECT_ROOT%\.uv-python"

where.exe uv.exe >nul 2>nul
if errorlevel 1 (
  echo [오류] uv를 찾을 수 없습니다.
  echo https://docs.astral.sh/uv/getting-started/installation/ 에서 uv를 설치한 뒤 다시 실행하세요.
  popd
  exit /b 1
)

uv.exe sync --locked --no-dev
if errorlevel 1 (
  echo [오류] MarkdownEditor 실행 환경을 준비하지 못했습니다.
  popd
  exit /b 1
)

uv.exe run --locked --no-dev markdowneditor %*
set "EXIT_CODE=%ERRORLEVEL%"
popd
exit /b %EXIT_CODE%
