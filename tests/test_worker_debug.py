"""On-demand diagnostics stay confined to the worker's stderr."""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agent'))
import mlx_worker as W

def test_stack_signal_is_explicit_and_has_no_locals():
    with patch('faulthandler.register') as register:
        assert W.enable_stack_dumps()
        register.assert_called_once_with(W.signal.SIGUSR1,file=W.sys.stderr,all_threads=True)

def test_no_signal_host_fails_soft():
    with patch.object(W,'signal',SimpleNamespace()),patch('faulthandler.register') as register:
        assert not W.enable_stack_dumps()
        register.assert_not_called()

def test_diagnostic_permission_failure_does_not_prevent_startup():
    with patch('faulthandler.register',side_effect=OSError('unavailable')):
        assert not W.enable_stack_dumps()
