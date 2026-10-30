# chat-lab

채팅 엔진 측정 런을 런 목록 → 턴 → 호출 순으로 들여다보는 로컬 개발자 도구다. 이 폴더는 그 화면(웹)이고, 런 폴더를 읽어
결합·지표·원가를 내는 쪽은 엔진 옆의 측정 서버(`apps/api/scripts/chat_lab/`)다. 누가 무엇을 하려고 쓰는지와 원칙은 같은 폴더의
`PRODUCT.md`, 비주얼 시스템은 `DESIGN.md` 에 있다. 이 문서는 띄우는 법, 측정 서버가 읽는 런 폴더 형식, 턴 기록 내보내기, 떼어
갈 때 챙길 것을 다룬다.

## 기동

- **측정 서버**: 띄우는 명령·기본 주소·인자·바인드·DB 규칙은 `DEV.md` 「5) 채팅 측정 도구(chat-lab)」 절에 있다.
- **웹**: 저장소 루트에서 `pnpm --filter chat-lab dev` — `http://127.0.0.1:5291` 에 뜬다. 포트는 고정이고(`strictPort`), 비어
  있지 않으면 다른 포트로 옮기지 않고 바로 실패한다. 측정 서버를 기본 주소가 아닌 곳에 띄웠으면
  `VITE_CHAT_LAB_API=http://127.0.0.1:<포트> pnpm --filter chat-lab dev` 처럼 주소를 바꾼다.
- **둘의 관계**: 웹은 측정 서버를 HTTP 로만 읽는다 — 런 폴더도 DB 도 직접 보지 않는다. 측정 서버의 CORS 는 웹 dev 오리진
  (`127.0.0.1`·`localhost` 의 5291)만 받아서, 웹 포트를 바꾸면 화면은 떠도 요청이 전부 막힌다. 웹 포트는 `vite.config.ts`, 받는
  오리진은 `apps/api/scripts/chat_lab/app.py` 에 따로 적혀 있어 둘을 함께 바꿔야 한다.
- **목록이 바뀌는 때**: 측정 서버는 첫 목록 요청 때 런 루트 전체를 훑고(실데이터에서 수십 초) 그 결과를 들고 있다. 이미 찾은
  묶음은 파일(드라이버 로그·짝 파일·같은 폴더의 기본 짝 이름과 매니페스트)의 수정 시각·크기가 바뀌면 다음 요청에서 그 묶음만
  짝을 다시 골라 다시 잇는다 — 진행 중인 측정이 줄을 덧붙이거나 턴 기록을 내보내도 다시 훑지 않고 반영된다. 새로 생긴 묶음은
  화면의 "새로 훑기"(`GET /runs?refresh=true`)를 눌러야 보인다.
- **그 밖의 웹 명령**: `pnpm --filter chat-lab run typecheck`·`test`·`build`, 그리고 `codegen`(`openapi.json` →
  `src/shared/api/generated.ts`). 측정 서버의 라우트·응답 모델을 고쳐 `openapi.json` 을 다시 떨궜으면(`DEV.md` 같은 절) 이어서
  `codegen` 을 돌려 `generated.ts` 도 함께 커밋한다. chat-lab CI 가 같은 명령으로 다시 만들어 보고 커밋본과 다르면 실패한다.

## 런 묶음 형식

측정 서버가 읽는 런 폴더 형식은 이 절 하나에만 적는다. 코드는 `apps/api/scripts/chat_lab/` 의 `bundles.py`(찾기·짝),
`join.py`(결합), `chat_turns_file.py`(턴 기록 파일), `run_id.py`(묶음 id)이고, 이 절과 코드가 다르면 코드가 맞다 — 이 절을 고친다.

### 묶음과 파일

묶음은 드라이버 로그 하나와 그 짝 파일(최대 셋)이다. 모두 JSON Lines(줄마다 JSON 객체 하나)다.

