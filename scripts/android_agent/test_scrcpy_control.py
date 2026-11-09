"""Offline regression for the child process stealing controller commands."""
from pathlib import Path
import subprocess
import sys
import unittest


class ScrcpyInputTests(unittest.TestCase):
    def test_adb_child_cannot_consume_parent_command_stream(self):
        # Give the parent a real command on fd0, then substitute a harmless
        # child that tries reading it. Without DEVNULL the child steals 'c'.
        probe = r'''
import subprocess, sys
from unittest.mock import Mock, patch
from scrcpy_control import ScrcpyControl
real_popen = subprocess.Popen
def child(_argv, **kwargs):
    return real_popen([sys.executable, '-c',
        'import sys; print(repr(sys.stdin.read(1)), flush=True)'], **kwargs)
sock = Mock()
sock.recv.return_value = b'\x00'
with patch.object(ScrcpyControl, '_adb', return_value=''), \
     patch('scrcpy_control.server_version', return_value='test'), \
     patch('scrcpy_control.socket.create_connection', return_value=sock), \
     patch('scrcpy_control.subprocess.Popen', side_effect=child):
    control = ScrcpyControl('offline-test')
    control.start()
    output, _ = control.proc.communicate(timeout=3)
    print(output.decode().strip())
    print(sys.stdin.readline().strip())
'''
        result = subprocess.run([sys.executable, '-c', probe],
            cwd=Path(__file__).parent, input='controller-command\n',
            capture_output=True, text=True, timeout=5, check=True)
        self.assertEqual(result.stdout.splitlines(), ["''", 'controller-command'])


if __name__ == '__main__':
    unittest.main()
