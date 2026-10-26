"""Build the privacy-safe read-only handbook for GitHub Pages."""
from pathlib import Path
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def main():
    subprocess.run([sys.executable, str(ROOT / 'build_delivery.py')], check=True, cwd=ROOT)
    html = (ROOT / '阅读总览.html').read_text(encoding='utf-8')
    repository = os.environ.get('GITHUB_REPOSITORY', 'yangwei251003/career-workbench')
    base = f'https://github.com/{repository}/blob/main/'
    html = html.replace('href="README.md"', f'href="{base}README.md"')
    html = html.replace('href="docs/', f'href="{base}docs/')
    # The handbook already contains all text, CSS and JavaScript in one file.
    output = ROOT / '_site'
    output.mkdir(exist_ok=True)
    (output / 'index.html').write_text(html, encoding='utf-8')
    (output / '.nojekyll').write_text('', encoding='utf-8')
    print('Built _site/index.html: static handbook only; no personal runtime records.')


if __name__ == '__main__':
    main()