| 파일 | 쓰는 쪽 | 같은 폴더 기본 이름 | 매니페스트 키 |
| --- | --- | --- | --- |
| 드라이버 로그 | 측정 드라이버 `apps/api/scripts/chat_play.py` 의 `--log` | 없음 — 이름이 아니라 내용으로 찾는다 | `chat`(없으면 `chat.jsonl`) |
| 기억 스냅숏 | 같은 드라이버의 `--snapshot-log` | `memory-snapshots.jsonl` | `snapshots` |
| 프롬프트 덤프 | 측정 대상 API 서버(설정 `PROMPT_DUMP_PATH`) | `prompt-dump.jsonl` | `dump` |
| 턴 기록 | 턴 기록 내보내기(아래 절) | `chat-turns.jsonl` | `turns` |

각 파일에서 그 묶음 방(`roomId`)의 줄만 쓴다.

### 드라이버 로그를 찾는 규칙

측정 서버의 런 루트(`--root`) 아래 `*.jsonl` 을 모두 경로 순으로 보고, 아래 셋을 모두 만족하면 드라이버 로그다. 경로의 어느
마디라도 링크면 건너뛰고, 읽지 못하는 파일(권한·사라짐)은 묶음이 아닌 것으로 친다.

1. 빈 줄을 뺀 첫 줄의 `kind` 가 드라이버 줄 종류 — `meta`·`opening`·`login`·`relogin`·`rebase`·`turn`·`pause`·`noteUpdate`·
   `check`·`preCheck`·`regenerate`·`edit` — 가운데 하나다. 훑는 비용 때문에 첫 줄로 먼저 거르고, 통과한 파일만 끝까지 읽는다.
   첫 줄이 `meta` 일 필요는 없다 — 로그인 줄(`login`·`relogin`)이나, 이미 있는 방을 새 로그로 이어 칠 때의 기준 다시 잡기 줄
   (`rebase`)로 시작하는 로그가 있다. 스냅숏(`roomStatic`·`memorySnapshot`)·덤프(`generation`·`judgment`·`background` 이거나
   `kind` 없음)·턴 기록(`export`)은 첫 줄에서 빠진다.
2. 턴 줄(`kind` 가 `turn`)이 하나 이상이다.
3. 줄들에 적힌 `roomId`(문자열) 값이 정확히 하나다. 로그인 줄처럼 `roomId` 칸이 없는 줄은 세지 않는다. 방이 둘 이상이거나
   하나도 없으면 묶음이 아니다.

경로에 `probes` 폴더가 있으면 그 폴더까지의 경로가 묶음의 `group` 이 되고, 목록은 그 키로 대량 시도 폴더를 한 줄로 접는다.

### 형식 세대

턴 줄을 보고 셋으로 가른다(목록의 `format`).

- **현행**(`current`): 턴 줄 가운데 `shortcutId` 나 `assistantMessageId` 가 있는 것이 하나라도 있다. 지금 드라이버는
  `shortcutId` 를 실패한 턴 줄에도 늘 쓰고, `assistantMessageId` 는 응답을 받은 줄에만 쓴다.
- **`assistantMessageId` 이전**(`preMessageId`): 턴 줄마다 `roomId` 는 있는데 위 두 칸이 없다. 열리지만 턴 기록 행을 붙일 응답
  id 가 없어, 턴 기록 파일을 짝으로 두어도 행을 턴에 잇지 않는다. 행마다 짝 없는 행(`unmatchedRow`) 불일치로 세지 않고 그 사실
  하나를 주의(`chatTurnsNotJoined`)로 달며, 붙은 행이 없으니 원가도 내지 않는다(0 원이 아니라 비어 있다). 내보내기도 거부한다
  (아래 「턴 기록 내보내기」).
- **옛 형식**(`legacy`): 턴 줄 가운데 `roomId` 칸이 없는 것이 하나라도 있다. 목록에만 보이고 열지 않는다(상세는 422,
  내보내기는 거부).

방 id 가 uuid 가 아닌 로그도 열지 않는다.

### 짝 파일

- **같은 폴더의 기본 이름이 먼저다.** 드라이버 로그와 같은 폴더에 기본 이름의 일반 파일(링크가 아닌 것)이 있으면 매니페스트와
  상관없이 그것을 쓴다. 매니페스트가 그 키에 다른 값을 적었으면 기본 이름을 썼다는 주의(`manifest`)를 단다.
- **`turns.jsonl` 은 짝이 아니다.** 옛 드라이버가 드라이버 로그를 그 이름으로 썼다 — 짝으로 읽으면 드라이버 로그를 턴 기록으로
  연다. 턴 기록의 기본 이름은 `chat-turns.jsonl` 이다.
