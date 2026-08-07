# apps/web — 국소 gotcha 노트

CLAUDE.md에서 분리한, **특정 코드를 만질 때만** 필요한 함정·결정 기록. 지속 컨벤션과 작업 라우팅은 [`CLAUDE.md`](./CLAUDE.md). 이 파일은 매 턴 자동 로드 대상이 아니다 — 이상적으로는 각 항목을 해당 코드 옆 주석으로 옮기는 게 낫다.

## 라우팅 / 라우터

- **History.prototype.pushState 우회** (`shared/lib/content-detail-modal/useContentDetailModal.ts`): TanStack Router의 `createBrowserHistory`가 `window.history.pushState`를 감시 래퍼로 덮으므로, 라우터 모르게 URL만 바꾸려면 `History.prototype.pushState.call(window.history, window.history.state, "", url)`로 프로토타입 메서드를 직접 호출한다. `back()`/`forward()`/`go()`는 패치 대상이 아니라 그대로 써도 된다.
- **redirect 서치 값에 `?` 포함 안전**: `navigate({ to: "/login", search: { redirect: "<pathname>?<query>" } })`는 라우터가 값을 percent-encode하고, `navigate({ to: redirectTo })`(디코딩된 원본)가 다시 정상 매치한다. `requireSession`의 `location.href`도 동일.
- **상세 모달에서 다른 화면으로 나갈 때는 엔트리를 replace한다**: `useContentDetailModal.open()`이 라우터 우회 pushState로 `/content/$type/$id` 엔트리를 하나 남기므로, 모달 안의 버튼/링크가 push로 이동하면 스택이 `[리스트, /content/x, 목적지]`가 되어 뒤로가기가 **풀페이지 상세**로 튄다(모달로 열었을 뿐인데 다른 화면이 나온다). 모달 안에서 나가는 경로는 `contentDetailModalAtom`을 `null`로 비우고(모달이 새 화면 위에 남는 것 방지) `contentDetailModalAtom !== null`일 때만 `replace`로 이동한다 — 풀페이지 상세에서 같은 버튼을 누른 경우는 push가 맞으므로 atom 값 유무로만 분기한다(`usePlayContent.start()`, `CharacterPlayButton`의 "내 대화 목록"). **아직 안 고친 곳**: `ContentDetailView`의 작성자 프로필 링크와 해시태그 버튼은 atom만 비우고 push라 `/content/x` 엔트리가 남는다.
- **content 타입 토글 vs 로컬 토글** (`routes/profile.$userId.tsx`): 헤더 전역 `contentTypeToggleAtom`과 프로필 로컬 `[스토리]/[캐릭터]` 토글은 별개다. 후자는 `validateSearch`(zod, `type` optional, 기본 `"character"`)로 관리하고 변경은 `Route.useNavigate()`로 search만 갱신. 공개여부 필터는 URL 없는 로컬 useState.

## 모달 / Radix

- **중첩 Dialog**: shadcn `Dialog`를 다른 `Dialog` 안에서 열어도 `DialogPortal`이 각자 포털/오버레이라 그대로 스택된다. `Escape`는 가장 위(안쪽)만 닫는다.
- **DialogContent에 DialogTitle 필수**: 없으면 a11y 경고. 풀페이지/모달 공용 뷰는 별도 `<DialogTitle className="sr-only">`를 모달 outlet에만 추가한다(공용 뷰를 Radix Title에 결합하지 않기 위함 — 풀페이지엔 Dialog가 없어 그 안에서 Radix Title을 쓰면 에러).
- **ToggleGroup 단일선택**: 초기값 `undefined`면 controlled/uncontrolled 전환 경고 → `value={state ?? ""}`("선택 없음"=빈 문자열, 어떤 item과도 매치 안 됨).

## 도메인 id · BE 매핑 경계

