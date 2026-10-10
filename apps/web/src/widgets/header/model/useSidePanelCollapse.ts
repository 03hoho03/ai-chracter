import { useState } from "react";
import { useMedia } from "react-use";

import {
  getNextScreenCollapsed,
  getSidePanelScreen,
  readSavedSidePanelCollapsed,
  resolveSidePanelCollapsed,
  toggleSidePanelCollapsed,
  writeSavedSidePanelCollapsed,
  type SidePanelScreen,
} from "./sidePanelCollapse";

export type SidePanelCollapse = {
  isCollapsed: boolean;
  /** 이번 접힘이 사용자의 토글로 생겼는가. 그때만 폭을 전환으로 움직인다 — 채팅·이미지 스튜디오에 들어오거나 창 크기가
   * 바뀌어 생긴 접힘은 같은 순간 본문 폭도 바뀌어, 전환을 두면 새 화면이 프레임마다 다시 배치되며 출렁인다. */
  isToggled: boolean;
  toggle: () => void;
};

type ScreenState = { screen: SidePanelScreen; collapsed: boolean | undefined };

/**
 * 좌측 패널의 접힘 상태. 규칙은 `sidePanelCollapse.ts` 에 있고 이 훅은 그것을 화면 이동·창 크기·토글에 잇는다.
 *
 * 패널은 `lg` 이상에서만 마운트되므로 이 훅은 패널 안이 아니라 늘 마운트된 셸에서 부른다. 패널 안에 두면 창을 `lg`
 * 아래로 줄였다 늘리는 사이에 채팅에서 펼친 상태가 지워져 다시 접힌다. 화면 이동도 패널이 없는 동안 계속 따라간다.
 *
 * - 저장값은 React 상태에 들고 저장소 쓰기는 그 뒤에 한다 — 저장소가 막힌 브라우저에서도 이번 방문 동안 토글이 먹는다.
 * - 화면의 임시값은 첫 렌더의 초기 상태로 계산한다. effect 로 계산하면 채팅에서 새로고침할 때 펼친 패널이 한 프레임
 *   그려진 뒤 접힌다.
 * - 화면이 바뀌면 렌더 중에 다음 임시값으로 옮긴다(이전 화면과 비교하는 React 의 "렌더 중 상태 조정"). effect 로 하면
 *   새 화면이 이전 접힘으로 한 번 그려진다.
 */
export function useSidePanelCollapse(pathname: string): SidePanelCollapse {
  const screen = getSidePanelScreen(pathname);
  // xl. 저장값이 없을 때의 기본값(넓으면 펼침)을 가른다. 기본값 없이 써서 첫 렌더부터 실제 값을 읽는다(`useIsSidePanelLayout` 과 같은 이유).
  const isWide = useMedia("(min-width: 80rem)");
  const [savedCollapsed, setSavedCollapsed] = useState(readSavedSidePanelCollapsed);
  const [screenState, setScreenState] = useState<ScreenState>(() => ({
    screen,
    collapsed: getNextScreenCollapsed(undefined, screen, undefined),
  }));
  const [isToggled, setIsToggled] = useState(false);
  const [previousIsWide, setPreviousIsWide] = useState(isWide);

  if (screenState.screen !== screen) {
    setScreenState({ screen, collapsed: getNextScreenCollapsed(screenState.screen, screen, screenState.collapsed) });
    setIsToggled(false);
  }
  if (previousIsWide !== isWide) {
    setPreviousIsWide(isWide);
    setIsToggled(false);
  }

  const isCollapsed = resolveSidePanelCollapsed({ savedCollapsed, screenCollapsed: screenState.collapsed, isWide });

  function toggle() {
    const next = toggleSidePanelCollapsed(screen, isCollapsed);
    if (next.shouldSave) {
      setSavedCollapsed(next.isCollapsed);
      writeSavedSidePanelCollapsed(next.isCollapsed);
    } else {
      setScreenState({ screen, collapsed: next.isCollapsed });
    }
    setIsToggled(true);
  }

  return { isCollapsed, isToggled, toggle };
}
