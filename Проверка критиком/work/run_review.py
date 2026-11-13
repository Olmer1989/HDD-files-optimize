"""Run original tests and independent probes on the accompanying review package."""
import os
from pathlib import Path
import subprocess
import sys

base=Path(__file__).resolve().parent
package=base/'review-package'
env=dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1')

def run(title,args,cwd):
    print('\n'+title,flush=True)
    p=subprocess.run(args,cwd=cwd,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    print(p.stdout.decode('utf-8',errors='replace').replace('\r\r\n','\n').replace('\r\n','\n'),end='',flush=True)
    print('Exit code:',p.returncode,flush=True)

print('Independent project review, 2026-11-13. Python:',sys.version.split()[0],flush=True)
print('All write operations use synthetic temporary files. Real disks are not scanned.',flush=True)
run('Original documented catalog command (import failure expected in this package)',
    [sys.executable,'-m','unittest','test_hashbase.py','test_recovery_plan.py'],package/'2 Программа быстрых ответов')
run('Original scanner tests',[sys.executable,'-m','unittest','discover','-p','test_*.py'],package/'4 Сканер')
code="import sys,types,unittest; from pathlib import Path; p=Path.cwd(); sys.path.insert(0,str(p)); m=types.ModuleType('catalog'); m.__path__=[str(p)]; sys.modules['catalog']=m; r=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromName('test_recovery_plan')); raise SystemExit(not r.wasSuccessful())"
run('Recovery tests after explicit package-path adaptation',[sys.executable,'-c',code],package/'2 Программа быстрых ответов')
run('Dependency isolation probe (openpyxl import failure expected)',[sys.executable,'-S','hashbase.py','--help'],package/'2 Программа быстрых ответов')
run('Independent regression probes (OK means the reported defects were reproduced)',[sys.executable,str(base/'review_cases.py')],base)
print('\nScope: original >2 GiB copy test and live GUI were not executed. Copy behavior was tested with small synthetic files in Windows PowerShell.',flush=True)
