export const API_BASE = import.meta.env.DEV
  ? 'http://localhost:8000'
  : '';

export const ENDPOINTS = {
  chat: `${API_BASE}/api/chat`,
  chatStream: `${API_BASE}/api/chat/stream`,
  generate: `${API_BASE}/api/generate`,
  generateStream: `${API_BASE}/api/generate/stream`,
  search: `${API_BASE}/api/search`,
  correct: `${API_BASE}/api/correct`,
  preview: `${API_BASE}/api/preview`,
  download: `${API_BASE}/api/download`,
  health: `${API_BASE}/api/health`,
  appEnv: `${API_BASE}/api/app/env`,
  modelsState: `${API_BASE}/api/models/state`,
  login: `${API_BASE}/api/auth/login`,
  register: `${API_BASE}/api/auth/register`,
  me: `${API_BASE}/api/auth/me`,
  sessions: `${API_BASE}/api/sessions`,
  upload: `${API_BASE}/api/upload`,
  assets: `${API_BASE}/api/assets`,
  finetuneStatus: `${API_BASE}/api/finetune/status`,
  finetuneDataset: `${API_BASE}/api/finetune/dataset`,
  finetuneTrain: `${API_BASE}/api/finetune/train`,
  finetuneCancel: `${API_BASE}/api/finetune/cancel`,
  finetuneRetrain: `${API_BASE}/api/finetune/retrain`,
  finetunePipeline: `${API_BASE}/api/finetune/pipeline`,
  finetuneStats: `${API_BASE}/api/finetune/dataset/stats`,
  finetuneModels: `${API_BASE}/api/finetune/models`,
  workspaceOpen: `${API_BASE}/api/workspace/open`,
};

export const ASSETS_BASE = `${API_BASE}/uploads`;
