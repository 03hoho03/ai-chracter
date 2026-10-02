# 작품 작성 내부 부록

운영자와 시드 작성자를 위한 문서다. 일반 제작자용 튜토리얼은 앱 안 가이드 페이지이고, 원고는 `apps/web/src/pages/creation-guide/manuscripts/story.md`와 `apps/web/src/pages/creation-guide/manuscripts/character.md`다. 튜토리얼이 제작자 말로 뭉뚱그린 사실을 여기서는 코드 심볼로 가리킨다. 줄번호가 아니라 함수·상수·테스트 이름으로 적었으니, 코드가 바뀌면 그 이름을 검색해 다시 확인한다.

튜토리얼의 예시 작품은 시드 두 파일이다.

- 스토리: `apps/api/scripts/seed_content/data/tutorial/stories/tutorial-filmclub.json`
- 메인 히로인 캐릭터: `apps/api/scripts/seed_content/data/tutorial/characters/tutorial-filmclub-yuna.json`

이 문서는 시드 문안을 옮겨 적지 않는다. 같은 글이 시드 JSON·운영 입력·가이드 원고 세 곳에 이미 있고, 여기에 네 번째 사본을 두면 그중 하나만 고쳐지고 끝난다. 필요한 곳은 파일과 필드 이름으로 가리킨다.

## 1. 필드가 프롬프트의 어디에 실리는가

생성 프롬프트는 `api/chat/prompt_builder.py`가 조립한다. 섹션의 문안과 순서는 코드가 아니라 DB의 프롬프트 세트에 있고(어드민 `/prompt-sets`), 코드는 어느 값이 어느 자리(`slot`)로 흘러가는지만 정한다. 호출부는 `api/chat/router.py`의 `_build_prompt`(실제 방)와 `_build_preview_prompt`(빌더 미리보기)다.

### 스토리 — 생성 호출 (`build_story_generation_prompt`, 매 턴)

괄호 안은 시드 JSON 키다.

- 스토리 설정(`settingText`) → `base_content` 자리의 `setting_text`.
- 커스텀 프롬프트(`customPrompt`) → 같은 `base_content` 자리의 `custom` 변형 행. 템플릿이 커스텀이면 `_story_generation_variant`가 `custom`을 고르고, `select_sections_for_render`가 같은 자리의 기본 행 대신 그 행을 실어 설정 글이 빠진다. 빌더에서도 커스텀을 고르면 스토리 설정 입력란이 숨는다(`widgets/build-story/ui/SettingTab.tsx`, 스키마는 `features/build-story/model/schema.ts`의 `storySettingSchema`).
- 규칙(`rules`), 사용자의 역할과 목표(`userGoal`) → `rules`·`user_goal` 자리. 템플릿 변형이 없는 자리라 어느 템플릿에서나 실린다.
- 전개 예시(`developmentExamples`, 최대 3쌍) → `development_examples` 자리(값 `example_lines`). 쌍마다 `prompt_set.user_label`과 `prompt_set.story_example_label`을 코드가 붙인다. 대화 기록 쪽 라벨은 `story_assistant_label`이라 둘이 다르다(의도된 현재 동작).
- 시작설정의 프롤로그(`startingSetups[].prologue`) → `prologue` 자리, **매 턴**. 미디어 북 태그는 지운 뒤 싣는다(아래 미디어 북 태그).
- 시작상황(`startingSetups[].openingMessage`) → **전용 자리가 없다.** 방을 만들 때 `_insert_opening_message`가 `opening_message or prologue`를 첫 어시스턴트 메시지로 넣고, 그 뒤로는 대화 기록(`history` 자리, 값 `history_lines`)의 일부로 실린다. 시작상황이 비어 있으면 프롤로그가 첫 메시지가 되므로 같은 글이 `prologue` 자리와 대화 기록 맨 앞에 두 번 실린다. 첫 메시지는 태그를 칸 id 형태로 바꿔 저장되고, 대화 기록으로 실릴 때 태그가 지워진다.
- 키워드북(`keywordNotes[].infoText`) → `keyword_notes` 자리(값 `keyword_note_lines`), 고른 노트의 정보만 상시 노트 → 키워드로 열린 노트 순으로. 적용 범위(`startingSetupId`, `null`이면 스토리 전체)는 호출부의 DB 조회가 좁힌다. 대화 기록보다 **뒤**에 실린다. 고르는 규칙은 `api/chat/keyword_notes.py`(`match_keyword_notes` → `recent_scan_turns` + `select_keyword_notes`, DB 없는 순수 함수)에 있고 실방과 빌더 미리보기가 같은 함수를 쓴다.
  - 스캔 글은 **직전 AI 응답 + 이번 사용자 메시지**다. 첫 턴의 직전 AI 응답은 첫 메시지(시작상황, 비었으면 프롤로그)다. 턴은 AI 응답을 경계로 묶는다 — 생성이 실패해 응답 없이 남은 사용자 메시지는 다음 메시지와 한 턴이 되어, 직전 AI 응답은 사용자가 마지막으로 읽은 응답이다. 편집·재생성·단축어 턴도 같은 규칙이다(재생성은 대상 사용자 메시지를 이번 메시지로 본다).
  - 비교는 키워드와 글을 NFC로 맞추고 `casefold`로 접은 뒤 부분 문자열로 한다 — 영문 대소문자를 가리지 않고, 트리거 `도희`는 "강도희"에도 걸린다. 글은 하나씩 따로 본다(두 글을 이어 붙인 경계에서는 걸리지 않는다). 대화 기록 쪽 글은 모델 사본처럼 미디어 북 태그를 지운 뒤 보고, 이번 사용자 메시지는 그대로 본다.
  - 노트 순서(`order`, 빌더 목록 위가 먼저)가 우선순위다. 한 턴에 키워드로 열리는 노트는 앞 5개(`MAX_TRIGGERED_KEYWORD_NOTES`)까지이고, 상시 노트(`alwaysOn`)는 트리거·유지와 무관하게 실리며 따로 센다(스토리당 최대 3개는 저장 검증이 보장한다).
  - 유지 턴(`stickyTurns`, 0~5)이 k면 이번 턴부터 k턴 전까지 중 한 턴의 스캔 글에서 걸렸을 때 실린다. 상태를 저장하지 않고 매 턴 이번 생성 프롬프트에 실리는 대화(요약이 덮은 앞부분 제외)로 다시 계산한다.
  - 금지 키워드(`excludeKeywords`)가 이번 턴 스캔 글에 있으면 그 노트는 유지 중이든 상시든 빠진다. 과거 턴에 트리거와 금지 키워드가 함께 있었으면 그 턴의 일치는 유지의 출발점이 되지 않는다.
  - 이름(`name`)은 빌더 목록용이라 모델에 보내지 않는다. 정보가 공백뿐인 노트와 공백뿐인 키워드는 매칭에서 건너뛴다.
  - **자기 강화 반복**: 실린 노트 때문에 AI가 응답에서 키워드를 말하면 그 응답이 다음 턴의 스캔 글이라 노트가 다시 열린다. 의도된 동작이고, 끊으려면 금지 키워드를 쓴다.
  - 저장(자동저장 PATCH) 검증은 `api/content/schemas.py`의 `KeywordNoteDraftInput`·`StoryDraftPayload`: 정보 800자, 트리거·금지 키워드 각 노트당 10개 × 20자, 이름 20자, 유지 0~5, 노트 50개, 상시 3개를 넘으면 422, 공백뿐인 키워드와 대소문자·유니코드 조합만 다른 중복 키워드도 422. 같은 저장 페이로드에 없는 시작설정을 가리키는 노트는 400(`KEYWORD_NOTE_STARTING_SETUP_NOT_FOUND`, `_update_story_draft`). 키워드가 없는 노트(상시 제외)와 정보가 빈 노트는 저장은 받고 발행이 막는다(`validate_story_publish`).
