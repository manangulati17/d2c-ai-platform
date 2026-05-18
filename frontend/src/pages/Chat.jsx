import { useState } from 'react';
import './Chat.css';

function Chat({ merchantId }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const parseCitations = (text) => {
    const citationRegex = /\[cited:\s*([a-f0-9-,\s]+)\]/gi;
    const parts = [];
    let lastIndex = 0;

    text.replace(citationRegex, (match, uuids, offset) => {
      if (offset > lastIndex) {
        parts.push({ type: 'text', content: text.slice(lastIndex, offset) });
      }

      const uuidList = uuids.split(',').map(uuid => uuid.trim());
      parts.push({ type: 'citations', uuids: uuidList });
      lastIndex = offset + match.length;
    });

    if (lastIndex < text.length) {
      parts.push({ type: 'text', content: text.slice(lastIndex) });
    }

    return parts.length > 0 ? parts : [{ type: 'text', content: text }];
  };

  const handleSend = async () => {
    if (!input.trim()) return;

    if (!merchantId) {
      setError('Enter a Merchant ID above first.');
      return;
    }

    setError('');
    const userMessage = { role: 'user', content: input };
    setMessages(prev => [...prev, userMessage]);
    setInput('');
    setLoading(true);

    try {
      const response = await fetch('http://localhost:8000/chat/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: input,
          merchant_id: merchantId,
          conversation_history: []
        })
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Chat request failed');
      }

      const data = await response.json();
      
      const assistantMessage = {
        role: 'assistant',
        content: data.assistant_message,
        citation_valid: data.citation_valid,
        cited_row_ids: data.cited_row_ids,
        iteration_count: data.iteration_count,
        tool_calls: data.tool_calls
      };

      setMessages(prev => [...prev, assistantMessage]);
    } catch (err) {
      console.error('Chat error:', err);
      setError(err.message || 'Failed to send message. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  if (!merchantId) {
    return (
      <div className="chat-page">
        <div className="chat-empty-merchant">
          Enter a Merchant ID above to get started.
        </div>
      </div>
    );
  }

  return (
    <div className="chat-page">
      <div className="chat-messages">
        {messages.length === 0 ? (
          <div className="chat-empty">
            <div className="chat-empty-text">Ask anything about your store data.</div>
            <div className="chat-empty-subtext">
              Revenue, ad spend, refunds — all your data, cited.
            </div>
          </div>
        ) : (
          messages.map((msg, idx) => (
            <div key={idx} className={msg.role === 'user' ? 'chat-message-user' : 'chat-message-assistant'}>
              {msg.role === 'user' ? (
                <div className="chat-bubble-user">{msg.content}</div>
              ) : (
                <div className="chat-bubble-assistant-wrapper">
                  <div className="chat-bubble-assistant">
                    {msg.citation_valid !== undefined && (
                      <div className={`chat-citation-dot ${msg.citation_valid ? 'chat-citation-valid' : 'chat-citation-invalid'}`}></div>
                    )}
                    <div className="chat-message-text">
                      {parseCitations(msg.content).map((part, i) => (
                        part.type === 'text' ? (
                          <span key={i}>{part.content}</span>
                        ) : (
                          part.uuids.map((uuid, j) => (
                            <span key={`${i}-${j}`} className="chat-citation-badge" title={uuid}>
                              {uuid.slice(0, 8)}...
                            </span>
                          ))
                        )
                      ))}
                    </div>
                    {msg.iteration_count !== undefined && (
                      <div className="chat-meta">
                        via {msg.iteration_count} tool call{msg.iteration_count !== 1 ? 's' : ''} · {msg.cited_row_ids?.length || 0} citation{msg.cited_row_ids?.length !== 1 ? 's' : ''}
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          ))
        )}
      </div>

      <div className="chat-input-area">
        <input
          type="text"
          className="chat-input"
          placeholder="Ask your data anything..."
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyPress={handleKeyPress}
          disabled={loading}
        />
        <button
          className="chat-send-button"
          onClick={handleSend}
          disabled={loading || !input.trim()}
        >
          {loading ? (
            <div className="chat-spinner"></div>
          ) : (
            'SEND →'
          )}
        </button>
      </div>

      {error && <div className="chat-error">{error}</div>}
    </div>
  );
}

export default Chat;
