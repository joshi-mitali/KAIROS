export async function api(path: string, options: RequestInit = {}) {
  const response = await fetch('/api' + path, { credentials: 'same-origin', ...options, headers: { 'Content-Type': 'application/json', ...options.headers } });
  const result = await response.json().catch(() => ({ detail: 'The server returned an unreadable response.' }));
  if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Check the entered values and try again.');
  return result;
}

export const post = (path: string, body: unknown) => api(path, { method: 'POST', body: JSON.stringify(body) });