- 단축어(`shortcuts[].prompt`) → 실행된 턴에만 `shortcut_prompt` 자리. FE는 단축어를 고르면 그 `prompt` 글을 사용자 메시지로 전송한다(`widgets/chat-room/ui/ChatRoomView.tsx`의 `handleShortcutSelect`). 그래서 같은 글이 사용자 메시지로 저장·표시되고, 그 턴의 키워드 매칭에는 이번 사용자 메시지로(직전 AI 응답과 함께), 스탯 판정 입력에는 사용자 발화로 들어간다. 대화 기록에 남으므로 유지 턴이 있는 노트는 뒤 턴에서도 이 글로 열릴 수 있다.
- 대화 프로필(사용자가 방에서 고른 것) → `user_persona` 자리. 빌더 필드가 아니다.
- 생성 프롬프트에 **없는 것**: 이름·한줄소개, 플레이가이드(`playguide`), 추천 답변(`suggestedReplies`), 스탯 정의와 현재 값, 엔딩, 등록 설명, 미디어 북(칸 이름·상황 설명·해금 힌트). 이야기를 쓰는 모델은 게이지 값을 모른다 — 튜토리얼이 "상태창에 수치를 쓰게 하지 말라"고 가르치는 근거가 이것이다. 이야기를 쓰는 모델은 어떤 그림이 붙을지도 모르고, 그림은 아래 칸 판정이 응답 뒤에 따로 고른다.

### 스토리 — 미디어 북

미디어 북은 스토리 버전에 딸린 인물 축 × 장면 축 표이고, 칸 하나에 이미지 한 장이 놓인다(`api/db/models/story.py`의 `MediaBookCell`, 좌표 UNIQUE). 칸마다 작성자가 상황 설명(100자)·해금 힌트(20자)·대화 중 노출 제외(`exclude_from_chat`)를 적는다. 칸은 버전당 `MEDIA_BOOK_MAX_CELLS`(50)개까지다. 시드 JSON에는 미디어 북 자리가 없고 `upsert.py`는 빈 미디어 북으로 검증하므로, 미디어 북이 있는 작품은 빌더로만 만든다.

### 스토리 — 미디어 북 태그

