"""Zustand store for chat state and offline queue."""
import { create } from 'zustand';
import { openDB, type IDBPDatabase } from 'idb';

// Types
interface Message {
  id: string;
  local_id?: string;
  conversation_id: number;
  content: string;
  sender_type: 'user' | 'contact' | 'system';
  status: 'pending' | 'sending' | 'sent' | 'failed';
  created_at: string;
}

interface OfflineMessage extends Message {
  local_id: string;
  retry_count: number;
}

interface ChatState {
  // Online state
  conversations: Map<number, Message[]>;
  activeConversation: number | null;
  isConnected: boolean;
  
  // Offline queue (IndexedDB backed)
  offlineQueue: OfflineMessage[];
  
  // Actions
  setConnected: (connected: boolean) => void;
  setActiveConversation: (id: number | null) => void;
  addMessage: (conversationId: number, message: Message) => void;
  updateMessageStatus: (localId: string, status: Message['status'], serverId?: string) => void;
  queueOfflineMessage: (message: Omit<OfflineMessage, 'local_id' | 'retry_count'>) => Promise<string>;
  getOfflineMessages: () => Promise<OfflineMessage[]>;
  flushOfflineQueue: () => Promise<void>;
}

// IndexedDB helpers
const DB_NAME = 'onechat-offline';
const DB_VERSION = 1;
const STORE_NAME = 'offline-messages';

let dbPromise: Promise<IDBPDatabase> | null = null;

function getDB(): Promise<IDBPDatabase> {
  if (!dbPromise) {
    dbPromise = openDB(DB_NAME, DB_VERSION, {
      upgrade(db) {
        db.createObjectStore(STORE_NAME, { keyPath: 'local_id' });
      },
    });
  }
  return dbPromise;
}

// Generate unique local ID
function generateLocalId(): string {
  return `local_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
}

export const useChatStore = create<ChatState>((set, get) => ({
  conversations: new Map(),
  activeConversation: null,
  isConnected: true,
  offlineQueue: [],
  
  setConnected: (connected) => {
    set({ isConnected: connected });
    if (connected) {
      // Attempt to flush offline queue when reconnected
      get().flushOfflineQueue();
    }
  },
  
  setActiveConversation: (id) => {
    set({ activeConversation: id });
  },
  
  addMessage: (conversationId, message) => {
    set((state) => {
      const convMessages = state.conversations.get(conversationId) || [];
      const updated = [...convMessages, message];
      // Sort by created_at
      updated.sort((a, b) => 
        new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
      );
      const newConversations = new Map(state.conversations);
      newConversations.set(conversationId, updated);
      return { conversations: newConversations };
    });
  },
  
  updateMessageStatus: (localId, status, serverId) => {
    set((state) => {
      const newConversations = new Map(state.conversations);
      newConversations.forEach((messages, convId) => {
        const updated = messages.map((msg) => {
          if (msg.local_id === localId || msg.id === localId) {
            return {
              ...msg,
              status,
              id: serverId || msg.id,
            };
          }
          return msg;
        });
        newConversations.set(convId, updated);
      });
      return { conversations: newConversations };
    });
  },
  
  queueOfflineMessage: async (message) => {
    const localId = generateLocalId();
    const offlineMsg: OfflineMessage = {
      ...message,
      local_id: localId,
      retry_count: 0,
    };
    
    // Store in IndexedDB
    const db = await getDB();
    await db.put(STORE_NAME, offlineMsg);
    
    // Update local state
    set((state) => ({
      offlineQueue: [...state.offlineQueue, offlineMsg],
    }));
    
    // Add to UI optimistically
    get().addMessage(message.conversation_id, {
      ...offlineMsg,
      id: localId,
    });
    
    return localId;
  },
  
  getOfflineMessages: async () => {
    const db = await getDB();
    const messages = await db.getAll(STORE_NAME);
    return messages as OfflineMessage[];
  },
  
  flushOfflineQueue: async () => {
    const db = await getDB();
    const messages = await db.getAll(STORE_NAME);
    
    if (messages.length === 0) return;
    
    // Try to send each message
    const tx = db.transaction(STORE_NAME, 'readwrite');
    const store = tx.objectStore(STORE_NAME);
    
    for (const msg of messages) {
      try {
        // TODO: Call API to send message
        // const response = await fetch('/api/v1/messages', { ... })
        
        // If successful, delete from queue
        await store.delete(msg.local_id);
        
        // Update UI
        get().updateMessageStatus(msg.local_id, 'sent');
      } catch (error) {
        // Increment retry count
        if (msg.retry_count < 5) {
          await store.put({
            ...msg,
            retry_count: msg.retry_count + 1,
          });
        } else {
          // Mark as failed in UI
          get().updateMessageStatus(msg.local_id, 'failed');
          await store.delete(msg.local_id);
        }
      }
    }
    
    // Refresh local queue state
    const remaining = await db.getAll(STORE_NAME);
    set({ offlineQueue: remaining as OfflineMessage[] });
  },
}));

// Auto-load offline messages on init
if (typeof window !== 'undefined') {
  useChatStore.getState().getOfflineMessages().then((messages) => {
    useChatStore.setState({ offlineQueue: messages });
  });
}
