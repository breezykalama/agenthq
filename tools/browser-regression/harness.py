"""Opt-in, local-only browser regression harness for organization selection and switching.

Runs the 16-check browser suite (B1-B16), the B5/B9 and B12 organization-switch scenarios and the
dashboard rendering-isolation scenarios in headless Chrome against a real backend and frontend,
using disposable local PostgreSQL and Redis containers. Nothing here runs automatically, and
every connection target is checked by guard() before use. See README.md in this directory.

    python harness.py up                         disposable PostgreSQL 18 + Redis, credentials
    python harness.py prepare-tree --ref REF     clean detached worktree of REF to test
    python harness.py seed --tree PATH           isolated test data (multi-membership flag off)
    python harness.py run --tree PATH SCENARIO...  core, b12-normal, b12-inflight, b12-race,
                                                 b12-negative, b5b9-normal, b5b9-inflight,
                                                 b5b9-race, b5-negative, b9-negative,
                                                 dash-normal, dash-stale, dash-wrong-header,
                                                 dash-negative
    python harness.py validate --tree PATH       every scenario above
    python harness.py guard-selftest             prove the safety guards reject unsafe targets
    python harness.py cleanup-selftest           prove cleanup refuses resources it does not own
    python harness.py down                       stop containers; remove worktrees, credentials

Run it with the backend's Python environment (it needs psycopg), e.g.
    uv run --project backend --frozen python tools/browser-regression/harness.py ...
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
LABEL = "agenthq.browser-regression"
DB_NAME = "agenthq_browser_regression"
DB_USER = "agenthq_br"
PG_IMAGE, REDIS_IMAGE = "postgres:18-bookworm", "redis:7-alpine"
DEFAULT_PORTS = {"pg": 55420, "redis": 56380, "backend": 8019, "frontend": 4174, "cdp": 9334}
HEADER = "X-AgentHQ-Organization"
LOOPBACK = {"127.0.0.1", "localhost"}
# Anything that looks like a hosted or shared environment is refused outright.
FORBIDDEN = re.compile(
    r"railway|render\.com|onrender|vercel|supabase|neon\.tech|amazonaws|azure|herokuapp|staging|prod",
    re.I,
)
# Files that would mix developer or deployment settings into a "disposable" run.
TREE_ENV_FILES = (
    "backend/.env",
    "frontend/.env",
    "frontend/.env.local",
    "frontend/.env.production",
    "frontend/.env.production.local",
)
B12_SCENARIOS = ("b12-normal", "b12-inflight", "b12-race", "b12-negative")
B5B9_SCENARIOS = ("b5b9-normal", "b5b9-inflight", "b5b9-race", "b5-negative", "b9-negative")
DASH_SCENARIOS = ("dash-normal", "dash-stale", "dash-wrong-header", "dash-negative")
SCENARIOS = ("core", *B12_SCENARIOS, *B5B9_SCENARIOS, *DASH_SCENARIOS)
# Deliberately different dashboard data per organization (Step 113): total agents and their risk
# mix differ, so each organization's rendered dashboard is recognisable. The first agent of each
# organization keeps its original name and risk ("Agent A" / "Agent B", low).
SEED_AGENTS = {"a": (17, "medium"), "b": (3, "high")}
RESULTS: list[tuple[str, bool]] = []


OWNER = "agenthq-browser-regression"
# The only entries 'up', 'prepare-tree', 'seed' and 'run' ever create in a state directory.
STATE_ENTRY = re.compile(
    r"^(run\.json|state\.json|pg\.env|mail\.log|chrome-profile|dist-[A-Za-z0-9._-]+"
    r"|(server|preview)-[A-Za-z0-9._-]+\.log|tree-[0-9a-f]{7})$"
)


class GuardError(SystemExit):
    pass


class CleanupRefused(SystemExit):
    """Ownership could not be proven; nothing has been deleted."""


def is_link(path: Path) -> bool:
    return path.is_symlink() or os.path.isjunction(path)


def norm(path: Path | str) -> str:
    return os.path.normcase(os.path.realpath(path))


def find_links(root: Path, skip: set[str] | None = None) -> list[Path]:
    """Symlinks/junctions under root, without ever descending into one."""
    skip = skip or set()
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        keep = []
        for name in dirnames + filenames:
            path = Path(dirpath) / name
            if os.path.normcase(os.path.abspath(path)) in skip:
                continue
            if is_link(path):
                found.append(path)
            elif name in dirnames:
                keep.append(name)
        dirnames[:] = keep
    return found


def check(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, bool(ok)))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""), flush=True)
    return bool(ok)


# ------------------------------------------------------------------------------------ state


def state_dir(args: argparse.Namespace) -> Path:
    path = Path(
        args.state_dir
        or os.environ.get("AGENTHQ_BROWSER_REGRESSION_STATE")
        or Path(tempfile.gettempdir()) / "agenthq-browser-regression"
    ).resolve()
    if path == REPO or REPO in path.parents:
        raise GuardError(
            "REFUSED: the state directory (credentials, profile, builds) must be outside "
            "the repository"
        )
    return path


def load(args: argparse.Namespace) -> tuple[Path, dict]:
    sd = state_dir(args)
    if not (sd / "run.json").exists():
        raise SystemExit(f"no harness run in {sd}; start one with 'harness.py up'")
    return sd, json.loads((sd / "run.json").read_text(encoding="utf-8"))


def save(sd: Path, run: dict) -> None:
    (sd / "run.json").write_text(json.dumps(run, indent=1), encoding="utf-8")


# ----------------------------------------------------------------------------------- guards


def guard(values: dict[str, str], run: dict) -> None:
    """Refuse anything but this run's disposable loopback services."""
    ports = run["ports"]
    for key in ("DATABASE_URL", "REDIS_URL"):
        value = values.get(key, "")
        if not value:
            continue
        parts = urlsplit(value)
        if parts.hostname not in LOOPBACK:
            raise GuardError(f"REFUSED: {key} host is not loopback")
        if parts.port != (ports["pg"] if key == "DATABASE_URL" else ports["redis"]):
            raise GuardError(f"REFUSED: {key} port is not this harness run's container port")
        if key == "DATABASE_URL" and parts.path.lstrip("/") != DB_NAME:
            raise GuardError("REFUSED: DATABASE_URL does not name the harness database")
    for key, value in values.items():
        if key.upper().endswith(("_URL", "_ORIGINS", "_ORIGIN")):
            if FORBIDDEN.search(value):
                raise GuardError(f"REFUSED: {key} references a non-local environment")
            for part in value.split(","):
                host = urlsplit(part.strip()).hostname
                if part.strip() and host not in LOOPBACK:
                    raise GuardError(f"REFUSED: {key} is not a loopback address")


