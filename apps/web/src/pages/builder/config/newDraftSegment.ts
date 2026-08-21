/**
 * 아직 서버에 초안이 없는 빌더의 `$draftId` 세그먼트 — `/builder/character/new`.
 *
 * 만들기와 이어쓰기가 **한 라우트**(`builder.$type.$draftId.tsx`)를 쓰는 이유가 여기 있다(US-007).
 * 첫 자동저장이 초안을 만들고 URL을 `/builder/$type/{초안 id}`로 바꾸는데, 라우트가 둘이면 그 순간
 * 라우트 컴포넌트가 갈려 빌더가 리마운트되고 입력 중이던 폼 상태와 포커스가 통째로 날아간다
 * (autoCodeSplitting이 라우트 파일마다 다른 lazy 컴포넌트를 만들기 때문 — 두 파일이 같은 컴포넌트를
 * 가리켜도 소용없다. 실측으로 확인했다). 한 라우트 안에서 파라미터만 바뀌면 TanStack Router는
 * 리마운트하지 않는다(`remountDeps`를 주지 않는 한).
 *
 * 실제 초안 id는 uuid라 이 값과 겹치지 않는다.
 */
export const NEW_DRAFT_SEGMENT = "new";
