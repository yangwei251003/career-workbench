"""Stop only the verified server belonging to this directory, without killing processes."""
import json
import os
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent


def main():
    try:
        runtime = json.loads((BASE / 'data' / 'runtime.json').read_text(encoding='utf-8'))
        port = runtime['port']
        if type(port) is not int:
            raise ValueError('Invalid port')
        url = f'http://127.0.0.1:{port}'
        with urllib.request.urlopen(url + '/api/health', timeout=2) as r:
            health = json.load(r)
        if health.get('app') != 'career-workbench' or Path(health.get('root', '')).resolve() != BASE or Path(health.get('dataRoot', '')).resolve() != BASE / 'data':
            print('当前端口属于其他程序，没有执行停止。')
            return
        with urllib.request.urlopen(url + '/api/bootstrap', timeout=2) as r:
            token = json.load(r)['token']
        request = urllib.request.Request(url + '/api/shutdown', data=b'{}', headers={'Content-Type': 'application/json', 'X-App-Token': token, 'Origin': url})
        with urllib.request.urlopen(request, timeout=3) as r:
            message = json.load(r)['message']
        # Wait for the verified service to release its files, without terminating it.
        if os.name == 'nt' and type(runtime.get('pid')) is int:
            import ctypes
            from ctypes import wintypes
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
            kernel.WaitForSingleObject.restype = wintypes.DWORD
            kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
            handle = kernel.OpenProcess(0x00100000, False, runtime['pid'])
            if handle:
                try:
                    if kernel.WaitForSingleObject(handle, 5000) != 0:
                        print('停止请求已送达，服务仍在退出；请稍后再打开工作台。')
                        return
                finally:
                    kernel.CloseHandle(handle)
        print(message)
    except (OSError, ValueError, KeyError):
        print('本目录工作台没有运行，或已停止。')


if __name__ == '__main__':
    main()
