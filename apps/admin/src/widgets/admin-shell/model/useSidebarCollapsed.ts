import { useState } from "react";

const STORAGE_KEY = "admin-sidebar-collapsed";

// 접힘은 이 브라우저의 편의 설정이라 localStorage 에 둔다. 사생활 모드·사이트 데이터 차단에서는 접근 자체가
// 예외를 던지므로 읽기·쓰기를 모두 감싸고, 못 읽으면 펼침으로 시작한다.
function readCollapsed() {
  try {
    return window.localStorage.getItem(STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

function writeCollapsed(isCollapsed: boolean) {
  try {
    window.localStorage.setItem(STORAGE_KEY, isCollapsed ? "1" : "0");
  } catch {
    // 저장에 실패해도 이번 화면의 접힘은 그대로 유지된다 — 다음 방문에 펼침으로 시작할 뿐이다.
  }
}

/** 사이드바 한 곳만 쓰므로 전역 상태로 올리지 않는다. */
export function useSidebarCollapsed() {
  const [isCollapsed, setIsCollapsed] = useState(readCollapsed);

  function toggle() {
    const next = !isCollapsed;
    setIsCollapsed(next);
    writeCollapsed(next);
  }

  return { isCollapsed, toggle };
}
