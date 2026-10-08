import type { ContentDraftPayload, NovelPermission } from "@/entities/content";

/**
 * 빌더 저장이 소설 만들기 허락 칸을 **이 화면에서 바꿨을 때만** 싣게 하는 기록.
 *
 * 이 칸은 작품 헤더 값이라 빌더 밖(작품 상세 "⋯" 메뉴)에서도 바뀐다. 빌더는 다른 칸을 고칠 때마다 폼 전체를 저장하므로,
 * 칸을 늘 실으면 빌더가 열려 있는 동안 다른 곳에서 바꾼 값을 다음 자동저장이 폼에 남은 옛 값으로 되돌린다. 서버는 칸이
 * 없으면 저장된 값을 그대로 두므로, 기준 값(불러온 값, 이후로는 이 화면이 마지막으로 보낸 값)과 같으면 칸을 빼고 보낸다.
 *
 * 기준은 응답을 기다리지 않고 **보내는 순간** 옮긴다. 자동저장은 앞 저장의 응답을 기다리지 않고 나가므로, 응답 뒤에 옮기면
 * 응답 전에 원래 값으로 되돌린 저장이 "기준과 같다"며 칸을 빼고, 서버에는 앞 저장의 값이 남는다. 실어 보낸 저장이 실패하면
 * 기준을 비워 다음 저장이 반드시 다시 싣게 한다.
 *
 * 기준을 저장 응답의 값으로 바꾸지 않는 이유: 응답에는 다른 곳에서 바꾼 값이 실려 오는데, 그걸 기준으로 삼으면 폼의 옛
 * 값과 달라져 다음 저장이 도로 덮는다.
 */
export function createNovelPermissionSync(initial: NovelPermission | undefined) {
  let lastSent = initial;

  return {
    /** 보낼 페이로드. 폼 값이 기준과 같으면 칸을 빼고, 다르면 싣고 그 값을 새 기준으로 삼는다. */
    prepare(payload: ContentDraftPayload): ContentDraftPayload {
      if (payload.novelPermission == null) return payload;
      if (payload.novelPermission !== lastSent) {
        lastSent = payload.novelPermission;
        return payload;
      }
      const withoutField = { ...payload };
      delete withoutField.novelPermission;
      return withoutField;
    },
    /** 저장이 실패한 뒤 부른다. 칸을 실었던 저장이면 서버에 닿았는지 모르므로 기준을 비운다. */
    fail(sent: ContentDraftPayload) {
      if (sent.novelPermission != null) lastSent = undefined;
    },
  };
}
