"""Launch embed.py on both Kaggle T4s (one process each)."""
import subprocess, os
procs = []
for g in (0, 1):
    env = dict(os.environ, CUDA_VISIBLE_DEVICES=str(g))
    procs.append(subprocess.Popen(f'cd /kaggle/working && python embed.py {g} 2 > log{g}.txt 2>&1', shell=True, env=env))
for p in procs: p.wait()
print('return codes', [p.returncode for p in procs])
