#!/usr/bin/env bash
# Claude Code 세션 시작 시 실행 (.claude/settings.json SessionStart 훅).
# 출력은 세션 컨텍스트에 들어간다. 사람이 직접 실행해도 된다: ./scripts/session-brief.sh
# 실패해도 세션을 막지 않도록 항상 0으로 끝난다.

ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$ROOT" || exit 0

echo "# 불앤베어 작업 현황 (세션 시작 시 자동 요약)"
echo

echo "## 지금 브랜치"
branch=$(git branch --show-current 2>/dev/null)
echo "- ${branch:-알 수 없음}"
changed=$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')
[ "$changed" != "0" ] && echo "- 커밋 안 된 변경 ${changed}개"
echo

echo "## 최근 작업 로그 (docs/WORKLOG.md, 최신 3개)"
if [ -f docs/WORKLOG.md ]; then
  # '---' 아래의 '## ' 항목을 최신순으로 3개
  awk 'f && /^## /{n++} n>3{exit} f && n>=1{print} /^---$/{f=1}' docs/WORKLOG.md
else
  echo "(작업 로그 없음)"
fi
echo

echo "## 열린 PR"
if command -v gh >/dev/null 2>&1; then
  prs=$(perl -e 'alarm 8; exec @ARGV' gh pr list --state open --limit 10 \
    --json number,title,author,headRefName \
    -q '.[] | "- #\(.number) \(.title) (\(.author.login), \(.headRefName))"' 2>/dev/null)
  echo "${prs:-- 없음 (또는 gh 로그인 필요)}"
else
  echo "- gh CLI 없음"
fi
echo

echo "## develop 최근 커밋"
git log --oneline -6 origin/develop 2>/dev/null || git log --oneline -6 develop 2>/dev/null || echo "- 확인 불가"
echo
echo "규칙: CLAUDE.md 참고. 작업을 마치면 docs/WORKLOG.md 맨 위에 항목을 추가할 것."
exit 0
