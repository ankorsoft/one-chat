"""Virtualized chat message list with dynamic sizing."""
'use client';

import { useRef, useEffect, useCallback } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import { useChatStore } from '@/stores/chat-store';

interface Message {
  id: string;
  local_id?: string;
  content: string | null;
  sender_type: 'user' | 'contact' | 'system';
  status: 'pending' | 'sending' | 'sent' | 'failed';
  created_at: string;
}

interface ChatMessagesProps {
  conversationId: number;
  messages: Message[];
  onScrollToBottom?: () => void;
}

// Estimate message height based on content
function estimateMessageHeight(message: Message): number {
  const baseHeight = 60; // Base height for avatar, timestamp, etc.
  const contentLength = message.content?.length || 0;
  // Approximate: 1 line per 50 chars, 24px per line
  const contentLines = Math.ceil(contentLength / 50);
  const contentHeight = contentLines * 24;
  return baseHeight + contentHeight;
}

export function ChatMessages({ conversationId, messages }: ChatMessagesProps) {
  const parentRef = useRef<HTMLDivElement>(null);
  const store = useChatStore();
  
  // Track measured sizes for each message
  const sizeMeasurements = useRef<Map<string, number>>(new Map());
  
  // Virtualizer with dynamic sizing
  const virtualizer = useVirtualizer({
    count: messages.length,
    getScrollElement: () => parentRef.current,
    estimateSize: useCallback((index: number) => {
      const message = messages[index];
      if (!message) return 80;
      
      // Use cached measurement if available
      const cached = sizeMeasurements.current.get(message.id || message.local_id || '');
      if (cached) return cached;
      
      // Otherwise estimate based on content
      return estimateMessageHeight(message);
    }, [messages]),
    overscan: 5,
    paddingStart: 10,
    paddingEnd: 10,
  });
  
  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    if (messages.length > 0) {
      virtualizer.scrollToIndex(messages.length - 1, {
        align: 'end',
        behavior: 'smooth',
      });
    }
  }, [messages.length]);
  
  // Handle scroll events for "scroll to bottom" button visibility
  const handleScroll = useCallback(() => {
    const scrollElement = parentRef.current;
    if (!scrollElement) return;
    
    const { scrollTop, scrollHeight, clientHeight } = scrollElement;
    const isNearBottom = scrollHeight - scrollTop - clientHeight < 100;
    
    // Could trigger showing/hiding a "scroll to bottom" button here
  }, []);
  
  return (
    <div
      ref={parentRef}
      className="flex-1 overflow-y-auto"
      onScroll={handleScroll}
      style={{
        height: '100%',
        minHeight: '400px',
      }}
    >
      <div
        style={{
          height: `${virtualizer.getTotalSize()}px`,
          width: '100%',
          position: 'relative',
        }}
      >
        {virtualizer.getVirtualItems().map((virtualRow) => {
          const message = messages[virtualRow.index];
          const isUser = message.sender_type === 'user';
          
          return (
            <div
              key={message.id || message.local_id}
              ref={(el) => {
                virtualizer.measureElement(el);
                
                // Cache the measured size
                if (el) {
                  const measuredHeight = el.offsetHeight;
                  const messageId = message.id || message.local_id || '';
                  
                  // Only update if significantly different to avoid re-renders
                  const cached = sizeMeasurements.current.get(messageId);
                  if (!cached || Math.abs(cached - measuredHeight) > 5) {
                    sizeMeasurements.current.set(messageId, measuredHeight);
                  }
                }
              }}
              data-index={virtualRow.index}
              className={`absolute left-0 right-0 flex ${
                isUser ? 'justify-end' : 'justify-start'
              }`}
              style={{
                transform: `translateY(${virtualRow.start}px)`,
              }}
            >
              <div
                className={`max-w-[70%] rounded-lg px-4 py-2 ${
                  isUser
                    ? 'bg-primary text-primary-foreground'
                    : 'bg-muted text-muted-foreground'
                }`}
              >
                {message.content && (
                  <p className="whitespace-pre-wrap break-words">
                    {message.content}
                  </p>
                )}
                <div className="mt-1 flex items-center gap-2 text-xs opacity-70">
                  <span>
                    {new Date(message.created_at).toLocaleTimeString([], {
                      hour: '2-digit',
                      minute: '2-digit',
                    })}
                  </span>
                  {isUser && (
                    <span>
                      {message.status === 'pending' && '⏳'}
                      {message.status === 'sending' && '📤'}
                      {message.status === 'sent' && '✓'}
                      {message.status === 'failed' && '❌'}
                    </span>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// Loading skeleton for virtualized list
export function ChatMessagesSkeleton() {
  return (
    <div className="flex-1 overflow-y-auto p-4">
      <div className="space-y-4">
        {[...Array(10)].map((_, i) => (
          <div
            key={i}
            className={`flex ${i % 2 === 0 ? 'justify-start' : 'justify-end'}`}
          >
            <div className="h-16 w-48 animate-pulse rounded-lg bg-muted" />
          </div>
        ))}
      </div>
    </div>
  );
}
