# Codex 작업 진입점

**작업 시작 전에 저장소 루트의 `CLAUDE.md`를 읽고 그 규칙을 준수한다.** 공통 규칙의 원본은 `CLAUDE.md`이며, 이 파일은 Codex가 기존 규칙·문서를 읽는 순서와 스킬 호출 대응을 안내한다.

루트 또는 하위 디렉터리에서 시작하더라도 변경 경로에 적용되는 하위 `CLAUDE.md`와 작업에 필요한 아래 문서를 읽는다. 작업별 문서 경로는 저장소 루트 기준이며, `~`는 사용자 홈이다. 하위 문서와 링크가 자동으로 읽힌다고 가정하지 않으며, 여러 영역을 건드리면 해당하는 행을 모두 적용한다.

## Codex 스킬 대응

루트 `CLAUDE.md`의 UI/프론트엔드 필수 스킬 `impeccable:impeccable`은 Codex에서 `$impeccable`에 대응한다. Codex 스킬 목록에 있으면 해당 스킬을 사용한다. metadata가 없거나 해당 지침 경로를 읽을 수 없으면 `~/.agents/skills/impeccable/SKILL.md`를 직접 읽는다. 사용할 모드와 작업 대상을 명시해 진행한다. <!-- cite-ok: 전역 스킬은 저장소 밖 사용자 홈의 표준 경로에서 관리한다. -->

FE 구조·렌더 단위처럼 lint만으로 판단하기 어려운 변경은 필요하면 `$hojeong-review`로 검토한다. metadata가 없거나 해당 지침 경로를 읽을 수 없으면 `~/.agents/skills/hojeong-review/SKILL.md`를 직접 읽는다. <!-- cite-ok: 전역 스킬은 저장소 밖 사용자 홈의 표준 경로에서 관리한다. -->

## 작업별 문서 읽기

| 작업 | 먼저 읽을 문서·적용할 기존 규칙 |
|---|---|
| 제품 목적·사용자 흐름 | `PRODUCT.md` |
| UI/프론트엔드 | `DESIGN.md` + `packages/ui/CLAUDE.md`. 루트 `CLAUDE.md`의 필수 스킬은 위 Codex 호출 대응을 따른다. |
| `apps/web` | `apps/web/CLAUDE.md`. 관련 코드의 국소 함정이 있을 때 `apps/web/FRONTEND_NOTES.md`도 읽는다. |
| `apps/admin` | `apps/admin/CLAUDE.md` **및 `apps/web/CLAUDE.md`**. admin 문서는 차이만 담으므로 공통 FE 규칙은 web 문서를 따른다. UI 규범은 `DESIGN.md` + `packages/ui/CLAUDE.md`를 함께 읽는다. |
| `apps/api`·DB·마이그레이션·API 테스트 | `apps/api/CLAUDE.md` + `apps/api/README.md`. 로컬 환경·시드·여러 체크아웃의 테스트 자원은 `DEV.md`를 읽는다. 해당 문서의 격리 규칙에 따라 같은 테스트 DB에서 pytest를 병렬 실행하지 않고 `TEST_DATABASE_URL`·`TEST_REDIS_URL`을 프로세스 환경에 주입한다. |
| `packages/ui` | `packages/ui/CLAUDE.md` + `DESIGN.md`. web 다크·라이트 및 라이트 고정 admin에 미치는 영향을 확인한다. |
| API 계약·`packages/api-types` | `packages/api-types/CLAUDE.md` + `apps/api/CLAUDE.md`. 해당 문서의 생성 규칙에 따라 생성물을 직접 수정하지 않고 OpenAPI와 생성 타입을 함께 재생성·커밋한다. |
| 시드·제작 가이드·프롬프트·운영 콘텐츠 | `AUTHORING.md` + 해당 API/web 문서. 가이드 원고와 시드의 대조 절에 따라 시드 문안을 바꾸면 가이드 인용도 대조하고, 시드 JSON만 바뀌어도 `pnpm --filter @ai-character-chat/web exec vitest run`을 직접 실행한다(Turbo 캐시는 API 시드 변경을 보지 않는다). |
| 브랜드·favicon·OG 자산 | `apps/web/brand/README.md` + `DESIGN.md` |
| 배포·운영·SEO·크론·이미지 추론 서버 | `DEPLOY.md` + 해당 앱 문서 |
| Ralph harness를 명시적으로 실행하는 작업 | 로컬 `scripts/ralph/`의 실행 지침을 읽고 그 harness에만 적용한다. 일반 작업에 Ralph의 자동 커밋·진행 파일 갱신 규칙을 적용하지 않는다. |

비주얼 규범과 예외는 `DESIGN.md`, 실제 색 토큰은 `packages/ui/src/styles/globals.css`를 따른다. `.impeccable/design.json`은 로컬 사이드카이며 일부 preview 예시는 현행 규범과 다를 수 있으므로 그대로 구현에 복사하지 않는다. `apps/web/FRONTEND_NOTES.md`는 관련 코드를 만질 때만 읽는 보조 문서다.
