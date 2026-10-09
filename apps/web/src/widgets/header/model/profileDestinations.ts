/** 목적지는 이 파일 하나에서만 정한다. 좌측 패널·모바일 드로어·프로필 메뉴가 모두 여기를 읽도록 둔다 — 여러 곳이 각자
 * 목록을 들면 한쪽에만 항목이 추가되는 게 이 저장소의 알려진 실패 모드다(`toContentStatusTags` 선례: "같은 작품이
 * 한 화면에서는 이용제한, 다른 화면에서는 공개가 됐다").
 *
 * 키마다 자리(패널 / 프로필 메뉴)를 한 번만 정하도록 나눈 목록이다. 패널이 보이는 폭에서는 헤더의 프로필 메뉴도 함께
 * 보이므로, 같은 목적지가 패널과 메뉴에 함께 있으면 메뉴를 연 화면에 같은 항목이 두 번 보인다. 패널이 없는 폭의
 * 드로어는 둘을 합쳐 그리도록 둔다(패널 키 + 메뉴 그룹 평면화).
 *
 * 키 유니언도 이 배열들에서 도출한다. 유니언을 따로 적으면 키를 유니언과 링크의 `switch`에만 더하고 배열에서
 * 빠뜨려도 컴파일이 통과해, 그 목적지가 어디에도 나타나지 않는다. */

/** 패널 내비(펼침·레일 공통) 순서. 라벨은 링크(`ProfileDestinationLink`)가 정한다. */
export const SIDE_PANEL_DESTINATION_KEYS = ["home", "builder", "my-works", "novels", "studio-images", "favorites"] as const;

/** 접힌 레일에만 내비 아래 따로 두도록 나눈 내 채팅목록. 펼친 패널에서는 최근 대화 섹션의 "전체 보기"가 같은 화면으로
 * 가게 한다. 레일은 최근 대화 섹션을 숨기고 내 채팅목록은 아래 프로필 메뉴 그룹에도 넣지 않았으므로, 이 칸이 없으면
 * 레일 화면에서 내 채팅목록에 한 번에 닿을 길이 없다. */
export const SIDE_PANEL_RAIL_CHATS_KEY = "chats";

/** 프로필 메뉴에 남는 목적지. 크리에이터 정산은 클로버 바로 뒤에 둔다 — 돈에 관한 화면끼리 붙인다. */
export const PROFILE_MENU_DESTINATION_GROUPS = [
  { label: "계정", keys: ["profile", "personas", "clover", "creator-payout", "mypage"] },
  { label: "고객센터", keys: ["about", "notices", "inquiry-new", "terms", "privacy", "operation-policy", "youth-policy", "refund-policy"] },
] as const satisfies readonly { label: string; keys: readonly string[] }[];

export type ProfileDestinationKey =
  | (typeof SIDE_PANEL_DESTINATION_KEYS)[number]
  | typeof SIDE_PANEL_RAIL_CHATS_KEY
  | (typeof PROFILE_MENU_DESTINATION_GROUPS)[number]["keys"][number];

/** 지금 프로필 메뉴와 모바일 드로어가 그리는 옛 배치(창작·활동·계정·고객센터). 두 화면이 위의 패널 키와 메뉴
 * 그룹을 읽도록 바뀌면 지운다. 키는 위 유니언 안에서만 고를 수 있어 여기에만 새 목적지를 더할 수는 없다. */
export const PROFILE_DESTINATION_GROUPS = [
  { label: "창작", keys: ["builder", "my-works", "studio-images", "creator-payout"] },
  { label: "활동", keys: ["chats", "novels", "favorites"] },
  { label: "계정", keys: ["profile", "personas", "clover", "mypage"] },
  { label: "고객센터", keys: ["about", "notices", "inquiry-new", "terms", "privacy", "operation-policy", "youth-policy", "refund-policy"] },
] as const satisfies readonly { label: string; keys: readonly ProfileDestinationKey[] }[];