- **같은 폴더 밖 파일은 매니페스트로만 잇는다.** 조상 폴더나 런 루트에서 짝을 찾아 붙이는 자동 규칙은 없다. 같은 방을 여러
  묶음이 쓰면(체크포인트 복원·가지치기 측정) 조상 폴더의 덤프를 방 id 로 걸러도 다른 시도의 줄이 섞이기 때문이다. 그래서 같은
  방을 쓰는 묶음이 런 루트에 둘 이상인데 이 묶음이 매니페스트로 같은 폴더 밖 짝을 쓰면 "방 공유" 주의(`roomShared`)를 단다.
  방을 혼자 쓰는 묶음이 폴더 밖 짝을 쓰는 것은 주의가 아니다.

기본 이름이 없을 때 쓰는 매니페스트는 드라이버 로그와 같은 폴더의 `chat-lab.json` 이다.

```json
{
  "chat": "chat.jsonl",
  "snapshots": "memory-snapshots.jsonl",
  "dump": "../dumps/prompt-dump.jsonl",
  "turns": "chat-turns.jsonl"
}
```

- 매니페스트는 그 폴더의 드라이버 로그 하나에만 걸린다 — `chat`(없으면 `chat.jsonl`)이 그 로그의 파일 이름과 같을 때만 읽고,
  다른 로그에는 조용히 쓰지 않는다.
- 값은 묶음 폴더 기준 상대 경로 문자열이다. 빈 값·절대 경로·resolve 한 뒤 런 루트 밖·파일이 아님이면 그 항목을 버리고 주의
  (`manifest`)를 단다. 빠진 키는 짝이 없는 것이다.
- 매니페스트가 JSON 객체로 읽히지 않으면 통째로 버리고, 그 폴더의 묶음에 주의(`manifest`)를 단다.

### 묶음 id

`runId` 는 런 루트 기준 드라이버 로그의 상대 경로(POSIX)를 base64url 로 감싸고 끝의 `=` 를 뗀 문자열이다. 경로의 `/` 가 URL
라우팅을 깨지 않게 한 마디로 감싼 것이고, 웹 주소와 측정 서버 경로에 실린다. 드라이버 로그를 옮기거나 이름을 바꾸면 id 도
바뀐다. 측정 서버는 되돌릴 때 정규형 상대 경로만 받고(`..`·`.`·빈 마디·절대 경로·NUL 거부), 마디에 링크가 있거나 resolve 한
결과가 루트 밖이면 거부한다. 어느 경우든 응답은 "그런 묶음이 없다" 404 다.

### 줄 읽기

드라이버 로그·스냅숏·덤프에 걸리는 규칙이다(턴 기록 파일은 아래 「턴 기록 파일 `chat-turns.jsonl`」의 읽기 규칙을 따른다).

- 파일을 개행으로 나눈 뒤 줄마다 따로 UTF-8 로 디코드한다. 기록 중인 파일은 마지막 줄이 여러 바이트 글자 가운데서 잘릴 수
  있어서, 통째로 디코드하면 그 한 줄 때문에 묶음 전체가 열리지 않는다.
- 파일 끝의 개행 없는 마지막 줄이 읽히지 않으면 기록 중에 잘린 줄로 보고 버린다(`incompleteLine` 주의). 그 밖에 읽지 못한 줄과
  JSON 객체가 아닌 줄은 건너뛴다(`unreadableLine` 주의).

### 덤프 판정

- 덤프 파일은 이름으로 고른다 — 같은 폴더의 `prompt-dump.jsonl` 이나 매니페스트의 `dump`.
- 그 파일 안에서 `roomId` 와 `prompt` 칸이 둘 다 있고 `kind` 가 `generation`·`judgment`·`background` 인 줄만 덤프 줄이다.
  `kind` 칸이 없는 줄은 옛 덤프의 생성 줄로 읽는다. `kind` 만 보지 않는 것은 옛 계측 파일(`trace.jsonl` 등)에도
  `kind: generation` 줄이 있지만 프롬프트가 없어서다. 덤프 꼴이 아닌 줄은 개수와 함께 주의(`notDumpLine`)로 남긴다.
