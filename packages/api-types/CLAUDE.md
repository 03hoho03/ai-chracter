# packages/api-types

- `src/generated.ts`는 `apps/api`의 OpenAPI 스펙(`apps/api/openapi.json`)에서 `openapi-typescript`로 코드젠한 결과물이다(techspec-overview-backend.md §3). **직접 수정하지 않는다.** `apps/api`에 엔드포인트를 추가/변경했다면 순서대로 재생성 후 커밋한다:
  1. `apps/api`에서 `uv run python scripts/export_openapi.py` → `apps/api/openapi.json` 갱신
  2. `pnpm --filter @ai-character-chat/api-types run codegen` → `src/generated.ts` 갱신
- `openapi.json`/`generated.ts` 둘 다 git에 커밋한다(`routeTree.gen.ts`와 같은 이유 — apps/api를 기동하지 않아도 fresh checkout에서 FE typecheck가 통과해야 한다).
- `src/index.ts`는 `generated.ts`의 `paths`/`operations`/`components`를 재노출하고, `ApiError`(FE 응답 인터셉터가 만드는 정규화 에러 포맷, `techspec-overview.md` §6.1)는 BE 스펙과 무관하므로 계속 수동으로 관리한다 — codegen을 다시 돌려도 덮어써지지 않는다.
