
export async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    credentials: 'same-origin',
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
  })

  const data = await response.json().catch(() => null)

  if (!response.ok) {
    throw new Error(
      data?.detail || `Request failed: ${response.status}`
    )
  }

  return data
}

export const authApi = {
  login: (email, password) =>
    api('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    }),

  me: () => api('/auth/me'),

  logout: () =>
    api('/auth/logout', { method: 'POST' }),
}

export const appointmentApi = {
  mine: () => api('/my/appointments'),
}
