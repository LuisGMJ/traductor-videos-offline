from __future__ import annotations

import ctypes
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import winreg
import zipfile


MARKER = b"TVI_PAYLOAD_V1"
APP_NAME = "TraductorVideos"
PUBLISHER = "Luis MJ"
MB_OKCANCEL = 0x00000001
MB_ICONINFORMATION = 0x00000040
MB_ICONERROR = 0x00000010
MB_ICONQUESTION = 0x00000020
IDOK = 1


UNINSTALL_TEMPLATE = r'''Add-Type -AssemblyName System.Windows.Forms

$ErrorActionPreference = "Stop"

$installDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$desktopShortcut = Join-Path ([Environment]::GetFolderPath("Desktop")) "TraductorVideos.lnk"
$startMenuDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\TraductorVideos"
$registryKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\TraductorVideos"

$answer = [System.Windows.Forms.MessageBox]::Show(
    "Se desinstalara TraductorVideos de esta cuenta de Windows.",
    "Confirmar desinstalacion",
    [System.Windows.Forms.MessageBoxButtons]::OKCancel,
    [System.Windows.Forms.MessageBoxIcon]::Question
)

if ($answer -ne [System.Windows.Forms.DialogResult]::OK) {
    exit 0
}

Get-Process TraductorVideos -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

if (Test-Path $desktopShortcut) {
    Remove-Item -LiteralPath $desktopShortcut -Force
}
if (Test-Path $startMenuDir) {
    Remove-Item -LiteralPath $startMenuDir -Recurse -Force
}
if (Test-Path $registryKey) {
    Remove-Item -LiteralPath $registryKey -Recurse -Force
}

$cleanupScript = Join-Path $env:TEMP ("traductorvideos-uninstall-" + [guid]::NewGuid().ToString("N") + ".cmd")
$cleanup = @(
    "@echo off",
    "ping 127.0.0.1 -n 3 >nul",
    "rmdir /s /q ""$installDir""",
    "del ""%~f0"""
)
Set-Content -Path $cleanupScript -Value $cleanup -Encoding ascii
Start-Process -FilePath "cmd.exe" -ArgumentList "/c `"$cleanupScript`"" -WindowStyle Hidden

[System.Windows.Forms.MessageBox]::Show(
    "TraductorVideos se desinstalo correctamente.",
    "Desinstalacion completada",
    [System.Windows.Forms.MessageBoxButtons]::OK,
    [System.Windows.Forms.MessageBoxIcon]::Information
) | Out-Null
'''


def bundled_root() -> Path:
    if getattr(sys, "_MEIPASS", None):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


def read_version() -> str:
    version_file = bundled_root() / "VERSION"
    if version_file.exists():
        return version_file.read_text(encoding="utf-8").strip() or "1.0.0"
    return "1.0.0"


def extract_payload(executable: Path, target_zip: Path) -> None:
    with executable.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        total_size = handle.tell()
        footer_size = 8 + len(MARKER)
        if total_size <= footer_size:
            raise RuntimeError("El instalador no contiene payload.")

        handle.seek(total_size - len(MARKER))
        marker = handle.read(len(MARKER))
        if marker != MARKER:
            raise RuntimeError("No se encontro el payload embebido en el instalador.")

        handle.seek(total_size - len(MARKER) - 8)
        payload_size = struct.unpack("<Q", handle.read(8))[0]
        payload_start = total_size - len(MARKER) - 8 - payload_size
        if payload_start < 0:
            raise RuntimeError("El tamano del payload no es valido.")

        handle.seek(payload_start)
        remaining = payload_size
        with target_zip.open("wb") as output:
            while remaining > 0:
                chunk = handle.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise RuntimeError("No se pudo leer el payload completo.")
                output.write(chunk)
                remaining -= len(chunk)


