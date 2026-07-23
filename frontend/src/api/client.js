import axios from 'axios';

const baseURL = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/$/, '');

const api = axios.create({ baseURL });

export const apiUrl = (path) => `${baseURL}/${path.replace(/^\//, '')}`;
export const encodePathSegment = (value) => encodeURIComponent(String(value));

const formatDetail = (detail) => {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail
      .map(item => typeof item === 'string' ? item : item?.msg)
      .filter(Boolean)
      .join('；');
  }
  if (detail && typeof detail === 'object') return detail.msg || '';
  return '';
};

const parseJsonMessage = (message) => {
  if (typeof message !== 'string') return null;
  try {
    return JSON.parse(message);
  } catch {
    return null;
  }
};

export const getApiErrorMessage = (error, fallback = '请求失败') => {
  const data = error?.response?.data;
  const uploadErrorData = parseJsonMessage(error?.message);
  return formatDetail(data?.detail)
    || formatDetail(data?.error)
    || formatDetail(data?.message)
    || formatDetail(uploadErrorData?.detail)
    || formatDetail(uploadErrorData?.error)
    || formatDetail(uploadErrorData?.message)
    || (error?.response ? fallback : error?.message)
    || fallback;
};

export default api;
