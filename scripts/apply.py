"""Apply (or undo) "Fool" mode for Claude Code in VS Code, in the environment this runs in.

Two parts:
  1. Hook: copy assets/review-edits-mode.py to ~/.claude/hooks/ and register it in
     ~/.claude/settings.json (hooks.PreToolUse, matcher "*"). Changes behavior of acceptEdits mode.
  2. Webview: patch webview/index.js of the newest Claude Code extension in each VS Code
     extensions folder found (~/.vscode/extensions, ~/.vscode-server/extensions, ...):
     - "Edit automatically" -> LABEL / DESCRIPTION, icon -> assets/icon.png.
     - Native diff tab also in full-editor sessions ("Open in Primary Editor"). Unpatched,
       those sessions skip the VS Code diff tab for Edit/Write approval and show only the
       in-chat preview / popup.
     Original kept as index.js.orig; patch is always made from it.

Usage:
  python3 apply.py                 # apply both
  python3 apply.py --restore       # put index.js back and unregister the hook
  python3 apply.py --check         # report state only, change nothing
  python3 apply.py --label X --description Y
  python3 apply.py --index-js PATH # patch this one file only (testing)
"""
import argparse
import base64
import json
import re
import shutil
import sys
from pathlib import Path

LABEL = "Fool"
DESCRIPTION = "It's a me, Fool! Ask Claude during it write code."

SKILL_DIR = Path(__file__).resolve().parent.parent
ICON = SKILL_DIR / "assets" / "icon.png"
HOOK_SRC = SKILL_DIR / "assets" / "review-edits-mode.py"
HOOK_NAME = HOOK_SRC.name

HOME = Path.home()
CLAUDE_DIR = HOME / ".claude"
SETTINGS = CLAUDE_DIR / "settings.json"
HOOK_DST = CLAUDE_DIR / "hooks" / HOOK_NAME
EXT_ROOTS = [
    HOME / ".vscode" / "extensions",
    HOME / ".vscode-insiders" / "extensions",
    HOME / ".vscode-server" / "extensions",
    HOME / ".vscode-server-insiders" / "extensions",
]

# acceptEdits:{icon:m(dAe,{}),iconV2:m(dFt,{}),iconV2Small:m(uFt,{}),label:"Edit automatically",description:"..."}
# Minified names change per release, so match the shape.
PATTERN = re.compile(
    r'acceptEdits:\{icon:([\w$]+)\([\w$]+,\{\}\),iconV2:\1\([\w$]+,\{\}\),'
    r'iconV2Small:\1\([\w$]+,\{\}\),label:"Edit automatically",description:"[^"]*"\}'
)


# Full-editor guards around the native diff tab:
#   permission handler, Edit and Write branches:
#     if(window.IS_FULL_EDITOR)return;let n=new AbortController;...t.openDiff(...)
#   accept path that saves through the open diff tab:
#     if(window.IS_FULL_EDITOR||!t.acceptDiff||b!==null)return;
# (regex, replacement, expected match count)
DIFF_PATCHES = [
    (re.compile(r'if\(window\.IS_FULL_EDITOR\)return;(let [\w$]+=new AbortController;)'), r'\1', 2),
    (re.compile(r'if\(window\.IS_FULL_EDITOR\|\|(![\w$]+\.acceptDiff\|\|)'), r'if(\1', 1),
]
DIFF_MARK = "/*fool:full-editor-diff*/"


def js_str(s):
    return json.dumps(s, ensure_ascii=False)


def version_key(p):
    # anthropic.claude-code-2.1.325-linux-x64 -> (2, 1, 325)
    m = re.match(r"anthropic\.claude-code-(\d+(?:\.\d+)*)", p.name)
    return tuple(int(x) for x in m.group(1).split(".")) if m else ()


def find_index_js():
    found = []
    for root in EXT_ROOTS:
        if not root.is_dir():
            continue
        dirs = [d for d in root.glob("anthropic.claude-code-*") if d.is_dir() and version_key(d)]
        if dirs:
            newest = max(dirs, key=version_key)
            found.append(newest / "webview" / "index.js")
    return found


