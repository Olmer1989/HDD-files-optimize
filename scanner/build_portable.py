"""Build a self-contained Windows x64 ZIP from an official Python package."""
import hashlib
import json
from pathlib import Path
import re
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
    app_version = re.search(r"^APP_VERSION = '([0-9.]+)'", (BASE / 'scanner' / 'portable.py').read_text(encoding='utf-8'), re.M).group(1)
    # Staged in dist\_build, never in dist\HDDScanner-Windows-x64: a scanner may be
    # running from that folder, and wiping it once deleted the app of a live scan.
    folder = dist / '_build' / 'HDDScanner-Windows-x64'
    if folder.exists():
        shutil.rmtree(folder)  # build output only; avoids stale files from older versions
    runtime = folder / 'runtime'
    runtime.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as package:
        package.extractall(runtime)
    # Isolated interpreter: add our sibling app folder, no global packages.
    (runtime / 'python313._pth').write_text('python313.zip\n.\n../app\n', encoding='ascii')
    app = folder / 'app'
    app.mkdir(exist_ok=True)
    for name in ['portable.py', 'portable_base.py', 'portable_jobs.py', 'inventory.py', 'hash_files.py', 'build_selection.py', 'rescan.py', 'winpath.py', 'fileinfo.py', 'test_rescan.py',
                 'test_portable.py', 'test_inventory.py', 'test_selection.py', 'test_hash_files.py']:
        shutil.copy2(BASE / 'scanner' / name, app / name)
    shutil.copy2(BASE / 'scanner' / 'PORTABLE.md', folder / 'READ_ME.md')
    (app / 'gui.ps1').write_text((BASE / 'scanner' / 'gui.ps1').read_text(encoding='utf-8-sig'), encoding='utf-8-sig')
    (folder / 'START.cmd').write_text('@echo off\r\npowershell.exe -NoProfile -STA -ExecutionPolicy Bypass -File "%~dp0app\\gui.ps1"\r\nif errorlevel 1 pause\r\n', encoding='ascii')
    (folder / 'CLI.cmd').write_text('@echo off\r\n"%~dp0runtime\\python.exe" -X utf8 -B "%~dp0app\\portable.py" %*\r\necho.\r\npause\r\n', encoding='ascii')
    (folder / 'SELF_TEST.cmd').write_text('@echo off\r\ncd /d "%~dp0app"\r\n"%~dp0runtime\\python.exe" -X utf8 -B -m unittest discover -v\r\npause\r\n', encoding='ascii')
    (folder / 'GUI_TEST.cmd').write_text('@echo off\r\npowershell.exe -NoProfile -STA -ExecutionPolicy Bypass -File "%~dp0app\\gui.ps1" -IntegrationTest\r\npause\r\n', encoding='ascii')
    (folder / 'runtime_source.json').write_text(json.dumps({'url': URL, 'sha256': SHA256,
                    'source': f'https://www.python.org/downloads/release/python-{VERSION.replace(".", "")}/'}, indent=2), encoding='utf-8')
    # One archive per release, named by version, to avoid two "different" copies.
    result = shutil.make_archive(str(dist / f'HDDScanner-Windows-x64-{app_version}'), 'zip', folder.parent, folder.name)
    print(result)

if __name__ == '__main__':
    main()