- 문법은 `{{img::인물/장면}}`이다. 슬래시가 정확히 하나여야 하고, 이름은 앞뒤 공백을 떼고 NFC로 맞춰 비교한다. 슬래시가 없거나 둘인 `{{…}}`는 태그가 아니라 글자 그대로 남는다. 문법과 태그를 지운 자리의 줄 정리 규칙은 `api/content/media_tags.py` 모듈 docstring에 있다.
- 그림이 되는 필드는 넷뿐이다: 시작상황(비었으면 프롤로그)이 복사된 첫 메시지, 스토리 상세의 프롤로그, 엔딩 에필로그, 등록 설명. 화면으로 나갈 때 그 글이 속한 버전(방이면 방이 고정한 버전, 상세면 현재 발행본)의 칸 id 형태로 바뀌고(`api/content/media_book.py`의 `normalize_texts`), 그 버전에 없는 이름의 태그는 지워져 아무것도 보이지 않는다. 오타 난 태그가 원문으로 드러나지 않으니, 그림이 안 나오면 인물·장면 이름부터 대조한다.
- 다른 필드(스토리 설정·규칙·키워드북 등)에 쓴 태그는 그림이 되지 않고, 지워지지도 않은 채 그 필드의 자리로 모델에 실린다.
- 모델로 가는 사본에서는 지운다(`strip_media_tags`). 생성 프롬프트의 `prologue` 자리와 대화 기록의 모든 줄, 엔딩 판정과 칸 판정의 대화 기록이 대상이다. 스탯 판정은 대화 기록을 싣지 않아 작성자 글이 들어가지 않는다. 이번 턴 사용자 메시지는 사용자가 방금 친 글이라 그대로 싣는다. 지우는 이유는 태그가 화면에서만 그림이 되는 표지라서다 — 모델이 받으면 태그를 흉내 내거나 인물·장면 이름이 문맥에 섞인다(`build_story_generation_prompt` docstring).
- 첫 메시지와 에필로그에 태그로 나온 칸은 보관함에서 본 칸으로 해금된다(`_insert_opening_message`, 엔딩 도달 경로).

### 스토리 — 미디어 북 칸 판정 (`build_image_judgment_prompt`, `scope="story"`, 매 턴)

- 캐릭터 상황별 이미지 판정과 같은 `image_judgment` 채널을 story 레인 문안으로 쓴다. 후보 줄(`media_cell_image_lines`)은 칸마다 entity_id, 인물 이름, 장면 이름, 그리고 비어 있지 않으면 상황 설명이다. 해금 힌트는 싣지 않는다 — 보관함에서 아직 못 본 칸 아래 보이는 글일 뿐 판정 근거가 아니다. 그래서 상황 설명이 빈 칸은 인물·장면 이름만으로 골라진다.
- 후보는 방이 고정한 버전의 칸 중 노출 제외가 아닌 것이고, 빌더 축 순서(인물 → 장면)로 싣는다. 이 순서는 우선순위가 아니다 — 응답은 칸 하나라, 여러 칸이 맞을 때 하나를 고르는 기준은 문안이 정한다(목록에서 앞의 것을 고르는 캐릭터 문안과 다르다). 지금 문안은 칸마다 인물이 이번 턴에 실제로 등장하는지, 장면 이름이 장소·상황과 맞는지, 상황 설명이 있으면 서술과 어긋나지 않는지를 차례로 보게 하고, 여럿이 맞으면 상황 설명이 이번 턴과 가장 가까운 칸 하나를 고르게 한다. 맞는 칸이 없으면 그림을 붙이지 않는다. 운영에서 쓰는 문안은 어드민 `/prompt-sets`에서 게시한 story 레인 프롬프트 세트가 정본이다. 이 판정 채널을 story 레인에 더한 마이그레이션의 `JUDGMENT_INSTRUCTION_BODY`는 처음 게시한 기본값일 뿐이고, 그 뒤 어드민에서 고친 문안은 저장소에 사본을 두지 않는다 — 그래서 마이그레이션만으로 만든 DB(테스트 DB 등)와 프롬프트 골든은 처음 문안 그대로이고, 운영 문안은 어드민이나 운영 DB에서 확인한다. 후보가 없으면(미디어 북 없음, 전부 노출 제외) 판정을 부르지 않는다.
- 입력 대화는 요약 윈도우를 적용한 대화 기록(태그 제거)과 이번 턴의 사용자 메시지·응답이다.
- 스탯 판정과 동시에 부르고, **최초 엔딩 도달 뒤에도 계속 돈다**(스탯·엔딩 판정은 엔딩 뒤 멈춘다). 재생성도 칸 판정을 다시 돈다.
- 조회·렌더·LLM 실패는 그 턴의 그림만 포기하고 스탯·엔딩 판정과는 무관하다(`_prepare_media_cell_judgment`, `_judge_media_cell`). story 레인 세트에 이 채널 행이 없으면 렌더가 비어 판정을 건너뛴다.
- 고른 칸은 응답 메시지의 `image_id`로 저장되고, 처음 본 칸은 보관함 해금 기록(`story_media_exposures`)에 남는다. 노출 제외 칸은 대화 중에는 나오지 않고 첫 메시지·에필로그 태그로만 해금된다. 그 길도 없는 못 본 노출 제외 칸은 보관함 목록에서 빠진다(`get_story_image_archive`). 못 본 칸은 발행 때 만든 블러본과 해금 힌트로 보인다.

### 캐릭터 — 생성 호출 (`build_generation_prompt`, 매 턴)

- 캐릭터 프롬프트(`characterPrompt`) → `character_prompt` 자리.
- 예시 대화(`exampleDialogues`, 개수 상한 없음) → `example_dialogues` 자리(값 `example_lines`), 매 턴 전부.
- 인트로(`intro`) → 전용 자리가 없고, 방을 만들 때 첫 어시스턴트 메시지로 들어가 대화 기록으로 실린다(`_insert_opening_message`).
- 생성 프롬프트에 없는 것: 이름·한줄소개, 플레이가이드, 상황별 이미지, 등록 설명.

### 화면 전용

