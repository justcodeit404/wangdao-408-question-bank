#!/usr/bin/env python3
"""带 gzip 支持的静态服务器，用于本地预览 math-bank/。

对 .json/.js/.css/.html 自动 gzip 后返回，显著降低 data-*.json 传输体积。
用法（在项目根目录执行）：
    python scripts/serve_bank.py [port]
默认端口 8080。
"""
import gzip
import io
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ROOT = PROJECT_ROOT / 'math-bank'
COMPRESSIBLE = {'.html', '.css', '.js', '.json', '.svg'}


class GzipStaticHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self):
        # 简单安全头
        self.send_header('Cache-Control', 'no-cache')
        super().end_headers()

    def _handle_image(self):
        """处理 /assets/pdf_images* 与 /crops* 请求：这些目录与 math-bank 同级，不在 ROOT 下。"""
        rel_path = self.path.lstrip('/').split('?')[0]
        if rel_path.startswith('assets/pdf_images') or rel_path.startswith('crops'):
            path = PROJECT_ROOT / rel_path
            if path.is_file():
                self.send_raw(path)
                return True
        return False

    def do_HEAD(self):
        if self._handle_image():
            return
        super().do_HEAD()

    def do_GET(self):
        if self._handle_image():
            return

        rel_path = self.path.lstrip('/').split('?')[0]
        path = Path(ROOT) / rel_path
        suffix = path.suffix.lower()

        accept_encoding = self.headers.get('Accept-Encoding', '')
        if 'gzip' in accept_encoding and suffix in COMPRESSIBLE and path.is_file():
            self.send_gzip(path)
        else:
            super().do_GET()

    def send_raw(self, path):
        data = path.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', self.guess_type(str(path)))
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_gzip(self, path):
        gz_path = Path(str(path) + '.gz')
        # 优先使用构建时预压缩的 .gz 文件，避免每次请求都实时压缩
        if gz_path.is_file():
            compressed = gz_path.read_bytes()
        else:
            data = path.read_bytes()
            buf = io.BytesIO()
            with gzip.GzipFile(fileobj=buf, mode='wb', compresslevel=9) as f:
                f.write(data)
            compressed = buf.getvalue()

        self.send_response(200)
        self.send_header('Content-Type', self.guess_type(str(path)))
        self.send_header('Content-Encoding', 'gzip')
        self.send_header('Content-Length', str(len(compressed)))
        self.send_header('Vary', 'Accept-Encoding')
        self.end_headers()
        self.wfile.write(compressed)

    def log_message(self, format, *args):
        # 把访问日志输出到 stderr，并标注传输大小
        sys.stderr.write(f"[{self.log_date_time_string()}] {args[0]}\n")


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    server = ThreadingHTTPServer(('127.0.0.1', port), GzipStaticHandler)
    print(f'Serving math-bank/ at http://127.0.0.1:{port}/')
    print('Press Ctrl+C to stop.')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nStopped.')


if __name__ == '__main__':
    main()
