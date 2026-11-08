"""Build a self-contained Windows x64 ZIP from an official Python package."""
import hashlib
import json
from pathlib import Path
import shutil
import urllib.request
import zipfile

BASE = Path(__file__).resolve().parents[1]
VERSION = '3.13.17'
URL = f'https://www.python.org/ftp/python/{VERSION}/python-{VERSION}-embed-amd64.zip'
SHA256 = '9e35319bffedab8b36ad44d8f377cb4f1733bcec257a0b6d04d94f01486ddb38'

def main():
    dist = BASE / 'dist'
    dist.mkdir(exist_ok=True)
    archive = dist / f'python-{VERSION}-embed-amd64.zip'
    if not archive.exists():
        with urllib.request.urlopen(URL, timeout=60) as response, archive.open('wb') as output:
            shutil.copyfileobj(response, output)
    actual = hashlib.sha256(archive.read_bytes()).hexdigest()
    if actual != SHA256:
        raise RuntimeError('Official Python archive checksum mismatch')
    folder = dist / 'HDDScanner-Windows-x64'
    runtime = folder / 'runtime'
    runtime.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as package:
        package.extractall(runtime)
    # Isolated interpreter: add our sibling app folder, no global packages.
    (runtime / 'python313._pth').write_text('python313.zip\n.\n../app\n', encoding='ascii')
    app = folder / 'app'
    app.mkdir(exist_ok=True)
    for name in ['portable.py', 'inventory.py', 'hash_files.py', 'build_selection.py',
                 'test_portable.py', 'test_inventory.py', 'test_selection.py', 'test_hash_files.py']:
        shutil.copy2(BASE / 'scanner' / name, app / name)
    shutil.copy2(BASE / 'scanner' / 'PORTABLE.md', folder / 'READ_ME.md')
    (folder / 'START.cmd').write_text('@echo off\r\n"%~dp0runtime\\python.exe" -X utf8 -B "%~dp0app\\portable.py" %*\r\necho.\r\npause\r\n', encoding='ascii')
    (folder / 'SELF_TEST.cmd').write_text('@echo off\r\ncd /d "%~dp0app"\r\n"%~dp0runtime\\python.exe" -X utf8 -B -m unittest discover -v\r\npause\r\n', encoding='ascii')
    (folder / 'runtime_source.json').write_text(json.dumps({'url': URL, 'sha256': SHA256,
                    'source': f'https://www.python.org/downloads/release/python-{VERSION.replace(".", "")}/'}, indent=2), encoding='utf-8')
    result = shutil.make_archive(str(dist / 'HDDScanner-Windows-x64'), 'zip', folder.parent, folder.name)
    print(result)

if __name__ == '__main__':
    main()
