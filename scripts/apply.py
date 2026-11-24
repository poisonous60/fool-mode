"""Apply (or undo) "Fool" mode for Claude Code in VS Code, in the environment this runs in.

Parts:
  1. Hook: copy assets/review-edits-mode.py to ~/.claude/hooks/ and register it in
     ~/.claude/settings.json (hooks.PreToolUse, matcher "*"). Changes behavior of acceptEdits mode.
  2. Webview: patch webview/index.js of the newest Claude Code extension in each VS Code
     extensions folder found (~/.vscode/extensions, ~/.vscode-server/extensions, ...):
     - "Edit automatically" -> LABEL / DESCRIPTION, icon -> assets/icon.png.
     - Native diff tab also in full-editor sessions ("Open in Primary Editor"). Unpatched,
       those sessions skip the VS Code diff tab for Edit/Write approval and show only the
       in-chat preview / popup.
     - Keyboard shortcuts from assets/keys.js (scroll, history, accept/reject/reason).
  3. Extension host: patch extension.js of the same extension so keybindings can trigger
     accept / reject / reason in the webview (claude-vscode.focusLastMessage forwards its argument).
  4. Markdown preview: append assets/md-preview-keys.js to VS Code's built-in markdown preview
     script (server and local copies), so Ctrl+Alt+Up/Down/PgUp/PgDn/Home/End scroll markdown diffs.
  5. Keybindings: for keys pressed outside the webview, add to the VS Code user keybindings.json
     Ctrl+Alt+Enter / Backspace / Z -> accept / reject / reason (via 3), and
     Ctrl+Alt+Up/Down/PgUp/PgDn/Home/End -> scroll, in a text diff only.
  6. PDF links: chat links like `file.pdf#L16` open in the PDF viewer extension (tomoki1207.pdf)
     at page 16. extension.js (3) calls pdfPreview.setPage; the PDF viewer gets assets/pdf-page.js
     (out/src/extension.js), assets/pdf-page-viewer.js (lib/main.js) and an activation event (package.json).
  Patched files (2-4, 6) keep their original as <name>.orig; patches are always made from it.

Usage:
  python3 apply.py                 # apply
  python3 apply.py --restore       # undo patch
  python3 apply.py --check         # report state only, change nothing
  python3 apply.py --label X --description Y
  python3 apply.py --index-js PATH # patch this one file only (testing)
"""
import argparse
import base64
import json
import os
import re
import shutil
import sys
from pathlib import Path

LABEL = "Fool"
DESCRIPTION = "It's a me, Fool! Ask Claude during it write code."

SKILL_DIR = Path(__file__).resolve().parent.parent
ICON = SKILL_DIR / "assets" / "icon.png"
KEYS_JS = SKILL_DIR / "assets" / "keys.js"
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

# Ctrl+Alt+Z ("reason") with no permission prompt: focus the chat input instead of the last message.
#   switch(e.request.type){...case"focus_last_message":if(this.isVisible.value)this.focusLastMessageSignal.emit();...
# Inserts a branch that does what case"focus_input" does. window.foolHasPrompt comes from keys.js.
FOCUS_SWITCH = re.compile(r'switch\(([\w$]+)\.request\.type\)\{case"tool_permission_request"')
FOCUS_CASE = re.compile(r'case"focus_last_message":(?=if\(this\.isVisible\.value\)this\.focusLastMessageSignal\.emit\(\))')
FOCUS_MARK = "/*fool:reason-focus-input*/"
KEYS_MARK = "/*fool:keys*/"

# VS Code keybindings.json block. Keys pressed in a diff tab go to VS Code, not the webview.
KB_BEGIN = "// fool:keys:begin"
KB_END = "// fool:keys:end"
KB_TEXT_DIFF = "claude-vscode.viewingProposedDiff && resourceScheme == _claude_vscode_fs_right"
KB_ENTRIES = [  # (key, command, args, when)
    ("ctrl+alt+enter", "claude-vscode.focusLastMessage", "accept", None),
    ("ctrl+alt+backspace", "claude-vscode.focusLastMessage", "reject", None),
    ("ctrl+alt+z", "claude-vscode.focusLastMessage", "reason", None),
    ("ctrl+alt+up", "editorScroll", {"to": "up", "by": "line", "value": 4}, KB_TEXT_DIFF),
    ("ctrl+alt+down", "editorScroll", {"to": "down", "by": "line", "value": 4}, KB_TEXT_DIFF),
    ("ctrl+alt+pageup", "editorScroll", {"to": "up", "by": "page"}, KB_TEXT_DIFF),
    ("ctrl+alt+pagedown", "editorScroll", {"to": "down", "by": "page"}, KB_TEXT_DIFF),
    ("ctrl+alt+home", "cursorTop", None, KB_TEXT_DIFF),
    ("ctrl+alt+end", "cursorBottom", None, KB_TEXT_DIFF),
]

