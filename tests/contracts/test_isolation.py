"""Isolation-only entry. No resolver import, behavior collection or Git fixture.

Run only after independent source inspection and narrow D1 execution clearance.
The observer supplies admission.json and sentinels before this process starts.
Assertions are local observations, not a self-issued admission or D1 receipt.
"""

import argparse
import copy
import json
import os
from pathlib import Path
import selectors
import signal
import sys
import time
import types


def _fixture(options):
    # Own preflight precedes even loading the reviewed helper source. This is
    # deliberately small; fixture.admission repeats the complete admission check.
    envelope = Path(options.envelope)
    if (not envelope.is_absolute() or envelope.resolve() != envelope
            or len(envelope.parts) < 3 or envelope == Path.home().resolve()
            or any((p / ".git").exists() for p in (envelope, *envelope.parents))):
        raise ValueError("unsafe isolation envelope")
    marker = envelope / "admission.json"
    if marker.is_symlink() or not marker.is_file():
        raise ValueError("external admission required before helper loading")
    record = json.loads(marker.read_text(encoding="utf-8"))
    if (record.get("envelope") != str(envelope) or record.get("uid") != os.getuid()
            or record.get("runs", {}).get(options.run_id) != "isolation"):
        raise ValueError("isolation admission mismatch")
    source = Path(__file__).resolve().with_name("fixture.py")
    module = types.ModuleType("reviewed_contract_fixture")
    module.__file__ = str(source)
    exec(compile(source.read_bytes(), str(source), "exec"), module.__dict__)
    return module


def _refuses(operation, run, case):
    run._checkpoint(case, "before-refusal")
    try:
        operation()
    except ValueError:
        run._checkpoint(case, "refused")
        return
    raise AssertionError("unsafe operation did not refuse")


def _routing(run):
    environment = run.environment()
    return {"run_id": run.options.run_id, "root": str(run.root),
            "environment": {key: environment[key] for key in ("PATH", "TMPDIR", "XDG_CACHE_HOME")}}


def _ready(handles, timeout=20):
    """Read one <=4096-byte JSON/LF frame per owned child under one deadline.

    Readability is not a complete line. Nonblocking os.read handles fragments,
    EOF and an absolute deadline without resetting the budget for partial data.
    """
    deadline = time.monotonic() + timeout
    buffers, messages, blocking = {}, {}, {}
    try:
        with selectors.DefaultSelector() as ready:
            for process, _ in handles:
                fd = process.stdout.fileno()
                blocking[fd] = os.get_blocking(fd)
                os.set_blocking(fd, False)
                buffers[process] = b""
                ready.register(fd, selectors.EVENT_READ, process)
            while ready.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("owned readiness deadline expired")
                events = ready.select(timeout=remaining)
                if not events:
                    raise TimeoutError("owned readiness deadline expired")
                for key, _ in events:
                    process = key.data
                    try:
                        chunk = os.read(key.fd, 4097 - len(buffers[process]))
                    except BlockingIOError:
                        continue
                    if not chunk:
                        raise EOFError("owned readiness ended before a complete frame")
                    buffers[process] += chunk
                    if len(buffers[process]) > 4096:
                        raise ValueError("owned readiness frame exceeds bound")
                    if b"\n" in buffers[process]:
                        frame, trailing = buffers[process].split(b"\n", 1)
                        if trailing:
                            raise ValueError("unexpected bytes after readiness frame")
                        messages[process] = json.loads(frame.decode("utf-8"))
                        ready.unregister(key.fd)
        return messages
    finally:
        for fd, previous in blocking.items():
            os.set_blocking(fd, previous)