def inspect_container(container_id: str) -> dict | None:
    out = subprocess.run(
        ["docker", "inspect", "--type", "container", container_id], capture_output=True, text=True
    )
    return json.loads(out.stdout)[0] if out.returncode == 0 else None


def container_matches(info: dict, record: dict, run_id: str) -> bool:
    """The live container is exactly the one this run created: same full ID, name, label, image."""
    return (
        info["Id"] == record["id"]
        and info["Name"] == "/" + record["name"]
        and (info["Config"].get("Labels") or {}).get(LABEL) == run_id
        and info["Config"]["Image"] == record["image"]
    )


def verify_disposable(run: dict) -> None:
    """Database and Redis must be this run's labelled, auto-removed, loopback-only containers."""
    for role, port, inner in (
        ("pg", run["ports"]["pg"], "5432/tcp"),
        ("redis", run["ports"]["redis"], "6379/tcp"),
    ):
        record = run["containers"].get(role)
        info = inspect_container(record["id"]) if record else None
        if info is None:
            raise GuardError(
                f"REFUSED: the recorded harness {role} container is not running "
                "(run 'harness.py up')"
            )
        name = record["name"]
        bindings = info["HostConfig"]["PortBindings"].get(inner) or []
        if (
            not container_matches(info, record, run["run_id"])
            or not info["State"]["Running"]
            or not info["HostConfig"]["AutoRemove"]
            or [(b["HostIp"], b["HostPort"]) for b in bindings] != [("127.0.0.1", str(port))]
        ):
            raise GuardError(f"REFUSED: {name} is not this run's disposable loopback container")
        if role == "pg" and "/var/lib/postgresql" not in (info["HostConfig"].get("Tmpfs") or {}):
            raise GuardError("REFUSED: the harness database is not on tmpfs")


def check_tree(tree: Path) -> str:
    if (
        not (tree / "backend" / "app").is_dir()
        or not (tree / "frontend" / "package.json").is_file()
    ):
        raise SystemExit(f"{tree} is not an AgentHQ checkout")
    found = [f for f in TREE_ENV_FILES if (tree / f).exists()]
    if found:
        raise GuardError(
            f"REFUSED: {tree} contains {', '.join(found)}; the backend/frontend would read "
            "developer "
            "settings from it. Use 'harness.py prepare-tree' for a clean worktree."
        )
    if not (tree / "frontend" / "node_modules").exists():
        raise SystemExit(
            f"{tree}/frontend/node_modules is missing (npm ci, or prepare-tree --node-modules-from)"
        )
    return (
        subprocess.run(
            ["git", "-C", str(tree), "rev-parse", "--short", "HEAD"], capture_output=True, text=True
        ).stdout.strip()
        or "unknown"
    )


# --------------------------------------------------------------------------- local services


def db_url(run: dict, driver: bool = True) -> str:
    scheme = "postgresql+psycopg" if driver else "postgresql"
    return f"{scheme}://{DB_USER}:{run['secrets']['pg']}@127.0.0.1:{run['ports']['pg']}/{DB_NAME}"


def backend_env(run: dict, *, production: bool) -> dict[str, str]:
    keep = (
        "SYSTEMROOT",
        "PATH",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "HOME",
        "APPDATA",
        "LOCALAPPDATA",
        "COMSPEC",
        "PATHEXT",
        "WINDIR",
        "NUMBER_OF_PROCESSORS",
        "PROCESSOR_ARCHITECTURE",
        "LANG",
    )
    env = {k: v for k, v in os.environ.items() if k.upper() in keep}  # nothing else is inherited
    origin = f"http://127.0.0.1:{run['ports']['frontend']}"
    env.update(
        DATABASE_URL=db_url(run),
        JWT_SECRET_KEY=run["secrets"]["jwt"],
        BOOTSTRAP_SECRET=run["secrets"]["bootstrap"],
        ENVIRONMENT="production" if production else "development",
        EMAIL_BACKEND="disabled" if production else "console",
        MULTI_ORGANIZATION_MEMBERSHIPS_ENABLED="false",
        ALLOW_PUBLIC_REGISTRATION="false",
        MCP_DISCOVERY_MODE="mock",
        AUTH_RATE_LIMIT_ATTEMPTS="1000",
        ACCESS_TOKEN_EXPIRE_MINUTES="600",
        BACKEND_CORS_ORIGINS=origin,
        FRONTEND_BASE_URL=origin,
        EMAIL_OUTBOX_POLL_SECONDS="0.5",
        PYTHONUNBUFFERED="1",
    )
    if production:
        env["REDIS_URL"] = f"redis://127.0.0.1:{run['ports']['redis']}/0"
    guard(env, run)
    return env


def http(
    method: str, url: str, body: dict | None = None, headers: dict | None = None
) -> tuple[int, dict]:
    if urlsplit(url).hostname not in LOOPBACK:
        raise GuardError("REFUSED: HTTP target is not loopback")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as err:
        raw = err.read()
        try:
            return err.code, json.loads(raw) if raw else {}
        except ValueError:
            return err.code, {}


def wait_http(url: str, attempts: int = 120) -> bool:
    for _ in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=1) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(0.5)
    return False


class Backend:
    def __init__(
        self,
        run: dict,
        sd: Path,
        tree: Path,
        label: str,
        *,
        production: bool,
        mail_log: Path | None = None,
    ):
        self.cwd = tree / "backend"
        self.env = backend_env(run, production=production)
        self.base = f"http://127.0.0.1:{run['ports']['backend']}"
        where = subprocess.run(
            [sys.executable, "-c", "import app; print(app.__file__)"],
            cwd=self.cwd,
            env=self.env,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if not check(
            f"[{label}] backend is imported from the tested tree",
            str(self.cwd.resolve()) in str(Path(where).resolve()),
        ):
            raise SystemExit(1)
        self.log = open(sd / f"server-{label}.log", "w", encoding="utf-8")
        # The application's own start sequence, against the disposable database only.
        mig = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=self.cwd,
            env=self.env,
            capture_output=True,
            text=True,
        )
        self.log.write(mig.stdout + mig.stderr)
        if not check(
            f"[{label}] start sequence 'alembic upgrade head' succeeds (disposable database)",
            mig.returncode == 0,
        ):
            raise SystemExit(1)
        port = str(run["ports"]["backend"])
        cmd = (
            [sys.executable, str(HERE / "serve_with_mail_log.py"), port, str(mail_log)]
            if mail_log
            else [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                port,
                "--log-level",
                "warning",
            ]
        )
        self.proc = subprocess.Popen(
            cmd, cwd=self.cwd, env=self.env, stdout=self.log, stderr=subprocess.STDOUT
        )
        if not wait_http(f"{self.base}/health"):
            self.stop()
            raise SystemExit(f"{label}: backend did not become healthy (see {self.log.name})")

    def stop(self) -> None:
        self.proc.terminate()
        self.proc.wait(timeout=30)
        self.log.close()