# claude-vscode.focusLastMessage passes its argument on to the webview (keys.js reads it as req.fool).
EXT_PATCHES = [
    (re.compile(r'(registerCommand\("claude-vscode\.focusLastMessage",)\(\)=>\{if\(!([\w$]+)\.focusLastMessage\(\)\)'),
     r'\1(foolArg)=>{if(!\2.focusLastMessage(foolArg))'),
    (re.compile(r'focusLastMessage\(\)\{let ([\w$]+)=this\.pickOneChatSurface\(\);if\(!\1\)return!1;return \1\.comms\.notifyFocusLastMessage\(\),'),
     r'focusLastMessage(foolArg){let \1=this.pickOneChatSurface();if(!\1)return!1;return \1.comms.notifyFocusLastMessage(foolArg),'),
    (re.compile(r'async notifyFocusLastMessage\(\)\{(await this\.clientReady,this\.send\(\{type:"request",channelId:"",requestId:"",request:\{type:"focus_last_message")\}'),
     r'async notifyFocusLastMessage(foolArg){\1,fool:foolArg}'),
    # openFile: a PDF link (`file.pdf#L16`) opens in the PDF viewer at that page (pdfPreview.setPage, see PDF_JS).
    #   let i=ee.Uri.file(s),a=!0;...n?.pinned&&{preview:!1}};ee.window.showTextDocument(i,d).then((p)=>{if(t?.searchText)
    (re.compile(r'(let ([\w$]+)=([\w$]+)\.Uri\.file\(([\w$]+)\),([\w$]+)=!0;.{0,1500}?\.pinned&&\{preview:!1\}\};)'
                r'(?=\3\.window\.showTextDocument\(\2,([\w$]+)\)\.then\(\([\w$]+\)=>\{if\(([\w$]+)\?\.searchText\))', re.S),
     r'\1if(/\\.pdf$/i.test(\4)&&\5){/*fool:pdf-page*/let foolPg=\7?.startLine;'
     r'Promise.resolve(foolPg?\3.commands.executeCommand("pdfPreview.setPage",\4,foolPg):!1).catch(()=>!1)'
     r'.then(()=>\3.commands.executeCommand("vscode.openWith",\2,"pdf.preview",\6))'
     r'.then(void 0,()=>\3.commands.executeCommand("vscode.open",\2,\6));return}'),
]
EXT_MARK = "foolArg"
PDF_MARK = "/*fool:pdf-page*/"

# PDF viewer extension (tomoki1207.pdf). A UI extension, so under Remote-WSL it is on the Windows side.
#   assets/pdf-page.js -> out/src/extension.js: command pdfPreview.setPage(fsPath, page)
#   assets/pdf-page-viewer.js -> lib/main.js: open at that page, or jump to it if already open
PDF_JS = [
    ("out/src/extension.js", SKILL_DIR / "assets" / "pdf-page.js"),
    ("lib/main.js", SKILL_DIR / "assets" / "pdf-page-viewer.js"),
]
PDF_ACTIVATION = "onCommand:pdfPreview.setPage"  # added to package.json activationEvents
PDF_EXT_ROOTS = EXT_ROOTS + sorted(Path("/mnt/c/Users").glob("*/.vscode/extensions"))

MD_KEYS_JS = SKILL_DIR / "assets" / "md-preview-keys.js"
MD_GLOBS = [
    (HOME / ".vscode-server" / "bin", "*/extensions/markdown-language-features/media/index.js"),
    (Path("/mnt/c/Users"), "*/AppData/Local/Programs/Microsoft VS Code/*/resources/app/extensions/markdown-language-features/media/index.js"),
    (Path("/mnt/c/Users"), "*/AppData/Local/Programs/Microsoft VS Code/resources/app/extensions/markdown-language-features/media/index.js"),
]


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