- 덤프 줄이 하나도 없으면(덤프 파일이 없거나, 어느 방의 것이든 꼴이 맞는 줄이 0) 그 묶음은 덤프가 없는 것으로 보고, 생성 덤프 없는 시도를
  불일치로 세지 않는다.

### 턴 기록 파일 `chat-turns.jsonl`

첫 줄은 머리 줄이고 나머지는 행 하나당 한 줄이다.

```json
{"kind": "export", "exportedAt": "<ISO 시각>", "roomId": "<방 uuid>", "scope": "<내보내기 시점 상태라는 문장>", "pricesAsOf": "<단가표 기준일>", "pricesSha256": "<단가표 sha256>", "statDefs": [{"id": "<스탯 id>", "name": "<이름>", "hiddenFromPlayer": false}]}
{"kind": "row", "row": {"<chat_turns 칼럼>": "<값>"}}
```

- **머리 줄**(`kind` 가 `export`): 내보낸 시각, 방 id, 이 파일이 "내보내기 시점 상태"라는 문장(`scope`), 단가표 기준일과 단가표
  내용의 sha256, 방 시작 설정의 스탯 정의(id·이름·숨김 여부).
  - 내보내기 시점 상태: DB 에는 그 방의 마지막 상태만 있어, 같은 방을 이어 친 다른 측정의 행이 섞일 수 있다.
  - 단가표: 원가는 읽는 때 지금 단가표로 다시 낸다. 기준일은 표 전체를 다시 확인한 날이라 그 뒤 줄이 더해져도 그대로여서
    날짜로는 판을 가를 수 없다. 그래서 sha256 이 지금 단가표와 다르면 주의(`pricesChanged`)를 단다.
  - 스탯 정의: 숨김 스탯은 방 스냅숏에 없고 턴 기록에 id 로만 남아, 이 정의가 없으면 이름도 숨김 표시도 보일 수 없다.
- **행 줄**(`kind` 가 `row`): `row` 칸에 `chat_turns` 행 하나를 칼럼 이름 그대로 담고, 값은 uuid·시각만 문자열로 바꾼다. 행을
  한 칸 안에 감싸는 것은 행 자신에도 `kind` 칼럼(send·edit·regenerate)이 있어서다.
- **읽기**: 파일이 UTF-8 로 읽히지 않거나, 첫 줄이 머리 줄이 아니거나, 머리 줄에 칸이 빠졌으면 파일을 쓰지 않고 주의(`unreadableLine`)로 남긴다. 행 줄이 깨졌으면
  그 줄만 건너뛰고 주의로 남긴다. 머리 줄의 `roomId` 가 묶음 방과 다르면 파일째 쓰지 않고 불일치(`chatTurnsRoomMismatch`)로 남긴다.
- 어느 줄도 `kind` 가 `turn` 이 아니고 첫 줄이 `export` 라 묶음을 찾을 때 드라이버 로그로 잡히지 않는다.

### 턴·시도 결합

- **턴과 시도**: 턴은 서로 다른 `clientTurn` 이고, 같은 번호의 턴 줄들은 그 턴의 시도(파일 순서)다. 사람이 친 턴을 나중에
  보충한 줄은 `clientTurn` 이 없어 `roomAfter.turnCount` 를 번호로 쓰고 보충 줄로 표시한다. 둘 다 없는 턴 줄은 불일치
  (`unplacedLine`)다. 첫 번호와 끝 번호 사이에 빠진 번호마다 불일치(`turnGap`)다.
- **DB 응답인 시도**: 생성 리플레이(`apps/api/scripts/replay/logs.py`)가 고르는 줄과 같다 — `roomAfter.turnCount` 가 그 번호인 첫
  턴 줄, 없으면 그 번호의 마지막 턴 줄.
