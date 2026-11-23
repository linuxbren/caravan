#!/usr/bin/env python3
"""Read-only, stdlib health checks. Never starts/stops services or downloads files."""
import argparse
import os
import platform
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from caravan_i18n import T  # noqa: E402  (Day 32: user-facing text)


def checks(home=None, port=8190):
    home = Path(home or Path.home())
    rows = []
    def add(level, message): rows.append((level, message))
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import caravan_version
        add("INFO", T("cli.doctor.installed_text", text=caravan_version.text()))
    except Exception:  # noqa: BLE001 - doctor must never fail on this
        add("INFO", T("cli.doctor.installed_version_unknown"))
    mac = platform.system() == "Darwin"
    add("OK" if mac else "ERROR", T("cli.doctor.macos_required_apple_silicon_macos_14"))
    add("OK" if platform.machine() == "arm64" else "ERROR", T("cli.doctor.native_apple_silicon_required_disable_rosetta"))
    if mac:
        version = platform.mac_ver()[0]
        add("OK" if version and int(version.split('.')[0]) >= 14 else "ERROR", T("cli.doctor.macos_v_upgrade_to_14_if", v=version or 'unknown'))
        memory = int(subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True))
        add("ERROR" if memory < 8*2**30 else "WARN" if memory < 16*2**30 else "OK", T("cli.doctor.caravan_checks_what_fits_more_memory"))
    add("ERROR" if os.getuid() == 0 else "OK", T("cli.doctor.use_your_normal_mac_account_without"))
    free = shutil.disk_usage(home).free
    add("OK" if free >= 8*2**30 else "ERROR", T("cli.doctor.free_disk_v_gb_setup_needs", v=free/2**30))
    add("OK" if os.access(home, os.W_OK) else "ERROR", T("cli.doctor.home_folder_must_be_writable"))
    py = home / ".caravan/venvs/mlx/bin/python"
    if py.exists():
        result = subprocess.run([str(py), "-c", "import mlx.core,mlx_lm,huggingface_hub,spake2,cryptography"], capture_output=True, text=True)
        add("ERROR" if result.returncode else "OK", T("cli.doctor.mlx_environment_v", v=T("cli.doctor.needs_repair_rerun_setup_stderr", stderr=result.stderr.strip()[-300:]) if result.returncode else T("cli.doctor.imports_correctly")))
    else:
        add("WARN", T("cli.doctor.mlx_environment_not_installed_yet_the"))
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            add("WARN", T("cli.doctor.port_port_is_in_use_possibly", port=port))
    except OSError:
        add("OK", T("cli.doctor.port_port_is_available_or_the", port=port))
    add("INFO", T("cli.doctor.login_is_required_after_reboot_filevault"))
    try:
        with socket.create_connection(("127.0.0.1", 8197), timeout=1):
            add("INFO", T("cli.doctor.mac_pairing_address_is_in_use"))
    except OSError:
        add("INFO", T("cli.doctor.mac_pairing_service_is_stopped_or"))
    try:
        with socket.create_connection(("127.0.0.1", 22), timeout=.5):
            add("INFO", T("cli.doctor.remote_login_is_reachable_add_macs"))
    except OSError:
        add("INFO", T("cli.doctor.to_add_this_mac_to_another"))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))
    from llama_runtime import ready, location, PIN
    add("OK" if ready(home) else "ERROR", T("cli.doctor.model_engine_version_v", version=PIN['version'], v=str(location(home)) if ready(home) else "not installed or incomplete. Rerun setup (or caravan update)."))
    try:
        import caravan_service
        from contextlib import redirect_stdout
        import io
        detail = io.StringIO()
        with redirect_stdout(detail):
            caravan_service.main(["status"])
        for line in detail.getvalue().splitlines():
            add("INFO", line)
    except (OSError, ValueError):
        add("INFO", T("cli.doctor.service_details_unavailable_rerun_setup"))
    add("INFO", T("cli.doctor.models_and_trusted_mac_connections_are"))
    try:
        from caravan_remote import doctor_line
        add("INFO", doctor_line(home=home, port=port))
    except Exception as e:  # noqa: BLE001
        add("INFO", T("cli.doctor.open_from_other_devices_could_not", splitlines=str(e).splitlines()[0][:120]))
    try:
        from caravan_lan import doctor_line as lan_doctor_line
        add("INFO", lan_doctor_line(home=home, port=port))
    except Exception as e:  # noqa: BLE001
        add("INFO", T("cli.doctor.open_on_the_local_network_could", splitlines=str(e).splitlines()[0][:120]))
    add("INFO", T("cli.doctor.no_network_checks_performed_downloads_require"))
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8190)
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535: parser.error(T("cli.doctor.port_must_be_1_65535"))
    rows = checks(port=args.port)
    for level, message in rows: print(f"[{level}] {message}")
    return int(any(level == "ERROR" for level, _ in rows))


if __name__ == "__main__": sys.exit(main())
