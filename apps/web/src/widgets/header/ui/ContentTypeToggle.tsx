import { toggleVariants } from "@ai-character-chat/ui/components/toggle";
import { ToggleGroup, ToggleGroupItem } from "@ai-character-chat/ui/components/toggle-group";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { Link, useNavigate, useRouterState, useSearch } from "@tanstack/react-router";

import { useCloverPricingQuery } from "@/entities/clover";
import { isContentType, resolveHomeContentType, toHomeTypeSwitchSearch } from "@/entities/content";
import { isWebnovelOpen, useSessionQuery } from "@/entities/session";

/** 캐릭터/스토리 유형 토글과 그 옆 "노벨" 링크를 한 줄로 내보낸다. 토글을 누르면 홈의 그 유형으로
 * 이동한다 — 유형의 진실은 홈 URL의 `?type=` 하나뿐이다(스토리는 파라미터 없음).
 *
 * `variant` — 헤더는 기본값 `"tab"`(라벨만 있는 라우트 전환 탭), 좌측 드로어는 `"outline"`
 * (가로 pill 쌍, `DESIGN.md` §Toggles 감사 테스트: 라벨 3자짜리 버튼 크기라 `list`가 아니라 기본 채움).
 * 재클릭 `""` emit 가드와 이동은 이 컴포넌트 한 곳에만 둔다 — 헤더·드로어 두 인스턴스가
 * 복제하면 한쪽이 조용히 새는 게 이 저장소의 실패 모드다("17곳 중 2곳만 맞았다"). 이동할 search는
 * 홈 첫 행의 유형 전환과 같은 `toHomeTypeSwitchSearch`가 만든다(정렬만 유지).
 *
 * "노벨"(`/webnovels`)은 내비 링크라 `ToggleGroup` **밖** 형제로 둔다 — 그룹은 radio 성격
 * (`role="radiogroup"`, roving focus)이라 링크를 넣으면 화살표 키 이동과 선택 의미에 섞인다. 시각은
 * `toggleVariants({ variant })`를 그대로 빌리고 선택 표시는 `data-state="on"`으로 켠다(밑줄·채움 셀렉터가
 * `data-[state=on]`에 걸려 있다). `aria-current="page"`는 TanStack `Link`가 활성일 때 스스로 붙인다.
 *
 * 이미지 생성 화면으로 가는 링크는 여기 두지 않는다 — 좌측 패널(좁은 화면은 드로어의 패널 목록)의 "이미지 생성"이 같은
 * 목적지라, 여기에도 두면 한 화면에 진입점이 둘이 된다.
 *
 * "노벨"은 비로그인에게도 보인다 — 누르면 라우트의 `requireSession`이 로그인으로 보냈다가 돌려보낸다. 노벨이 닫혀 있으면(`isWebnovelOpen` — 공개 가격
 * 응답과 `/me` 의 켜짐 표시) 링크를 그리지 않는다. 응답을 받기 전에도 그리지 않는다 — 꺼진 서비스의 탭이 잠깐 보였다 사라지는 것보다
 * 켜진 서비스의 탭이 잠깐 늦게 나타나는 편이 낫다. 헤더는 노벨 코드를 import 하지 않는다(경로 문자열과 플래그만) —
 * 노벨 화면이 첫 화면 번들로 끌려오지 않게.
 *
 * **선택 표시는 홈에서만 켠다.** 홈이면 토글 값이 URL 유형이고, 홈 밖(노벨 화면 포함 전부)에서는 `""`
 * (선택 없음)라 캐릭터/스토리 어느 쪽에도 밑줄이 없다 — 홈 밖 화면은 어느 유형에도 속하지 않는데 밑줄을
 * 남기면 "지금 이 유형을 보고 있다"는 거짓 신호가 된다. 그래서 홈 밖에서는 어느 항목을 눌러도 값이 바뀐
 * 것으로 와 가드를 통과하고 그 유형의 홈으로 간다.
 *
 * `onSelected` — 토글 경로에서는 값이 실제로 바뀔 때만 호출부에 알린다. 재클릭 가드(아래
 * `isContentType` 체크)를 통과한 뒤 `navigate` 다음 **마지막에** 부른다 — 드로어가
 * 이걸로 자기 닫기를 트리거하므로, 닫기가 이동보다 먼저 일어나면 안 된다.
 * 링크 경로는 다르다: `Link`는 사용자 `onClick`을 자기 이동 핸들러보다 **먼저** 부르므로 닫기가 이동보다
 * 앞선다. 드로어의 다른 행(닫기 `onClick`을 `Link`에 넘긴다)도 같은 순서라 그 행들과 동작이 같다. 이 컴포넌트는
 * Sheet 밖(헤더)에서도 쓰여 `SheetClose`를 쓸 수 없으므로 `onSelected`로 닫는다. */