- 플레이가이드는 `get_play_guide`가 따로 내려 주는 값이고 어떤 모델 호출에도 들어가지 않는다. 채팅방 더보기 메뉴의 플레이가이드 모달(`features/play-guide`)이 보여 준다.
- 추천 답변은 첫 사용자 메시지 전까지만 칩으로 보이고(`shouldShowSuggestedReplies`), 누르면 그 글이 곧바로 사용자 메시지로 전송된다. 목록 자체는 모델이 읽지 않는다.
- 프롤로그는 스토리 상세의 시작설정 선택 영역에도 보인다(`widgets/content-detail/ui/StoryDetailBody.tsx`).
- 엔딩힌트는 엔딩 컬렉션 모달에서 아직 도달하지 못한 엔딩 아래에 보인다(`features/ending-collection/ui/EndingCollectionModal.tsx`). 에필로그는 모델이 쓰지 않고 저장된 글이 그대로 `ChatEndingReachedEvent`로 나간다(미디어 북 태그만 칸 id 형태로 바뀐다).

## 2. 스탯 판정

- 매 턴 생성 응답 뒤 `build_stat_judgment_prompt`가 판정 프롬프트를 만든다. 입력은 스탯 정의(이름·설명·범위·현재 값)와 **이번 턴의 사용자 메시지와 응답**뿐이다. 지난 대화와 스토리 설정은 싣지 않는다. 그래서 스탯 설명은 그것만 읽고 판단할 수 있어야 하고, "이번 턴에 안 나오면 그대로"가 한 문장으로 충분하다.
- 모델은 스탯마다 **절대값**(`StatJudgmentResult.stat_changes[].new_value`)을 낸다. 변화량 필드는 없다.
- `api/chat/stats.py`의 `apply_stat_changes`가 반영한다. 코드가 거는 제한은 최소·최대 클램프뿐이다. 한 턴의 변화 폭을 제한하는 코드는 없고, 폭 규칙은 DB의 스탯 판정 문안과 각 스탯 설명에 적힌 폭에만 있다. 스탯 설명에 폭을 숫자로 적어 두는 이유다.
- 턴당 자동 변화(`perTurnDelta`)가 있는 스탯은 시스템이 매 턴 그 값을 더하고, 모델이 그 스탯에 낸 판단은 무시한다. 판정 프롬프트에도 "시스템이 자동 조정하는 값이니 넣지 말라"는 표시가 붙는다. 행동에 따라 변하는 스탯에 이 필드를 넣으면 모델이 그 스탯을 영영 못 움직인다.
- 판정 호출이 실패한 턴은 `apply_stat_changes`가 불리지 않아 자동 변화 카운터도 그 턴은 멈춘다. 같은 `try` 안에 있는 엔딩 판정도 그 턴은 건너뛴다(`_stream_new_turn`).
- 재생성(`regenerate_message`)은 응답만 바꾸고 스탯·엔딩 판정과 턴 수를 다시 돌리지 않는다.
- 메시지 수정(`edit_message`)은 잘라 낸 응답 수만큼 `turn_count`를 되돌리지만 스탯 값과 엔딩 도달 상태는 되돌리지 않는다(턴별 변경 이력이 없다 — 그 함수 docstring의 알려진 한계). 편집을 거친 방은 자동 변화 카운터가 턴 수보다 앞서 줄어 있을 수 있고, 호감도도 같은 경로로 쌓일 수 있다. 이른 턴 엔딩을 턴 게이트로 막는 이유 중 하나다(아래 엔딩 판정).
- 게이지는 `StatGaugePanel`이 그린다. 이름·아이콘·색·값·단위만 보이고 설명은 보이지 않는다. 칸 폭이 고정이라 긴 이름은 잘린다.

## 3. 엔딩 판정

