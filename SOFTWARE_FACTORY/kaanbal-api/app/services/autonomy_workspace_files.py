"""Standalone, credential-free file protocol executed in a workbench container.

The API sends this trusted source to Python in isolated mode. Repository Python
modules are never imported by this protocol.
"""
import base64
import io
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
import zipfile

MAX_FILE = 1024 * 1024
MAX_TOTAL = 2 * 1024 * 1024


def allowed(name):
    parts = name.split("/")
    return bool(name) and len(name) <= 500 and "\\" not in name and not PurePosixPath(name).is_absolute() and all(
        p not in ("", ".", "..") and p.lower() != ".git" and not p.lower().startswith(".env")
        and not p.lower().endswith((".pem", ".key")) and not any(ord(c) < 32 for c in p)
        for p in parts)


def file_path(root, name):
    if not allowed(name):
        raise ValueError("invalid path")
    target = root / name
    for path in (target, *target.parents):
        if path == root:
            break
        if path.is_symlink():
            raise ValueError("symlinks are not supported")
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError("path outside workspace")
    return target


def git(root, *args):
    env = {"PATH": os.defpath, "HOME": "/tmp", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
    return subprocess.check_output(["git", "-c", "core.hooksPath=" + os.devnull, "-c", "core.fsmonitor=false", "-c", "core.quotePath=false", "-C", str(root), *args], env=env, stderr=subprocess.PIPE, timeout=30)


def initialize(root, archive):
    if root.exists():
        raise ValueError("workspace already initialized")
    root.mkdir(parents=True)
    total, count, seen, archive_root = 0, 0, set(), None
    with zipfile.ZipFile(io.BytesIO(base64.b64decode(archive, validate=True))) as source:
        for entry in source.infolist():
            parts = entry.filename.split("/", 1)
            if len(parts) != 2 or not parts[1] or entry.is_dir():
                continue
            if archive_root is None:
                archive_root = parts[0]
            if parts[0] != archive_root:
                raise ValueError("multiple archive roots")
            name = parts[1]
            if not allowed(name):
                # Do not read credential files, even if someone committed them.
                if any(p.lower().startswith(".env") or p.lower().endswith((".pem", ".key")) for p in name.split("/")):
                    continue
                raise ValueError("unsafe archive path")
            mode = entry.external_attr >> 16
            if stat.S_ISLNK(mode) or name in seen:
                raise ValueError("symlink or duplicate entry")
            seen.add(name)
            total += entry.file_size
            count += 1
            if total > 100 * 1024 * 1024 or count > 10000 or entry.file_size > 10 * 1024 * 1024:
                raise ValueError("archive limits exceeded")
            target = file_path(root, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read(entry))
            target.chmod(0o755 if mode & 0o111 else 0o644)
    git(root, "init", "--quiet")
    git(root, "add", "--all")
    git(root, "-c", "user.name=Kaanbal", "-c", "user.email=agent@localhost", "commit", "--quiet", "--allow-empty", "-m", "Workspace baseline")
    return {"files": count, "bytes": total, "baseline": git(root, "rev-parse", "HEAD").decode().strip()}


def read_file(root, name):
    target = file_path(root, name)
    if not target.is_file() or target.stat().st_size > MAX_FILE:
        raise ValueError("missing file or file limit exceeded")
    with target.open("r", encoding="utf-8") as handle:
        content = handle.read(MAX_FILE + 1)
    if len(content.encode("utf-8")) > MAX_FILE or "\x00" in content:
        raise ValueError("not a supported text file")
    return content


def snapshot(root, baseline):
    if len(baseline) != 40 or any(c not in "0123456789abcdef" for c in baseline):
        raise ValueError("invalid baseline")
    changed = git(root, "diff", "--no-ext-diff", "--no-textconv", "--no-renames", "--name-only", "-z", baseline, "--").decode().split("\x00")
    untracked = git(root, "ls-files", "--others", "--exclude-standard", "-z").decode().split("\x00")
    paths = sorted(set(changed + untracked) - {""})
    if len(paths) > 100:
        raise ValueError("too many changed files")
    changes, total = [], 0
    for name in paths:
        target = file_path(root, name)
        content = read_file(root, name) if target.exists() else None
        total += len(content.encode("utf-8")) if content is not None else 0
        if total > MAX_TOTAL:
            raise ValueError("change size exceeded")
        mode = "100755" if target.exists() and target.stat().st_mode & 0o111 else "100644"
        changes.append({"path": name, "mode": mode, "content": content})
    return {"changes": changes}


def dispatch(payload, root=Path("/workspace/repo")):
    action = payload["action"]
    if action == "initialize":
        return initialize(root, payload["archive"])
    if action == "read":
        return {"path": payload["path"], "content": read_file(root, payload["path"])}
    if action == "write":
        target = file_path(root, payload["path"])
        content = payload.get("content")
        if content is None:
            if target.exists():
                target.unlink()
        else:
            if not isinstance(content, str) or len(content.encode()) > MAX_FILE or "\x00" in content:
                raise ValueError("file size or format")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        return {"path": payload["path"], "deleted": content is None}
    if action == "snapshot":
        return snapshot(root, payload["baseline"])
    if action == "list":
        names = git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z").decode().split("\x00")
        return {"files": sorted({n for n in names if n and allowed(n)})[:10000]}
    raise ValueError("unknown file action")


if __name__ == "__main__":
    print(json.dumps(dispatch(json.loads(sys.stdin.readline())), ensure_ascii=False))
