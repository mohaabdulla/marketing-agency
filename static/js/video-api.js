export async function api(path, options = {}) {
  const response = await fetch(`/api/video${path}`, {
    ...options,
    headers: options.body instanceof FormData ? options.headers : {'Content-Type': 'application/json', ...options.headers},
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    const detail = payload.detail;
    throw new Error(typeof detail === 'string' ? detail : detail ? detail.map(x => `${x.loc?.slice(1).join('.')}: ${x.msg}`).join('; ') : `Request failed (${response.status})`);
  }
  return response.json();
}
export const post = (path, body) => api(path, {method:'POST', body:JSON.stringify(body)});
export const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const id = () => Array.from(crypto.getRandomValues(new Uint8Array(16)), b => b.toString(16).padStart(2, '0')).join('');
export function report(error) { document.getElementById('vs-message').textContent = typeof error === 'string' ? error : error?.message ?? String(error); }
export async function upload(file) { const data = new FormData(); data.append('file', file); return api('/upload', {method:'POST', body:data}); }
