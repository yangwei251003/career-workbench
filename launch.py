"""Start/reopen this local app without installing anything."""
from pathlib import Path
import ctypes
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser

BASE = Path(__file__).resolve().parent


def health(port):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/health', timeout=1) as r:
            data = json.load(r)
        if data.get('app') == 'career-workbench' and Path(data.get('root', '')).resolve() == BASE and Path(data.get('dataRoot', '')).resolve() == BASE / 'data':
            return True
    except Exception:
        pass
    return False


def main():
    data_dir = BASE / 'data'
    runtime = data_dir / 'runtime.json'
    if runtime.exists():
        try:
            port = json.loads(runtime.read_text(encoding='utf-8'))['port']
            if type(port) is int and health(port):
                webbrowser.open(f'http://127.0.0.1:{port}')
                return
        except Exception:
            pass
    port = None
    for candidate in range(8026, 8047):
        if health(candidate):
            webbrowser.open(f'http://127.0.0.1:{candidate}')
            return
        try:
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', candidate))
            port = candidate
            break
        except OSError:
            continue
    if port is None:
        raise RuntimeError('本地端口暂不可用，请稍后重试。')
    data_dir.mkdir(parents=True, exist_ok=True)
    kwargs = {'cwd': str(BASE), 'stdin': subprocess.DEVNULL}
    if os.name == 'nt':
        kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
    with (data_dir / '运行日志.txt').open('ab') as log:
        process = subprocess.Popen([sys.executable, str(BASE / 'server.py'), '--port', str(port)], stdout=log, stderr=log, **kwargs)
    for _ in range(50):
        if health(port):
            webbrowser.open(f'http://127.0.0.1:{port}')
            return
        if process.poll() is not None:
            break
        time.sleep(.2)
    raise RuntimeError('启动未完成。请查看工作台 data 文件夹中的运行日志；现有记录不会自动重置。')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        if os.name == 'nt':
            ctypes.windll.user32.MessageBoxW(0, str(exc), '职业发展工作台', 0x10)
        else:
            print(str(exc), file=sys.stderr)
        sys.exit(1)
