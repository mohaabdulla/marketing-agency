export async function agencyApi(path, options = {}) {
  const response = await fetch('/api/agency' + path, {
    ...options,
    headers: options.body instanceof FormData ? options.headers : {'Content-Type':'application/json',...options.headers},
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = data.detail;
    const text = Array.isArray(detail) ? detail.map(x => `${x.loc?.join('.')}: ${x.msg}`).join('; ')
      : typeof detail === 'object' ? `${detail.message || 'Request failed'} (${detail.trace_id || response.status})`
      : detail || `Request failed (${response.status})`;
    const error = new Error(text); error.status = response.status; throw error;
  }
  return data;
}
export const agencyPost = (path,body={}) => agencyApi(path,{method:'POST',body:JSON.stringify(body)});
export const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const human = key => key.replaceAll('_',' ').replace(/\b\w/g,c=>c.toUpperCase());