def run_powershell(script: str) -> None:
    subprocess.run(
        [
            os.path.join(os.environ["WINDIR"], "System32", "WindowsPowerShell", "v1.0", "powershell.exe"),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        check=True,
    )


def create_shortcuts(app_exe: Path, uninstall_script: Path) -> None:
    desktop = Path.home() / "Desktop"
    start_menu_dir = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / APP_NAME
    start_menu_dir.mkdir(parents=True, exist_ok=True)

    desktop_shortcut = desktop / f"{APP_NAME}.lnk"
    start_shortcut = start_menu_dir / f"{APP_NAME}.lnk"
    uninstall_shortcut = start_menu_dir / f"Desinstalar {APP_NAME}.lnk"

    ps = f"""
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut('{desktop_shortcut}')
$shortcut.TargetPath = '{app_exe}'
$shortcut.WorkingDirectory = '{app_exe.parent}'
$shortcut.IconLocation = '{app_exe}'
$shortcut.Save()
$shortcut = $shell.CreateShortcut('{start_shortcut}')
$shortcut.TargetPath = '{app_exe}'
$shortcut.WorkingDirectory = '{app_exe.parent}'
$shortcut.IconLocation = '{app_exe}'
$shortcut.Save()
$shortcut = $shell.CreateShortcut('{uninstall_shortcut}')
$shortcut.TargetPath = '{Path(os.environ["WINDIR"]) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"}'
$shortcut.Arguments = '-ExecutionPolicy Bypass -NoProfile -File "{uninstall_script}"'
$shortcut.WorkingDirectory = '{app_exe.parent}'
$shortcut.IconLocation = '{app_exe}'
$shortcut.Save()
"""
    run_powershell(ps)


def register_uninstall(version: str, install_dir: Path, app_exe: Path, uninstall_script: Path) -> None:
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\TraductorVideos"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
        winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, APP_NAME)
        winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, version)
        winreg.SetValueEx(key, "Publisher", 0, winreg.REG_SZ, PUBLISHER)
        winreg.SetValueEx(key, "InstallLocation", 0, winreg.REG_SZ, str(install_dir))
        winreg.SetValueEx(key, "DisplayIcon", 0, winreg.REG_SZ, str(app_exe))
        winreg.SetValueEx(
            key,
            "UninstallString",
            0,
            winreg.REG_SZ,
            f'{Path(os.environ["WINDIR"]) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"} -ExecutionPolicy Bypass -NoProfile -File "{uninstall_script}"',
        )
        winreg.SetValueEx(key, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "NoRepair", 0, winreg.REG_DWORD, 1)


def install_app(update_status) -> tuple[Path, str]:
    version = read_version()
    executable = Path(sys.executable)
    install_dir = Path(os.environ["LOCALAPPDATA"]) / "Programs" / APP_NAME
    app_exe = install_dir / f"{APP_NAME}.exe"
    uninstall_script = install_dir / "uninstall.ps1"

    update_status("Extrayendo instalador...")
    with tempfile.TemporaryDirectory(prefix="traductorvideos-installer-") as temp_raw:
        temp_dir = Path(temp_raw)
        payload_zip = temp_dir / f"{APP_NAME}.zip"
        extract_payload(executable, payload_zip)

        update_status("Descomprimiendo archivos...")
        unpack_dir = temp_dir / "app"
        with zipfile.ZipFile(payload_zip, "r") as archive:
            archive.extractall(unpack_dir)

        update_status("Cerrando instancias anteriores...")
        subprocess.run(["taskkill", "/IM", f"{APP_NAME}.exe", "/F"], capture_output=True, text=True)

        if install_dir.exists():
            shutil.rmtree(install_dir, ignore_errors=True)

        update_status("Copiando aplicacion...")
        install_dir.mkdir(parents=True, exist_ok=True)
        for item in unpack_dir.iterdir():
            destination = install_dir / item.name
            if item.is_dir():
                shutil.copytree(item, destination, dirs_exist_ok=True)
            else:
                shutil.copy2(item, destination)

        update_status("Creando acceso directo...")
        uninstall_script.write_text(UNINSTALL_TEMPLATE, encoding="utf-8")
        create_shortcuts(app_exe, uninstall_script)
        register_uninstall(version, install_dir, app_exe, uninstall_script)

    return app_exe, version


def message_box(text: str, title: str, flags: int) -> int:
    return ctypes.windll.user32.MessageBoxW(None, text, title, flags)


def run_self_check() -> int:
    executable = Path(sys.executable)
    with tempfile.TemporaryDirectory(prefix="traductorvideos-installer-check-") as temp_raw:
        temp_dir = Path(temp_raw)
        payload_zip = temp_dir / "payload.zip"
        extract_payload(executable, payload_zip)
        with zipfile.ZipFile(payload_zip, "r") as archive:
            names = archive.namelist()
        if "TraductorVideos.exe" not in names:
            raise RuntimeError("El payload no contiene TraductorVideos.exe")
    print("installer_self_check_ok")
    return 0


def main() -> int:
    if "--self-check" in sys.argv:
        return run_self_check()

    destination = Path(os.environ["LOCALAPPDATA"]) / "Programs" / APP_NAME
    result = message_box(
        f"Se instalara {APP_NAME} en:\n\n{destination}\n\nSe crearan accesos directos en Escritorio y menu Inicio.",
        f"Instalar {APP_NAME}",
        MB_OKCANCEL | MB_ICONQUESTION,
    )
    if result != IDOK:
        return 0

    try:
        app_exe, version = install_app(lambda _text: None)
        message_box(
            f"{APP_NAME} v{version} se instalo correctamente.",
            "Instalacion completada",
            MB_ICONINFORMATION,
        )
        subprocess.Popen([str(app_exe)], cwd=str(app_exe.parent))
        return 0
    except Exception as exc:  # noqa: BLE001
        message_box(str(exc), "Error de instalacion", MB_ICONERROR)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
