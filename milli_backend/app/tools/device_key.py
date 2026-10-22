"""Create device API keys.

    python -m app.tools.device_key new lobby-cam-01 --env-file .env
    python -m app.tools.device_key hash          (prompts for an existing key)
    python -m app.tools.device_key check --sdkconfig ../milli_firmware/sdkconfig --env-file .env
    python -m app.tools.device_key sync-firmware --sdkconfig ../milli_firmware/sdkconfig --env-file .env

`new` prints the API key once. Only its SHA-256 digest goes into
MILLI_DEVICE_CREDENTIALS; put the key itself in the device's firmware config.
"""

import argparse
import getpass
import re
import sys
from pathlib import Path

from app.core.security import generate_api_key, hash_api_key, is_valid_device_id, parse_device_credentials

ENV_VAR = "MILLI_DEVICE_CREDENTIALS"


def upsert_env_credential(env_file: Path, device_id: str, digest: str) -> None:
    lines = env_file.read_text(encoding="utf-8").splitlines() if env_file.exists() else []
    prefix = f"{ENV_VAR}="
    for index, line in enumerate(lines):
        if line.strip().startswith(prefix):
            current = line.strip()[len(prefix):].strip().strip("'\"")
            credentials = parse_device_credentials(current)
            credentials[device_id] = digest
            lines[index] = prefix + ",".join(f"{d}:{h}" for d, h in credentials.items())
            break
    else:
        lines.append(f"{prefix}{device_id}:{digest}")
    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


def sdkconfig_value(sdkconfig: Path, name: str) -> str | None:
    match = re.search(rf'^{re.escape(name)}="(.*)"\s*$', sdkconfig.read_text(encoding="utf-8"), re.MULTILINE)
    return match.group(1) if match else None


def credentials_from_env_file(env_file: Path) -> dict[str, str]:
    for line in env_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith(f"{ENV_VAR}="):
            return parse_device_credentials(stripped.split("=", 1)[1].strip().strip("'\""))
    return {}


def check_firmware_credentials(sdkconfig: Path, env_file: Path) -> int:
    """Compare the firmware's device ID and key with the backend .env. Prints no secrets."""
    device_id = sdkconfig_value(sdkconfig, "CONFIG_MILLI_DEVICE_ID") or ""
    api_key = sdkconfig_value(sdkconfig, "CONFIG_MILLI_DEVICE_API_KEY")
    stored = credentials_from_env_file(env_file)
    registered = bool(device_id) and device_id in stored
    matches = registered and api_key is not None and stored[device_id] == hash_api_key(api_key)
    print(f"device_id={device_id or '(not set)'}")
    print(f"firmware_key={'set (' + str(len(api_key)) + ' chars)' if api_key else 'missing'}")
    print(f"backend_entry={'present' if registered else 'missing'}")
    print(f"match={'yes' if matches else 'no'}")
    if not matches:
        print(
            "The firmware key is not the key registered for this device. "
            "Run: python -m app.tools.device_key sync-firmware --sdkconfig <sdkconfig> --env-file .env",
            file=sys.stderr,
        )
        return 1
    return 0


def sync_firmware_credentials(sdkconfig: Path, env_file: Path) -> int:
    """Register the key already configured in the firmware. The key is never printed."""
    device_id = sdkconfig_value(sdkconfig, "CONFIG_MILLI_DEVICE_ID") or ""
    api_key = sdkconfig_value(sdkconfig, "CONFIG_MILLI_DEVICE_API_KEY") or ""
    if not is_valid_device_id(device_id) or not api_key.strip() or api_key != api_key.strip():
        print("sdkconfig needs a valid CONFIG_MILLI_DEVICE_ID and a non-empty CONFIG_MILLI_DEVICE_API_KEY.",
              file=sys.stderr)
        return 1
    upsert_env_credential(env_file, device_id, hash_api_key(api_key))
    print(f"Registered {device_id} from the firmware config. Restart the server to apply. The key was not printed.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.tools.device_key", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)

    new = commands.add_parser("new", help="generate a new API key for a device")
    new.add_argument("device_id")
    new.add_argument("--env-file", type=Path, help="add or replace the device in this .env file")

    commands.add_parser("hash", help="print the credential digest for an existing key")

    check = commands.add_parser("check", help="compare the firmware sdkconfig with .env, without printing the key")
    check.add_argument("--sdkconfig", type=Path, required=True)
    check.add_argument("--env-file", type=Path, required=True)

    sync = commands.add_parser("sync-firmware", help="register the firmware's existing key in .env")
    sync.add_argument("--sdkconfig", type=Path, required=True)
    sync.add_argument("--env-file", type=Path, required=True)

    args = parser.parse_args(argv)

    if args.command == "check":
        return check_firmware_credentials(args.sdkconfig, args.env_file)
    if args.command == "sync-firmware":
        return sync_firmware_credentials(args.sdkconfig, args.env_file)

    if args.command == "hash":
        api_key = getpass.getpass("API key: ")
        if not api_key:
            print("No key entered.", file=sys.stderr)
            return 1
        print(hash_api_key(api_key))
        return 0

    if not is_valid_device_id(args.device_id):
        print("Device ID must be 1-64 characters: letters, digits, '-' or '_' (starting with a letter or digit).",
              file=sys.stderr)
        return 1

    api_key = generate_api_key()
    digest = hash_api_key(api_key)
    print(f"Device ID : {args.device_id}")
    print(f"API key   : {api_key}")
    print("            (shown once - store it in the device config; never commit it)")
    print(f"Credential: {args.device_id}:{digest}")
    if args.env_file:
        upsert_env_credential(args.env_file, args.device_id, digest)
        print(f"Updated {ENV_VAR} in {args.env_file}. Restart the server to apply.")
    else:
        print(f"Add the credential to {ENV_VAR} in .env (comma-separate multiple devices).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
