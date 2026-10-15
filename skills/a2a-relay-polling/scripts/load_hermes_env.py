"""Load ~/.hermes/.env, honouring HERMES_HOME, so secrets never touch argv.

Shell `source ~/.hermes/.env` BREAKS on values holding paths with spaces
(e.g. CHROME_PATH=/Applications/Google Chrome.app/...) - bash tries to execute
the tail. Parse line-by-line instead; export nothing, just populate os.environ.

Usage:
    from load_hermes_env import load_env
    load_env()          # then os.environ['A2A_HUB_TOKEN'] etc. are set
"""
import os
import pathlib


def load_env(env_path=None):
    path = pathlib.Path(env_path or os.getenv("HERMES_HOME", "~/.hermes")).expanduser() / ".env"
    loaded = {}
    if not path.exists():
        return loaded
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        if key:
            os.environ[key] = val
            loaded[key] = val
    return loaded


if __name__ == "__main__":
    d = load_env()
    tok = d.get("A2A_HUB_TOKEN", "")
    print(f"A2A_AGENT_ID = {d.get('A2A_AGENT_ID', '(unset)')}")
    print(f"A2A_HUB_TOKEN = {tok[:6]}...{tok[-4:]}" if tok else "A2A_HUB_TOKEN = (unset)")
