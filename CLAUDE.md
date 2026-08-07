# AI 캐릭터 챗 서비스

## 작업 규칙

- UI/프론트엔드 관련 작업(디자인, 레이아웃, 컴포넌트 스타일링, 반응형, 접근성, 인터랙션/모션 등)으로 판단되면 impeccable 플러그인의 스킬(`impeccable:impeccable`)을 사용해서 진행한다.

## Design Context

전략은 `PRODUCT.md`, 비주얼 시스템은 `DESIGN.md`(+ `.impeccable/design.json` 사이드카)에 있다. **UI를 만들거나 고치기 전에 `DESIGN.md`를 읽는다.** 색 토큰의 유일한 소스는 `packages/ui/src/styles/globals.css`이고, 구현 규칙은 `packages/ui/CLAUDE.md`에 있다.

- **Register:** product. **North Star:** "불 꺼진 방의 유일한 빛" — 늦은 밤 불 끄고 침대에서 혼자 캐릭터와 대화하는 장면. 화면이 그 방의 유일한 광원이라는 전제가 아래 규칙 전부를 만든다.
- **다크가 기본값이다**(web은 저장값 없으면 다크로 부팅, admin은 라이트 고정). 라이트는 열등한 대안이 아니라 낮·admin용 대등한 팔레트다.
- **다크에서 순백 금지** — 밝기 천장은 `foreground`(oklch 0.930)다. `text-white`/`#fff`/`oklch(1)`를 다크에 쓰지 않는다.
- **`primary`는 핑크-레드 강조**이자 이 시스템의 유일한 유채색 솔리드 채움이다(라이트 `oklch(0.5 0.19 0)` / 다크 `oklch(0.72 0.18 0)`, `ring`도 같은 값). 채움 위 텍스트는 `primary-foreground`로 뒤집는다(라이트 6.70:1 / 다크 7.18:1) — `destructive`도 동일한 반전 쌍을 유지해야 한다(밝힌 빨강 위 흰 텍스트는 3.68:1로 AA 미달).
- **색은 강조 지점(`primary`/`ring`)과 사용자 콘텐츠(썸네일, 스탯 스와치), `destructive`에만 있고 배경·카드·보더 사다리는 무채색을 유지한다.** `destructive`는 항상 `/10` 틴트이며 솔리드 레드 채움은 이 시스템에 없다 — 솔리드 채움이 `primary` 하나뿐이라 둘은 형태로도 갈린다.
- **정지 상태에 그림자 없음** — 깊이는 명도 사다리로 만든다(다크 0.160→0.210→0.260→0.300, 라이트는 반전).
- **모든 애니메이션에 `motion-safe:`를 붙인다.** 어두운 방에서 갑작스러운 움직임은 놀람이다.
- **타이포는 Pretendard Variable 하나**, 굵기는 medium/semibold/bold 셋뿐, 크기 천장은 `text-2xl`(clamp·vw 유동 타이포 금지). 본문 기본은 `text-sm`.
- **크롬은 sticky 헤더 하나(`h-14`)뿐이다.** 하단 탭바·사이드 레일·푸터를 추가하지 않는다.