def _release(timeout=20):
    """Bound the worker's one-byte parent command too; EOF is not a release."""
    fd = sys.stdin.fileno()
    previous = os.get_blocking(fd)
    deadline = time.monotonic() + timeout
    os.set_blocking(fd, False)
    try:
        with selectors.DefaultSelector() as ready:
            ready.register(fd, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not ready.select(timeout=remaining):
                    raise TimeoutError("owned worker release deadline expired")
                try:
                    command = os.read(fd, 1)
                except BlockingIOError:
                    continue
                if not command:
                    raise EOFError("owned worker release missing; retained")
                return command
    finally:
        os.set_blocking(fd, previous)


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    for name in ("envelope", "run-id", "git", "python"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--worker", choices=("hold", "abnormal", "partial", "eof", "timeout"))
    options = parser.parse_args()
    fixture = _fixture(options)
    run = fixture.Run(options, "isolation")
    if options.worker:
        if any(key in os.environ for key in fixture._Checkpoint._fields):
            raise fixture._ObservationFailure("observer fields reached worker")
        routing = _routing(run)
        assert routing["environment"] == {key: os.environ.get(key) for key in routing["environment"]}
        assert "HOME" not in os.environ and "CODEX_HOME" not in os.environ
        # Empty SIG_BLOCK queries the inherited mask; it adds no blocked signal.
        assert not {signal.SIGINT, signal.SIGTERM} & signal.pthread_sigmask(signal.SIG_BLOCK, set())
        assert signal.getsignal(signal.SIGTERM) == signal.SIG_DFL
        run.create()
        run.write("cache/recoverable", "synthetic retained evidence\n")
        run.write("cache/routing.json", json.dumps(routing))
        if options.worker == "abnormal":
            os.kill(os.getpid(), signal.SIGTERM)
            raise AssertionError("signal did not terminate owned worker")
        frame = (json.dumps(routing, sort_keys=True) + "\n").encode("utf-8")
        os.write(sys.stdout.fileno(), frame)
        if options.worker in ("partial", "eof", "timeout"):
            if _release() != b"p":
                raise ValueError("readiness probe release missing; retained")
            if options.worker != "timeout":
                os.write(sys.stdout.fileno(), b'{"partial":')
            if options.worker == "eof":
                return 0  # Retain an attributed root for parent EOF observation.
        if _release() != b"x":
            raise ValueError("worker release missing; retained")
        run.close()
        return 0

    if not any(key in os.environ for key in fixture._Checkpoint._fields):
        return fixture.guarded(run, lambda: exercise(run, fixture, options))
    try:
        run._observer = fixture._Checkpoint.from_environment(run)
        return fixture.guarded(run, lambda: exercise(run, fixture, options))
    except BaseException:
        # Guard and exercise finally blocks have already restored wrappers and
        # attempted bounded recovery. Observed failures never print tracebacks.
        if run._observer is not None:
            run._observer.latch()
            run._observer.terminal_diagnostic()
        # Failed observer admission has no request to diagnose or fabricate.
        return 1


def exercise(run, fixture, options):
    parent_environment = dict(os.environ)
    parent_cwd = Path.cwd()
    run._checkpoint("ALL", "entry")
    # All invalid targets are inside the synthetic envelope, except metadata-only
    # tests of root/home. No payload is installed in a shared parent.
    original = run.root
    for number, target in enumerate((Path(original.anchor), Path.home().resolve(), run.envelope,
                                    run.envelope / "sentinels", run.envelope / "../escape"), 1):
        run.root = target
        _refuses(run.create, run, "R%02d" % number)
    run.root = original
    run.create()
    for number, relative in enumerate(("../sibling", "/absolute", "cache/../../escape", "cache//empty"), 6):
        _refuses(lambda relative=relative: run.write(relative, "never"), run, "R%02d" % number)
    alias = run.root / "cache/alias"
    alias.symlink_to(run.envelope / "sentinels", target_is_directory=True)
    _refuses(lambda: run.write("cache/alias/payload", "never"), run, "R10")
    alias.unlink()

    ownership = run.root / ".run-owner.json"
    owned_bytes = ownership.read_bytes()
    ownership.unlink()
    _refuses(run.close, run, "R11")
    ownership.write_text("{}", encoding="utf-8")
    _refuses(run.close, run, "R12")
    ownership.write_bytes(owned_bytes)
    run.root = run.envelope / "sentinels"
    _refuses(run.close, run, "R13")
    run.root = original
    _refuses(lambda: fixture.Run(options, "isolation").create(), run, "R14")

    def child_run(label):
        child_options = copy.copy(options)
        child_options.run_id = options.run_id + "-" + label
        child = fixture.Run(child_options, "isolation")
        child.validate()
        child._observer = run._observer
        return child

    def worker(child, mode):
        argv = [options.python, "-I", "-S", "-B", str(Path(__file__).resolve()),
                "--envelope", options.envelope, "--run-id", child.options.run_id,
                "--git", options.git, "--python", options.python, "--worker", mode]
        # The child creates its own root/cache after its admission. Parent only
        # supplies routing; it never precreates or shares worker directories.
        if run._observer is not None:
            slot = child.options.run_id[len(options.run_id) + 1:]
            run._observer.prepare(case, slot, child)
        return run.start(argv, environment=child.environment(), input=b"x")

    def cleanup(child, process):
        run._checkpoint(case, "before-cleanup", (process,))
        child.close()
        run._checkpoint(case, "after-cleanup", (process,))

    def confirmed_reap(expected_processes):
        outcomes = run.reap_all()
        assert {row["pid"] for row in outcomes} == {p.pid for p in expected_processes}
        assert all(row["state"] == "reaped" and not row["errors"] for row in outcomes)
        assert all(p.returncode is not None for p in expected_processes)
        assert not run.processes
        return outcomes

    # Simultaneous processes, distinct externally allowed roots. Both are started
    # before either is waited. Successful worker cleanup never touches this root.
    case = "C01"
    first, second = child_run("a"), child_run("b")
    first_handle, second_handle = worker(first, "hold"), worker(second, "hold")
    assert first.root != second.root != run.root
    messages = _ready((first_handle, second_handle))
    assert messages == {first_handle[0]: _routing(first), second_handle[0]: _routing(second)}
    for key in ("PATH", "TMPDIR", "XDG_CACHE_HOME"):
        assert len({first.environment()[key], second.environment()[key], run.environment()[key]}) == 3
    # Both roots coexist before either worker receives its cleanup release.
    first.validate(existing=True)
    second.validate(existing=True)
    run._checkpoint(case, "ready", (first_handle[0], second_handle[0]))
    for child, handle in ((first, first_handle), (second, second_handle)):
        result = run.finish(handle)
        assert (result.returncode, result.stdout, result.stderr) == (0, b"", b"")
        assert not child.root.exists() and run.root.is_dir()

    # Protocol negatives reuse the admitted -a slot only after its prior root
    # and child are gone; no additional envelope fields or run IDs are needed.
    for number, (mode, expected_error) in enumerate(
            (("partial", TimeoutError), ("eof", EOFError), ("timeout", TimeoutError)), 2):
        case = "C%02d" % number
        child = child_run("a")
        handle = worker(child, mode)
        assert _ready((handle,)) == {handle[0]: _routing(child)}
        run._checkpoint(case, "ready", (handle[0],))
        assert os.write(handle[0].stdin.fileno(), b"p") == 1
        try:
            _ready((handle,), timeout=0.25)
        except expected_error:
            pass
        else:
            raise AssertionError("incomplete readiness did not refuse within deadline")
        run._checkpoint(case, "protocol-rejected", (handle[0],))
        confirmed_reap((handle[0],))
        child.validate(existing=True)
        cleanup(child, handle[0])

    # Deterministically signal inside a real constructor before/after launch.
    # The object must already be owned, and interruption is delivered only after
    # construction/registration; no process search or unrelated process is used.
    case = "C05"
    child = child_run("a")
    original_init = fixture.subprocess.Popen.__init__
    constructed = []

    def interrupted_init(process, *args, **kwargs):
        assert process in run.processes
        os.kill(os.getpid(), signal.SIGINT)
        original_init(process, *args, **kwargs)
        if run._observer is not None:
            run._observer.register(process)
        constructed.append(process)
        assert _ready(((process, None),)) == {process: _routing(child)}
        run._checkpoint(case, "ready", (process,))
        os.kill(os.getpid(), signal.SIGTERM)

    fixture.subprocess.Popen.__init__ = interrupted_init
    try:
        try:
            worker(child, "hold")
        except KeyboardInterrupt:
            run._checkpoint(case, "interrupt-delivered", tuple(constructed))
        else:
            raise AssertionError("startup interruption was not delivered")
    finally:
        fixture.subprocess.Popen.__init__ = original_init
    assert len(constructed) == 1 and set(constructed) == run.processes
    run._checkpoint(case, "wrappers-restored", tuple(constructed))
    confirmed_reap(constructed)
    cleanup(child, constructed[0])

    # A failure before launch releases only the empty startup slot, with no root
    # creation or invented PID/termination observation.
    case = "C06"
    child = child_run("a")
    failed_launches = []

    def failing_before_launch(process, *args, **kwargs):
        assert process in run.processes
        failed_launches.append(process)
        raise OSError("synthetic pre-launch constructor failure")

    fixture.subprocess.Popen.__init__ = failing_before_launch
    try:
        try:
            worker(child, "hold")
        except OSError:
            pass
        else:
            raise AssertionError("pre-launch constructor failure was not reported")
    finally:
        fixture.subprocess.Popen.__init__ = original_init
    assert not run.processes and not child.root.exists()
    run._checkpoint(case, "wrappers-restored", tuple(failed_launches))

    # A constructor failure after an actual launch must retain its real handle.
    case = "C07"
    child = child_run("a")
    constructed = []

    def failing_init(process, *args, **kwargs):
        original_init(process, *args, **kwargs)
        if run._observer is not None:
            run._observer.register(process)
        constructed.append(process)
        assert _ready(((process, None),)) == {process: _routing(child)}
        run._checkpoint(case, "ready", (process,))
        raise OSError("synthetic post-launch constructor failure")

    fixture.subprocess.Popen.__init__ = failing_init
    try:
        try:
            worker(child, "hold")
        except OSError:
            pass
        else:
            raise AssertionError("constructor failure was not reported")
    finally:
        fixture.subprocess.Popen.__init__ = original_init
    assert len(constructed) == 1 and set(constructed) == run.processes
    run._checkpoint(case, "wrappers-restored", tuple(constructed))
    confirmed_reap(constructed)
    cleanup(child, constructed[0])

    # One synthetic kill failure must not abandon a sibling. The failed handle
    # stays owned until a later bounded recovery confirms that it was reaped.
    case = "C08"
    first, second = child_run("a"), child_run("b")
    first_handle, second_handle = worker(first, "hold"), worker(second, "hold")
    assert _ready((first_handle, second_handle)) == {
        first_handle[0]: _routing(first), second_handle[0]: _routing(second)}
    original_killpg = fixture.os.killpg
    original_wait = fixture.subprocess.Popen.wait
    previous_handlers = {signum: signal.getsignal(signum) for signum in (signal.SIGINT, signal.SIGTERM)}
    observed_signals, completed_attempts = [], []
    injected = False
    resumed = False
    children = (first_handle[0], second_handle[0])
    retained = {child.root: {
        relative: (child.root / relative).read_bytes()
        for relative in (".run-owner.json", "cache/recoverable", "cache/routing.json")
    } for child in (first, second)}
    run._checkpoint(case, "ready", children)

    def record_signal(signum, frame):
        observed_signals.append(signum)
        previous_handlers[signum](signum, frame)

    def wait_with_interruption(process, *args, **kwargs):
        nonlocal injected
        assert process in children and run._defer_interrupts > 0
        assert kwargs == {"timeout": 5} and not args
        if not injected:
            injected = True
            os.kill(os.getpid(), signal.SIGTERM)
        try:
            return original_wait(process, *args, **kwargs)
        finally:
            completed_attempts.append(process.pid)

    def fail_one(pid, signum):
        if pid == first_handle[0].pid:
            raise OSError("synthetic owned-child kill failure")
        return original_killpg(pid, signum)

    try:
        for signum in previous_handlers:
            signal.signal(signum, record_signal)
        fixture.os.killpg = fail_one
        fixture.subprocess.Popen.wait = wait_with_interruption
        try:
            run.reap_all()
            resumed = True  # No cleanup or next launch may become reachable.
        except KeyboardInterrupt:
            # Handle only this known injection, after proving both attempted
            # recovery and evidence retention. Unexpected interruption propagates.
            if not injected or observed_signals != [signal.SIGTERM]:
                raise
            assert sorted(completed_attempts) == sorted(process.pid for process in children)
            assert not resumed and run._defer_interrupts == 0
            assert not run._pending_interrupts
            assert run.processes == {first_handle[0]}
            for child in (first, second):
                child.validate(existing=True)
                assert {relative: (child.root / relative).read_bytes()
                        for relative in retained[child.root]} == retained[child.root]
            outcomes = {row["pid"]: row for row in run.last_reap}
            run._checkpoint(case, "interrupt-delivered", children)
        else:
            raise AssertionError("recovery returned before delivering handled interruption")
    finally:
        fixture.os.killpg = original_killpg
        fixture.subprocess.Popen.wait = original_wait
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
    assert outcomes[first_handle[0].pid]["state"] == "unreaped"
    assert outcomes[first_handle[0].pid]["errors"] == ["OSError", "TimeoutExpired"]
    assert outcomes[second_handle[0].pid] == {"pid": second_handle[0].pid, "state": "reaped", "errors": []}
    assert run.processes == {first_handle[0]}
    run._checkpoint(case, "wrappers-restored", children)

    def exited_during_kill(pid, signum):
        original_killpg(pid, signum)
        raise ProcessLookupError("synthetic exit race after owned-child termination")

    fixture.os.killpg = exited_during_kill
    try:
        confirmed_reap((first_handle[0],))
    finally:
        fixture.os.killpg = original_killpg
    cleanup(first, first_handle[0])
    cleanup(second, second_handle[0])

    case = "C09"
    abnormal = child_run("abnormal")
    handle = worker(abnormal, "abnormal")
    result = run.finish(handle)
    assert result.returncode == -signal.SIGTERM and result.stdout == b""
    abnormal.validate(existing=True)
    assert (abnormal.root / "cache/recoverable").read_bytes() == b"synthetic retained evidence\n"
    cleanup(abnormal, handle[0])
    run.validate(existing=True)
    run._checkpoint("ALL", "before-cleanup")
    run.close()
    run._checkpoint("ALL", "after-cleanup")
    assert not original.exists()
    fixture.admission(options, "isolation")
    assert dict(os.environ) == parent_environment and Path.cwd() == parent_cwd
    assert not run.processes
    run._checkpoint("ALL", "complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