- **생성 덤프**: 그 방·그 턴의 생성 줄(파일 순서) 가운데 마지막 것을 위에서 고른 시도에 붙인다(리플레이가 대조하는 덤프와 같은
  것). 앞선 생성 덤프 k개는 시도별로 가르지 않고 그 턴의 "앞선 생성 덤프"로 둔다 — 연결 오류 시도는 서버에 닿았는지 모르고,
  HTTP 200 이어도 생성 앞에서 끝나면 덤프가 없어서, n번째 시도와 n번째 덤프를 짝지으면 틀릴 수 있다. 고른 시도가 서버 앞에서
  거부된 것(HTTP 비200)이면 덤프가 없는 것이 정상이라 생성 덤프는 모두 앞선 것이다. 고른 시도가 HTTP 200 인데 생성 덤프가
  없으면 불일치(`missingDump`), 그 턴이 없는 생성 줄도 불일치(`unmatchedDumpLine`)다.
- **판정 덤프**: (방, 턴)으로 그 턴에 순서대로 모두 붙인다. 그 턴이 없으면 불일치(`unmatchedDumpLine`)다.
- **백그라운드 덤프**: `turn` 칸이 있으면 그 턴, 없으면 파일 순서상 바로 앞 생성 줄의 턴에 둔다. 어느 쪽이든 배치는 추정이라
  줄마다 주의(`placementEstimated`)를 단다 — 백그라운드 작업은 응답을 보낸 뒤 돌아 다음 턴 생성 줄보다 늦게 쓰일 수 있고, 요약
  접기 줄의 턴 칸은 작업이 읽은 방 턴 수라 다음 턴이 먼저 커밋되면 하나 크다. 놓을 턴이 없으면 불일치(`unmatchedDumpLine`)다.
- **교체 줄**(`regenerate`·`edit`): `clientTurn` 이 없고 대상 턴은 `turnBefore` 다. 그 턴에 "응답 교체됨"으로 붙고 타임라인
  표지가 된다. 그 턴의 응답을 바꾼 것으로 치는 줄은 HTTP 200·완료·빈 응답이 아닌 교체 줄 가운데 마지막 것이다(실패한 교체는
  응답을 바꾸지 않는다). 대상 턴이 없으면 불일치(`unplacedLine`)다.
- **표지 줄**: `rebase`·`check`·`noteUpdate`·`pause` 는 그 줄을 쓸 때까지 마친 턴 수 자리의 타임라인 표지다(`noteUpdate`·`pause` 는
  `turnCount`, 나머지는 `roomAfter`·`accumulated`·`fetched` 의 `turnCount`).
- **턴 기록 행**: 행의 `assistant_message_id` 가 시도의 `assistantMessageId` 와 같은 시도에 붙는다(고른 시도가 아니어도). 맞는
  시도가 없는 행은 불일치(`unmatchedRow`)다. `assistantMessageId` 이전 형식은 잇지 않는다(위 「형식 세대」).
- **실제 생성 모델**(목록 항목과 상세 `run` 의 `effectiveChatModels`): 방 스냅숏(`roomStatic`)의 `effectiveChatModel` 이다.
  스냅숏에 그 값이 없으면 턴 기록 파일의 행 전부의 `chat_model` 을 모두 싣는다 — 시도에 붙지 않은 행과, 행을 잇지 않는
  `assistantMessageId` 이전 형식의 행도 센다(다른 방의 파일은 위 규칙대로 쓰지 않는다). 원가는 여전히 붙은 행만 합한다. 둘 다
  없으면 비고, 목록 표의 모델 칸은 덤프 생성 줄의 보낸 모델을 대신 적는다.
- **스탯 대조**: 드라이버는 보이는 스탯을 이름 키(`roomAfter.stats`)로, 턴 기록은 id 키(`stat_changes`, 값은 `[전, 후]`)로
  남겨서, 방 스냅숏(`roomStatic`)의 id↔이름 표로 잇고 스냅숏에 없는 스탯은 내보낸 정의(숨김 제외)로 채운다. 스냅숏마다 스탯
  목록이 다르거나 이름이 같은 스탯이 있으면 이름을 id 로 되돌릴 수 없어 대조를 건너뛰고 주의(`statDefsChanged`)를 단다. 고른
  시도의 드라이버 값과 그 시도에 붙은 행의 뒤 값이 다르면 불일치(`statMismatch`)다. 내보낸 정의와 방 스냅숏이 둘 다 있는데
  내보낸 정의(숨김 제외)가 마지막 방 스냅숏의 스탯 목록과 달라도 불일치(`statMismatch`)다. 숨김 스탯은 방 스냅숏에 없어 견주지 않는다(견주면 늘 거짓 불일치가 된다).

