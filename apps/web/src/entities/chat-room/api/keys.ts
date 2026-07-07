export const chatRoomKeys = {
  all: ["chat-room"] as const,
  list: (contentId: string) => [...chatRoomKeys.all, "list", contentId] as const,
  detail: (roomId: string) => [...chatRoomKeys.all, "detail", roomId] as const,
};