- 시점: `api/chat/ending_rules.py`의 `is_ending_check_due` — `turn_count >= gate` 이고 `(turn_count - gate) % 5 == 0`인 턴에만. 게이트(빌더의 최소 턴수)는 폼에서 10 이상이다.
- 순서: `_stream_new_turn`이 `Ending.order` 순으로 돌며 판정 시점인 엔딩마다 **먼저 스탯 규칙을 계산하고**(`evaluate_rule_list`, 이번 턴 스탯 반영 뒤 값), 참일 때만 모델을 부른다(`build_ending_judgment_prompt`). 둘 다 참인 첫 엔딩에서 멈춘다. 발동은 둘의 논리곱이라 순서와 무관하게 결과가 같고, 규칙이 거짓인 엔딩은 호출 비용이 들지 않는다. 규칙이 없는 엔딩은 매 판정 시점에 모델을 부른다 — 판정 턴의 호출 수는 많아야 규칙을 통과한 엔딩 수다.
- 규칙 평가: `evaluate_rule_list`는 항목의 `next_op`(and/or)로 왼쪽부터 순차 누적한다(괄호 우선순위가 아니다). 빈 목록은 참이라, 규칙이 없으면 판단 프롬프트만으로 발동한다. 시작설정에 없는 스탯을 가리키는 항목은 거짓이고(대화는 계속되며 서버 경고 로그가 남는다), 빌더 초안 저장은 그런 규칙을 422 `ENDING_RULE_STAT_NOT_FOUND`로, 발행은 400 `missingFields`의 `endings.statRules`로 막는다. 버전을 옮긴 방에서 새 버전에 생긴 스탯은 시작값으로 채워진다. FE `entities/chat-room/model/endingRules.ts`가 같은 알고리즘(없는 스탯은 거짓)의 짝이다.
- 판정 모델의 입력: 엔딩의 판단 프롬프트와 대화 기록, 이번 턴. 스탯 값·스탯 정의·스토리 설정은 싣지 않는다. 판정 윈도우 설정(`memory_window_ending_judgment`, 기본 꺼짐)을 켜면 요약이 덮은 원문 대신 현재 요약을 싣는다.
- 그래서 판단 프롬프트는 규칙이 잴 수 없는 서사적 사건만 묻는다. 규칙의 임계값을 판단 프롬프트가 되물으면 모델이 그 숫자를 서사로 재해석해 발동을 거부한 실측이 있다(`test_seed_ending_judgment_prompts_do_not_restate_rule_thresholds` docstring).
- 목록 순서는 **같은 판정 턴 안의** 우선순위일 뿐이다. 노말·배드가 루트와 같은 게이트에서 판단 프롬프트만으로 참이 되면 첫 판정 턴에 방이 끝나 뒤의 루트 기회가 사라진다. 예시 작품은 노말·배드의 게이트를 늦추고, 초기값에서 거짓인 시계 스탯(`perTurnDelta`) 조건을 넣어 이것을 막는다. 게이트는 턴 수로 판정되므로 메시지 수정으로 카운터가 앞서간 방에서도 이른 발동을 막는다.
- 빌더 미리보기(`_stream_preview_turn`)는 같은 순서(생성 → 스탯 판정 → 엔딩별 규칙 → 엔딩 판정)와 같은 엔진(`apply_stat_changes`·`evaluate_rule_list`·`is_ending_check_due`·`match_keyword_notes`)을 쓰고, 방 상태만 DB 대신 Redis(`api/chat/preview_session.py`)에 둔다. 미리보기는 페이로드의 첫 시작설정으로만 시작한다(`_build_preview_start_state`). 상황별 이미지 매칭은 미리보기에서 돌지 않는다. 미디어 북 칸 판정은 돌고, 후보는 페이로드의 칸 중 노출 제외가 아니고 요청자 소유의 준비된 이미지가 붙은 칸이다(`_prepare_preview_media_cell_judgment`).

## 4. 요약 접기와 첫 메시지 고정

- 긴 방은 `api/chat/memory_fold.py`가 오래된 대화를 요약 스냅샷으로 접는다. 커서 뒤 대화가 `FOLD_AT_TURNS`(30)턴에 닿거나, 원문이 `FOLD_AT_CHARS`(24,000자)를 넘고 접은 뒤에도 `MIN_TURNS_AFTER_EARLY_FOLD`(10)턴이 남으면 가장 오래된 `FOLD_TURNS`(10)턴을 접는다. 요약 호출은 클로버를 깎지 않고 레이트리밋에도 세지 않는다.
- 생성 프롬프트는 `api/chat/memory_window.py`의 `prompt_window`로 요약이 덮은 메시지를 빼고 현재 요약을 대신 싣는다(`memory_window_generation`, 기본 켜짐).
- 첫 메시지(시작상황·프롤로그 또는 캐릭터 인트로)는 `opening_message`로 골라 **요약 커서가 지나가도 윈도우 맨 앞에 남긴다.** 요약 접기의 턴·글자 셈에서도 빠진다. 단 방의 첫 메시지가 사용자 메시지면(오프닝이 지워졌으면) 고정할 것이 없다 — `prompt_window` docstring.
- 그래서 튜토리얼은 시작상황을 "첫 화면에 한 번 나오고, 그 뒤로는 지난 대화로 남는다"고 쓴다. 시작상황에 설정을 몰아넣지 말라는 이유는 "안 실려서"가 아니라, 사용자에게 그대로 보이고 모델에게는 지시가 아니라 자기가 한 말로 읽히기 때문이다.

## 5. 발행 자동 심사

- **심사는 이미지만 본다.** 작가가 쓴 글(이름·소개·설정·프롬프트·규칙·예시·등록 설명·시작설정·칸의 상황 설명과 해금 힌트 등)은 심사 프롬프트에 싣지 않는다. 글은 공개 뒤 신고로만 걸러진다.
- 심사 프롬프트에는 이미지와, 코드가 만든 이미지 목록 라벨만 실린다. 라벨은 첨부 순서대로 `1. 대표 이미지` 뒤에 캐릭터는 `n. 상황 이미지 k`, 스토리는 `n. 미디어 북 {인물}·{장면}`이다. 칸 라벨에는 작가가 지은 인물·장면 이름이 들어가지만 그림을 가리키는 식별용이고 심사 대상이 아니라고 프롬프트에 적혀 있다. 판정 사유는 이 라벨로 그림을 가리킨다.
- 스토리: `api/content/publish.py`의 `build_story_publish_filter_prompt`. 대표 이미지와 미디어 북 칸 그림(같은 호출의 이미지 파트, `_load_story_publish_filter_images`).
  - 칸 그림은 대표 이미지 뒤에 칸마다 축소본(`_thumb.webp`, 긴 변 512px) 한 장씩, 라벨과 같은 축 순서(인물 → 장면)로 실린다. 원본을 50장 싣지 않으려고 축소본을 쓴다. 축소본을 하나라도 못 읽으면 심사 없이 발행을 멈춘다 — 그 칸을 빼고 심사하면 아무도 보지 않은 그림이 발행된다.
  - **노출 제외 칸도 심사한다.** 대화 중에만 안 나올 뿐 태그·보관함으로 보이는 그림이다.
  - 심사 앞의 필드 검증(`validate_story_publish`)은 칸 수 상한 초과(`mediaBook.cells`)와 그 버전에 없는 인물·장면을 가리키는 칸(`mediaBook.orphanCells`)을 400 `missingFields`로 막는다. 블러본은 발행 때 만든다.