- **startingSetupId vs pinnedStartingSetupId**: `room.startingSetupId`는 entity_id(버전 안정 참조). 물리적 PK를 path param으로 요구하는 엔드포인트엔 `room.contentSnapshot?.pinnedStartingSetupId`. `contentSnapshot`은 스토리 챗에만 존재하므로 관련 prop은 항상 optional로 받고, 없으면 그 항목을 비활성.
- **toChatRoomState 경계** (`entities/chat-room/model/toChatRoomState.ts`): BE DTO(raw 컬럼명 `minValue`/`maxValue`, 연산자 `gte`/`lte`/`eq`) → `ChatRoomState`(FE provisional 타입 `min`/`max`, `>=`) 변환을 이 파일 하나가 전담(`OPERATOR_MAP` 등). 캐릭터 챗은 스토리 전용 필드(`startingSetupId`/`stats`/`contentSnapshot`)를 `null`/`undefined`로 받는다.
- **imageUrl / toChatMessage nullable**: BE nullable(`string | null`)과 FE optional(`string | undefined`) 불일치는 `entities/chat-room`의 `toChatMessage()`가 명시 매핑으로 흡수(예전 `messages: dto.messages` 직통은 잠재 불일치였다).
- **ComparisonOp 6 vs BE enum 5**: `shared/lib/rule-engine`의 `ComparisonOp`는 6개(`!=` 포함, 평가 엔진 타입이라 그대로), BE `EndingRuleOperator`는 5개(not-equal 없음). 빌더 스키마의 `comparisonOpSchema`를 5개로 좁혀 `!=`를 선택 불가로 막아 매핑 Record가 방어 코드 없이 exhaustive.
- **초기화 setQueryData 훅 고정** (`useResetChatRoomMutation`): "서버 응답으로 detail 캐시 통째 교체"가 유일하게 옳은 동작이라 `onSuccess`의 `setQueryData`를 훅 안에 고정(호출부가 잊어도 지켜지게 — 다른 토글류가 호출부에서 캐시를 결정하는 것과 다름). list 캐시(`lastMessagePreview`) 무효화는 호출부가 별도로.
- **endingReached epilogue 세션 한정**: `endingStatus.epilogue`(+`endingId`/`reachedAtTurn`)는 SSE로만 채워지고 `GET /chat-rooms/{id}`는 `ending_reached: bool`만 준다 → 새로고침/포커스 리페치 시 `null`로 되돌아간다(의도됨, 영속은 엔딩 컬렉션 기능 몫).

## 스키마 / zod

- **zod v4 discriminatedUnion 어노테이션 함정**: 멤버를 `const x: z.ZodType<T> = z.object({...})`로 미리 넓혀 재사용하면 discriminant 추론에 쓰는 내부 캐퍼빌리티(`$ZodTypeDiscriminable`)가 지워져 타입 에러(v3의 흔한 패턴이 v4 discriminatedUnion에서 깨짐). 재귀 rule 스키마(`singleRuleSchema`/`ruleGroupSchema`/`ruleListItemSchema`)는 명시 어노테이션 없이 자연 추론에 맡기고, "rule-engine 타입 재사용" 요구는 `formToServer`/`serverToForm` 파라미터 타입에 `z.infer` 결과를 흘려보내 구조적으로 검증한다.

## situationalImages 전용 이미지 필드

- `situationalImages`처럼 draft PATCH가 아니라 별도 엔드포인트(`POST /assets/{id}/register-situational-image`)로만 반영되는 필드는 공용 `GeneratedImageField`(업로드 결과가 draft PATCH로 나가는 전제)를 재사용하지 않고 전용 컴포넌트(`SituationalImageRow` + `shared/lib/asset/registerSituationalImage.ts`)를 쓴다. 등록 호출엔 draft 응답에 없던 `contentVersionId`가 필요(`CharacterDraftResponse`에 추가), "노출 상황" 텍스트가 비면 422라 업로드 핸들러가 호출 전 확인.

## 검증 환경 (로컬)

- **Redis 세션 > Postgres**: 로컬 재시딩으로 세션 쿠키의 `user_id`가 `users`에 없어지면, 로그인 필요 뮤테이션이 BE FK 위반 500을 내고 브라우저는 이를 "CORS policy"(`net::ERR_FAILED`)로 **오표시**한다(프리플라이트는 정상 200). CORS 의심 전에 `/dev/session-echo`로 새 세션 발급받아 쿠키 갱신.
- **LLM 없는 화면 검증**: `GEMINI_API_KEY` 없으면 SSE 토큰 스트림/정책위반/발행 필터 분기를 재현 못 한다. BE를 임시 수정(하드코딩 토큰 목록 / `raise LLMPolicyViolationError` / `get_llm_client`에 `DEV_FAKE_LLM=1` 페이크) 후 브라우저 확인 → `git checkout -- <file>`로 완전 원복(커밋 전 `git status` 확인). FastAPI `Depends()`가 라우트 본문 전에 resolve되므로, LLM 불필요 분기(`missingFields`)조차 `get_llm_client()` 생성 시점 `ValueError`로 막히는 점 주의.
- **MCP drag 한계**: chrome-devtools MCP의 범용 `drag`(uid→uid)는 dnd-kit `PointerSensor`(실제 pointerdown/move/up 이벤트 필요)에 반응하지 않는다 → `evaluate_script`로 `PointerEvent`(pointerdown → 여러 pointermove → pointerup, `bubbles:true`/`pointerId`/`isPrimary:true`) 시퀀스를 직접 디스패치해 확인(코드 버그가 아니라 툴 한계).

## 미해결 — 이슈로 승격 대상

- **ContentCard 이중 구현 debt**: 공용 `entities/content/ui/ContentCard`와 프로필 로컬 `ContentCard`(`ProfileContentSection`)가 별개로 남아 있다(프로필 쪽은 `role="button"` 마이그레이션도 미완). 프로필 카드를 만질 일이 있으면 통합 함께 고려.
