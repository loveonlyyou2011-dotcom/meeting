import shutil
from pathlib import Path


def resolve_ffmpeg() -> str:
    """PATH에서 ffmpeg를 찾고, 없으면 winget 기본 설치 경로를 추가로 탐색한다.

    winget으로 방금 설치한 경우 현재 세션의 PATH가 아직 갱신되지 않아
    `shutil.which`가 실패할 수 있어 폴백이 필요하다.
    """
    found = shutil.which("ffmpeg")
    if found:
        return found

    winget_packages = Path.home() / "AppData" / "Local" / "Microsoft" / "WinGet" / "Packages"
    if winget_packages.exists():
        for exe in winget_packages.glob("Gyan.FFmpeg*/**/bin/ffmpeg.exe"):
            return str(exe)

    return "ffmpeg"
