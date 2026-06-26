import os
import subprocess
from app import vectorize as vz


def test_vendor_binaries_exist():
    assert os.path.exists(vz.POTRACE_EXE)
    d = os.path.dirname(vz.POTRACE_EXE)
    assert os.path.exists(os.path.join(d, "libpotrace-0.dll"))
    assert os.path.exists(os.path.join(d, "zlib1.dll"))


def test_potrace_runs():
    env = dict(os.environ)
    env["PATH"] = os.path.dirname(vz.POTRACE_EXE) + os.pathsep + env.get("PATH", "")
    r = subprocess.run([vz.POTRACE_EXE, "--version"], env=env,
                       capture_output=True, text=True)
    assert r.returncode == 0
    assert "potrace" in (r.stdout + r.stderr).lower()