- 캐릭터: `build_character_publish_filter_prompt`. 대표 이미지와 상황별 이미지(`_load_publish_filter_images`). 상황별 이미지의 노출 상황 문장은 싣지 않는다.
- 그림이 작품과 어울리는지는 심사하지 않는다(심사 문안에 그렇게 적혀 있다).
- 같은 작품을 다시 발행할 때 그림·순서·칸 이름·활성 심사 세트·모델이 그대로면 지난 통과를 그대로 쓴다(`api/content/publish_filter_memo.py`). 글만 고친 재발행은 다시 심사하지 않는다.
- 판정 축(선정성·폭력성·혐오 표현·불법 콘텐츠)은 코드가 아니라 DB의 발행 심사 문안에 있다(어드민 `/prompt-sets`의 발행 심사 레인). 결과 스키마는 `PublishFilterResult`(`passed`, `reason`).
- fail-closed: `passed`가 거짓이면 400 `{reason}`으로 발행하지 않는다. 심사 호출 자체가 실패하면 예외가 발행 라우트 밖으로 나가 역시 발행되지 않는다.
- 시드 경로(`apps/api/scripts/seed_content/upsert.py`)는 이 모델 심사를 부르지 않고 필드 검증(`validate_story_publish`·`validate_character_publish`)만 한다. 로컬 시드가 들어갔다고 운영 심사를 통과한다는 뜻이 아니다.

## 6. 레이트리밋과 클로버 요점

- 정책 상수는 `api/core/rate_limit_gate.py`, 비용은 `api/core/clover.py`에 있다.
- 채팅 게이트 `enforce_chat_rate_limit` 하나를 네 경로(메시지 전송·재생성·편집·빌더 미리보기)가 공유한다. 재생성·편집도 1건으로 센다. 미리보기 한 턴도 실제 채팅과 똑같이 세고 차감된다.
- 순서는 버스트(`CHAT_BURST_LIMIT`/`CHAT_BURST_WINDOW_SECONDS`) → 면제 확인 → 일일(`CHAT_DAILY_LIMIT`, KST 자정 기준) → 클로버다. 면제 계정(`users.rate_limit_exempt`)도 버스트는 받는다. 일일 무료분을 다 쓴 뒤에만 클로버(`CHAT_TURN_COST`)가 대신 내고, 그날 처음이면 차감 전에 확인을 받는다.
- 이미지 생성은 토큰 버킷(`IMAGE_TOKEN_CAPACITY`, `IMAGE_TOKEN_REFILL_SECONDS`)이고 장당 클로버는 `IMAGE_UNIT_COST`다. 면제 계정은 건너뛰지만 큐 상한(`QUEUE_FULL_RETRY_AFTER_SECONDS`로 재시도 안내)은 받는다.
- Redis 장애 중에는 게이트가 통과시킨다(fail-open).

## 7. 시드 작성 불변식

테스트가 강제하는 것이다. 새 시드나 문안 수정은 이 테스트들을 통과해야 한다.

`apps/api/tests/test_seed_content_data.py` — 매트릭스 시드와 튜토리얼 시드 모두(`load_all_stories`·`load_all_characters`·`STORY_DIRS`·`CHARACTER_DIRS`):

- `test_every_seed_story_passes_publish_validation`, `test_every_seed_character_passes_publish_validation` — 발행 필수 필드.
- `test_every_seed_story_setting_text_instructs_the_narrator` — 스토리 설정이 서술자 지시를 담는다.
- `test_no_seed_content_file_contains_escaped_newlines` — 값 안에 이스케이프된 줄바꿈 글자가 남지 않는다.
- `test_seed_story_ending_thresholds_are_reachable_but_not_free` — 엔딩 규칙 임계값이 스탯 범위 안이고, 초기값 그대로는 참이 아니다. 노말·배드도 예외가 아니다(빈 규칙은 참이라 역시 실패).
- `test_seed_story_development_examples_are_label_free_pairs` — 전개 예시는 `userLine`/`assistantLine` 쌍 목록이고 3쌍 이하, 텍스트 안에 화자 라벨이 없고, 서술 칸이 비지 않는다. 쌍 목록 키가 없으면 재시드 때 전개 예시가 빈 배열로 덮인다.
- `test_seed_story_setting_text_does_not_quote_stat_names`, `test_seed_story_setting_text_does_not_hand_the_narrator_a_named_stat` — 스토리 설정이 스탯 이름을 인용하거나 "이름 + 스탯/게이지/수치"로 지목하지 않는다. 지목하면 모델이 본문에 가짜 표시기를 그린 실측이 있다(docstring).
- `test_seed_ending_judgment_prompts_do_not_restate_rule_thresholds` — 판단 프롬프트가 규칙의 임계값을 되묻지 않는다.
- `test_seed_per_turn_counters_are_system_driven_not_llm_judged` — 설명이 "매 턴 반드시" 류로 읽히는 스탯은 `perTurnDelta`가 있어야 한다.
- `test_every_seed_story_keeps_its_matrix_concept`, `test_major_story_matches_the_fixed_concept` — 매트릭스 폴더만 본다(아래 8).

