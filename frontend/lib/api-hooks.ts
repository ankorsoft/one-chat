"""TanStack Query hooks for API data fetching."""
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';

const API_BASE = '/api/v1';

// Types
interface User {
  user_id: number;
  workspace_id: number;
  email?: string;
  full_name?: string;
}

interface Conversation {
  id: number;
  workspace_id: number;
  channel_account_id: number;
  external_chat_id: string;
  title: string | null;
  last_message_at: string | null;
}

interface Message {
  id: string;
  conversation_id: number;
  content: string | null;
  sender_type: string;
  status: string;
  created_at: string;
}

interface AuthTokens {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

// Auth hooks
export function useLogin() {
  return useMutation<AuthTokens, Error, { email: string; password: string }>({
    mutationFn: async (credentials) => {
      const response = await fetch(`${API_BASE}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(credentials),
        credentials: 'include',
      });
      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Login failed');
      }
      return response.json();
    },
  });
}

export function useRegister() {
  return useMutation<AuthTokens, Error, { 
    email: string; 
    password: string; 
    full_name: string;
    workspace_name?: string;
  }>({
    mutationFn: async (data) => {
      const response = await fetch(`${API_BASE}/auth/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
        credentials: 'include',
      });
      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Registration failed');
      }
      return response.json();
    },
  });
}

export function useCurrentUser() {
  return useQuery<User | null>({
    queryKey: ['currentUser'],
    queryFn: async () => {
      const response = await fetch(`${API_BASE}/auth/me`, {
        credentials: 'include',
      });
      if (!response.ok) {
        return null;
      }
      return response.json();
    },
    retry: false,
  });
}

// Conversations hooks
export function useConversations(workspaceId?: number) {
  return useQuery<Conversation[]>({
    queryKey: ['conversations', workspaceId],
    queryFn: async () => {
      const response = await fetch(
        `${API_BASE}/conversations${workspaceId ? `?workspace_id=${workspaceId}` : ''}`,
        { credentials: 'include' }
      );
      if (!response.ok) {
        throw new Error('Failed to fetch conversations');
      }
      return response.json();
    },
    enabled: !!workspaceId,
  });
}

export function useConversationMessages(conversationId: number) {
  return useQuery<Message[]>({
    queryKey: ['messages', conversationId],
    queryFn: async () => {
      const response = await fetch(
        `${API_BASE}/conversations/${conversationId}/messages`,
        { credentials: 'include' }
      );
      if (!response.ok) {
        throw new Error('Failed to fetch messages');
      }
      return response.json();
    },
    enabled: !!conversationId,
  });
}

// CSRF token hook
export function useCSRFToken() {
  return useQuery<string>({
    queryKey: ['csrfToken'],
    queryFn: async () => {
      const response = await fetch(`${API_BASE}/auth/csrf-token`);
      const data = await response.json();
      return data.csrf_token;
    },
    staleTime: Infinity,
  });
}

// Send message mutation
export function useSendMessage() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: async ({ 
      conversationId, 
      content 
    }: { 
      conversationId: number; 
      content: string;
      csrf_token?: string;
    }) => {
      const response = await fetch(
        `${API_BASE}/conversations/${conversationId}/messages`,
        {
          method: 'POST',
          headers: { 
            'Content-Type': 'application/json',
            'X-CSRF-Token': '', // Will be set from cookie
          },
          credentials: 'include',
          body: JSON.stringify({ content }),
        }
      );
      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Failed to send message');
      }
      return response.json();
    },
    onSuccess: (_, variables) => {
      // Invalidate messages query to refetch
      queryClient.invalidateQueries({ 
        queryKey: ['messages', variables.conversationId] 
      });
    },
  });
}

// WebSocket connection status
export function useWebSocketStatus() {
  return useQuery({
    queryKey: ['wsStatus'],
    queryFn: async () => {
      // This is a placeholder - actual WS status comes from the store
      return { connected: true };
    },
    refetchInterval: 5000,
  });
}
