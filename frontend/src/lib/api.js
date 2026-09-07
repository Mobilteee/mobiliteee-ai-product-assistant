const API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8000';

export async function streamQuery({ question, history, apiKey, baseUrl, model, user_id, doc_ids, strategy, preset, conversation_id }) {
  const response = await fetch(`${API_BASE}/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      question,
      history,
      api_key: apiKey,
      base_url: baseUrl,
      model,
      user_id,
      doc_ids,
      strategy,
      preset,
      conversation_id,
    }),
  });

  if (!response.ok) {
    throw new Error(`API request failed: ${response.status}`);
  }
  if (!response.body) {
    throw new Error('No response body');
  }
  return response.body.getReader();
}

function parseEventBlock(raw) {
  let event = null;
  const dataLines = [];
  for (const line of raw.split('\n')) {
    if (line.startsWith('event:')) {
      event = line.slice(6).trim();
    } else if (line.startsWith('data:')) {
      let value = line.slice(5);
      // SSE strips a single leading space after "data:" (the glue the server
      // adds). Remove exactly one so a token's own leading space(s) survive.
      if (value[0] === ' ') value = value.slice(1);
      dataLines.push(value);
    }
  }
  if (event && dataLines.length > 0) {
    return { event, data: dataLines.join('\n') };
  }
  return null;
}

export async function* streamSSE(reader) {
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let boundary = buffer.indexOf('\n\n');
    while (boundary !== -1) {
      const raw = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const parsed = parseEventBlock(raw);
      if (parsed) yield parsed;
      boundary = buffer.indexOf('\n\n');
    }
  }

  // Process any trailing block that arrived without a closing "\n\n". Don't
  // trim: a token whose final chars are whitespace must keep them verbatim.
  const tail = parseEventBlock(buffer);
  if (tail) yield tail;
}

export async function listDocuments(user_id = 1) {
  const response = await fetch(`${API_BASE}/documents?user_id=${user_id}`);
  if (!response.ok) {
    throw new Error(`Failed to load documents: ${response.status}`);
  }
  return response.json();
}

export async function uploadDocuments(files, user_id = 1) {
  const formData = new FormData();
  for (const file of files) {
    formData.append('files', file);
  }
  const response = await fetch(`${API_BASE}/documents/upload?user_id=${user_id}`, {
    method: 'POST',
    body: formData,
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    const detail = payload?.detail || response.status;
    throw new Error(`Upload failed: ${detail}`);
  }
  return response.json();
}

export async function getTaskStatus(taskId) {
  const response = await fetch(`${API_BASE}/documents/task/${taskId}`);
  if (!response.ok) {
    throw new Error(`Failed to get task status: ${response.status}`);
  }
  return response.json();
}
export async function getRetrievalConfig() {
  const response = await fetch(API_BASE + '/retrieval/config');
  if (!response.ok) {
    throw new Error('Failed to load retrieval config: ' + response.status);
  }
  return response.json();
}
export async function submitFeedback(payload) {
  const response = await fetch(API_BASE + '/feedback', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      user_id: payload.user_id || 1,
      thumbs: payload.thumbs,
      question: payload.question || '',
      answer_excerpt: payload.answer_excerpt || '',
      reasons: payload.reasons || [],
    }),
  });
  if (!response.ok) {
    throw new Error('Feedback submit failed: ' + response.status);
  }
  return response.json();
}

export async function getMetricsOverview() {
  const response = await fetch(API_BASE + '/metrics/overview?user_id=1');
  if (!response.ok) {
    throw new Error('Failed to load metrics: ' + response.status);
  }
  return response.json();
}
export async function getDocumentContent(docId, user_id = 1) {
  const response = await fetch(API_BASE + '/documents/' + docId + '/content?user_id=' + user_id);
  if (!response.ok) {
    throw new Error('Failed to load document content: ' + response.status);
  }
  return response.json();
}
export async function getConversations(user_id = 1) {
  const response = await fetch(API_BASE + '/conversations?user_id=' + user_id);
  if (!response.ok) throw new Error('Failed to load conversations: ' + response.status);
  const data = await response.json();
  return data.conversations || [];
}

export async function createConversation(user_id = 1, title = '新的会话') {
  const response = await fetch(API_BASE + '/conversations', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_id, title }),
  });
  if (!response.ok) throw new Error('Failed to create conversation');
  return response.json();
}

export async function getConversationMessages(conversationId, user_id = 1) {
  const response = await fetch(API_BASE + '/conversations/' + conversationId + '/messages?user_id=' + user_id);
  if (!response.ok) throw new Error('Failed to load conversation messages');
  const data = await response.json();
  return data.messages || [];
}

export async function deleteConversation(conversationId, user_id = 1) {
  const response = await fetch(API_BASE + '/conversations/' + conversationId + '?user_id=' + user_id, { method: 'DELETE' });
  if (!response.ok) throw new Error('Failed to delete conversation');
  return response.json();
}