조용히 버리는 줄은 없다 — 이 방의 덤프 줄과 턴 기록 행은 모두 어딘가에 붙거나 불일치로 남는다. 예외는 잇지 않는
`assistantMessageId` 이전 형식의 턴 기록 행으로, 그 수를 주의(`chatTurnsNotJoined`) 하나에 적는다.

### 불일치와 주의

위 결과는 두 목록으로 따로 나간다. 둘을 섞지 않는 까닭은 `PRODUCT.md` 「원칙」에 있다.

- **불일치**(`mismatches`, 목록의 불일치 수는 이것만 센다): `missingDump`·`unmatchedRow`·`turnGap`·`statMismatch`·
  `unmatchedDumpLine`·`unplacedLine`·`chatTurnsRoomMismatch`.
- **주의**(`cautions`): `placementEstimated`·`roomShared`·`incompleteLine`·`unreadableLine`·`manifest`·`notDumpLine`·
  `pricesChanged`·`statDefsChanged`·`chatTurnsNotJoined`.

각 종류가 생기는 조건은 위 소절들에 있고, 응답의 `kind` 값 목록은 측정 서버 스키마(`openapi.json`)에 있다.

## 턴 기록 내보내기

턴 기록(`chat_turns`)은 런 당시 로컬 DB 에만 있고 그 DB 볼륨은 대개 지워져서, 묶음 옆에 파일로 옮겨 둔다.

- **쓰는 것**: 그 묶음 방의 `chat_turns` 행 전부(턴 번호·생성 시각·id 순)와 방 시작 설정의 스탯 정의를 읽어, 드라이버 로그와
  같은 폴더의 `chat-turns.jsonl` 로 쓴다(형식은 위 「턴 기록 파일 `chat-turns.jsonl`」). 같은 폴더의 임시 파일에 다 쓴 뒤 이름을
  바꿔, 쓰다 끊겨도 반쯤 쓴 파일이 남지 않는다. 드라이버 로그·스냅숏·덤프는 건드리지 않는다.
- **두 길**: 웹 런 상세의 "턴 기록 내보내기"(측정 서버 `POST /runs/{runId}/export-turns`, 본문 `{"force": <bool>}`)와 명령줄.
  둘이 같은 함수를 부르고 거부 규칙도 같다. 명령·인자·종료 코드는 `DEV.md` 「5) 채팅 측정 도구(chat-lab)」 절에 있다.
- **로컬 DB 만**: 호스트 허용 목록은 `DEV.md` 같은 절에 있다. 거기에 더해 호스트가 없는 주소(유닉스 소켓)도 로컬로 단정할 수
  없어 거부하고, 주소 칸이 로컬이어도 쿼리의 `host`·`hostaddr` 가 하나라도 목록 밖이면 거부한다 — 드라이버는 그 쿼리 값으로
  접속하기 때문이다. 측정 서버는 띄울 때 이 가드를 걸고 DB 엔진은 첫 내보내기 요청 때 만든다(목록·상세는 DB 에 닿지 않는다).
  트랜잭션은 읽기 전용이다.