def remove_file(path: Path) -> None:
    """Delete a file, waiting for Windows to release handles held by a just-stopped process."""
    for _ in range(40):
        try:
            path.unlink(missing_ok=True)
            return
        except PermissionError:
            time.sleep(0.25)
    raise SystemExit(f"could not delete {path}; delete it by hand (it may hold credentials)")


def kill_tree(proc: subprocess.Popen) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
    else:
        import signal

        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    proc.wait(timeout=30)


# --------------------------------------------------------------------------------- commands


def ensure_fresh_state_dir(sd: Path) -> None:
    """'up' only ever uses a state directory it creates itself; it never adopts existing content."""
    if is_link(sd):
        raise CleanupRefused(f"REFUSED: {sd} is a link; choose another --state-dir")
    if (sd / "run.json").exists():
        raise SystemExit(f"a harness run already exists in {sd}; run 'harness.py down' first")
    if sd.exists() and any(sd.iterdir()):
        raise CleanupRefused(
            f"REFUSED: {sd} exists and is not empty; the harness will not adopt (and later delete) "
            "content it did not create. Choose another --state-dir."
        )


def cmd_up(args: argparse.Namespace) -> None:
    sd = state_dir(args)
    ensure_fresh_state_dir(sd)
    if shutil.which("docker") is None:
        raise SystemExit("docker is required")
    sd.mkdir(parents=True, exist_ok=True)
    run_id = secrets.token_hex(8)
    run = {
        "owner": OWNER,
        "run_id": run_id,
        "state_dir": str(sd),
        "ports": {
            **DEFAULT_PORTS,
            **{
                k: v
                for k, v in {
                    "pg": args.pg_port,
                    "redis": args.redis_port,
                    "backend": args.backend_port,
                    "frontend": args.frontend_port,
                    "cdp": args.cdp_port,
                }.items()
                if v
            },
        },
        "containers": {},  # role -> {"name", "id", "image"}, recorded as each one is created
        "secrets": {
            "pg": secrets.token_urlsafe(24),
            "jwt": secrets.token_urlsafe(48),
            "bootstrap": secrets.token_urlsafe(24),
        },
        "worktrees": [],
        "seeded": False,
    }
    save(sd, run)  # before the containers start, so 'down' can always clean up
    env_file = sd / "pg.env"
    env_file.write_text(
        f"POSTGRES_USER={DB_USER}\nPOSTGRES_PASSWORD={run['secrets']['pg']}\nPOSTGRES_DB={DB_NAME}\n",
        encoding="utf-8",
    )
    common = ["docker", "run", "--rm", "-d", "--label", f"{LABEL}={run_id}"]
    specs = (
        (
            "pg",
            PG_IMAGE,
            [
                "-p",
                f"127.0.0.1:{run['ports']['pg']}:5432",
                "--env-file",
                str(env_file),
                "--tmpfs",
                "/var/lib/postgresql",
                PG_IMAGE,
            ],
        ),
        (
            "redis",
            REDIS_IMAGE,
            [
                "-p",
                f"127.0.0.1:{run['ports']['redis']}:6379",
                REDIS_IMAGE,
                "redis-server",
                "--save",
                "",
                "--appendonly",
                "no",
            ],
        ),
    )
    try:
        for role, image, rest in specs:
            name = f"agenthq-br-{role}-{run_id}"
            r = subprocess.run(common + ["--name", name] + rest, capture_output=True, text=True)
            if r.returncode != 0:
                raise SystemExit(f"docker run failed: {r.stderr.strip()[-300:]}")
            # Ownership record: the full container ID docker returned for the container we made.
            run["containers"][role] = {"name": name, "id": r.stdout.strip(), "image": image}
            save(sd, run)
    finally:
        remove_file(env_file)
    import psycopg

    for _ in range(120):
        try:
            with psycopg.connect(db_url(run, driver=False), connect_timeout=2):
                break
        except psycopg.OperationalError:
            time.sleep(0.5)
    else:
        raise SystemExit("PostgreSQL did not become ready")
    verify_disposable(run)
    print(
        f"harness run {run_id}: PostgreSQL 18 on 127.0.0.1:{run['ports']['pg']}, "
        "Redis on 127.0.0.1:"
        f"{run['ports']['redis']} (tmpfs/no persistence, auto-removed); state in {sd}"
    )


