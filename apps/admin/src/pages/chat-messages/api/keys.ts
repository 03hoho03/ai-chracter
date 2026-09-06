export type ChatMessagesCursor = {
  beforeCreatedAt: string;
  beforeId: string;
};

export const chatMessagesKeys = {
  all: (roomId: string) => ["chat-messages", roomId] as const,
  list: (roomId: string, cursor: ChatMessagesCursor) =>
    [...chatMessagesKeys.all(roomId), "list", cursor.beforeCreatedAt, cursor.beforeId] as const,
};
