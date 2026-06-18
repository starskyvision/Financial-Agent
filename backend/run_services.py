#!/usr/bin/env python
"""
Financial Agent 服务启动器。

自动清理旧进程，按顺序启动：Docker → Backend → Celery → (可选) Frontend。

用法:
    python run_services.py              # 启动全部（除前端）
    python run_services.py --frontend   # 包含前端
    python run_services.py --kill       # 仅清理旧进程
"""

import os
import sys
import time
import signal
import socket
import subprocess
import argparse

ROOT = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(ROOT)


def _is_port_in_use(port: int) -> bool:
    """检查端口是否被占用。"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", port))
        sock.close()
        return False
    except OSError:
        return True


def kill_old():
    """清理所有旧进程。"""
    import platform
    killed = []

    if platform.system() == "Windows":
        # 按端口杀进程
        for port in [8000, 5173]:
            if _is_port_in_use(port):
                try:
                    result = subprocess.run(
                        ["cmd", "/c", f'for /f "tokens=5" %a in (\'netstat -ano ^| findstr :{port} ^| findstr LISTENING\') do taskkill /F /PID %a'],
                        capture_output=True, text=True, shell=True,
                    )
                    if result.returncode == 0:
                        killed.append(f"port {port}")
                except Exception:
                    pass

        # 杀 Celery
        try:
            subprocess.run(["taskkill", "/F", "/IM", "celery.exe"],
                          capture_output=True)
        except Exception:
            pass
    else:
        # Unix
        try:
            subprocess.run(["pkill", "-f", "celery"], capture_output=True)
            subprocess.run(["pkill", "-f", "uvicorn"], capture_output=True)
        except Exception:
            pass

    time.sleep(2)
    if killed:
        print(f"Killed: {', '.join(killed)}")


def start_docker():
    """启动 Docker 容器。"""
    try:
        subprocess.run(
            ["docker", "start", "financial-agent-redis-1", "financial-agent-postgres-1"],
            capture_output=True, check=True,
        )
        print("Docker containers started")
        time.sleep(3)
    except subprocess.CalledProcessError:
        print("WARNING: Docker containers may not be running. Start with: docker compose up -d")


def start_backend():
    """启动后端（后台进程）。"""
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def start_celery():
    """启动 Celery Worker（后台进程）。"""
    pid_file = os.path.join(ROOT, ".celery_worker.pid")
    if os.path.exists(pid_file):
        os.remove(pid_file)

    return subprocess.Popen(
        [sys.executable, "-m", "celery", "-A", "services.task_queue.celery_app",
         "worker", "--loglevel=info", "-P", "solo", "-n", "worker1"],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def start_frontend():
    """启动前端（后台进程）。"""
    return subprocess.Popen(
        ["npm", "run", "dev"],
        cwd=os.path.join(PROJECT, "frontend"),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def wait_backend(timeout: int = 30) -> bool:
    """等待后端就绪。"""
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen("http://localhost:8000/api/v1/health", timeout=2)
            return True
        except Exception:
            time.sleep(1)
    return False


def main():
    parser = argparse.ArgumentParser(description="Financial Agent Service Launcher")
    parser.add_argument("--frontend", action="store_true", help="Also start frontend dev server")
    parser.add_argument("--kill", action="store_true", help="Only kill old processes, then exit")
    args = parser.parse_args()

    # 1. Kill old processes
    print("=== Cleaning up old processes ===")
    kill_old()

    if args.kill:
        print("Done. All old processes killed.")
        return

    # 2. Docker
    print("=== Starting Docker containers ===")
    start_docker()

    # 3. Backend
    print("=== Starting Backend (port 8000) ===")
    backend = start_backend()
    print("Waiting for backend warm-up (embedder model loading)...")
    if not wait_backend():
        print("ERROR: Backend failed to start within 30 seconds")
        backend.kill()
        sys.exit(1)
    print("Backend ready")

    # 4. Celery
    print("=== Starting Celery Worker (worker1) ===")
    celery = start_celery()
    time.sleep(4)
    print("Celery worker1 ready")

    # 5. Frontend (optional)
    if args.frontend:
        print("=== Starting Frontend (port 5173) ===")
        start_frontend()
        time.sleep(5)
        print("Frontend ready")

    print()
    print("=" * 50)
    print("  All services started!")
    print(f"  Backend:  http://localhost:8000")
    print(f"  Docs:     http://localhost:8000/docs")
    if args.frontend:
        print(f"  Frontend: http://localhost:5173")
    print(f"  Celery:   worker1")
    print("=" * 50)
    print()
    print("Press Ctrl+C to stop all services.")

    # Wait for interrupt
    try:
        signal.pause()
    except AttributeError:
        # Windows doesn't have signal.pause
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass

    print("\nShutting down...")
    for proc in [backend, celery]:
        if proc and proc.poll() is None:
            proc.terminate()
    print("Done.")


if __name__ == "__main__":
    main()