def cmd_prepare_tree(args: argparse.Namespace) -> None:
    sd, run = load(args)
    sha = subprocess.run(
        ["git", "-C", str(REPO), "rev-parse", "--verify", f"{args.ref}^{{commit}}"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    if not sha:
        raise SystemExit(f"unknown ref {args.ref}")
    tree = sd / f"tree-{sha[:7]}"
    if tree.exists():
        raise SystemExit(f"{tree} already exists")
    r = subprocess.run(
        ["git", "-C", str(REPO), "worktree", "add", "--detach", str(tree), sha],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        raise SystemExit(r.stderr.strip())
    # Ownership record, written as soon as git has created the worktree.
    record = {"path": str(tree), "sha": sha, "modules": None}
    run["worktrees"].append(record)
    save(sd, run)
    modules = tree / "frontend" / "node_modules"
    if args.node_modules_from:
        source = Path(args.node_modules_from).resolve()
        if not (source / ".package-lock.json").exists() and not (source / "vite").exists():
            raise SystemExit(f"{source} does not look like a frontend node_modules directory")
        if os.name == "nt":
            subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(modules), str(source)],
                capture_output=True,
                check=True,
            )
        else:
            modules.symlink_to(source, target_is_directory=True)
        record["modules"] = {"kind": "link", "target": str(source)}
        print(f"linked {modules} -> {source} (unlinked again by 'down')")
    else:
        npm = shutil.which("npm.cmd") or shutil.which("npm") or "npm"
        subprocess.run([npm, "ci", "--no-audit", "--no-fund"], cwd=tree / "frontend", check=True)
        record["modules"] = {"kind": "npm"}
    save(sd, run)
    print(f"prepared clean detached worktree of {sha[:7]}:")
    print(tree)  # last line: the --tree path


def seed(run: dict, sd: Path, tree: Path) -> dict:
    """Isolated test data. The multi-membership flag stays OFF: dual's extra memberships are
    operator-provisioned through the application's own models on the disposable database."""
    mail_log = sd / "mail.log"
    names = ("dual", "admin_b", "admin_c", "admin_d", "single_a")
    pw = {k: secrets.token_urlsafe(18) + "aA1!" for k in names}
    st: dict = {"password": pw, "org": {}, "user": {}}
    srv = Backend(run, sd, tree, "seed", production=False, mail_log=mail_log)
    base = srv.base

    def login(email: str, password: str) -> str:
        code, body = http(
            "POST", f"{base}/api/v1/auth/login", {"email": email, "password": password}
        )
        assert code == 200, (email, code)
        return body["access_token"]

    def bearer(token: str, org: str | None = None) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}", **({HEADER: org} if org else {})}

    def orm(code: str) -> str:
        prelude = (
            "import sys, json, uuid\nfrom datetime import UTC, datetime\nsys.path.insert(0, '.')\n"
            "from sqlalchemy import select\nfrom app.core.security import hash_password\n"
            "from app.db.session import get_session_local\n"
            "from app.models.organization import Organization, OrganizationMembership\n"
            "from app.models.user import User, UserRole\ndb = get_session_local()()\n"
        )
        r = subprocess.run(
            [sys.executable, "-c", prelude + code],
            cwd=srv.cwd,
            env=srv.env,
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            raise SystemExit("ORM step failed: " + r.stderr[-400:])
        return r.stdout.strip()

    def mail_token(recipient: str, action: str) -> str:
        for _ in range(40):
            text = mail_log.read_text(encoding="utf-8") if mail_log.exists() else ""
            blocks = [b for b in text.split("console_email recipient=") if b.startswith(recipient)]
            found = [
                m.group(1)
                for b in blocks
                for m in re.finditer(rf"auth={action}#token=([A-Za-z0-9_\-.~%]+)", b)
            ]
            if found:
                return found[-1]
            time.sleep(0.5)
        raise SystemExit(f"no {action} e-mail for {recipient}")

    try:
        code, body = http(
            "POST",
            f"{base}/api/v1/organizations/bootstrap",
            {
                "organization_name": "Rehearsal Org A",
                "admin_full_name": "Dual User",
                "admin_email": "dual@rehearsal.example.com",
                "admin_password": pw["dual"],
            },
            {"X-Bootstrap-Secret": run["secrets"]["bootstrap"]},
        )
        check("[seed] bootstrap Org A (real API)", code == 201, str(code))
        st["org"]["a"] = body["user"]["organization_membership"]["organization_id"]
        st["user"]["dual"] = body["user"]["id"]
        code, _ = http(
            "POST",
            f"{base}/api/v1/auth/verify-email",
            {"token": mail_token("dual@rehearsal.example.com", "verify-email")},
        )
        check("[seed] bootstrap admin verifies e-mail", code == 200, str(code))
        out = orm(f"""
pw = json.loads({json.dumps(json.dumps(pw))})
dual = db.get(User, uuid.UUID({json.dumps(st["user"]["dual"])}))
ids = {{}}
for key, role in (("b", UserRole.AUDITOR), ("c", UserRole.ADMIN), ("d", UserRole.ADMIN)):
    org = Organization(name=f"Rehearsal Org {{key.upper()}}", slug=f"rehearsal-org-{{key}}")
    admin = User(email=f"admin-{{key}}@rehearsal.example.com", full_name=f"Admin {{key.upper()}}",
                 password_hash=hash_password(pw[f"admin_{{key}}"]), role=UserRole.ADMIN,
                 email_verified=True, email_verified_at=datetime.now(UTC))
    db.add_all([org, admin]); db.flush()
    db.add(OrganizationMembership(organization_id=org.id, user_id=admin.id, role=UserRole.ADMIN))
    db.add(OrganizationMembership(organization_id=org.id, user_id=dual.id, role=role))
    ids[key] = str(org.id)
db.commit()
print(json.dumps(ids))
""")
        st["org"].update(json.loads(out))
        check(
            "[seed] Orgs B, C, D with admins; dual provisioned as B auditor, C admin, "
            "D admin (ORM, flag off)",
            True,
        )
        tok = {
            k: login(f"admin-{k[-1]}@rehearsal.example.com", pw[k]) for k in ("admin_b", "admin_c")
        }
        tok["dual"] = login("dual@rehearsal.example.com", pw["dual"])
        code, body = http(
            "POST",
            f"{base}/api/v1/organization-invites",
            {
                "email": "single-a@rehearsal.example.com",
                "role": "operator",
                "full_name": "single_a",
            },
            bearer(tok["dual"], st["org"]["a"]),
        )
        assert code == 201, code
        code, _ = http(
            "POST",
            f"{base}/api/v1/organization-invites/accept",
            {"token": body["token"], "password": pw["single_a"]},
        )
        check(
            "[seed] single_a joins Org A via invite as operator (first membership; flag off)",
            code == 200,
            str(code),
        )
        code, _ = http(
            "POST",
            f"{base}/api/v1/users/{st['user']['dual']}/deactivate",
            None,
            bearer(tok["admin_c"]),
        )
        check("[seed] Org C admin deactivates dual's membership (API)", code == 200, str(code))
        for key, token, org in (("a", tok["dual"], st["org"]["a"]), ("b", tok["admin_b"], None)):
            count, extra_risk = SEED_AGENTS[key]
            for i in range(1, count + 1):
                code, _ = http(
                    "POST",
                    f"{base}/api/v1/agents",
                    {
                        "name": f"Agent {key.upper()}" + ("" if i == 1 else f"-{i:02d}"),
                        "owner": "owner@rehearsal.example.com",
                        "department": "governance",
                        "risk_level": "low" if i == 1 else extra_risk,
                    },
                    bearer(token, org),
                )
                assert code == 201, code
            code, _ = http(
                "POST",
                f"{base}/api/v1/mcp-servers",
                {
                    "name": f"Gateway {key.upper()}",
                    "server_url": f"https://{key}.rehearsal.example.com/mcp",
                },
                bearer(token, org),
            )
            assert code == 201, code
        check(
            "[seed] 17 agents + Gateway A in Org A; 3 agents + Gateway B in Org B (API)",
            True,
            ", ".join(
                f"{k.upper()}: {n} agents, extra risk {r}" for k, (n, r) in SEED_AGENTS.items()
            ),
        )
        orm(
            "org = db.scalar(select(Organization).where(Organization.slug == 'rehearsal-org-d'))\n"
            "org.deleted_at = datetime.now(UTC)\ndb.commit()\n"
        )
        check("[seed] Org D soft-deleted (dual keeps an active membership row in it)", True)
        code, body = http(
            "GET",
            f"{base}/api/v1/auth/me",
            None,
            bearer(login("dual@rehearsal.example.com", pw["dual"])),
        )
        active = sorted(m["organization"]["name"] for m in body.get("organization_memberships", []))
        check(
            "[seed] dual's usable memberships are exactly A and B",
            active == ["Rehearsal Org A", "Rehearsal Org B"],
            ",".join(active),
        )
        code, _ = http(
            "POST",
            f"{base}/api/v1/auth/register",
            {
                "email": "walk-in@rehearsal.example.com",
                "full_name": "Walk In",
                "password": "Walk-In-Password-123!",
            },
        )
        check("[seed] public registration stays disabled (403)", code == 403, str(code))
    finally:
        srv.stop()
        remove_file(mail_log)  # verification links are credentials
    return st


def cmd_seed(args: argparse.Namespace) -> None:
    sd, run = load(args)
    if run["seeded"]:
        raise SystemExit("already seeded; 'down' and 'up' again for fresh data")
    if run.get("seed_started"):
        # Seeding is not idempotent (bootstrap, agents, memberships): a second attempt on a
        # partially seeded database would duplicate data, so only a fresh database is accepted.
        raise SystemExit(
            "a previous seed attempt did not complete; 'down' and 'up' for a fresh database"
        )
    tree = Path(args.tree).resolve()
    print(f"tree {tree} at {check_tree(tree)}")
    verify_disposable(run)
    run["seed_started"] = True
    save(sd, run)
    st = seed(run, sd, tree)
    (sd / "state.json").write_text(json.dumps(st), encoding="utf-8")
    run["seeded"] = all(ok for _, ok in RESULTS)
    save(sd, run)
    sys.exit(0 if run["seeded"] else 1)


TABLE_SQL = (
    "select count(*), md5(coalesce(string_agg(x::text, chr(10) order by x::text), '')) "
    'from "{t}" x'
)


def snapshot(run: dict) -> dict[str, list]:
    import psycopg

    with psycopg.connect(db_url(run, driver=False)) as db:
        return {
            t: list(db.execute(TABLE_SQL.format(t=t)).fetchone())
            for (t,) in db.execute(
                "select tablename from pg_tables where schemaname='public' order by 1"
            ).fetchall()
        }


def find_chrome(explicit: str | None) -> str:
    candidates = [explicit, os.environ.get("CHROME_PATH")]
    candidates += [
        shutil.which(n)
        for n in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome")
    ]
    for root in filter(
        None,
        (
            os.environ.get("PROGRAMFILES"),
            os.environ.get("PROGRAMFILES(X86)"),
            os.environ.get("LOCALAPPDATA"),
        ),
    ):
        candidates.append(str(Path(root) / "Google" / "Chrome" / "Application" / "chrome.exe"))
    candidates.append("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    for c in candidates:
        if c and Path(c).is_file():
            return c
    raise SystemExit("Chrome/Chromium not found; pass --chrome or set CHROME_PATH")


def browser_phase(args: argparse.Namespace, scenarios: list[str]) -> int:
    sd, run = load(args)
    if not run["seeded"]:
        raise SystemExit("seed first ('harness.py seed --tree ...')")
    bad = [s for s in scenarios if s not in SCENARIOS]
    if bad:
        raise SystemExit(f"unknown scenario(s) {bad}; choose from {SCENARIOS}")
    tree = Path(args.tree).resolve()
    head = check_tree(tree)
    verify_disposable(run)
    st = json.loads((sd / "state.json").read_text(encoding="utf-8"))
    ports = run["ports"]
    api_base, app_origin = (
        f"http://127.0.0.1:{ports['backend']}",
        f"http://127.0.0.1:{ports['frontend']}",
    )
    guard({"VITE_API_BASE_URL": api_base, "APP_ORIGIN": app_origin}, run)
    label = args.label or f"run-{head}"
    npx = shutil.which("npx.cmd") or shutil.which("npx") or "npx"
    dist = sd / f"dist-{label}"
    build_env = {**os.environ, "VITE_API_BASE_URL": api_base}
    build = subprocess.run(
        [npx, "vite", "build", "--outDir", str(dist), "--emptyOutDir"],
        cwd=tree / "frontend",
        env=build_env,
        capture_output=True,
        text=True,
    )
    check(
        f"[{label}] frontend of {head} builds against the local API",
        build.returncode == 0,
        build.stderr[-200:] if build.returncode else "",
    )
    before = snapshot(run)
    server = Backend(run, sd, tree, label, production=True)
    preview = chrome = None
    codes: list[int] = []
    try:
        preview = subprocess.Popen(
            [
                npx,
                "vite",
                "preview",
                "--outDir",
                str(dist),
                "--host",
                "127.0.0.1",
                "--port",
                str(ports["frontend"]),
                "--strictPort",
            ],
            cwd=tree / "frontend",
            stdout=open(sd / f"preview-{label}.log", "w"),
            stderr=subprocess.STDOUT,
            start_new_session=os.name != "nt",
        )
        if not wait_http(f"{app_origin}/login", 60):
            raise SystemExit("frontend preview did not start")
        profile = sd / "chrome-profile"
        chrome = subprocess.Popen(
            [
                find_chrome(args.chrome),
                "--headless=new",
                f"--remote-debugging-port={ports['cdp']}",
                "--remote-debugging-address=127.0.0.1",
                f"--user-data-dir={profile}",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-extensions",
                "--window-size=1400,1000",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if not wait_http(f"http://127.0.0.1:{ports['cdp']}/json/version", 60):
            raise SystemExit("Chrome DevTools endpoint did not start")
        with urllib.request.urlopen(f"http://127.0.0.1:{ports['cdp']}/json/version") as resp:
            browser = json.loads(resp.read())["Browser"]
        print(
            f"browser: {browser}; frontend + backend: {head} "
            "(production mode, multi-membership flag off)",
            flush=True,
        )
        pw = st["password"]
        env = {
            **os.environ,
            "CDP_PORT": str(ports["cdp"]),
            "APP_ORIGIN": app_origin,
            "API_BASE": api_base,
            "DUAL_EMAIL": "dual@rehearsal.example.com",
            "DUAL_PW": pw["dual"],
            "SINGLE_EMAIL": "single-a@rehearsal.example.com",
            "SINGLE_PW": pw["single_a"],
            "ITERATIONS": str(args.iterations),
            **{f"ORG_{k.upper()}": v for k, v in st["org"].items()},
        }
        for scenario in scenarios:
            print(f"--- scenario: {scenario}", flush=True)
            script = (
                "browser_core.mjs"
                if scenario == "core"
                else "b12.mjs"
                if scenario in B12_SCENARIOS
                else "b5b9.mjs"
                if scenario in B5B9_SCENARIOS
                else "dashboard_isolation.mjs"
            )
            result = subprocess.run(
                ["node", str(HERE / script)], env={**env, "MODE": scenario}, timeout=900
            )
            codes.append(result.returncode)
            check(f"[{label}] scenario {scenario}", result.returncode == 0)
    finally:
        if chrome:
            chrome.terminate()
            chrome.wait(timeout=30)
        if preview:
            kill_tree(preview)
        server.stop()
    after = snapshot(run)
    changed = sorted(t for t in before if before[t] != after.get(t))
    print(f"      tables changed by this browser phase: {changed or 'none'}", flush=True)
    failed = [n for n, ok in RESULTS if not ok]
    print(
        f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} harness checks passed"
        + (f"; failed: {failed}" if failed else "")
    )
    return 1 if failed else 0


def cmd_run(args: argparse.Namespace) -> None:
    sys.exit(browser_phase(args, args.scenarios))


def cmd_validate(args: argparse.Namespace) -> None:
    sys.exit(
        browser_phase(
            args,
            [*B12_SCENARIOS, *B5B9_SCENARIOS, *DASH_SCENARIOS] + ["core"] * args.core_runs,
        )
    )


def cmd_guard_selftest(args: argparse.Namespace) -> None:
    run = {"run_id": "selftest", "ports": dict(DEFAULT_PORTS), "secrets": {"pg": "x"}}
    good = f"postgresql+psycopg://u:p@127.0.0.1:{DEFAULT_PORTS['pg']}/{DB_NAME}"
    cases = [
        (
            "remote database host",
            {
                "DATABASE_URL": f"postgresql+psycopg://u:p@db.example.com:{DEFAULT_PORTS['pg']}/{DB_NAME}"
            },
        ),
        (
            "hosted database (Railway-style URL)",
            {"DATABASE_URL": "postgresql://u:p@containers.railway.app:5432/railway"},
        ),
        (
            "loopback but not the harness port",
            {"DATABASE_URL": f"postgresql+psycopg://u:p@127.0.0.1:5432/{DB_NAME}"},
        ),
        (
            "loopback, harness port, other database",
            {"DATABASE_URL": f"postgresql+psycopg://u:p@127.0.0.1:{DEFAULT_PORTS['pg']}/agenthq"},
        ),
        ("remote Redis", {"DATABASE_URL": good, "REDIS_URL": "redis://cache.example.com:6379/0"}),
        ("hosted frontend origin", {"BACKEND_CORS_ORIGINS": "https://agenthq.vercel.app"}),
        ("non-loopback API base", {"VITE_API_BASE_URL": "https://api.example.com"}),
    ]
    for name, values in cases:
        try:
            guard(values, run)
            check(f"guard rejects: {name}", False, "accepted")
        except GuardError as err:
            check(f"guard rejects: {name}", True, str(err))
    try:
        guard(
            {
                "DATABASE_URL": good,
                "REDIS_URL": f"redis://127.0.0.1:{DEFAULT_PORTS['redis']}/0",
                "BACKEND_CORS_ORIGINS": f"http://127.0.0.1:{DEFAULT_PORTS['frontend']}",
            },
            run,
        )
        check("guard accepts this run's loopback services", True)
    except GuardError as err:
        check("guard accepts this run's loopback services", False, str(err))
    try:
        verify_disposable(
            {
                **run,
                "containers": {
                    role: {"name": f"agenthq-br-{role}-doesnotexist", "id": "0" * 64, "image": img}
                    for role, img in (("pg", PG_IMAGE), ("redis", REDIS_IMAGE))
                },
            }
        )
        check(
            "container check rejects a database that is not a harness container", False, "accepted"
        )
    except GuardError as err:
        check("container check rejects a database that is not a harness container", True, str(err))
    for env_file in TREE_ENV_FILES[:1]:
        probe = Path(tempfile.mkdtemp(prefix="agenthq-br-tree-"))
        try:
            (probe / "backend" / "app").mkdir(parents=True)
            (probe / "frontend").mkdir()
            (probe / "frontend" / "package.json").write_text("{}")
            (probe / env_file).write_text("# placeholder\n")
            check_tree(probe)
            check(f"tree check rejects a checkout containing {env_file}", False, "accepted")
        except GuardError as err:
            check(
                f"tree check rejects a checkout containing {env_file}", True, str(err).split(";")[0]
            )
        finally:
            shutil.rmtree(probe)
    try:
        state_dir(argparse.Namespace(state_dir=str(REPO / "tmp-state")))
        check("state directory inside the repository is rejected", False, "accepted")
    except GuardError as err:
        check("state directory inside the repository is rejected", True, str(err))
    failed = [n for n, ok in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} guard checks passed")
    sys.exit(1 if failed else 0)


# ---------------------------------------------------------------------------------- cleanup
#
# Cleanup is two-phase. plan_cleanup() proves ownership of every resource from the records 'up'
# and 'prepare-tree' wrote when they created it, and raises CleanupRefused on any mismatch BEFORE
# anything is deleted. A name prefix or label match is never enough: containers are stopped only
# by their recorded full ID after name, label and image also match; worktrees are removed only if
# they sit directly in the state directory, carry the recorded name and commit, and are registered
# with this repository as detached worktrees; links are removed only if they point exactly where
# the record says. Processes are never killed by PID lookup: the harness only terminates the
# subprocess handles it spawned itself (in browser_phase / Backend), never anything else.


def registered_worktrees() -> dict[str, dict]:
    out = subprocess.run(
        ["git", "-C", str(REPO), "worktree", "list", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    found: dict[str, dict] = {}
    for block in out.strip().split("\n\n"):
        lines = block.splitlines()
        path = next((ln[9:] for ln in lines if ln.startswith("worktree ")), None)
        if path:
            found[norm(path)] = {
                "head": next((ln[5:] for ln in lines if ln.startswith("HEAD ")), ""),
                "detached": "detached" in lines,
            }
    return found


def plan_cleanup(sd: Path) -> dict:
    if is_link(sd):
        raise CleanupRefused(f"REFUSED: {sd} is a link; nothing is deleted")
    if (
        sd == Path(sd.anchor)
        or norm(sd) in {norm(Path.home()), norm(REPO)}
        or REPO.is_relative_to(sd)
    ):
        raise CleanupRefused(f"REFUSED: {sd} is not a harness state directory; nothing is deleted")
    marker = sd / "run.json"
    if not marker.is_file() or is_link(marker):
        raise CleanupRefused(f"REFUSED: {sd} has no harness run record; nothing is deleted")
    run = json.loads(marker.read_text(encoding="utf-8"))
    if run.get("owner") != OWNER or norm(run.get("state_dir", "")) != norm(sd):
        raise CleanupRefused(
            f"REFUSED: {marker} was not written for this directory; nothing is deleted"
        )

    containers = []
    for role, record in run.get("containers", {}).items():
        info = inspect_container(record["id"])
        if info is None:
            containers.append((role, record, False))  # already gone (auto-removed)
            continue
        if not container_matches(info, record, run["run_id"]):
            raise CleanupRefused(
                f"REFUSED: container {record['id'][:12]} does not match the recorded {role} "
                "container (ID, name, label and image must all match); nothing is deleted"
            )
        containers.append((role, record, True))

    registered = registered_worktrees()
    trees, skip = [], set()
    for record in run.get("worktrees", []):
        path = Path(record["path"])
        if norm(path.parent) != norm(sd) or path.name != f"tree-{record['sha'][:7]}":
            raise CleanupRefused(
                f"REFUSED: recorded worktree {path} is not a harness worktree inside {sd}; "
                "nothing is deleted"
            )
        if not path.exists() and norm(path) not in registered:
            continue  # already removed
        reg = registered.get(norm(path))
        if not reg or reg["head"] != record["sha"] or not reg["detached"] or is_link(path):
            raise CleanupRefused(
                f"REFUSED: {path} is not registered with this repository as the detached worktree "
                f"of {record['sha'][:7]} that the harness created; nothing is deleted"
            )
        if not (path / ".git").is_file():
            raise CleanupRefused(f"REFUSED: {path} is not a linked worktree; nothing is deleted")
        modules = path / "frontend" / "node_modules"
        expected = record.get("modules") or {}
        link = None
        if is_link(modules):
            if expected.get("kind") != "link" or norm(modules) != norm(expected["target"]):
                raise CleanupRefused(
                    f"REFUSED: {modules} links somewhere the harness did not record; "
                    "nothing is deleted"
                )
            link = modules
            skip.add(os.path.normcase(os.path.abspath(modules)))
        elif modules.exists() and expected.get("kind") == "link":
            raise CleanupRefused(
                f"REFUSED: {modules} was recorded as a link but is now a real directory; "
                "nothing is deleted"
            )
        others = find_links(path, skip)
        if others:
            raise CleanupRefused(
                f"REFUSED: unexpected link(s) inside {path}: {[str(p) for p in others[:3]]}; "
                "nothing is deleted"
            )
        trees.append((record, path, link))

    recorded_trees = {Path(r["path"]).name for r in run.get("worktrees", [])}
    for entry in sd.iterdir():
        if not STATE_ENTRY.match(entry.name) or (
            entry.name.startswith("tree-") and entry.name not in recorded_trees
        ):
            raise CleanupRefused(
                f"REFUSED: unexpected entry {entry} in the state directory; nothing is deleted"
            )
    tree_dirs = {os.path.normcase(os.path.abspath(p)) for _, p, _ in trees}
    links = find_links(sd, skip | tree_dirs)
    if links:
        raise CleanupRefused(
            f"REFUSED: unexpected link(s) in the state directory: {[str(p) for p in links[:3]]}; "
            "nothing is deleted"
        )
    return {"sd": sd, "run": run, "containers": containers, "trees": trees}


def execute_cleanup(plan: dict) -> None:
    sd, run = plan["sd"], plan["run"]
    for role, record, alive in plan["containers"]:
        if alive:
            info = inspect_container(record["id"])  # re-check immediately before acting
            if info is not None:
                if not container_matches(info, record, run["run_id"]):
                    raise CleanupRefused(f"REFUSED: {role} container changed; stopping cleanup")
                subprocess.run(["docker", "stop", record["id"]], capture_output=True, check=True)
        state = "stopped and auto-removed" if alive else "already gone; nothing stopped"
        print(f"{role} container {record['name']} ({record['id'][:12]}): {state}")
    for _record, path, link in plan["trees"]:
        if link is not None:
            target = os.path.realpath(link)
            os.unlink(link) if link.is_symlink() else os.rmdir(link)  # removes the link only
            if is_link(link) or link.exists():
                raise CleanupRefused(f"REFUSED: could not unlink {link}; stopping cleanup")
            print(f"unlinked {link} (target {target} untouched: {os.path.isdir(target)})")
        if find_links(path):
            raise CleanupRefused(f"REFUSED: link(s) appeared inside {path}; stopping cleanup")
        r = subprocess.run(
            ["git", "-C", str(REPO), "worktree", "remove", "--force", str(path)],
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            raise CleanupRefused(f"REFUSED: git could not remove {path}: {r.stderr.strip()}")
        print(f"removed worktree {path}")
    if find_links(sd):
        raise CleanupRefused(f"REFUSED: link(s) appeared in {sd}; stopping cleanup")
    shutil.rmtree(sd)
    print(f"deleted {sd} (credentials, test-data passwords, browser profile, builds, logs)")


def cmd_down(args: argparse.Namespace) -> None:
    sd = state_dir(args)
    if not sd.exists():
        print(f"nothing to clean up: {sd} does not exist")
        return
    execute_cleanup(plan_cleanup(sd))


def cmd_cleanup_selftest(args: argparse.Namespace) -> None:
    """Deliberate ownership mismatches against sentinel resources this self-test creates itself."""
    root = Path(tempfile.mkdtemp(prefix="agenthq-br-cleanup-selftest-"))
    decoy = root / "decoy-node-modules"
    decoy.mkdir()
    (decoy / "keep.txt").write_text("must survive cleanup\n")
    other_target = root / "other-target"
    other_target.mkdir()
    head = subprocess.run(
        ["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    sentinel = {"name": f"agenthq-br-pg-selftest-{secrets.token_hex(4)}", "image": REDIS_IMAGE}
    my_links: list[Path] = []
    my_trees: list[Path] = []

    def fake_state(name: str, **extra) -> Path:
        sd = root / name
        sd.mkdir()
        base = {"owner": OWNER, "run_id": "selftest-run", "state_dir": str(sd)}
        save(sd, {**base, "containers": {}, "worktrees": [], **extra})
        return sd

    def sentinel_running() -> bool:
        info = inspect_container(sentinel["id"])
        return bool(info and info["State"]["Running"])

    def link_dir(link: Path, target: Path) -> None:
        if os.name == "nt":
            subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link), str(target)],
                capture_output=True,
                check=True,
            )
        else:
            link.symlink_to(target, target_is_directory=True)
        my_links.append(link)

    def add_tree(sd: Path) -> Path:
        path = sd / f"tree-{head[:7]}"
        subprocess.run(
            ["git", "-C", str(REPO), "worktree", "add", "--detach", str(path), head],
            capture_output=True,
            check=True,
        )
        my_trees.append(path)
        return path

    def expect_refused(name: str, sd: Path, survives) -> None:
        try:
            execute_cleanup(plan_cleanup(sd))
            check(name, False, "cleanup proceeded")
        except CleanupRefused as err:
            check(name, sd.exists() and survives(), str(err)[:150])

    try:
        r = subprocess.run(
            ["docker", "run", "--rm", "-d", "--label", f"{LABEL}=selftest-run", "--name"]
            + [sentinel["name"], REDIS_IMAGE],
            capture_output=True,
            text=True,
            check=True,
        )
        sentinel["id"] = r.stdout.strip()

        sd = fake_state("unrecorded-container")
        execute_cleanup(plan_cleanup(sd))
        check(
            "a container with the harness name prefix and this run's label, but not recorded, "
            "is left running",
            sentinel_running() and not sd.exists(),
        )
        sd = fake_state(
            "same-name-other-id",
            containers={"pg": {"name": sentinel["name"], "id": "0" * 64, "image": REDIS_IMAGE}},
        )
        execute_cleanup(plan_cleanup(sd))
        check(
            "a container matching the recorded name and label but not the recorded ID is never "
            "stopped",
            sentinel_running(),
        )
        expect_refused(
            "recorded ID but another run's label: refused, foreign container left running",
            fake_state("other-run-label", run_id="another-run", containers={"pg": sentinel}),
            sentinel_running,
        )
        expect_refused(
            "recorded ID but a different name: refused, foreign container left running",
            fake_state("other-name", containers={"pg": {**sentinel, "name": "agenthq-br-pg-x"}}),
            sentinel_running,
        )
        expect_refused(
            "worktree record pointing at the development checkout: refused, checkout untouched",
            fake_state(
                "dev-checkout", worktrees=[{"path": str(REPO), "sha": head, "modules": None}]
            ),
            lambda: (REPO / ".git").exists(),
        )
        outside = root / "outside"
        outside.mkdir()
        outside_tree = add_tree(outside)
        expect_refused(
            "registered worktree outside the state directory: refused, worktree untouched",
            fake_state(
                "outside-tree",
                worktrees=[{"path": str(outside_tree), "sha": head, "modules": None}],
            ),
            lambda: (outside_tree / ".git").is_file(),
        )
        sd = fake_state("plain-dir")
        (sd / f"tree-{head[:7]}").mkdir()
        (sd / f"tree-{head[:7]}" / "keep.txt").write_text("not a worktree\n")
        save(
            sd,
            {
                **json.loads((sd / "run.json").read_text()),
                "worktrees": [{"path": str(sd / f"tree-{head[:7]}"), "sha": head, "modules": None}],
            },
        )
        expect_refused(
            "a directory named like a harness worktree but not registered with git: refused",
            sd,
            lambda: (sd / f"tree-{head[:7]}" / "keep.txt").exists(),
        )
        sd = root / "wrong-link"
        sd.mkdir()
        tree = add_tree(sd)
        link_dir(tree / "frontend" / "node_modules", decoy)
        run = {"owner": OWNER, "run_id": "selftest-run", "state_dir": str(sd), "containers": {}}
        run["worktrees"] = [
            {
                "path": str(tree),
                "sha": head,
                "modules": {"kind": "link", "target": str(other_target)},
            }
        ]
        save(sd, run)
        expect_refused(
            "node_modules linked somewhere other than recorded: refused, link and target untouched",
            sd,
            lambda: is_link(tree / "frontend" / "node_modules") and (decoy / "keep.txt").exists(),
        )
        run["worktrees"][0]["modules"]["target"] = str(decoy)
        save(sd, run)
        execute_cleanup(plan_cleanup(sd))
        my_trees.remove(tree)
        check(
            "owned worktree with a recorded node_modules link: removed without following the link",
            not sd.exists()
            and (decoy / "keep.txt").exists()
            and norm(tree) not in registered_worktrees(),
        )
        sd = fake_state("unexpected-file")
        (sd / "notes.txt").write_text("someone else's file\n")
        expect_refused(
            "unexpected file in the state directory: refused, file untouched",
            sd,
            lambda: (sd / "notes.txt").exists(),
        )
        sd = fake_state("planted-link")
        (sd / "chrome-profile").mkdir()
        link_dir(sd / "chrome-profile" / "escape", decoy)
        expect_refused(
            "link planted inside the state directory: refused, link target untouched",
            sd,
            lambda: (decoy / "keep.txt").exists(),
        )
        sd = root / "no-record"
        sd.mkdir()
        (sd / "data.txt").write_text("x\n")
        expect_refused(
            "directory without a harness run record: refused",
            sd,
            lambda: (sd / "data.txt").exists(),
        )
        sd = fake_state("forged-record")
        save(
            sd, {**json.loads((sd / "run.json").read_text()), "state_dir": str(root / "elsewhere")}
        )
        expect_refused("run record written for another directory: refused", sd, lambda: True)
        try:
            ensure_fresh_state_dir(root / "no-record")
            check("'up' refuses to adopt a non-empty existing directory", False, "accepted")
        except CleanupRefused as err:
            check("'up' refuses to adopt a non-empty existing directory", True, str(err)[:110])
    finally:
        if sentinel.get("id") and inspect_container(sentinel["id"]):
            subprocess.run(["docker", "stop", sentinel["id"]], capture_output=True)
        for link in my_links:
            if is_link(link):
                os.unlink(link) if link.is_symlink() else os.rmdir(link)
        for tree in my_trees:
            subprocess.run(
                ["git", "-C", str(REPO), "worktree", "remove", "--force", str(tree)],
                capture_output=True,
            )
        if not find_links(root):
            shutil.rmtree(root)
        else:
            print(f"left {root} in place: it still contains links")
    check(
        "self-test teardown left no sentinel container",
        not inspect_container(sentinel.get("id", "0")),
    )
    check(
        "self-test teardown left no self-test worktree",
        not any("agenthq-br-cleanup-selftest-" in p for p in registered_worktrees()),
    )
    check("developer node_modules untouched", (REPO / "frontend" / "node_modules").is_dir())
    failed = [n for n, ok in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} cleanup ownership checks passed")
    sys.exit(1 if failed else 0)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--state-dir", help="where credentials, profile and builds live (default: system temp dir)"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    up = sub.add_parser("up")
    for name in ("pg", "redis", "backend", "frontend", "cdp"):
        up.add_argument(f"--{name}-port", type=int)
    up.set_defaults(func=cmd_up)
    prep = sub.add_parser("prepare-tree")
    prep.add_argument("--ref", default="HEAD")
    prep.add_argument(
        "--node-modules-from", help="link an existing frontend/node_modules instead of 'npm ci'"
    )
    prep.set_defaults(func=cmd_prepare_tree)
    sd_ = sub.add_parser("seed")
    sd_.add_argument("--tree", required=True)
    sd_.set_defaults(func=cmd_seed)
    for name, func in (("run", cmd_run), ("validate", cmd_validate)):
        p = sub.add_parser(name)
        p.add_argument("--tree", required=True)
        p.add_argument("--label")
        p.add_argument("--chrome")
        p.add_argument("--iterations", type=int, default=10, help="iterations per scenario")
        if name == "run":
            p.add_argument("scenarios", nargs="+")
        else:
            p.add_argument("--core-runs", type=int, default=3)
        p.set_defaults(func=func)
    sub.add_parser("guard-selftest").set_defaults(func=cmd_guard_selftest)
    sub.add_parser("cleanup-selftest").set_defaults(func=cmd_cleanup_selftest)
    sub.add_parser("down").set_defaults(func=cmd_down)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