export function ContentTypeToggle({
  variant = "tab",
  onSelected,
}: { variant?: "tab" | "outline"; onSelected?: () => void } = {}) {
  // 홈이 아니면 `undefined`다 — 이 한 값이 "홈인가"와 "홈의 유형·정렬"을 함께 준다. 상세 모달은 라우터를
  // 우회해 URL만 바꾸므로(`useContentDetailModal`) 모달이 열려 있어도 여기서는 여전히 홈이다.
  const homeSearch = useSearch({ from: "/", shouldThrow: false });
  const navigate = useNavigate();
  // pathname 접두사로 판정한다 — 노벨 목록 아래 화면(작품 정보 등) 전체가 대상이다.
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const isWebnovels = pathname === "/webnovels" || pathname.startsWith("/webnovels/");
  const isWebnovelLinkShown = isWebnovelOpen(
    useCloverPricingQuery().data?.novelPublicEnabled,
    useSessionQuery().data?.novelPublicEnabled,
  );

  const handleValueChange = (value: string) => {
    // Radix ToggleGroup(type="single")은 이미 선택된 항목을 다시 누르면 빈 문자열을 emit한다 — 그 경우 무시해
    // 홈에서 토글이 항상 정확히 하나만 선택된 상태를 유지하게 한다(재클릭이면 `onSelected`도 안
    // 불린다). 홈 밖에서는 선택이 없으니 어느 항목을 눌러도 그 값이 와서 여기를 통과해 홈으로 간다.
    if (!isContentType(value)) return;
    void navigate({ to: "/", search: toHomeTypeSwitchSearch(value, homeSearch?.sort) });
    onSelected?.();
  };

  return (
    // gap-2 — `ToggleGroup` 기본 간격(spacing 2)과 같게 해 링크가 그룹의 세 번째 항목처럼 놓이게 한다. 드로어(`outline`)
    // 에서는 줄을 넘길 수 있게 둔다 — 줄을 넘지 못하면 시트 폭이 모자랄 때 마지막 pill 이 잘린다.
    <div className={cn("flex items-center gap-2", variant === "outline" && "flex-wrap")}>
      <ToggleGroup
        type="single"
        variant={variant}
        value={homeSearch ? resolveHomeContentType(homeSearch.type) : ""}
        onValueChange={handleValueChange}
        aria-label="콘텐츠 유형 전환"
        className="shrink-0"
      >
        {/* 라벨이 상시 노출되므로 접근가능 이름은 텍스트 노드에서 계산된다 — `aria-label="캐릭터"/"스토리"`는
            죽은 prop이라 제거했다. */}
        <ToggleGroupItem value="character">캐릭터</ToggleGroupItem>
        <ToggleGroupItem value="story">스토리</ToggleGroupItem>
      </ToggleGroup>
      {/* `shrink-0`은 `toggleVariants`가 아니라 `ToggleGroupItem`이 붙이는 클래스라 여기 직접 준다. */}
      {isWebnovelLinkShown && (
        <Link
          to="/webnovels"
          data-state={isWebnovels ? "on" : "off"}
          onClick={() => onSelected?.()}
          className={cn(toggleVariants({ variant }), "shrink-0")}
        >
          노벨
        </Link>
      )}
    </div>
  );
}