def patch_from_orig(target, transform, check, marks):
    current = target.read_text(encoding="utf-8")
    if check:
        for name, mark in marks:
            print(f"  [{'patched' if mark in current else 'NOT patched'}] {name}: {target}")
        return True
    backup = target.with_name(target.name + ".orig")
    if not backup.exists():
        shutil.copy2(target, backup)
    text, ok = transform(backup.read_text(encoding="utf-8"))
    if text is None:
        return False
    target.write_text(text, encoding="utf-8")
    print(f"  [patched] {target}" + ("" if ok else " (partly, see FAIL above)"))
    return ok


def webview_marks(label):
    return [("Fool label", f"label:{js_str(label)}"), ("full-editor diff tab", DIFF_MARK),
            ("keyboard shortcuts", KEYS_MARK), ("Ctrl+Alt+Z -> chat input", FOCUS_MARK)]


def webview_patch(label, desc):
    def transform(text):
        matches = list(PATTERN.finditer(text))
        if len(matches) != 1:
            print(f"  [FAIL] webview/index.js: expected 1 acceptEdits picker entry, found {len(matches)}. "
                  "Extension code changed; update PATTERN in apply.py.")
            return None, False
        m = matches[0]
        jsx = m.group(1)
        uri = "data:image/png;base64," + base64.b64encode(ICON.read_bytes()).decode()

        def img(size, pad):
            return (f'{jsx}("img",{{src:"{uri}",width:{size},height:{size},alt:"",'
                    f'style:{{display:"block",margin:"{pad}px"}}}})')

        repl = (f"acceptEdits:{{icon:{img(16, 0)},iconV2:{img(20, 0)},iconV2Small:{img(16, 2)},"
                f"label:{js_str(label)},description:{js_str(desc)}}}")
        text = text[:m.start()] + repl + text[m.end():]

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

        sw = FOCUS_SWITCH.findall(text)
        cases = FOCUS_CASE.findall(text)
        focus_ok = len(sw) == 1 and len(cases) == 1
        if focus_ok:
            v = sw[0]
            text = FOCUS_CASE.sub(lambda _: (
                f'case"focus_last_message":{FOCUS_MARK}if({v}.request.fool==="reason"&&'
                f'!window.foolHasPrompt?.(this.isVisible.value)){{this.inputFocusRequestedAt=Date.now(),'
                f'this.inputFocusRequests.value++;break}}'), text)
        else:
            print(f"  [FAIL] Ctrl+Alt+Z -> chat input: expected 1 switch and 1 focus_last_message case, "
                  f"found {len(sw)} and {len(cases)}. Update FOCUS_SWITCH / FOCUS_CASE in apply.py.")

        text += "\n;" + KEYS_MARK + KEYS_JS.read_text(encoding="utf-8")
        return text, diff_ok and focus_ok
    return transform


def extension_patch(text):
    for rx, sub in EXT_PATCHES:
        got = len(rx.findall(text))
        if got != 1:
            print(f"  [FAIL] extension.js: expected 1 of {rx.pattern}, found {got}. "
                  "Extension code changed; update EXT_PATCHES in apply.py.")
            return None, False
    for rx, sub in EXT_PATCHES:
        text = rx.sub(sub, text)
    return text, True


def pdf_js_patch(asset):
    def transform(text):
        return text + "\n;" + PDF_MARK + asset.read_text(encoding="utf-8"), True
    return transform


def pdf_package_patch(text):
    data = json.loads(text)
    data.setdefault("activationEvents", []).append(PDF_ACTIVATION)
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n", True


def pdf_version_key(p):
    # tomoki1207.pdf-1.2.2 -> (1, 2, 2)
    m = re.match(r"tomoki1207\.pdf-(\d+(?:\.\d+)*)", p.name)
    return tuple(int(x) for x in m.group(1).split(".")) if m else ()


def find_pdf_ext():
    found = []
    for root in PDF_EXT_ROOTS:
        if not root.is_dir():
            continue
        dirs = [d for d in root.glob("tomoki1207.pdf-*") if d.is_dir() and pdf_version_key(d)]
        if dirs:
            found.append(max(dirs, key=pdf_version_key))
    return found


def md_preview_patch(text):
    return text + "\n;" + KEYS_MARK + MD_KEYS_JS.read_text(encoding="utf-8"), True


def find_md_preview_js():
    return [p for root, pat in MD_GLOBS if root.is_dir() for p in sorted(root.glob(pat))]