`apps/api/tests/test_seed_dev_content.py` — `seed_dev` 경로가 모든 시드 파일을 발행하고, 전개 예시를 JSON 그대로 쓰고, 두 번 돌려도 같은지.

`apps/api/tests/test_seed_tutorial_content.py` — 튜토리얼 전용:

- `test_tutorial_content_slugs_are_fixed`, `test_tutorial_content_stays_outside_the_diversity_matrix`, `test_every_seed_invariant_list_covers_the_tutorial_folders`, `test_seed_slugs_do_not_collide_across_folders`.
- `test_tutorial_stat_icons_and_colors_are_builder_choices`, `test_tutorial_stat_initial_values_sit_inside_their_range`, `test_tutorial_ending_gates_meet_the_builder_minimum` — 매트릭스 시드는 생성기가 이것을 강제하지만 튜토리얼 JSON은 손으로 쓰므로 여기서 본다.

가이드 원고가 인용하는 시드 문안에는 두 가지 추가 제약이 있다.

- 영문 대문자 뒤에 하이픈과 숫자가 붙는 꼴을 쓰지 않는다. 원고는 추적되는 `.md`라 CI `citations`가 줄 전체를 읽고, 인용 블록 안에서는 예외 표시를 달 자리가 없다.
- 백틱 네 개 이상이 이어진 글을 쓰지 않는다. 원고의 예시 블록 펜스가 백틱 네 개라 일찍 닫힌다.

## 8. 튜토리얼 시드가 다양성 매트릭스 밖인 이유

- 매트릭스(`seed_content/matrix.py`, `diversity_matrix.json`, `test_seed_matrix.py`)는 장르당 세 칸과 축별 분포를 고정 slug 목록으로 강제한다. 튜토리얼 예시 작품은 그 칸을 채우려고 만든 작품이 아니라 제작 가이드의 단계마다 좋은 작성 예로 읽히도록 설계한 작품이라, 매트릭스 폴더에 넣으면 매트릭스 대조가 깨지고 매트릭스를 고치면 30편의 분포가 흔들린다.
- 그래서 폴더를 나눴다: `seed_content/loader.py`의 `TUTORIAL_STORIES_DIR`·`TUTORIAL_CHARACTERS_DIR`. 매트릭스 검사는 `load_stories()`·`load_characters()`의 기본 폴더만 보고, 발행·서술 불변식은 `STORY_DIRS`·`CHARACTER_DIRS`·`load_all_*()`로 두 폴더를 다 본다. `seed_dev.py`도 `load_all_*()`로 두 폴더를 다 넣는다.
- 새 튜토리얼 작품(예: 이미지 튜토리얼용)을 더할 때도 같은 폴더에 두고 `test_seed_tutorial_content.py`의 slug 목록을 늘린다.

## 9. 가이드 원고와 시드의 대조

- 원고의 예시 블록은 여는 줄에 `seed=<slug>:<JSON 경로>` 또는 `free`를 단다. `seed=` 블록 본문은 그 필드 값의 부분 문자열이어야 하고, 원고 검사 테스트(`apps/web/src/pages/creation-guide/model/`)가 이것을 강제한다. 시드 문안을 고치면 원고 인용도 같이 고친다.
- 시드 JSON만 고친 경우에도 이 대조가 돌아야 하므로 확인은 turbo를 거치지 않고 `pnpm --filter @ai-character-chat/web exec vitest run`으로 한다. turbo의 web 테스트 캐시 입력에는 `apps/api`가 없어서, 시드만 바뀐 뒤 turbo로 돌리면 캐시된 결과가 재생된다.
- 원고에서 탭 단계 절의 제목 id는 빌더 탭 id(`STORY_TABS`·`CHARACTER_TABS`)와 같다. 빌더에 탭이 생기면 원고에 절을 더한다.

## 10. 알려진 한계

튜토리얼 예시 작품을 로컬에서 루트마다 여러 방씩 끝까지 돌려 본 관찰이다. 코드나 문안으로 아직 막지 못한 것이고, 한 방 단위의 사례라 비율로 읽지 않는다.

