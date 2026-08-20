#!/usr/bin/env python3
"""Prepare and start KnowledgeMapNotes on Windows, Linux, or macOS."""

from __future__ import annotations

import hashlib
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import venv
from itertools import chain
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parent
BACKEND_DIR = ROOT / "backend"
FRONTEND_DIR = ROOT / "frontend"
VENV_DIR = ROOT / ".venv"
MODELS_DIR = ROOT / "models"
PYPI_INDEX = "https://pypi.tuna.tsinghua.edu.cn/simple"
PYPI_FALLBACK_INDEX = "https://pypi.org/simple"
TORCH_FIND_LINKS = "https://mirrors.aliyun.com/pytorch-wheels/cpu/"
DEPENDENCY_SETUP_VERSION = "2"
MODEL_SPECS = (
    ("BAAI/bge-base-zh", MODELS_DIR / "bge-base-zh"),
    ("BAAI/bge-reranker-base", MODELS_DIR / "bge-reranker-base"),
)


def _run(command: list[str], *, cwd: Path = ROOT) -> None:
    print(f"[setup] {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def _venv_python() -> Path:
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def _ensure_virtualenv() -> Path:
    python = _venv_python()
    if not python.exists():
        if sys.version_info < (3, 10):
            raise RuntimeError("Python 3.10 or newer is required.")
        print(f"[setup] Creating virtual environment at {VENV_DIR}", flush=True)
        venv.EnvBuilder(with_pip=True).create(VENV_DIR)
    else:
        result = subprocess.run(
            [str(python), "--version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"The existing virtual environment is unusable: {VENV_DIR}. "
                "Remove or rename it, then run this launcher again."
            )

    pip_check = subprocess.run(
        [str(python), "-m", "pip", "--version"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if pip_check.returncode != 0:
        _run([str(python), "-m", "ensurepip", "--upgrade"])
    return python


def _dependency_fingerprint(python: Path) -> str:
    digest = hashlib.sha256()
    digest.update((BACKEND_DIR / "requirements.txt").read_bytes())
    digest.update(DEPENDENCY_SETUP_VERSION.encode("ascii"))
    digest.update(platform.system().encode("ascii"))
    version = subprocess.check_output(
        [str(python), "-c", "import sys; print(sys.version)"], text=True
    )
    digest.update(version.encode("utf-8"))
    return digest.hexdigest()


def _ensure_python_dependencies(python: Path) -> None:
    marker = VENV_DIR / ".kmn-dependencies.sha256"
    fingerprint = _dependency_fingerprint(python)
    imports_work = subprocess.run(
        [str(python), "-c", "import fastapi, modelscope, sentence_transformers, torch"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0
    if imports_work and marker.exists() and marker.read_text().strip() == fingerprint:
        print("[setup] Python dependencies are up to date.", flush=True)
        return

    common_indexes = [
        "--index-url",
        PYPI_INDEX,
        "--extra-index-url",
        PYPI_FALLBACK_INDEX,
    ]
    pip = [str(python), "-m", "pip"]
    env = os.environ.copy()
    env["PIP_ROOT_USER_ACTION"] = "ignore"
    print("[setup] Installing Python dependencies. This can take a while.", flush=True)
    subprocess.run(pip + ["install", "--upgrade", "pip"] + common_indexes, check=True, env=env)
    subprocess.run(
        pip + ["install", "modelscope"] + common_indexes,
        check=True,
        env=env,
    )
    subprocess.run(
        pip + ["install", "torch", "--find-links", TORCH_FIND_LINKS] + common_indexes,
        check=True,
        env=env,
    )
    subprocess.run(
        pip
        + ["install", "-r", str(BACKEND_DIR / "requirements.txt")]
        + common_indexes,
        check=True,
        env=env,
    )
    marker.write_text(fingerprint + "\n", encoding="utf-8")


def _model_is_complete(model_dir: Path) -> bool:
    return (
        (model_dir / "config.json").is_file()
        and any(model_dir.rglob("*.safetensors"))
        and (model_dir / ".modelscope-complete").is_file()
    )


def _modelscope_command() -> Path:
    name = "modelscope.exe" if os.name == "nt" else "modelscope"
    command = Path(sys.executable).parent / name
    if not command.is_file():
        raise RuntimeError(f"ModelScope command was not installed at {command}")
    return command


def _ensure_models() -> None:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    command = _modelscope_command()
    for model_id, model_dir in MODEL_SPECS:
        if _model_is_complete(model_dir):
            print(f"[setup] Model is ready: {model_id}", flush=True)
            continue
        print(f"[setup] Downloading {model_id} to {model_dir}", flush=True)
        _run(
            [
                str(command),
                "download",
                model_id,
                "--local_dir",
                str(model_dir),
                "--exclude",
                "*.bin",
                "*.onnx",
            ]
        )
        if not (model_dir / "config.json").is_file() or not any(
            model_dir.rglob("*.safetensors")
        ):
            raise RuntimeError(f"Model download is incomplete: {model_dir}")
        (model_dir / ".modelscope-complete").write_text(model_id + "\n", encoding="utf-8")


def _dotenv_value(value: Path) -> str:
    normalized = value.resolve().as_posix().replace('"', '\\"')
    return f'"{normalized}"'


def _update_env_file() -> None:
    env_file = BACKEND_DIR / ".env"
    if not env_file.exists():
        shutil.copyfile(BACKEND_DIR / ".env.example", env_file)

    updates = {
        "IS_USE_LOCAL": "True",
        "EMBEDDINGS_PATH": _dotenv_value(MODEL_SPECS[0][1]),
        "RERANK_MODEL": _dotenv_value(MODEL_SPECS[1][1]),
    }
    lines = env_file.read_text(encoding="utf-8").splitlines()
    found: set[str] = set()
    updated_lines: list[str] = []
    assignment = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")
    for line in lines:
        match = assignment.match(line)
        key = match.group(1) if match else None
        if key in updates:
            if key not in found:
                updated_lines.append(f"{key}={updates[key]}")
                found.add(key)
            continue
        updated_lines.append(line)
    for key, value in updates.items():
        if key not in found:
            updated_lines.append(f"{key}={value}")
    env_file.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")
    print(f"[setup] Local model paths updated in {env_file}", flush=True)


def _hash_files(paths: Iterable[Path], *, relative_to: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        if not path.is_file():
            continue
        digest.update(path.relative_to(relative_to).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _frontend_files() -> Iterable[Path]:
    excluded = {"node_modules", "dist"}
    for path in FRONTEND_DIR.rglob("*"):
        if path.is_file() and not excluded.intersection(path.relative_to(FRONTEND_DIR).parts):
            yield path


def _npm_command() -> str:
    command = shutil.which("npm")
    if not command:
        raise RuntimeError("Node.js 18 or newer is required to build the frontend.")
    version = subprocess.check_output([command, "--version"], text=True).strip()
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node.js 18 or newer is required to build the frontend.")
    node_version = subprocess.check_output([node, "--version"], text=True).strip()
    match = re.match(r"v?(\d+)", node_version)
    if not match or int(match.group(1)) < 18:
        raise RuntimeError(f"Node.js 18 or newer is required; found {node_version}.")
    print(f"[setup] Using Node.js {node_version} and npm {version}.", flush=True)
    return command


def _ensure_frontend() -> None:
    build_marker = FRONTEND_DIR / "dist" / ".kmn-build.sha256"
    frontend_hash = _hash_files(_frontend_files(), relative_to=FRONTEND_DIR)
    if (
        (FRONTEND_DIR / "dist" / "index.html").is_file()
        and build_marker.exists()
        and build_marker.read_text().strip() == frontend_hash
    ):
        print("[setup] Frontend build is up to date.", flush=True)
        return

    npm = _npm_command()
    lock_file = FRONTEND_DIR / "package-lock.json"
    lock_hash = hashlib.sha256(lock_file.read_bytes()).hexdigest()
    install_marker = FRONTEND_DIR / "node_modules" / ".kmn-lock.sha256"
    if not install_marker.exists() or install_marker.read_text().strip() != lock_hash:
        _run([npm, "ci"], cwd=FRONTEND_DIR)
        install_marker.write_text(lock_hash + "\n", encoding="utf-8")
    _run([npm, "run", "build"], cwd=FRONTEND_DIR)
    build_marker.write_text(frontend_hash + "\n", encoding="utf-8")


def _port_is_available(host: str, port: int) -> bool:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    address = (host, port, 0, 0) if family == socket.AF_INET6 else (host, port)
    try:
        with socket.socket(family, socket.SOCK_STREAM) as candidate:
            if os.name == "nt":
                candidate.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            candidate.bind(address)
    except socket.gaierror as exc:
        raise RuntimeError(f"HOST could not be resolved: {host!r}.") from exc
    except OSError:
        return False
    return True


def _find_available_port(host: str, preferred_port: int) -> int:
    if not 1 <= preferred_port <= 65535:
        raise RuntimeError(f"PORT must be between 1 and 65535; found {preferred_port}.")
    candidates = chain(range(preferred_port, 65536), range(1024, preferred_port))
    for port in candidates:
        if _port_is_available(host, port):
            return port
    raise RuntimeError(f"No available TCP port was found for host {host}.")


def _server_address() -> tuple[str, int]:
    from dotenv import dotenv_values

    file_values = dotenv_values(BACKEND_DIR / ".env")
    host = os.environ.get("HOST") or file_values.get("HOST") or "127.0.0.1"
    port_value = os.environ.get("PORT") or file_values.get("PORT") or "8000"
    try:
        preferred_port = int(port_value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"PORT must be an integer; found {port_value!r}.") from exc
    return str(host), preferred_port


def _access_url(host: str, port: int) -> str:
    if host in {"0.0.0.0", "::", "[::]"}:
        display_host = "127.0.0.1"
    elif ":" in host and not host.startswith("["):
        display_host = f"[{host}]"
    else:
        display_host = host
    return f"http://{display_host}:{port}"


def _start_backend() -> int:
    env = os.environ.copy()
    env["IS_USE_LOCAL"] = "True"
    env["EMBEDDINGS_PATH"] = str(MODEL_SPECS[0][1].resolve())
    env["RERANK_MODEL"] = str(MODEL_SPECS[1][1].resolve())
    env["FRONTEND_DIST"] = str((FRONTEND_DIR / "dist").resolve())
    host, preferred_port = _server_address()
    port = _find_available_port(host, preferred_port)
    env["HOST"] = host
    env["PORT"] = str(port)
    if port != preferred_port:
        print(
            f"[start] Port {preferred_port} is already in use; using port {port}.",
            flush=True,
        )
    url = _access_url(host, port)
    print(f"[start] KnowledgeMapNotes is starting at {url}", flush=True)
    process = subprocess.Popen([sys.executable, "main.py"], cwd=BACKEND_DIR, env=env)
    try:
        return process.wait()
    except KeyboardInterrupt:
        process.terminate()
        try:
            return process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            return process.wait()


def _prepared_main() -> int:
    _ensure_models()
    _update_env_file()
    _ensure_frontend()
    return _start_backend()


def main() -> int:
    if "--prepared" in sys.argv[1:]:
        return _prepared_main()
    python = _ensure_virtualenv()
    _ensure_python_dependencies(python)
    try:
        return subprocess.call([str(python), str(Path(__file__).resolve()), "--prepared"])
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        raise SystemExit(1)
