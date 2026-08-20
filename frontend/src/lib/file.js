export const PROCESSING_STATUSES = ['uploading', 'importing', 'processing', 'updating', 'resuming', 'pausing', 'redrawing'];
export const TERMINAL_STATUSES = ['completed', 'paused', 'interrupted', 'error'];

const STAGE_KEYS = ['entity_extraction', 'relationship_extraction', 'knowledge_fusion'];

function normalizeStage(stage, key) {
  const source = stage || {};
  const completed = Number(source.completed ?? 0);
  const total = Number(source.total ?? 0);
  return {
    completed: Number.isFinite(completed) ? completed : 0,
    total: Number.isFinite(total) ? total : 0,
    remaining: source.remaining == null ? null : Number(source.remaining),
    percentage: Number(source.percentage ?? (total ? completed * 100 / total : 0)),
    latestItemSeconds: source.latest_item_seconds ?? source.latestItemSeconds,
    averageItemSeconds: source.average_item_seconds ?? source.averageItemSeconds,
    cumulativeSeconds: Number(source.cumulative_seconds ?? source.cumulativeSeconds ?? 0),
    sampleCount: Number(source.sample_count ?? source.sampleCount ?? 0),
    itemsPerMinute: source.items_per_minute ?? source.itemsPerMinute,
    estimatedRemainingSeconds: source.estimated_remaining_seconds ?? source.estimatedRemainingSeconds,
    unit: source.unit || (key === 'knowledge_fusion' ? '实体对' : '文本块'),
    totalKnown: source.total_known ?? source.totalKnown ?? false,
  };
}

export const statusMeta = {
  uploading: { label: '上传中', tone: 'info' },
  importing: { label: '迁移包导入中', tone: 'info' },
  processing: { label: '处理中', tone: 'info' },
  updating: { label: '增量更新中', tone: 'warning' },
  resuming: { label: '继续处理中', tone: 'info' },
  pausing: { label: '暂停中', tone: 'warning' },
  redrawing: { label: '重绘图谱中', tone: 'warning' },
  paused: { label: '已暂停', tone: 'warning' },
  interrupted: { label: '部分完成', tone: 'warning' },
  completed: { label: '已完成', tone: 'success' },
  error: { label: '处理失败', tone: 'danger' },
};

export function normalizeFile(file) {
  const status = file.status || 'completed';
  return {
    name: file.filename || file.name || String(file),
    status,
    displayStatus: file.display_status || statusMeta[status]?.label || status,
    size: file.size || 0,
    percentage: Number(file.percentage ?? (status === 'completed' ? 100 : 0)),
    processingStage: file.processing_stage || file.processingStage || '',
    stageProgress: STAGE_KEYS.reduce((result, key) => {
      result[key] = normalizeStage(
        (file.stage_progress || file.stageProgress || {})[key],
        key,
      );
      return result;
    }, {}),
    overallPercentage: Number(file.overall_percentage ?? file.overallPercentage ?? file.percentage ?? 0),
    overallSpeedPercentPerMinute: file.overall_speed_percent_per_minute ?? file.overallSpeedPercentPerMinute,
    estimatedTotalRemainingSeconds: file.estimated_total_remaining_seconds ?? file.estimatedTotalRemainingSeconds ?? file.estimated_remaining_seconds,
    completedChunks: Number(file.completed_chunks || file.completedChunks || 0),
    totalChunks: Number(file.total_chunks || file.totalChunks || 0),
    latestChunkSeconds: file.latest_chunk_seconds ?? file.latestChunkSeconds,
    estimatedRemainingSeconds: file.estimated_remaining_seconds ?? file.estimatedRemainingSeconds,
    partialAvailable: Boolean(file.partial_available ?? file.partialAvailable),
    resumable: Boolean(file.resumable),
    errorMessage: file.error_message || file.errorMessage || '',
    documentModified: Boolean(file.document_modified ?? file.documentModified),
    documentRevision: Number(file.document_revision || file.documentRevision || 0),
    characterCount: Number(file.character_count ?? file.characterCount ?? 0),
    lastEditedAt: file.last_edited_at || file.lastEditedAt || '',
    isUpdate: Boolean(file.is_update ?? file.isUpdate),
  };
}

export const canViewFile = (file) => file?.status === 'completed'
  || (['paused', 'interrupted'].includes(file?.status) && file?.partialAvailable);

export const graphNameOf = (filename = '') => {
  const index = filename.lastIndexOf('.');
  return index > 0 ? filename.slice(0, index) : filename;
};

export const fileExtension = (filename = '') => {
  if (filename.toLowerCase().endsWith('.kmn.zip')) return 'KMN';
  return filename.split('.').pop()?.toUpperCase() || '文件';
};

export function formatRemainingTime(seconds) {
  if (!Number.isFinite(Number(seconds))) return '';
  const value = Math.max(0, Number(seconds));
  if (value < 60) return `约 ${Math.ceil(value)} 秒`;
  if (value < 3600) return `约 ${Math.ceil(value / 60)} 分钟`;
  return `约 ${(value / 3600).toFixed(1)} 小时`;
}
