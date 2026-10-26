import { z } from "zod";

/** 채팅 방의 입력 초안. 클로버가 모자라 충전하러 다녀오는 동안(결제창이 페이지를 떠났다 돌아오는 경우 포함) 쓰던 글과
 * 거절된 메시지를 잃지 않으려고 탭 저장소(`sessionStorage`)에 방마다 둔다. 탭 저장소인 이유: 이 탭의 왕복을 견디면
 * 충분하고, 탭을 닫으면 함께 사라져야 한다(다른 기기·다른 탭으로 번질 이유가 없다).
 *
 * - `input` — 입력창에 쓰던 글. 입력할 때마다 덮어쓴다.
 * - `rejected` — 클로버가 모자라 서버가 시작 전에 거절한 새 메시지. 서버에 남지 않았으므로 돌아와서 다시 보낼 글이다.
 *
 * 로그아웃·탈퇴는 전부 지운다(`clearAllChatDrafts`) — 같은 탭에서 다음 계정이 앞 계정의 글을 보면 안 된다. */
const CHAT_DRAFT_KEY_PREFIX = "ttona.chatDraft.";

const chatDraftSchema = z.object({ input: z.string(), rejected: z.string() });

export type ChatDraft = z.infer<typeof chatDraftSchema>;

type ChatDraftStorage = Pick<Storage, "getItem" | "setItem" | "removeItem" | "key" | "length">;

/** 사이트 데이터가 차단된 브라우저에서는 `sessionStorage` 참조 자체가 던진다 — 아래 함수들이 함께 삼킨다. 저장하지
 * 못하면 초안이 이 화면에만 남을 뿐이다. */
function browserStorage(): ChatDraftStorage {
  return window.sessionStorage;
}

function chatDraftKey(roomId: string): string {
  return `${CHAT_DRAFT_KEY_PREFIX}${roomId}`;
}

/** 저장값이 없거나 깨졌거나 못 읽으면 없는 것이다. */
export function readChatDraft(roomId: string, getStorage: () => ChatDraftStorage = browserStorage): ChatDraft | null {
  try {
    const raw = getStorage().getItem(chatDraftKey(roomId));
    if (raw === null) return null;
    const parsed = chatDraftSchema.safeParse(JSON.parse(raw));
    return parsed.success ? parsed.data : null;
  } catch {
    return null;
  }
}

function writeChatDraft(roomId: string, draft: ChatDraft, getStorage: () => ChatDraftStorage): void {
  try {
    const storage = getStorage();
    if (draft.input === "" && draft.rejected === "") storage.removeItem(chatDraftKey(roomId));
    else storage.setItem(chatDraftKey(roomId), JSON.stringify(draft));
  } catch {
    // 저장하지 못해도 입력창의 글은 그대로다.
  }
}

function updateChatDraft(
  roomId: string,
  change: Partial<ChatDraft>,
  getStorage: () => ChatDraftStorage,
): void {
  const current = readChatDraft(roomId, getStorage) ?? { input: "", rejected: "" };
  writeChatDraft(roomId, { ...current, ...change }, getStorage);
}

export function saveChatDraftInput(
  roomId: string,
  input: string,
  getStorage: () => ChatDraftStorage = browserStorage,
): void {
  updateChatDraft(roomId, { input }, getStorage);
}

export function saveRejectedChatMessage(
  roomId: string,
  text: string,
  getStorage: () => ChatDraftStorage = browserStorage,
): void {
  updateChatDraft(roomId, { rejected: text }, getStorage);
}

/** 새 메시지가 전해졌으면 거절됐던 메시지는 할 일을 다했다. 입력 초안은 그사이 새로 쓴 글이라 남긴다. */
export function clearRejectedChatMessage(roomId: string, getStorage: () => ChatDraftStorage = browserStorage): void {
  updateChatDraft(roomId, { rejected: "" }, getStorage);
}

/** 방을 지웠으면 그 방의 초안도 지운다. */
export function removeChatDraft(roomId: string, getStorage: () => ChatDraftStorage = browserStorage): void {
  try {
    getStorage().removeItem(chatDraftKey(roomId));
  } catch {
    // 못 지운 초안은 탭을 닫으면 사라진다.
  }
}

/** 모든 방의 초안을 지운다(로그아웃·탈퇴). 지우는 동안 인덱스가 밀리므로 키를 먼저 모은다. */
export function clearAllChatDrafts(getStorage: () => ChatDraftStorage = browserStorage): void {
  try {
    const storage = getStorage();
    const keys: string[] = [];
    for (let index = 0; index < storage.length; index += 1) {
      const key = storage.key(index);
      if (key?.startsWith(CHAT_DRAFT_KEY_PREFIX)) keys.push(key);
    }
    for (const key of keys) storage.removeItem(key);
  } catch {
    // 못 지운 초안은 탭을 닫으면 사라진다.
  }
}

/** 방에 들어올 때 입력창에 넣을 글을 고르고(`pickChatDraftToRestore`), 그 글을 입력 초안으로 옮기며 거절 칸을 비운다.
 * 되살린 순간 그 글은 입력창의 글이다 — 거절 칸에 남겨 두면 사용자가 입력창에서 지운 뒤에도 다음에 방에 들어올 때 또
 * 돌아온다. 두 번 불러도 같은 글을 돌려준다(개발 모드는 상태 초기값 함수를 두 번 부른다). */
export function takeChatDraftToRestore(roomId: string, getStorage: () => ChatDraftStorage = browserStorage): string {
  const draft = readChatDraft(roomId, getStorage);
  const text = pickChatDraftToRestore(draft);
  if (draft) writeChatDraft(roomId, { input: text, rejected: "" }, getStorage);
  return text;
}

/** 방에 돌아왔을 때 입력창에 넣을 글. 입력 초안이 있으면 그것이고, 없으면 거절된 메시지다.
 *
 * 입력 초안을 거절된 메시지로 덮지 않는다 — 보낼 때 입력창을 비우므로 거절된 메시지는 언제나 입력창이 빈 뒤에 생기고,
 * 그 뒤 입력창에 글이 있다면 거절 뒤에 새로 쓴 글이다. 더 나중의 뜻을 앞의 글로 지우지 않는다. */
export function pickChatDraftToRestore(draft: ChatDraft | null): string {
  if (!draft) return "";
  return draft.input.trim() !== "" ? draft.input : draft.rejected;
}
