import logging
import os
import pexpect
import subprocess

from scale_build.exceptions import CallError


logger = logging.getLogger(__name__)


def run(*args, **kwargs):
    if isinstance(args[0], tuple):
        a = list(args[0])
        a.insert(0, "sudo")
        args[0] = a
    elif isinstance(args[0], list):
        args[0].insert(0, "sudo")

    if isinstance(args[0], list):
        args = tuple(args[0])
    kwargs.setdefault('stdout', subprocess.PIPE)
    kwargs.setdefault('stderr', subprocess.PIPE)
    exception_message = kwargs.pop('exception_msg', None)
    check = kwargs.pop('check', True)
    shell = kwargs.pop('shell', False)
    log = kwargs.pop('log', False)
    env = kwargs.pop('env', None) or os.environ
    if log:
        kwargs['stderr'] = subprocess.STDOUT

    proc = subprocess.Popen(
        args, stdout=kwargs['stdout'], stderr=kwargs['stderr'], shell=shell, env=env, encoding='utf8', errors='ignore'
    )
    if log:
        for line in map(str.rstrip, iter(proc.stdout.readline, '')):
            logger.debug(line)

    stdout, stderr = proc.communicate()

    cp = subprocess.CompletedProcess(args, proc.returncode, stdout=stdout, stderr=stderr)
    if check:
        error_str = exception_message or stderr or ''
        if cp.returncode:
            raise CallError(
                f'Command {" ".join(args) if isinstance(args, list) else args!r} returned exit code '
                f'{cp.returncode}' + (f' ({error_str})' if error_str else '')
            )
    return cp


def interactive_run(command):
    child = pexpect.spawnu(command)
    print(f'Executing {command!r} command')
    child.interact()
    child.kill(1)