def restore_orig(target):
    backup = target.with_name(target.name + ".orig")
    if backup.exists():
        shutil.copy2(backup, target)
        print(f"  [restored] {target}")
    else:
        print(f"  [no backup, untouched] {target}")


def find_keybindings():
    cands = sorted(Path("/mnt/c/Users").glob("*/AppData/Roaming/Code/User/keybindings.json"))
    if os.environ.get("APPDATA"):
        cands.append(Path(os.environ["APPDATA"]) / "Code" / "User" / "keybindings.json")
    cands.append(HOME / ".config" / "Code" / "User" / "keybindings.json")
    return next((c for c in cands if c.is_file()), None)


def kb_strip(src):
    return re.sub(r"[ \t]*" + re.escape(KB_BEGIN) + r".*?" + re.escape(KB_END) + r"[^\n]*\n?",
                  "", src, flags=re.S)


def kb_add(src):
    m = re.search(r"^\s*\[", src, flags=re.M)
    if not m:
        return None
    rest = src[m.end():]
    empty = re.fullmatch(r"(\s|//[^\n]*)*\]\s*", rest) is not None
    items = []
    for key, cmd, args, when in KB_ENTRIES:
        e = {"key": key, "command": cmd}
        if args is not None:
            e["args"] = args
        if when is not None:
            e["when"] = when
        items.append("    " + json.dumps(e, ensure_ascii=False))
    block = f"\n    {KB_BEGIN}\n" + ",\n".join(items) + ("" if empty else ",") + f"\n    {KB_END}"
    return src[:m.end()] + block + rest


def keybindings(mode, path=None):
    kb = path or find_keybindings()
    if kb is None:
        print("  [none] VS Code keybindings.json not found")
        return True
    src = kb.read_text(encoding="utf-8-sig")
    if mode == "check":
        print(f"  [{'patched' if KB_BEGIN in src else 'NOT patched'}] {kb}")
        return True
    new = kb_strip(src)
    if mode == "apply":
        new = kb_add(new)
        if new is None:
            print(f"  [FAIL] {kb}: no '[' found")
            return False
    if new == src:
        print(f"  [unchanged] {kb}")
        return True
    shutil.copy2(kb, kb.with_name("keybindings.json.fool-bak"))
    kb.write_text(new, encoding="utf-8")
    print(f"  [{'patched' if mode == 'apply' else 'restored'}] {kb}")
    return True


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
    ap.add_argument("--keybindings", type=Path, help="patch only this keybindings.json (testing)")
    a = ap.parse_args()

    if a.index_js:
        transform = webview_patch(a.label, a.description)
        sys.exit(0 if patch_from_orig(a.index_js, transform, a.check, webview_marks(a.label)) else 1)
    if a.keybindings:
        mode = "check" if a.check else "restore" if a.restore else "apply"
        sys.exit(0 if keybindings(mode, a.keybindings) else 1)

    files = []
    targets = find_index_js()
    for t in targets:
        files.append((t, webview_patch(a.label, a.description), webview_marks(a.label)))
        files.append((t.parent.parent / "extension.js", extension_patch,
                      [("focusLastMessage arg", EXT_MARK), ("PDF link page", PDF_MARK)]))
    files += [(p, md_preview_patch, [("md preview shortcuts", KEYS_MARK)]) for p in find_md_preview_js()]
    pdf_exts = find_pdf_ext()
    for d in pdf_exts:
        files += [(d / rel, pdf_js_patch(asset), [("PDF page", PDF_MARK)]) for rel, asset in PDF_JS]
        files.append((d / "package.json", pdf_package_patch, [("PDF page activation", PDF_ACTIVATION)]))

    print("Files:")
    if not targets:
        print("  [none] no anthropic.claude-code-* found under " + ", ".join(map(str, EXT_ROOTS)))
    if not pdf_exts:
        print("  [none] no tomoki1207.pdf-* found (PDF links open without a page)")
    ok = True
    for f, transform, marks in files:
        if a.restore:
            restore_orig(f)
        else:
            ok &= patch_from_orig(f, transform, a.check, marks)

    print("Hook:")
    if a.restore:
        remove_hook()
    else:
        install_hook(a.check)

    print("Keybindings:")
    ok &= keybindings("check" if a.check else "restore" if a.restore else "apply")

    if not a.check:
        print("Done. Reload the VS Code window (Developer: Reload Window).")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