def patch_index(target, label, desc, check):
    backup = target.with_name(target.name + ".orig")
    current = target.read_text(encoding="utf-8")
    is_patched = backup.exists() and f"label:{js_str(label)}" in current
    if check:
        print(f"  [{'patched' if is_patched else 'NOT patched'}] {target}")
        print(f"  [{'patched' if DIFF_MARK in current else 'NOT patched'}] full-editor diff tab")
        return True
    if not backup.exists():
        shutil.copy2(target, backup)
    text = backup.read_text(encoding="utf-8")
    matches = list(PATTERN.finditer(text))
    if len(matches) != 1:
        print(f"  [FAIL] {target}: expected 1 acceptEdits picker entry, found {len(matches)}. "
              "Extension code changed; update PATTERN in apply.py.")
        return False
    m = matches[0]
    jsx = m.group(1)
    uri = "data:image/png;base64," + base64.b64encode(ICON.read_bytes()).decode()

    def img(size, pad):
        return (f'{jsx}("img",{{src:"{uri}",width:{size},height:{size},alt:"",'
                f'style:{{display:"block",margin:"{pad}px"}}}})')

    repl = (f"acceptEdits:{{icon:{img(16, 0)},iconV2:{img(20, 0)},iconV2Small:{img(16, 2)},"
            f"label:{js_str(label)},description:{js_str(desc)}}}")
    text = text[:m.start()] + repl + text[m.end():]

    ok = True
    diff_ok = True
    for rx, sub, want in DIFF_PATCHES:
        got = len(rx.findall(text))
        if got != want:
            diff_ok = False
            print(f"  [FAIL] full-editor diff: expected {want} of {rx.pattern}, found {got}. "
                  "Extension code changed; update DIFF_PATCHES in apply.py.")
    if diff_ok:
        for rx, sub, _ in DIFF_PATCHES:
            text = rx.sub(sub, text)
        text = DIFF_MARK + text
    else:
        ok = False

    target.write_text(text, encoding="utf-8")
    print(f"  [patched] {target}" + ("" if diff_ok else " (label only, diff tab patch skipped)"))
    return ok


def restore_index(target):
    backup = target.with_name(target.name + ".orig")
    if backup.exists():
        shutil.copy2(backup, target)
        print(f"  [restored] {target}")
    else:
        print(f"  [no backup, untouched] {target}")


def load_settings():
    if not SETTINGS.exists():
        return {}
    return json.loads(SETTINGS.read_text(encoding="utf-8-sig") or "{}")


def save_settings(data):
    if SETTINGS.exists():
        shutil.copy2(SETTINGS, SETTINGS.with_name("settings.json.fool-bak"))
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def is_our_hook(h):
    return HOOK_NAME in h.get("command", "")


def hook_registered(data):
    return any(is_our_hook(h) for g in data.get("hooks", {}).get("PreToolUse", [])
               for h in g.get("hooks", []))


def install_hook(check):
    data = load_settings()
    registered = hook_registered(data)
    if check:
        print(f"  [{'registered' if registered else 'NOT registered'}] {SETTINGS}")
        print(f"  [{'present' if HOOK_DST.exists() else 'MISSING'}] {HOOK_DST}")
        return
    HOOK_DST.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(HOOK_SRC, HOOK_DST)
    print(f"  [copied] {HOOK_DST}")
    if registered:
        print(f"  [already registered] {SETTINGS}")
        return
    cmd = f'"{Path(sys.executable).as_posix()}" "{HOOK_DST.as_posix()}"'
    data.setdefault("hooks", {}).setdefault("PreToolUse", []).append(
        {"matcher": "*", "hooks": [{"type": "command", "command": cmd, "timeout": 5}]}
    )
    save_settings(data)
    print(f"  [registered] {SETTINGS}: {cmd}")


def remove_hook():
    data = load_settings()
    if not hook_registered(data):
        print(f"  [not registered] {SETTINGS}")
        return
    groups = []
    for g in data["hooks"]["PreToolUse"]:
        g["hooks"] = [h for h in g.get("hooks", []) if not is_our_hook(h)]
        if g["hooks"]:
            groups.append(g)
    data["hooks"]["PreToolUse"] = groups
    if not groups:
        del data["hooks"]["PreToolUse"]
    if not data["hooks"]:
        del data["hooks"]
    save_settings(data)
    print(f"  [unregistered] {SETTINGS} (hook file left at {HOOK_DST})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--restore", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--label", default=LABEL)
    ap.add_argument("--description", default=DESCRIPTION)
    ap.add_argument("--index-js", type=Path, help="patch only this file (no hook changes)")
    a = ap.parse_args()

    if a.index_js:
        sys.exit(0 if patch_index(a.index_js, a.label, a.description, a.check) else 1)

    targets = find_index_js()
    print("Extension webview:")
    if not targets:
        print("  [none] no anthropic.claude-code-* found under " + ", ".join(map(str, EXT_ROOTS)))
    ok = True
    for t in targets:
        if a.restore:
            restore_index(t)
        else:
            ok &= patch_index(t, a.label, a.description, a.check)

    print("Hook:")
    if a.restore:
        remove_hook()
    else:
        install_hook(a.check)

    if not a.check:
        print("Done. Reload the VS Code window (Developer: Reload Window).")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