- **거부**: 파일 시스템 검사를 DB 를 읽기 전에 한다. 괄호는 측정 서버 응답의 `reason` 과 상태 코드다.
  - 옛 형식이거나 방 id 가 uuid 가 아니다(`unsupported`, 422).
  - `assistantMessageId` 이전 형식이다(`unsupportedFormat`, 422). 턴 기록을 응답과 이을 열쇠가 없어 내보내도 이을 수 없고, 파일만
    남으면 묶음이 "턴 기록 있음"으로 보이는데 원가·토큰은 끝내 빈다. 강제여도 쓰지 않는다.
  - 묶음 폴더나 그 조상이 런 루트의 `archive/` 나 저장소의 `apps/api/probe-runs/archive/` 와 같은 폴더다(`archived`, 403). git 이
    추적하는 폴더라 쓰면 대화 원문이 든 파일이 공개 저장소에 커밋될 수 있다. 경로 글자가 아니라 장치·inode 로 같은 폴더인지
    본다 — 대소문자를 가리지 않는 파일 시스템이나 링크로 닿는 경로도 막으려는 것이다.
  - 그 폴더에 서로 다른 방의 드라이버 로그가 있다(`multipleRooms`, 422). 턴 기록 파일 이름은 폴더에 하나라 그 폴더의 모든 로그가
    그 파일을 짝으로 읽는데, 어느 방의 기록을 써야 하는지 정할 수 없다.
  - 파일이 이미 있다(`exists`, 409) — 손으로 고쳤거나 지금 DB 에 없는 행을 담았을 수 있어 되돌릴 수 없다. 강제(`force`)로만
    바꾼다.
  - 그 자리에 링크나 일반 파일이 아닌 것이 있다(`notFile`, 422). 강제여도 쓰지 않는다.
  - DB 에 그 방이 없거나(`noRoom`, 422) 행이 0 이다(`noRows`, 422) — 다른 DB 를 가리킨 것이다. 빈 파일을 남기면 묶음이 "턴 기록
    있음"으로 보이고 다음 시도가 덮어쓰기 거부에 막힌다.
  - 측정 서버에서는 그 밖에 그런 묶음이 없으면 404(`notFound`), DB 가 설정되지 않았거나 DB 접속·파일 쓰기가 실패하면 503(`dbUnavailable`), 본문이
    `application/json` 이 아니면 415(`notJson`)다.

## 기록 한계

측정 기록에 없어 보여 줄 수 없는 값(판정 응답 원문 등)은 측정 서버가 턴 상세 응답의 `recordLimits` 에 자리(`slot`)와 문장(`text`)
으로 준다. 화면은 그 문장을 그대로 쓴다(까닭은 `PRODUCT.md` 「원칙」, 모양은 `DESIGN.md` 「Record Limit Note (Signature)」).
문장의 원문은 측정 서버 코드에만 두고 여기에 옮기지 않는다.

## 다른 저장소로 떼어 갈 때

- **옮길 것**: `apps/chat-lab` 전체. 워크스페이스 패키지 의존이 없다 — `package.json` 에 `workspace:` 의존이 없고, 소스가
  `packages/*` 를 import 하지 않고, `tsconfig.json` 도 다른 설정을 상속하지 않는다.
- **남는 것**: 측정 서버 `apps/api/scripts/chat_lab/` 와 진입 명령 둘(`chat_lab_server.py`·`chat_lab_export_turns.py`). 엔진의 DB
  모델·단가표와 생성 리플레이 규칙(`apps/api/scripts/replay/`)을 import 하므로 엔진과 함께 있는다.
- **두 저장소 사이의 계약**: 측정 서버 HTTP 스키마 `apps/chat-lab/openapi.json`(측정 서버가 떨구고 웹 `codegen` 이 읽는다)과 이
  문서의 「런 묶음 형식」 절. 스키마를 떨구는 명령은 지금 이 폴더의 `openapi.json` 에 쓰고 api CI(`.github/workflows/api.yml`)가
  그 경로로 드리프트를 보므로, 떼어 낼 때 그 출력 자리와 새 저장소로 스키마를 넘기는 길을 함께 바꾼다. CORS 가 받는 웹 오리진
  (포트 5291)도 측정 서버 쪽에 남는다.
- **함께 옮길 저장소 루트 설정**:
  - 루트 `eslint.config.mjs` 에서 chat-lab 에 걸리는 것 — 이름으로 chat-lab 을 가리키는 줄(생성물 `generated.ts` 무시, 타입 기반
    규칙의 tsconfig 목록, chat-lab 전용 상대 import 블록 둘, `src/app/router.tsx`·`src/vite-env.d.ts` 의
    `consistent-type-definitions` 예외)과, 저장소 전체 TS 블록·테스트 블록. 그 플러그인들은 루트 `package.json` 의
    devDependencies 에 있다. lint 는 지금 루트 `pnpm run lint`(`.github/workflows/lint.yml`)가 저장소 전체로 돌리므로 새 저장소에는
    lint 단계를 따로 둔다.
  - `.github/workflows/chat-lab.yml` — `generated.ts` 드리프트 검사·typecheck·test·build. 설치할 pnpm 버전은 루트
    `package.json` 의 `packageManager` 가 정한다.
  - 루트 `.gitignore` 의 `dist/`·`node_modules/`.