- **호칭이 가끔 섞인다.** 스토리 설정에 호칭을 인물마다 하나로 정하고 "다른 사람의 호칭을 빌려 쓰지 않는다"는 배타 문장까지 넣고, 전개 예시에 세 호칭을 모두 시범했다. 그래도 긴 대화에서 한 인물이 다른 인물의 호칭으로 사용자를 부르는 턴이 드물게 나온다. 설정 문안으로 줄일 수는 있지만 없앨 수는 없는 것으로 본다.
- **숨긴 것이 드러나지 않으면 루트 엔딩이 안 난다.** 루트 판단 프롬프트는 숨긴 것의 공개(고백·영상 보여 주기)를 묻는다. 서술 모델이 그 장면을 만들지 않으면 목표 호감도가 규칙을 넘어도 판정이 거절된다. 이 경우 호감도가 루트 기준 이상이면 노말·배드 규칙이 거짓이라 방이 끝나지 않고, 그 뒤로는 5턴마다(`is_ending_check_due`) 노말·배드도 판정 호출은 되지만 규칙에서 떨어지므로 실제 기회는 루트 재판정뿐이다. 그래서 스토리 설정에 공개 장면의 장소·사물·이력 조건을 적어 두었다.
- **스탯 판정은 이번 턴 한 쌍만 본다.** `build_stat_judgment_prompt`의 입력은 스탯 정의·현재값과 이번 턴의 사용자 메시지와 응답뿐이고 앞 턴 맥락은 없다. 그래서 앞 턴에서 쌓인 맥락("여러 번 도와줬다")은 판정 근거가 되지 못한다. 또 평범한 턴에도 +3 이상이 붙는 일이 흔해서 누적되면 호감도가 예상보다 빨리 오른다. 스탯 설명의 "같은 장면에 있기만 했으면 0~1" 단계가 이것을 누르려는 문장이다.
- **빈 발화에 서술 모델이 사용자 몫을 쓴다.** 사용자 메시지가 거의 비어 있거나 행동만 짧게 있는 턴에, 서술 모델이 사용자의 대사·행동을 대신 쓰거나, 대화 기록에 쓰이는 화자 라벨(`사용자:`·`진행자:` 꼴)을 응답 본문에 찍은 사례가 있었다. 스토리 설정의 "서술자는 사용자의 대사·행동·감정을 대신 쓰지 않는다"와 전개 예시의 끝맺음으로 줄이고 있지만, 공통 프롬프트 층의 문제라 작품 문안만으로는 막히지 않는다.

## 11. 운영 게시 절차

운영 콘텐츠는 **빌더 UI로 입력하고 발행한다.** 운영에서 `seed_dev.py`를 돌리거나 스크립트로 DB에 넣지 않는다. 시드 경로는 발행 심사를 건너뛰고 공개 범위를 강제로 공개로 만든다(`upsert.py`).

1. 공통 프롬프트(DB)를 바꿨다면 먼저 운영 활성 세트를 기준으로 **바뀐 섹션만** 덧붙여 게시하고, 되돌리기용 이전 버전 id를 기록한다. 로컬 게시본을 통째로 붙이면 운영에만 있던 문안이 덮인다.
2. 운영 seed 계정으로 로그인해 빌더에 입력한다. 입력 전에 저장소 JSON을 **필드별 입력표**로 만든다. JSON 키와 빌더 라벨이 다르다.
   - `settingText` → 스토리 설정, `customPrompt` → 커스텀 프롬프트, `promptTemplate` → 프롬프트 템플릿(`emotional` = 감정형), `userGoal` → 사용자의 역할과 목표, `rules` → 규칙, `developmentExamples` → 전개 예시.
   - `startingSetups[].openingMessage` → 시작상황, `playguide` → 플레이가이드, `suggestedReplies` → 추천 답변.
   - `statDefs[].perTurnDelta` → 턴당 자동 변화, `description` → 설명.
   - `endings[].turnCountGate` → 엔딩조건(최소 턴수), `judgmentPrompt` → 판단 프롬프트, `hint` → 엔딩힌트, `statRules` → 스탯 기반 규칙. JSON은 스탯을 이름(`"stat"`)으로 가리키고 로더가 id로 바꾼다(`_resolve_stat_refs`).
   - `keywordNotes[].infoText` → 정보, `triggerKeywords` → 트리거 키워드, `startingSetupId: null` → 적용 대상 "스토리 전체". 입력표에 적용 대상 행을 따로 둔다. 시드 JSON은 `null`만 쓸 수 있어서 "특정 시작설정"을 고르면 대조가 어긋난다. 노트의 배열 순서가 빌더 목록 순서(우선순위)이니 그 순서대로 입력한다. `name` → 이름, `excludeKeywords` → 금지 키워드, `stickyTurns` → 유지 턴, `alwaysOn` → 상시 적용. 시드 JSON에 키가 없는 옵션은 입력표에서 기본값(이름 비움, 금지 없음, 유지 0, 상시 꺼짐)으로 둔다.
   - 캐릭터: `intro` → 인트로, `exampleDialogues` → 예시 대화, `characterPrompt` → 캐릭터 프롬프트, `situationalImages[].triggerCondition` → 노출 상황.
   - 루트 `description` → 등록 설명(캐릭터는 상세 탭).
3. 이미지: 대표 이미지는 생성 이미지에서 고를 수 있다. 상황별 이미지는 업로드 전용이라 파일로 받아 올린다. 참조 생성은 본인의 완성된 생성 이미지만 참조로 쓸 수 있으므로 기준 이미지를 지우지 않는다.
4. 대조: 발행 전에 운영 초안을 API로 읽어 저장소 JSON과 필드별로 비교한다. id·이미지 id·순서에서 파생되는 값은 빼고, 엔딩 규칙은 운영의 `statId`를 스탯 이름으로 풀어 JSON의 `"stat"`과 비교한다. 키워드북 노트의 순서는 우선순위라 파생값이 아니니, 시드 배열 순서와 운영 빌더 목록 순서도 비교한다. 불일치가 0이어야 발행한다.
5. 발행하고 자동 심사 결과를 기록한다. 탈락하면 사유를 받아 문안을 고치되, **저장소 JSON도 같이** 고친다(원고 인용 대조가 그 뒤를 따른다).
6. 스모크: 스토리는 루트 하나로 몇 턴(게이지 변화, 상태창, 표기), 캐릭터는 몇 턴(호칭·말투, 상황별 이미지 노출).
7. 되돌리기: 콘텐츠는 삭제가 아니라 비공개로 전환한다. 프롬프트는 기록해 둔 이전 버전을 다시 게시한다.
