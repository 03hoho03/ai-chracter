/**
 * 화면에 오래 머무는 비활성 기본(`primary`) 버튼(바꾼 것이 없을 때의 "초안 저장")에 준다. 기본 비활성은 핑크 채움을 반투명으로
 * 둘 뿐이라 연분홍 덩어리가 그대로 남아 눌러야 할 버튼처럼 읽히고, 비활성 컨트롤은 무채색이어야 한다는 규칙(DESIGN.md Colors
 * 절)에도 어긋난다. 무채색 채움 + 흐린 글자로 바꿔 변경이 생겨 핑크로 켜지는 순간이 곧 "이제 저장할 수 있다"가 되게 한다.
 * 요청 중에 잠깐 잠그는 버튼은 대상이 아니다(누른 직후라 상태가 이미 보인다).
 */
export const RESTING_DISABLED_PRIMARY_CLASS = "disabled:bg-secondary disabled:text-muted-foreground disabled:opacity-100";
