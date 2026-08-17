import http from './http'

export const trainingApi = {
  agents: () => http.get('/training/agents'),
  agentDetail: (id) => http.get(`/training/agents/${id}`),
  startScenario: (id) => http.post(`/training/scenarios/${id}/start`),
  command: (sid, command) => http.post(`/training/sandbox/${sid}/command`, { command }),
  submit: (id) => http.post(`/training/scenarios/${id}/submit`),
  sessions: () => http.get('/training/sandbox/sessions'),
  ranking: () => http.get('/training/ranking'),
  stats: () => http.get('/training/stats'),
  badges: () => http.get('/training/badges'),

  // 课程管理（manager/admin）——AI 生成耗时较长，覆盖全局 20s 超时
  generateCourse: (topic) => http.post('/training/manage/generate', { topic }, { timeout: 120000 }),
  manageCourses: () => http.get('/training/manage/courses'),
  manageCourseDetail: (id) => http.get(`/training/manage/courses/${id}`),
  createCourse: (data) => http.post('/training/manage/courses', data),
  updateCourse: (id, data) => http.put(`/training/manage/courses/${id}`, data),
  deleteCourse: (id) => http.delete(`/training/manage/courses/${id}`),
  publishCourse: (id) => http.post(`/training/manage/courses/${id}/publish`),
  unpublishCourse: (id) => http.post(`/training/manage/courses/${id}/unpublish`),
  addScenario: (courseId, data) => http.post(`/training/manage/courses/${courseId}/scenarios`, data),
  updateScenario: (scenarioId, data) => http.put(`/training/manage/scenarios/${scenarioId}`, data),
  deleteScenario: (scenarioId) => http.delete(`/training/manage/scenarios/${scenarioId}`)
}
