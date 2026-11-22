import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


RELEASE = Path(__file__).resolve().parents[1]


class PortableLauncherTests(unittest.TestCase):
    def launch(self, *, failure=None, release_variable=True):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / 'bin'
            binary.mkdir()
            staged = root / 'spool/slurm_script'
            staged.parent.mkdir()
            shutil.copy2(RELEASE / 'repro/full60_bf16.sbatch', staged)
            stub = '#!' + sys.executable + '\n' + '''import json, os, sys
from pathlib import Path
program = Path(sys.argv[0]).name
if program == 'scontrol':
    print('node0\\nnode1\\nnode2\\nnode3')
else:
    with open(os.environ['FULL60_TEST_CALLS'], 'a') as handle:
        handle.write(json.dumps(dict(program=program, args=sys.argv[1:]))+'\\n')
    if os.environ.get('FULL60_TEST_FAIL') in sys.argv[1:]:
        sys.exit(17)
'''
            for name in ('python', 'srun', 'scontrol'):
                path = binary / name
                path.write_text(stub)
                path.chmod(0o755)
            run = root / 'run'
            run.mkdir()
            log = root / 'calls.jsonl'
            environment = dict(os.environ, PATH=str(binary) + os.pathsep + os.environ['PATH'],
                FULL60_PYTHON=str(binary / 'python'), FULL60_RELEASE=str(RELEASE),
                FULL60_TEST_CALLS=str(log), FULL60_TEST_FAIL=failure or 'never-fail',
                SLURM_JOB_ID='synthetic-job', SLURM_JOB_NUM_NODES='4',
                SLURM_JOB_NODELIST='node[0-3]', SLURM_RESTART_COUNT='0')
            if not release_variable:
                environment.pop('FULL60_RELEASE')
            result = subprocess.run(['bash', str(staged), str(run), 'synthetic-binding'],
                env=environment, capture_output=True, text=True)
            calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
            return result, calls

    def test_slurm_spooled_script_uses_explicit_release(self):
        result, calls = self.launch()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(calls), 6)
        control = str(RELEASE / 'repro/full60_bf16.py')
        self.assertTrue(all(control in call['args'] for call in calls))
        inference = [call for call in calls if 'inference' in call['args']]
        self.assertEqual(len(inference), 1)

    def test_failed_node_admission_stops_before_workers(self):
        result, calls = self.launch(failure='node-preflight')
        self.assertEqual(result.returncode, 17)
        self.assertEqual(len(calls), 1)
        self.assertFalse(any('launch-node' in call['args'] for call in calls))

    def test_release_location_is_mandatory(self):
        result, calls = self.launch(release_variable=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, [])


if __name__ == '__main__':
    unittest.main()