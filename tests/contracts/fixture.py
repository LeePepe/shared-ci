"""Internal synthetic fixture seam; no top-level writes, workloads or imports of candidates.

See the registry contract for the externally owned admission.json format.
Admission remains an external precondition; these checks cannot authenticate it.
Failures retain resources. No ambient packages, inherited PATH or network tools.
"""

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import signal
import stat
import subprocess
import time


class _ObservationFailure(BaseException):
    """Not an expected ValueError/OSError/KeyboardInterrupt regression outcome."""


class _Checkpoint:
    """Private isolation seam; ACKs authorize progress, never establish proof.

    The two finite schedules differ only in C08 sibling iteration order. Child
    selectors come from retained Popen objects, not process discovery. The
    external observer must independently check identities and filesystem state.
    """

    _fields = ("D1_OBS_REQUEST_FD", "D1_OBS_ACK_FD", "D1_OBS_INVOCATION")

    @classmethod
    def from_environment(cls, owner):
        values = [os.environ.get(key) for key in cls._fields]
        if all(value is None for value in values):
            return None
        if any(value is None for value in values):
            raise _ObservationFailure("partial observer configuration")
        return cls(*values, owner)

    def __init__(self, request, ack, invocation, owner):
        self.owner = owner
        self.failed = False
        self.recovery_deadline = None
        self.failure = None
        self.active_request = None
        self.recovery_finished = False
        self.diagnostic_attempted = False
        self.seq = 0
        self.outstanding = False
        self.children = {}
        self.generations = {"a": 0, "b": 0, "abnormal": 0}
        self.case = "ALL"
        self.pending = None
        self.wait_attempts = {}
        self.cleaned = set()
        self.cursor = 0
        self.plans = [self._schedule(order) for order in (("a", "b"), ("b", "a"))]
        self.deadline = time.monotonic() + 180
        try:
            if not re.fullmatch(r"[0-9a-f]{32}", invocation):
                raise ValueError("invalid observer invocation")
            if any(not re.fullmatch(r"[0-9]+", value) for value in (request, ack)):
                raise ValueError("invalid observer descriptor")
            self.request, self.ack = int(request), int(ack)
            self.invocation = invocation
            if min(self.request, self.ack) < 3 or self.request == self.ack:
                raise ValueError("invalid observer descriptor pair")
            transferred = {}
            for fd, direction in ((self.request, os.O_WRONLY), (self.ack, os.O_RDONLY)):
                flags = fcntl.fcntl(fd, fcntl.F_GETFL)
                identity = os.fstat(fd)
                if (not stat.S_ISFIFO(identity.st_mode)
                        or flags & os.O_ACCMODE != direction
                        or not flags & os.O_NONBLOCK):
                    raise ValueError("observer pipe flags mismatch")
                transferred[fd] = ((identity.st_dev, identity.st_ino, identity.st_mode,
                                    identity.st_uid), flags)
            if signal.getsignal(signal.SIGCHLD) != signal.SIG_DFL:
                raise ValueError("default waitable SIGCHLD required")
            # pass_fds transfers these pipes across exec as inheritable. Adopt
            # only the validated pair, then seal and recheck before any writes.
            for fd in transferred:
                os.set_inheritable(fd, False)
            for fd, (expected_identity, expected_flags) in transferred.items():
                identity = os.fstat(fd)
                if ((identity.st_dev, identity.st_ino, identity.st_mode, identity.st_uid)
                        != expected_identity or fcntl.fcntl(fd, fcntl.F_GETFL) != expected_flags
                        or os.get_inheritable(fd)):
                    raise ValueError("observer descriptor adoption failed")
        except BaseException as error:
            self.latch()
            raise _ObservationFailure("observer admission failed") from error

    @staticmethod
    def _schedule(order):
        # Rows: case, phase, attempt, ((slot, generation, expected rc), ...).
        events = [("ALL", "entry", 0, ())]

        def add(case, phase, children=(), attempt=0):
            events.append((case, phase, attempt, tuple(children)))

        def wait(case, slot, generation, rc, attempt=1):
            add(case, "before-wait", ((slot, generation, None),), attempt)
            add(case, "wait-failed" if rc is None else "after-wait",
                ((slot, generation, rc),), attempt)

        def cleanup(case, children):
            add(case, "before-cleanup", children)
            add(case, "after-cleanup", children)

        for number in range(1, 15):
            case = "R%02d" % number
            add(case, "before-refusal")
            add(case, "refused")
        a, b = ("a", 1, None), ("b", 1, None)
        add("C01", "registered", (a,))
        add("C01", "registered", (b,))
        add("C01", "ready", (a, b))
        wait("C01", "a", 1, 0)
        wait("C01", "b", 1, 0)
        for number in range(2, 5):
            case, child = "C%02d" % number, ("a", number, None)
            add(case, "registered", (child,))
            add(case, "ready", (child,))
            add(case, "protocol-rejected", (child,))
            rc = 0 if number == 3 else -signal.SIGKILL
            wait(case, "a", number, rc)
            cleanup(case, (("a", number, rc),))
        for number in (5, 6, 7):
            case, child = "C%02d" % number, ("a", number, None)
            add(case, "launch-failed" if number == 6 else "registered", (child,))
            if number != 6:
                add(case, "ready", (child,))
            if number == 5:
                add(case, "interrupt-delivered", (child,))
            add(case, "wrappers-restored", (child,))
            if number != 6:
                wait(case, "a", number, -signal.SIGKILL)
                cleanup(case, (("a", number, -signal.SIGKILL),))
        a, b = ("a", 8, None), ("b", 2, None)
        add("C08", "registered", (a,))
        add("C08", "registered", (b,))
        add("C08", "ready", (a, b))
        for slot in order:
            wait("C08", slot, 8 if slot == "a" else 2,
                 None if slot == "a" else -signal.SIGKILL)
        retained = (a, ("b", 2, -signal.SIGKILL))
        add("C08", "interrupt-delivered", retained)
        add("C08", "wrappers-restored", retained)
        wait("C08", "a", 8, -signal.SIGKILL, 2)
        cleanup("C08", (("a", 8, -signal.SIGKILL),))
        cleanup("C08", (("b", 2, -signal.SIGKILL),))
        add("C09", "registered", (("abnormal", 1, None),))
        wait("C09", "abnormal", 1, -signal.SIGTERM)
        cleanup("C09", (("abnormal", 1, -signal.SIGTERM),))
        cleanup("ALL", ())
        add("ALL", "complete")
        return events

    def latch(self, reason="unexpected"):
        if not self.failed:
            self.failed = True
            self.recovery_deadline = time.monotonic() + 11
            # A tuple binds the first failure, never a later handler/scenario.
            # No actual outstanding request means no attributable diagnostic.
            if self.active_request is not None:
                self.failure = (*self.active_request, reason)

    def terminal_diagnostic(self):
        """One nonblocking stderr write after guard unwind, with no new budget.

        Missing/partial output is deliberately unusable as negative evidence.
        A secondary recovery failure also withholds the diagnostic rather than
        disguising that failure as a clean instance of the first transport fault.
        """
        if self.diagnostic_attempted:
            return
        self.diagnostic_attempted = True
        if (not self.failed or self.failure is None or not self.recovery_finished
                or self.owner._guarded or self.owner._defer_interrupts
                or self.owner.processes or self.owner._pending_interrupts):
            return
        try:
            invocation, seq, case, phase, reason = self.failure
            raw = (json.dumps(dict(v=2, invocation=invocation, seq=seq, case=case,
                                   phase=phase, reason=reason), sort_keys=True,
                              separators=(",", ":"), ensure_ascii=False,
                              allow_nan=False) + "\n").encode("utf-8")
            if len(raw) > 512 or not stat.S_ISFIFO(os.fstat(2).st_mode):
                return
            os.set_blocking(2, False)
            if os.get_blocking(2) or time.monotonic() >= self.recovery_deadline:
                return
            # <=512 bytes fits POSIX PIPE_BUF. No loop, ACK, retry or new timer.
            os.write(2, raw)
        except BaseException:
            # The observed parent still exits nonzero; no traceback/private data.
            return

    def check(self):
        if self.failed:
            raise _ObservationFailure("observer failure latched; resources retained")
        if time.monotonic() >= self.deadline:
            self.latch()
            raise _ObservationFailure("observed invocation deadline expired")

    def prepare(self, case, slot, child):
        self.check()
        if self.pending is not None or slot not in self.generations:
            self.latch()
            raise _ObservationFailure("overlapping or invalid launch reservation")
        generation = self.generations[slot] + 1
        event = (case, "launch-failed" if case == "C06" else "registered", 0,
                 ((slot, generation, None),))
        if (len(self.owner.processes) >= 2
                or not any(self.cursor < len(plan) and plan[self.cursor] == event for plan in self.plans)
                or child.root.exists() or child.root.is_symlink()):
            self.latch()
            raise _ObservationFailure("launch transition rejected before construction")
        self.case = case
        self.generations[slot] = generation
        self.pending = (slot, generation, child)

    def authorize_cleanup(self, child):
        self.check()
        previous = self.plans[0][self.cursor - 1] if self.cursor else None
        expected = () if child is self.owner else tuple(
            (slot, generation, process.returncode)
            for process, (slot, generation, registered, pid) in self.children.items()
            if registered is child and pid is not None and process not in self.owner.processes)
        if (previous is None or previous[1] != "before-cleanup"
                or previous[3] != expected or (child is not self.owner and len(expected) != 1)
                or self.owner.processes):
            self.latch()
            raise _ObservationFailure("cleanup transition rejected before deletion")

    def register(self, process):
        self.check()
        if process in self.children:
            return  # C05/C07 registered inside their real-constructor wrapper.
        if self.pending is None:
            self.latch()
            raise _ObservationFailure("unreserved launch")
        slot, generation, child = self.pending
        self.pending = None
        self.children[process] = (slot, generation, child, getattr(process, "pid", None))
        self.emit(self.case, "registered" if getattr(process, "pid", None) is not None
                  else "launch-failed", (process,))

    def before_wait(self, process):
        attempt = self.wait_attempts.get(process, 0) + 1
        self.wait_attempts[process] = attempt
        self.emit(self.case, "before-wait", (process,), attempt)

    def after_wait(self, process, failed=False):
        self.emit(self.case, "wait-failed" if failed else "after-wait",
                  (process,), self.wait_attempts[process])

    def emit(self, case, phase, processes=(), attempt=0):
        self.check()
        try:
            if self.outstanding or self.seq >= 128 or type(attempt) is not int:
                raise ValueError("checkpoint sequence misuse")
            children = []
            for process in processes:
                slot, generation, child, pid = self.children[process]
                rc = getattr(process, "returncode", None)
                if (getattr(process, "pid", None) != pid
                        or (pid is not None and (type(pid) is not int or pid <= 0))
                        or (rc is not None and type(rc) is not int)):
                    raise ValueError("child identity or return code changed")
                if pid is None and (slot, generation) != ("a", 6):
                    raise ValueError("missing actual child identity")
                children.append(dict(slot=slot, generation=generation, pid=pid, rc=rc))
            children.sort(key=lambda row: row["slot"])
            if len({row["slot"] for row in children}) != len(children):
                raise ValueError("duplicate checkpoint child")
            event = (case, phase, attempt, tuple(
                (row["slot"], row["generation"], row["rc"]) for row in children))
            plans = [plan for plan in self.plans
                     if self.cursor < len(plan) and plan[self.cursor] == event]
            if not plans:
                raise ValueError("checkpoint transition rejected")
            if phase == "launch-failed" and children[0]["pid"] is not None:
                raise ValueError("fabricated failed launch")
            if phase == "after-cleanup":
                for process in processes:
                    child = self.children[process][2]
                    if child.root.exists() or child.root.is_symlink():
                        raise ValueError("root cleanup unreconciled")
                    self.cleaned.add(process)
            if phase == "complete":
                if (self.pending is not None or len(self.children) != 11
                        or self.generations != {"a": 8, "b": 2, "abnormal": 1}
                        or self.owner.processes or self.owner.root.exists()
                        or self.owner.root.is_symlink()):
                    raise ValueError("lifetime count unreconciled")
                for process, (slot, generation, child, pid) in self.children.items():
                    if child.root.exists() or child.root.is_symlink():
                        raise ValueError("retained root at completion")
                    if pid is not None and (process.returncode is None
                            or self.wait_attempts.get(process) != (2 if (slot, generation) == ("a", 8) else 1)
                            or ((generation != 1 or slot == "abnormal") and process not in self.cleaned)):
                        raise ValueError("child completion unreconciled")
            self.seq += 1
            frame = dict(v=2, invocation=self.invocation, seq=self.seq, case=case,
                         phase=phase, attempt=attempt, children=children)
            raw = (json.dumps(frame, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
            if len(raw) > 4096:
                raise ValueError("oversize checkpoint")
            self.outstanding = True
            self._exchange(raw, (self.invocation, self.seq, case, phase))
            self.outstanding = False
            self.active_request = None
            self.plans = plans
            self.cursor += 1
        except BaseException as error:
            self.latch()
            raise _ObservationFailure("observer checkpoint failed; resources retained") from error

    def _exchange(self, raw, request_identity):
        exchange_deadline = time.monotonic() + 1
        deadline = min(self.deadline, exchange_deadline)

        def reject(reason):
            if time.monotonic() >= deadline:
                reason = "ack-timeout" if exchange_deadline <= self.deadline else "unexpected"
            self.latch(reason)
            raise _ObservationFailure("observer exchange rejected")

        def check_deadline():
            now = time.monotonic()
            if now >= deadline:
                # An invocation ceiling is not the intended one-second fault.
                reject("ack-timeout" if exchange_deadline <= self.deadline else "unexpected")

        def ready(fd, event):
            with selectors.DefaultSelector() as selector:
                selector.register(fd, event)
                while True:
                    check_deadline()
                    events = selector.select(max(0, deadline - time.monotonic()))
                    check_deadline()
                    if events:
                        return

        # Unsolicited/duplicate bytes cannot become the next request's ACK.
        try:
            os.read(self.ack, 257)
        except BlockingIOError:
            pass
        else:
            raise ValueError("unexpected ACK bytes or EOF before request")
        while raw:
            ready(self.request, selectors.EVENT_WRITE)
            try:
                written = os.write(self.request, raw)
            except BlockingIOError:
                continue
            if written <= 0:
                raise ValueError("checkpoint write failed")
            self.active_request = request_identity
            raw = raw[written:]
        response = b""
        while b"\n" not in response:
            ready(self.ack, selectors.EVENT_READ)
            try:
                chunk = os.read(self.ack, 257 - len(response))
            except BlockingIOError:
                continue
            check_deadline()
            if not chunk:
                reject("ack-eof")
            response += chunk
            if len(response) > 256:
                reject("ack-malformed")
        check_deadline()
        if (response.count(b"\n") != 1
                or not response.endswith(b"\n") or b"\r" in response):
            reject("ack-malformed")

        def pairs(items):
            result = {}
            for key, value in items:
                if key in result:
                    raise ValueError("duplicate ACK key")
                result[key] = value
            return result

        def invalid_constant(_value):
            raise ValueError("nonfinite ACK value")

        try:
            ack = json.loads(response[:-1].decode("utf-8", errors="strict"),
                             object_pairs_hook=pairs, parse_constant=invalid_constant)
            if (type(ack) is not dict or set(ack) != {"v", "invocation", "seq", "action"}
                    or type(ack["v"]) is not int or ack["v"] != 2
                    or type(ack["seq"]) is not int
                    or ack["invocation"] != self.invocation
                    or ack["action"] not in ("continue", "abort")):
                raise ValueError("invalid ACK fields")
            # Validate the entire closed/canonical shape before selecting a
            # sequence/abort reason. Wrong nonce/version are malformed, not N04.
            if (json.dumps(ack, separators=(",", ":"), ensure_ascii=False,
                           allow_nan=False) + "\n").encode("utf-8") != response:
                raise ValueError("noncompact ACK")
        except (ValueError, UnicodeError, RecursionError):
            # A real expired deadline must not be relabelled by the parser.
            check_deadline()
            reject("ack-malformed")
        check_deadline()
        if ack["seq"] != self.seq:
            reject("ack-sequence")
        if ack["action"] == "abort":
            reject("ack-abort")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(raw):
    path = Path(raw)
    if not path.is_absolute() or str(path) != raw or ".." in path.parts:
        raise ValueError("noncanonical absolute path")
    if path.resolve() != path:
        raise ValueError("symlink or alias target")
    return path


def read_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate admission key")
            result[key] = value
        return result
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs)


def arguments(stage):
    parser = argparse.ArgumentParser(allow_abbrev=False)
    for name in ("envelope", "run-id", "git", "python"):
        parser.add_argument("--" + name, required=True)
    if stage == "behavior":
        parser.add_argument("--shell", required=True)
        parser.add_argument("--dirname", required=True)
    if stage == "schema":
        parser.add_argument("--validator-root", required=True)
        parser.add_argument("--validator-version", required=True)
    return parser


def admission(options, stage):
    envelope = canonical(options.envelope)
    if (envelope == Path(envelope.anchor) or len(envelope.parts) < 3
            or envelope == Path.home().resolve() or not envelope.is_dir()):
        raise ValueError("unsafe external envelope")
    if any((parent / ".git").exists() for parent in (envelope, *envelope.parents)):
        raise ValueError("repository envelope refused")
    record_path = envelope / "admission.json"
    if record_path.is_symlink() or not record_path.is_file():
        raise ValueError("external admission absent")
    record = read_json(record_path)
    if (record.get("schema") != 1 or record.get("envelope") != str(envelope)
            or record.get("uid") != os.getuid() or envelope.stat().st_uid != os.getuid()
            or record_path.stat().st_uid != os.getuid()
            or not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", options.run_id)
            or record.get("runs", {}).get(options.run_id) != stage
            or not re.fullmatch(r"[0-9a-f]{64}", record.get("nonce", ""))):
        raise ValueError("external envelope admission mismatch")
    for name in ("git", "python", "shell", "dirname"):
        if hasattr(options, name):
            tool = canonical(getattr(options, name))
            expected = record["tools"][name]
            if (str(tool) != expected["path"] or not tool.is_file()
                    or not os.access(tool, os.X_OK) or digest(tool) != expected["sha256"]):
                raise ValueError("tool admission mismatch")
    for relative, expected in record["sentinels"].items():
        target = envelope / relative
        if (not relative.startswith("sentinels/") or ".." in target.parts
                or target.resolve() != target or digest(target) != expected):
            raise ValueError("external sentinel mismatch")
    return envelope, record, digest(record_path)


def guarded(run, operation):
    """Retain resources on any failure; stop/reap only this parent's children."""
    if run._guarded:
        raise ValueError("nested process guard refused")
    previous = {}

    def interrupted(signum, _frame):
        if run._defer_interrupts:
            run._pending_interrupts.append(signum)
        else:
            raise KeyboardInterrupt("owned test interrupted; resources retained")

    try:
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous[signum] = signal.signal(signum, interrupted)
        run._guarded = True
        return operation()
    except BaseException:
        if run._observer is not None:
            run._observer.latch()
        raise
    finally:
        # Keep the non-raising deferral active until every owned child has had
        # its own bounded recovery attempt. No signal mask or SIG_IGN disposition
        # is installed, so children do not inherit blocked/ignored termination.
        run._defer_interrupts += 1
        try:
            outcomes = run.reap_all()
        finally:
            for signum, handler in previous.items():
                signal.signal(signum, handler)
            run._guarded = False
            run._defer_interrupts -= 1
        if run.processes or any(row["errors"] for row in outcomes):
            raise RuntimeError("owned-child recovery incomplete; resources retained: " + json.dumps(outcomes))
        run.deliver_pending_interrupt()
        if run._observer is not None and run._observer.failed:
            run._observer.recovery_finished = True


class Run:
    def __init__(self, options, stage):
        self.options = options
        self.stage = stage
        self.envelope, self.record, self.admission_hash = admission(options, stage)
        self.root = self.envelope / options.run_id
        self.identity = {"run_id": options.run_id, "root": str(self.root),
                         "nonce": self.record["nonce"], "admission_sha256": self.admission_hash}
        self.processes = set()
        self._guarded = False
        self._defer_interrupts = 0
        self._pending_interrupts = []
        self.last_reap = []
        self._observer = None

    def _checkpoint(self, case, phase, processes=(), attempt=0):
        if self._observer is not None:
            self._observer.emit(case, phase, processes, attempt)

    def _check_progress(self):
        if self._observer is not None:
            self._observer.check()

    def validate(self, existing=False):
        envelope, record, admission_hash = admission(self.options, self.stage)
        if envelope != self.envelope or record != self.record or admission_hash != self.admission_hash:
            raise ValueError("admission changed")
        if self.root != envelope / self.options.run_id or self.root.resolve() != self.root:
            raise ValueError("run canonical identity changed")
        if existing:
            marker = self.root / ".run-owner.json"
            if marker.is_symlink() or not marker.is_file() or read_json(marker) != self.identity:
                raise ValueError("cleanup ownership mismatch; retained")
        elif self.root.exists() or self.root.is_symlink():
            raise ValueError("preexisting destination refused")

    def create(self):
        self._check_progress()
        self.validate()
        self.root.mkdir(mode=0o700)
        (self.root / ".run-owner.json").write_text(json.dumps(self.identity), encoding="utf-8")
        for name in ("provider", "caller", "tools", "cache"):
            (self.root / name).mkdir()

    def target(self, relative):
        self.validate(existing=True)
        if not relative or Path(relative).is_absolute() or any(p in ("", ".", "..") for p in relative.split("/")):
            raise ValueError("unsafe relative target")
        target = self.root / relative
        if target.resolve() != target:
            raise ValueError("symlink target refused")
        target.relative_to(self.root)
        return target

    def write(self, relative, content):
        self._check_progress()
        target = self.target(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
        return target

    def environment(self):
        return {"PATH": str(self.root / "tools"), "LC_ALL": "C", "PYTHONIOENCODING": "utf-8",
                "TMPDIR": str(self.root / "cache"), "XDG_CACHE_HOME": str(self.root / "cache"),
                "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_SYSTEM": os.devnull, "GIT_ATTR_NOSYSTEM": "1",
                "GIT_NO_REPLACE_OBJECTS": "1", "GIT_NO_LAZY_FETCH": "1",
                "GIT_TERMINAL_PROMPT": "0", "GIT_ALLOW_PROTOCOL": "",
                "GIT_PROTOCOL_FROM_USER": "0", "GIT_OPTIONAL_LOCKS": "0",
                "GIT_AUTHOR_NAME": "Synthetic Fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
                "GIT_COMMITTER_NAME": "Synthetic Fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
                "GIT_AUTHOR_DATE": "2001-01-01T00:00:00Z", "GIT_COMMITTER_DATE": "2001-01-01T00:00:00Z"}

    def start(self, argv, *, cwd=None, environment=None, input=None):
        self._check_progress()
        if not self._guarded:
            raise ValueError("child startup requires an active process guard")
        self.validate(existing=True)
        if self._observer is not None:
            if self._observer.pending is None:
                self._observer.latch()
                raise _ObservationFailure("unreserved child startup")
            environment = dict(self.environment() if environment is None else environment)
            for key in _Checkpoint._fields:
                environment.pop(key, None)
        self._defer_interrupts += 1
        try:
            # Pre-register the actual Popen object before its constructor can
            # launch anything. Retain it if construction raises after launch;
            # a deferred Python signal handler cannot interrupt PID assignment.
            # This is an internal POSIX fixture seam, not a new process launcher.
            process = subprocess.Popen.__new__(subprocess.Popen)
            self.processes.add(process)
            try:
                process.__init__(argv, cwd=cwd or self.root,
                                 env=self.environment() if environment is None else environment,
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 start_new_session=True, bufsize=0, close_fds=True)
                if self._observer is not None:
                    self._observer.register(process)
            except BaseException:
                if getattr(process, "pid", None) is None and not getattr(process, "_child_created", False):
                    # Constructor failed before creating a child: nothing to reap.
                    self.processes.remove(process)
                    if self._observer is not None and not self._observer.failed:
                        self._observer.register(process)
                raise
        finally:
            self._defer_interrupts -= 1
        self.deliver_pending_interrupt()
        return process, input

    def deliver_pending_interrupt(self):
        if not self._defer_interrupts and self._pending_interrupts:
            self._pending_interrupts.clear()
            raise KeyboardInterrupt("owned test interrupted; resources retained")

    def reap_all(self):
        """Attempt every owned child independently; never drop an unreaped handle.

        wait(timeout) confirms reaping without waiting for inherited stdout/stderr
        pipe EOF. Outcomes are local state for inspection, not an external receipt.
        """
        if self._observer is not None and self._observer.failed:
            return self._recover_observed_failure()
        outcomes = []
        self._defer_interrupts += 1
        try:
            for process in tuple(self.processes):
                row = {"pid": getattr(process, "pid", None), "state": "unreaped", "errors": []}
                try:
                    if row["pid"] is None:
                        raise RuntimeError("startup identity unconfirmed")
                    # Observation must precede every consuming wait, including
                    # poll(). The unobserved path retains its original behavior.
                    if ((self._observer is not None and self._observer.case != "C03")
                            or (self._observer is None and process.poll() is None)):
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            # Retain the handle and still perform the real wait.
                            pass
                        except Exception as error:
                            row["errors"].append(type(error).__name__)
                    if self._observer is not None:
                        self._observer.before_wait(process)
                    try:
                        process.wait(timeout=5)
                    except BaseException:
                        if self._observer is not None:
                            self._observer.after_wait(process, failed=True)
                        raise
                    if process.returncode is None:
                        raise RuntimeError("child termination unconfirmed")
                    # Ownership ends only after confirmed termination and reaping.
                    self.processes.remove(process)
                    row["state"] = "reaped"
                    if self._observer is not None:
                        self._observer.after_wait(process)
                    for stream in (process.stdin, process.stdout, process.stderr):
                        if stream is not None:
                            try:
                                stream.close()
                            except Exception as error:
                                row["errors"].append(type(error).__name__)
                except BaseException as error:
                    if self._observer is not None and self._observer.failed:
                        # Unwind all injected wrappers before the outer guard
                        # performs failure recovery. Never consume a sibling here.
                        raise
                    # A failing child must not prevent attempts on its siblings.
                    row["errors"].append(type(error).__name__)
                outcomes.append(row)
        finally:
            self.last_reap = outcomes
            self._defer_interrupts -= 1
        # Explicit recovery must interrupt before normal cleanup/startup resumes.
        # The outer guard retains its own deferral during final sibling recovery.
        self.deliver_pending_interrupt()
        return outcomes

    def _recover_observed_failure(self):
        """No ACKs or deletion; one latched 11-second deadline for all handlers.

        Called by the outer guard only after exercise's finally blocks restore
        constructor/kill/wait/signal wrappers. These source-owned waits are NOT
        the positive observed zombie->wait->absence proof.
        """
        outcomes = []
        deadline = self._observer.recovery_deadline
        # Signal all still-owned siblings before any bounded wait. No poll,
        # process search, group discovery, or independent cleanup authority.
        for process in tuple(self.processes):
            row = {"pid": getattr(process, "pid", None), "state": "unreaped", "errors": []}
            outcomes.append((process, row))
            if row["pid"] is None:
                row["errors"].append("UnconfirmedIdentity")
                continue
            if time.monotonic() >= deadline:
                row["errors"].append("RecoveryDeadline")
                continue
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except BaseException as error:
                row["errors"].append(type(error).__name__)
        for process, row in outcomes:
            if row["pid"] is None:
                continue
            try:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("shared recovery deadline expired")
                process.wait(timeout=min(5, remaining))
                if process.returncode is None:
                    raise RuntimeError("child termination unconfirmed")
                self.processes.remove(process)
                row["state"] = "reaped"
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream is not None:
                        stream.close()
            except BaseException as error:
                row["errors"].append(type(error).__name__)
        self.last_reap = [row for _, row in outcomes]
        return self.last_reap

    def finish(self, handle):
        self._check_progress()
        process, input = handle
        if process not in self.processes:
            raise ValueError("unowned child handle")
        # On any exception ownership remains with the outer guard, which attempts
        # bounded recovery of all siblings, including this child.
        if self._observer is not None:
            # Release exactly once before the observer's exit barrier. C09
            # self-terminates and needs no command. No consuming call precedes ACK.
            if self._observer.case != "C09":
                if input != b"x" or os.write(process.stdin.fileno(), b"x") != 1:
                    self._observer.latch()
                    raise _ObservationFailure("worker release failed")
            input = None
            self._observer.before_wait(process)
        stdout, stderr = process.communicate(input, timeout=20)
        process.wait(timeout=0)
        if process.returncode is None:
            raise RuntimeError("child termination unconfirmed")
        self.processes.remove(process)
        if self._observer is not None:
            self._observer.after_wait(process)
        return subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)

    def call(self, argv, **kwargs):
        return self.finish(self.start(argv, **kwargs))

    def git(self, directory, *argv, check=True, input=None):
        result = self.call([self.options.git, "--no-pager", "-c", "protocol.allow=never",
                            "-C", str(directory), *argv], input=input)
        if check and result.returncode:
            raise AssertionError("synthetic Git operation failed")
        return result

    def close(self):
        self._check_progress()
        if self.processes:
            raise ValueError("active owned processes; cleanup refused")
        self.validate(existing=True)
        if self._observer is not None:
            self._observer.authorize_cleanup(self)
        # rmtree does not follow child symlinks. The root itself and ownership
        # were rechecked; external no-concurrent-mutation admission still applies.
        shutil.rmtree(self.root)
        admission(self.options, self.stage)


class Distribution:
    def __init__(self, run):
        self.run = run
        source = run.record["source"]
        self.source = canonical(source["root"])
        self.revision = source["revision"]
        if not re.fullmatch(r"(?!0{40}$)[0-9a-f]{40}", self.revision):
            raise ValueError("source pin not admitted")
        # This external manifest includes every candidate file and mode; it is
        # not generated from the candidate registry. Original-source preservation
        # and independent expectations remain external review obligations.
        self.manifest = source["files"]
        if not isinstance(self.manifest, dict) or len(self.manifest) != 39:
            raise ValueError("complete 39-file candidate manifest required")
        self.check_files(self.source)
        actual = run.git(self.source, "rev-parse", "HEAD").stdout.decode().strip()
        if actual != self.revision:
            raise ValueError("bundle producer HEAD mismatch")
        self.bundle = run.root / "cache/provider.bundle"
        run.git(self.source, "bundle", "create", str(self.bundle), "HEAD")
        # A complete bundle has no '-' prerequisite header lines.
        header = self.bundle.read_bytes().split(b"\n\n", 1)[0]
        if any(line.startswith(b"-") for line in header.splitlines()):
            raise ValueError("incomplete bundle")
        self.root = self.materialize("provider/distribution")
        self.check_files(self.root)
        self.caller = self.make_caller()

    def check_files(self, root):
        for relative, mark in self.manifest.items():
            path = root / relative
            if (".." in Path(relative).parts or Path(relative).is_absolute()
                    or path.resolve() != path or not path.is_file()
                    or digest(path) != mark["sha256"]
                    or ("100755" if path.stat().st_mode & 0o111 else "100644") != mark["mode"]):
                raise ValueError("externally admitted source manifest mismatch")

    def materialize(self, relative):
        target = self.run.target(relative)
        if target.exists():
            raise ValueError("distribution destination exists")
        self.run.git(self.run.root, "init", "--template=", "--object-format=sha1", str(target))
        self.run.git(target, "bundle", "unbundle", str(self.bundle))
        self.run.git(target, "checkout", "--detach", self.revision)
        return target

    def make_caller(self):
        run = self.run
        caller = run.root / "caller"
        run.git(caller, "init", "--template=", "--object-format=sha1")
        index = {"schema": 1, "kind": "index", "routes": [
            {"patterns": ["src/**"], "context": "src/CONTEXT.md"}],
            "exclusions": [{"patterns": ["CONTEXT.md", "ai/**", "docs/**", "scripts/**", "reference.json"],
                            "reason": "synthetic caller metadata"}]}
        self.leaf = {"schema": 1, "kind": "leaf", "layer": "Source", "parent": "CONTEXT.md",
                     "scope": ["src/**"], "group": "core", "dependencies": [], "dependents": [],
                     "red_lines": ["synthetic boundary"], "gates": []}
        self.context("CONTEXT.md", index)
        self.context("src/CONTEXT.md", self.leaf)
        for path in ("src/example.py", "ai/registry.json", "docs/integration-and-migration.md", "scripts/contracts/resolve.py"):
            run.write("caller/" + path, "caller decoy\n")
        run.git(caller, "add", "--", ".")
        run.git(caller, "commit", "-m", "synthetic caller")
        for command, name in (("python3", "python"), ("git", "git"), ("dirname", "dirname")):
            if hasattr(run.options, name):
                (run.root / "tools" / command).symlink_to(getattr(run.options, name))
        return caller

    def context(self, path, data):
        self.run.write("caller/" + path, "---\n" + json.dumps(data) + "\n---\n# Synthetic context\n")

    def resolve(self, entry="task.upgrade", *, root=None, revision=None, environment=None, tokens=None):
        provider = root or self.root
        argv = [self.run.options.python, "-I", "-S", "-B", str(provider / "scripts/contracts/resolve.py")]
        argv += tokens if tokens is not None else ["--git", self.run.options.git, "--revision", revision or self.revision, "--entry", entry]
        return self.run.call(argv, cwd=self.caller, environment=environment)

    def mark(self, path, root=None, revision=None):
        provider, pin = root or self.root, revision or self.revision
        row = self.run.git(provider, "ls-tree", "-z", pin, "--", path).stdout
        meta, name = row.rstrip(b"\0").split(b"\t", 1)
        mode, typ, oid = meta.decode().split()
        if name.decode() != path or typ != "blob":
            raise AssertionError("independent expected blob absent")
        raw = self.run.git(provider, "cat-file", "blob", oid).stdout
        return {"blob": oid, "mode": mode, "sha256": hashlib.sha256(raw).hexdigest()}, raw

    def negative(self, label, edit):
        root = self.materialize("provider/negative-" + label)
        edit(root)
        self.run.git(root, "add", "--all")
        self.run.git(root, "commit", "--allow-empty", "-m", "synthetic negative " + label)
        pin = self.run.git(root, "rev-parse", "HEAD").stdout.decode().strip()
        return root, pin

    def context_call(self, command, *args, wrapper=False, input=None):
        provider = self.root / "scripts/context"
        argv = ([self.run.options.shell, str(provider / command)] if wrapper else
                [self.run.options.python, "-I", "-S", "-B", str(provider / "_context.py"), command])
        return self.run.call(argv + list(args), cwd=self.caller, input=input)
