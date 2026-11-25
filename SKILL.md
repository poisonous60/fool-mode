---
name: fool-patch
description: Claude Code VS Code 확장의 "Edit automatically"(acceptEdits) 모드를 "Fool" 모드로 바꿔 적용한다 — 코드 수정만 승인받고 나머지 툴은 묻지 않고 실행. 확장 webview 이름/아이콘 패치 + PreToolUse 훅 등록.
compatibility: Requires Python 3 and the Claude Code VS Code extension (Windows, Linux, VS Code Remote-WSL, or Remote-SSH)
---

## 하는 일

`scripts/apply.py`가 훅 등록과 확장 `index.js` 패치를 한다. 아래 경로 중 `scripts/`, `assets/`는 이 스킬 폴더 기준이다.

1. **훅** — `assets/review-edits-mode.py`를 `~/.claude/hooks/`에 복사하고 `~/.claude/settings.json`의 `hooks.PreToolUse`(matcher `*`)에 등록. 이미 등록돼 있으면 파일만 갱신. acceptEdits 모드에서:
   - 문서 파일(`.md .mdx .markdown .txt .rst .adoc`) Edit/Write → allow
   - 그 밖의 Edit/Write, NotebookEdit → ask (diff 승인 창)
   - AskUserQuestion / ExitPlanMode / EnterPlanMode → 건드리지 않음
   - 나머지 툴 → allow
2. **이름/아이콘** — `~/.vscode/extensions`, `~/.vscode-server/extensions` 등에서 가장 최신 `anthropic.claude-code-*`의 `webview/index.js`를 찾아 picker 항목을 `Fool` + `assets/icon.png`로 교체. 원본은 `index.js.orig`, 항상 원본에서 다시 패치.
3. **전체 에디터 diff 탭** — 같은 `index.js`에서 `window.IS_FULL_EDITOR` 조건 3개(Edit/Write 승인 핸들러의 `openDiff` 앞 2개, diff 탭으로 수락하는 경로 1개)를 뺀다. 원래는 "Claude Code: Open in Primary Editor"로 연 세션에서 VS Code diff 탭이 안 열리고 채팅 안 미리보기/팝업만 나옴. 패치된 파일은 맨 앞에 `/*fool:full-editor-diff*/` 표시가 붙음. 패턴이 안 맞으면 `[FAIL] full-editor diff`가 뜨고 이름 패치만 적용됨 → `apply.py`의 `DIFF_PATCHES`를 고친다.
4. **단축키** (채팅 패널, diff 탭 둘 다)
   - `Ctrl+Alt+↑/↓/PgUp/PgDn/Home/End` 스크롤
   - `Ctrl+Alt+Enter` 승인, `Ctrl+Alt+Backspace` 거절
   - `Ctrl+Alt+Z` 거절 이유 입력칸으로 이동 (권한 창이 없으면 채팅 입력칸으로 이동, `index.js`의 `focus_last_message` 분기 패치 + `keys.js`의 `window.foolHasPrompt`)
   - `Ctrl+Alt+H` history (채팅 패널만)
   - diff 탭용 단축키는 확장 `package.json`의 `contributes.keybindings`에도 넣는다. 확장이 있는 쪽(SSH·WSL 서버)에서 실행하면 그 서버에 붙은 VS Code 창에서 바로 동작한다.
5. **PDF 링크 페이지 열기** — 채팅의 `파일.pdf#L16` 링크를 누르면 PDF 뷰어(tomoki1207.pdf)에서 16페이지로 연다.
   - Link a PDF page as `[text](file.pdf#L<page>)`.

VS Code Remote-WSL이면 확장 webview는 WSL 쪽(`~/.vscode-server/extensions/...-linux-x64`)이 쓰이므로 WSL에서 실행해야 한다. Windows 로컬 VS Code는 Windows의 Claude Code에서 실행.

## 절차

사용자에게 묻지 않고 끝까지 한다. 기준은 사용자가 지금 쓰고 있는 VS Code 창이다.

1. 스킬 폴더에서 `git pull --ff-only`.
2. 적용:
   ```
   python3 scripts/apply.py
   ```
   (Windows는 `python3` 대신 `python`)
   - 이름 바꾸기: `--label "이름" --description "설명"`
   - 되돌리기: `--restore` (index.js 원복 + 훅 등록 해제 + keybindings.json 블록 제거, 훅 파일은 남김)
3. 지금 창 기준으로 적용됐는지 확인한다 (`python3 scripts/apply.py --check` 출력과 대조):
   - **확장**: 실행 중인 `claude` 프로세스의 실행 파일 경로(`<extensions 폴더>/anthropic.claude-code-<버전>/resources/native-binary/claude`)로 지금 창이 쓰는 extensions 폴더를 찾는다. 그 폴더의 `extensions.json`에 등록된 `anthropic.claude-code` 버전이 Reload 뒤 쓰이는 버전이다. 그 버전의 `webview/index.js`, `extension.js`, `package.json`이 모두 patched여야 한다.
   - **Markdown 미리보기**: 지금 창의 VS Code 커밋(원격이면 실행 중인 `code-<커밋>` 서버 프로세스)에 해당하는 `markdown-language-features/media/index.js`가 patched여야 한다.
   - **훅**: 이 세션의 `~/.claude/settings.json`에 등록돼 있어야 한다.
   - **문법**: 패치한 JS를 `node --check`로 검사한다 (`webview/index.js`는 `.mjs`로 복사해서).
4. 안 된 부분(`[FAIL]`, 지금 창이 쓰는 파일이 목록에 없음, 문법 오류)은 agent가 바로 `apply.py`를 고치고 2번부터 다시 한다. 패턴이 안 맞으면 대상 파일에서 `apply.py` 주석에 적힌 코드 주변을 찾아 정규식을 고치고, 경로를 못 찾으면 탐색 경로를 추가한다. 기능 하나가 실패해도 나머지는 적용되게 한다.
   - PDF 뷰어(tomoki1207.pdf)가 없으면 PDF 부분은 건너뛴다. 설치하지 않는다.
5. 적용된 것과 안 된 것을 보고하고 `Developer: Reload Window`를 안내한다. 훅은 새 세션부터 확실히 적용된다.

## 주의

- 확장 업데이트마다 새 버전 폴더가 생기므로 절차를 다시 실행해야 함 (훅은 그대로 유지됨). PDF 뷰어 확장이 업데이트돼도 마찬가지.
- settings.json을 고치기 전 `settings.json.fool-bak`으로 백업함.
- 훅 `allow`도 Claude Code가 항상 묻는 위험 동작(중요 경로 `rm` 등)은 우회하지 못함.
