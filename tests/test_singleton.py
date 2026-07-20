"""Single-instance lock (lesysbot/core/singleton.py)."""

from __future__ import annotations

import os
import subprocess
import sys

from lesysbot.core import singleton
from lesysbot.core.config import Settings

# Exits 0 if the lock for "testbot" could be acquired, 1 if it's held elsewhere.
CHILD = (
    "import sys; from lesysbot.core.singleton import acquire_instance_lock; "
    "sys.exit(0 if acquire_instance_lock('testbot') else 1)"
)


def _try_from_subprocess(home: str) -> int:
    env = dict(os.environ, LESYSBOT_HOME=home)
    return subprocess.run([sys.executable, "-c", CHILD], env=env).returncode


def test_lock_blocks_second_process(tmp_path, monkeypatch):
    monkeypatch.setenv("LESYSBOT_HOME", str(tmp_path))
    assert singleton.acquire_instance_lock("testbot")
    try:
        assert _try_from_subprocess(str(tmp_path)) == 1
    finally:
        singleton.release_instance_lock("testbot")
    # Released → a fresh process acquires it fine.
    assert _try_from_subprocess(str(tmp_path)) == 0


def test_reacquire_same_process_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("LESYSBOT_HOME", str(tmp_path))
    assert singleton.acquire_instance_lock("testbot")
    try:
        assert singleton.acquire_instance_lock("testbot")
    finally:
        singleton.release_instance_lock("testbot")


def test_holder_pid_records_owner(tmp_path, monkeypatch):
    monkeypatch.setenv("LESYSBOT_HOME", str(tmp_path))
    assert singleton.acquire_instance_lock("testbot")
    try:
        assert singleton.holder_pid("testbot") == os.getpid()
    finally:
        singleton.release_instance_lock("testbot")


def test_instance_key_separates_bots_by_token():
    a, b, c = Settings(), Settings(), Settings()
    for s in (a, b, c):
        s.messaging.provider = "telegram"
    a.messaging.telegram.token = "111:aaa"
    b.messaging.telegram.token = "111:aaa"
    c.messaging.telegram.token = "222:bbb"
    assert singleton.instance_key(a) == singleton.instance_key(b)
    assert singleton.instance_key(a) != singleton.instance_key(c)
