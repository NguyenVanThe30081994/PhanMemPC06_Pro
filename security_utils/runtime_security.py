# -*- coding: utf-8 -*-
"""
Runtime security helpers that do not depend on Flask request context.
"""
import ipaddress
import hashlib
import hmac
import os
import secrets
import stat
import zipfile
from base64 import urlsafe_b64encode
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


_TEMP_PASSWORD_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#$%^&*"


def ensure_persistent_secret_key(data_root, explicit_secret=""):
    secret_value = (explicit_secret or "").strip()
    if secret_value:
        return secret_value

    secret_dir = Path(data_root).resolve()
    secret_dir.mkdir(parents=True, exist_ok=True)
    secret_path = secret_dir / ".secret_key"

    if secret_path.exists():
        stored_secret = secret_path.read_text(encoding="utf-8").strip()
        if stored_secret:
            return stored_secret

    generated_secret = secrets.token_urlsafe(48)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(str(secret_path), flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(generated_secret)
            handle.write("\n")
    except Exception:
        try:
            os.unlink(secret_path)
        except OSError:
            pass
        raise
    return generated_secret


def parse_trusted_cidrs(raw_value):
    networks = []
    for item in str(raw_value or "").split(","):
        item = item.strip()
        if not item:
            continue
        try:
            networks.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            continue
    return tuple(networks)


def _parse_ip_address(value):
    try:
        return ipaddress.ip_address((value or "").strip())
    except ValueError:
        return None


def fingerprint_security_value(secret_key, namespace, value):
    if not secret_key or not namespace or not value:
        return ""
    payload = f"{namespace}\x00{value}".encode("utf-8")
    return hmac.new(str(secret_key).encode("utf-8"), payload, hashlib.sha256).hexdigest()


def build_ip_network_hint(value):
    parsed = _parse_ip_address(value)
    if parsed is None:
        return ""
    if parsed.version == 4:
        prefix = 24
    else:
        prefix = 64 if (parsed.is_private or parsed.is_loopback or parsed.is_link_local) else 48
    return str(ipaddress.ip_network(f"{parsed}/{prefix}", strict=False))


def describe_user_agent(user_agent):
    agent = str(user_agent or "").strip().lower()
    if not agent:
        return "Trình duyệt không xác định"

    browser = "Trình duyệt không xác định"
    browser_markers = (
        ("edg/", "Microsoft Edge"),
        ("chrome/", "Google Chrome"),
        ("firefox/", "Mozilla Firefox"),
        ("safari/", "Safari"),
        ("opr/", "Opera"),
    )
    for marker, label in browser_markers:
        if marker in agent:
            browser = label
            break

    platform = "thiết bị không xác định"
    platform_markers = (
        ("iphone", "iPhone"),
        ("ipad", "iPad"),
        ("android", "Android"),
        ("windows", "Windows"),
        ("mac os x", "macOS"),
        ("linux", "Linux"),
    )
    for marker, label in platform_markers:
        if marker in agent:
            platform = label
            break

    return f"{browser} trên {platform}"


def _derive_fernet_key(secret_key, namespace="pc06-secret-box"):
    if not secret_key:
        return None
    raw = hashlib.sha256(f"{namespace}\x00{secret_key}".encode("utf-8")).digest()
    return urlsafe_b64encode(raw)


def encrypt_secret_value(secret_key, plaintext, namespace="pc06-secret-box"):
    value = str(plaintext or "").strip()
    if not value:
        return ""
    fernet_key = _derive_fernet_key(secret_key, namespace=namespace)
    if not fernet_key:
        raise ValueError("Missing secret key for encryption.")
    token = Fernet(fernet_key).encrypt(value.encode("utf-8")).decode("utf-8")
    return f"enc:{token}"


def decrypt_secret_value(secret_key, ciphertext, namespace="pc06-secret-box"):
    value = str(ciphertext or "").strip()
    if not value:
        return ""
    if not value.startswith("enc:"):
        return value
    fernet_key = _derive_fernet_key(secret_key, namespace=namespace)
    if not fernet_key:
        raise ValueError("Missing secret key for decryption.")
    token = value[4:].encode("utf-8")
    try:
        return Fernet(fernet_key).decrypt(token).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("Encrypted secret value is invalid or cannot be decrypted.") from exc


def is_trusted_proxy(remote_addr, trusted_cidrs):
    remote_ip = _parse_ip_address(remote_addr)
    if remote_ip is None:
        return False
    return any(remote_ip in network for network in trusted_cidrs)


def extract_client_ip(remote_addr, forwarded_for="", trusted_cidrs=()):
    if not is_trusted_proxy(remote_addr, trusted_cidrs):
        return (remote_addr or "unknown").strip() or "unknown"

    forwarded_chain = [part.strip() for part in str(forwarded_for or "").split(",") if part.strip()]
    for candidate in forwarded_chain:
        parsed = _parse_ip_address(candidate)
        if parsed is not None:
            return candidate
    return (remote_addr or "unknown").strip() or "unknown"


def resolve_safe_path(base_dir, unsafe_relative_path, allow_missing=False):
    base_path = Path(base_dir).resolve()
    candidate_path = (base_path / (unsafe_relative_path or "")).resolve()

    try:
        candidate_path.relative_to(base_path)
    except ValueError as exc:
        raise ValueError("Unsafe path traversal attempt blocked.") from exc

    if not allow_missing and not candidate_path.exists():
        raise FileNotFoundError(str(candidate_path))
    return candidate_path


def _is_symlink_member(member):
    return stat.S_ISLNK(member.external_attr >> 16)


def safe_extract_zip(
    zip_path,
    dest_dir,
    max_members=2000,
    max_total_size=250 * 1024 * 1024,
    blocked_roots=None,
    blocked_names=None,
):
    destination = Path(dest_dir).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    blocked_roots = {str(item or "").strip().lower() for item in (blocked_roots or set()) if str(item or "").strip()}
    blocked_names = {str(item or "").strip().lower() for item in (blocked_names or set()) if str(item or "").strip()}

    with zipfile.ZipFile(zip_path) as archive:
        members = archive.infolist()
        if len(members) > max_members:
            raise ValueError("Goi cap nhat chua qua nhieu tep.")

        total_uncompressed_size = 0
        for member in members:
            filename = member.filename or ""
            if not filename or filename.endswith("/"):
                continue
            if member.file_size < 0:
                raise ValueError("Kich thuoc tep trong goi cap nhat khong hop le.")
            total_uncompressed_size += member.file_size
            if total_uncompressed_size > max_total_size:
                raise ValueError("Goi cap nhat vuot qua gioi han kich thuoc cho phep.")
            if _is_symlink_member(member):
                raise ValueError("Goi cap nhat chua lien ket bieu tuong khong duoc phep.")
            parts = [part for part in Path(filename).parts if part not in {"", "."}]
            if any(part in {".."} for part in parts):
                raise ValueError("Goi cap nhat chua duong dan khong hop le.")
            root_name = (parts[0].lower() if parts else "")
            basename = (Path(filename).name or "").lower()
            if root_name in blocked_roots or basename in blocked_names:
                raise ValueError("Goi cap nhat chua tep hoac thu muc bi cam.")
            resolve_safe_path(destination, filename, allow_missing=True)

        archive.extractall(destination)


def generate_temporary_password(length=16):
    target_length = max(12, int(length or 0))
    while True:
        password = "".join(secrets.choice(_TEMP_PASSWORD_ALPHABET) for _ in range(target_length))
        if (
            any(ch.islower() for ch in password)
            and any(ch.isupper() for ch in password)
            and any(ch.isdigit() for ch in password)
            and any(not ch.isalnum() for ch in password)
        ):
            return password
