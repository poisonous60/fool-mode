"""PreToolUse hook: repurpose acceptEdits ("Edit automatically", renamed "Fool") mode.

In acceptEdits mode only:
  - Edit / Write on a document file (DOC_EXTS) -> allow (no prompt)
  - Edit / Write on any other file, NotebookEdit -> ask (approval prompt with diff)
  - interactive tools                            -> untouched (their own UI must still show)
  - every other tool                             -> allow (no prompt)
Other modes: no output, normal behavior.
"""
import json
import sys
from pathlib import PurePath

EDIT_TOOLS = {"Edit", "Write", "NotebookEdit"}
INTERACTIVE_TOOLS = {"AskUserQuestion", "ExitPlanMode", "EnterPlanMode"}
DOC_EXTS = {".md", ".mdx", ".markdown", ".txt", ".rst", ".adoc"}

data = json.loads(sys.stdin.buffer.read().decode("utf-8-sig"))
if data.get("permission_mode") != "acceptEdits":
    sys.exit(0)

tool = data.get("tool_name", "")
if tool in INTERACTIVE_TOOLS:
    sys.exit(0)

if tool in EDIT_TOOLS:
    path = (data.get("tool_input") or {}).get("file_path", "")
    is_doc = tool != "NotebookEdit" and PurePath(path).suffix.lower() in DOC_EXTS
    decision = "allow" if is_doc else "ask"
else:
    decision = "allow"

print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": decision,
        "permissionDecisionReason": "Fool mode",
    }
}))
