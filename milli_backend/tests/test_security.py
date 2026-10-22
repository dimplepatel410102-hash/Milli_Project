import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.security import (
    DeviceCredentialStore,
    hash_api_key,
    parse_device_credentials,
)
from app.tools.device_key import main as device_key_main

DIGEST = hash_api_key("some-key")


def test_parse_credentials():
    parsed = parse_device_credentials(f" cam-1:{DIGEST} , cam_2:{DIGEST.upper()},")
    assert parsed == {"cam-1": DIGEST, "cam_2": DIGEST}


@pytest.mark.parametrize(
    "raw",
    [
        "cam-1",
        "cam-1:plaintext-key",
        f":{DIGEST}",
        f"bad id:{DIGEST}",
        f"cam-1:{DIGEST},cam-1:{DIGEST}",
    ],
    ids=["no-separator", "plaintext", "empty-id", "space-in-id", "duplicate"],
)
def test_parse_credentials_rejects_bad_entries(raw):
    with pytest.raises(ValueError) as info:
        parse_device_credentials(raw)
    assert DIGEST not in str(info.value)


def test_credential_store_verify():
    store = DeviceCredentialStore({"cam-1": DIGEST})
    assert store.verify("cam-1", "some-key")
    assert not store.verify("cam-1", "other-key")
    assert not store.verify("cam-2", "some-key")


def test_settings_reject_unknown_image_format():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, allowed_image_formats="JPEG,HEIC")


def test_settings_normalise_formats():
    settings = Settings(_env_file=None, allowed_image_formats=" jpeg, png ,jpeg")
    assert settings.allowed_formats == ("JPEG", "PNG")


def test_device_key_tool_writes_only_digest(tmp_path, capsys):
    env_file = tmp_path / ".env"
    env_file.write_text("MILLI_LOG_LEVEL=INFO\nMILLI_DEVICE_CREDENTIALS=\n", encoding="utf-8")

    assert device_key_main(["new", "lobby-cam-01", "--env-file", str(env_file)]) == 0
    api_key = next(line.split(":", 1)[1].strip() for line in capsys.readouterr().out.splitlines()
                   if line.startswith("API key"))

    content = env_file.read_text(encoding="utf-8")
    assert api_key not in content
    assert f"MILLI_DEVICE_CREDENTIALS=lobby-cam-01:{hash_api_key(api_key)}" in content
    assert "MILLI_LOG_LEVEL=INFO" in content

    assert device_key_main(["new", "door-cam-02", "--env-file", str(env_file)]) == 0
    line = next(l for l in env_file.read_text(encoding="utf-8").splitlines() if l.startswith("MILLI_DEVICE_CREDENTIALS"))
    assert set(parse_device_credentials(line.split("=", 1)[1])) == {"lobby-cam-01", "door-cam-02"}


def test_device_key_tool_rejects_bad_device_id(capsys):
    assert device_key_main(["new", "bad id"]) == 1


def test_check_and_sync_firmware_credentials_without_printing_the_key(tmp_path, capsys):
    sdkconfig = tmp_path / "sdkconfig"
    env_file = tmp_path / ".env"
    env_file.write_text("MILLI_DEVICE_CREDENTIALS=milli-cam-01:" + hash_api_key("old-key") + "\n", encoding="utf-8")
    sdkconfig.write_text(
        'CONFIG_MILLI_DEVICE_ID="milli-cam-01"\nCONFIG_MILLI_DEVICE_API_KEY="firmware-key"\n',
        encoding="utf-8",
    )

    assert device_key_main(["check", "--sdkconfig", str(sdkconfig), "--env-file", str(env_file)]) == 1
    mismatch = capsys.readouterr()
    assert "match=no" in mismatch.out
    assert "firmware-key" not in mismatch.out and "firmware-key" not in mismatch.err

    assert device_key_main(["sync-firmware", "--sdkconfig", str(sdkconfig), "--env-file", str(env_file)]) == 0
    assert "firmware-key" not in env_file.read_text(encoding="utf-8")
    assert device_key_main(["check", "--sdkconfig", str(sdkconfig), "--env-file", str(env_file)]) == 0
    assert "match=yes" in capsys.readouterr().out
