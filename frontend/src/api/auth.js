import http from './http'

export const authApi = {
  login: (data) => http.post('/auth/login', data),
  logout: () => http.post('/auth/logout', {}),
  me: () => http.get('/users/me'),
  changePassword: (data) => http.post('/auth/change-password', data),
  captcha: () => http.get('/auth/captcha'),
  mfaSetup: (mfa_token) => http.post('/auth/mfa/setup', { mfa_token }),
  mfaConfirm: (mfa_token, code) => http.post('/auth/mfa/confirm', { mfa_token, code }),
  mfaVerify: (mfa_token, code) => http.post('/auth/mfa/verify', { mfa_token, code }),
  mfaBind: () => http.post('/auth/mfa/bind', {}),
  mfaBindConfirm: (code) => http.post('/auth/mfa/bind-confirm', { code }),
  mfaDisable: (code) => http.post('/auth/mfa/disable', { code }),
  sessions: () => http.get('/auth/sessions'),
  revokeSession: (id) => http.post(`/auth/sessions/${id}/revoke`)
}
