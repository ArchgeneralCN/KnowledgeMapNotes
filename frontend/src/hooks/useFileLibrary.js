import { useCallback, useEffect, useRef, useState } from 'react';
import api, { encodePathSegment, getApiErrorMessage } from '../api/client.js';
import { normalizeFile, PROCESSING_STATUSES } from '../lib/file.js';

export default function useFileLibrary({
  noteType,
  useImg2txt,
  chunkMaxTokens,
  chunkMinTokens,
  communityMinSizeMode,
  communityMinSize,
  communityAutoPercent,
  customPrompts,
  toast,
}) {
  const [files, setFiles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const timers = useRef(new Map());

  const stopPolling = useCallback((filename) => {
    const timer = timers.current.get(filename);
    if (timer) window.clearTimeout(timer);
    timers.current.delete(filename);
  }, []);

  const patchFile = useCallback((filename, patch) => {
    setFiles((current) => current.map((file) => file.name === filename ? { ...file, ...patch } : file));
  }, []);

  const pollFile = useCallback((filename) => {
    stopPolling(filename);
    const schedule = (run, delay = 3000) => {
      timers.current.set(filename, window.setTimeout(run, delay));
    };
    const run = async () => {
      try {
        const { data } = await api.get(`/processing-status/${encodePathSegment(filename)}`);
        const normalized = normalizeFile({ ...data, filename });
        patchFile(filename, normalized);
        if (PROCESSING_STATUSES.includes(normalized.status)) {
          schedule(run);
        } else {
          stopPolling(filename);
          if (normalized.status === 'completed') toast(`“${filename}”已完成处理`, 'success');
        }
      } catch (error) {
        // A refresh can briefly race backend startup or status persistence.
        // Keep the last known processing state and retry instead of presenting
        // a transient transport failure as a failed document job.
        patchFile(filename, {
          displayStatus: error?.response?.status === 404 ? '等待处理状态' : '正在重新连接',
          errorMessage: '',
        });
        schedule(run, error?.response?.status === 404 ? 3000 : 5000);
      }
    };
    run();
  }, [patchFile, stopPolling, toast]);

  const refresh = useCallback(async ({ quiet = false } = {}) => {
    if (!quiet) setLoading(true);
    try {
      const { data } = await api.get('/list-files');
      const next = Array.isArray(data?.files) ? data.files.map(normalizeFile) : [];
      setFiles(next);
      next.filter((file) => PROCESSING_STATUSES.includes(file.status)).forEach((file) => pollFile(file.name));
    } catch (error) {
      toast(getApiErrorMessage(error, '无法读取文件库'), 'error');
    } finally {
      setLoading(false);
    }
  }, [pollFile, toast]);

  useEffect(() => {
    refresh();
    const activeTimers = timers.current;
    return () => activeTimers.forEach((timer) => window.clearTimeout(timer));
  }, [refresh]);

  const upload = useCallback(async (fileList) => {
    const selected = Array.from(fileList || []);
    if (!selected.length) return;
    setUploading(true);
    for (const rawFile of selected) {
      const isTransferPackage = rawFile.name.toLowerCase().endsWith('.kmn.zip');
      try {
        const supportedSource = /\.(txt|md|pdf)$/i.test(rawFile.name);
        if (!isTransferPackage && !supportedSource) {
          throw new Error('仅支持 TXT、Markdown、PDF 或 .kmn.zip 图谱迁移包');
        }
        const existing = files.find((item) => item.name.toLowerCase() === rawFile.name.toLowerCase());
        if (!isTransferPackage && existing && existing.status !== 'error') {
          const accepted = window.confirm(`“${rawFile.name}”已存在。继续将对原文与图谱执行增量更新。`);
          if (!accepted) continue;
        }
        if (!isTransferPackage) await api.post('/ai-settings/validate');

        const optimistic = normalizeFile({ filename: rawFile.name, status: existing ? 'updating' : 'uploading' });
        setFiles((current) => {
          const withoutOld = current.filter((item) => item.name !== rawFile.name);
          return [optimistic, ...withoutOld];
        });

        const form = new FormData();
        form.append('file', rawFile);
        form.append('noteType', noteType);
        form.append('use_img2txt', String(useImg2txt));
        form.append('chunkMaxTokens', String(chunkMaxTokens));
        form.append('chunkMinTokens', String(chunkMinTokens));
        form.append('communityMinSizeMode', communityMinSizeMode);
        form.append('communityMinSize', String(communityMinSize));
        form.append('communityAutoPercent', String(communityAutoPercent));
        if (noteType === 'custom') {
          form.append('entityPrompt', customPrompts.entityExtraction || '');
          form.append('relationshipPrompt', customPrompts.relationshipExtraction || '');
          form.append('fusionPrompt', customPrompts.knowledgeFusion || '');
        }
        const { data } = await api.post('/upload', form, {
          onUploadProgress: (event) => {
            if (!event.total) return;
            patchFile(rawFile.name, { percentage: Math.round((event.loaded / event.total) * 12) });
          },
        });
        if (isTransferPackage) {
          const importedName = data.filename || rawFile.name.replace(/\.kmn\.zip$/i, '.txt');
          const importedFile = normalizeFile({
            ...data,
            filename: importedName,
            status: data.status || 'importing',
            display_status: data.display_status || '迁移包导入中',
            percentage: data.percentage ?? 95,
          });
          setFiles((current) => [
            importedFile,
            ...current.filter((item) => item.name !== rawFile.name && item.name !== importedName),
          ]);
          if (PROCESSING_STATUSES.includes(importedFile.status)) {
            pollFile(importedName);
            toast(data.message || `“${importedName}”正在导入`);
          } else {
            toast(data.message || `“${importedName}”已导入`, 'success');
          }
          continue;
        }

        const nextStatus = data.status || (data.is_update ? 'updating' : 'processing');
        patchFile(rawFile.name, {
          status: nextStatus,
          displayStatus: data.display_status,
          isUpdate: Boolean(data.is_update),
          percentage: 12,
        });
        toast(data.message || `“${rawFile.name}”已开始处理`, 'success');
        pollFile(rawFile.name);
      } catch (error) {
        if (isTransferPackage) {
          setFiles((current) => current.filter((item) => item.name !== rawFile.name));
          refresh({ quiet: true });
        } else {
          patchFile(rawFile.name, { status: 'error', displayStatus: '上传失败', errorMessage: getApiErrorMessage(error) });
        }
        toast(getApiErrorMessage(error, `“${rawFile.name}”导入失败`), 'error');
      }
    }
    setUploading(false);
  }, [chunkMaxTokens, chunkMinTokens, communityAutoPercent, communityMinSize, communityMinSizeMode, customPrompts, files, noteType, patchFile, pollFile, refresh, toast, useImg2txt]);

  const pause = useCallback(async (file) => {
    try {
      patchFile(file.name, { status: 'pausing', displayStatus: '正在安全暂停' });
      await api.post(`/pause-processing/${encodePathSegment(file.name)}`);
      pollFile(file.name);
      toast('暂停请求已提交');
    } catch (error) { toast(getApiErrorMessage(error, '暂停失败'), 'error'); refresh({ quiet: true }); }
  }, [patchFile, pollFile, refresh, toast]);

  const resume = useCallback(async (file) => {
    try {
      await api.post(`/resume-processing/${encodePathSegment(file.name)}`);
      patchFile(file.name, { status: 'resuming', displayStatus: '继续处理中' });
      pollFile(file.name);
    } catch (error) { toast(getApiErrorMessage(error, '继续处理失败'), 'error'); }
  }, [patchFile, pollFile, toast]);

  const remove = useCallback(async (file) => {
    try {
      await api.delete(`/delete/${encodePathSegment(file.name)}`);
      stopPolling(file.name);
      setFiles((current) => current.filter((item) => item.name !== file.name));
      localStorage.removeItem(`chat_${file.name}`);
      localStorage.removeItem(`kg_${file.name}`);
      toast('文件及关联数据已删除', 'success');
    } catch (error) { toast(getApiErrorMessage(error, '删除失败'), 'error'); }
  }, [stopPolling, toast]);

  const clearHistory = useCallback(async (file) => {
    try {
      await api.delete(`/rag-history/${encodePathSegment(file.name)}`);
      localStorage.removeItem(`chat_${file.name}`);
      toast('该文件的问答历史已清除', 'success');
    } catch (error) { toast(getApiErrorMessage(error, '清除失败'), 'error'); }
  }, [toast]);

  const redraw = useCallback(async (file, renderer = 'pyvis') => {
    try {
      patchFile(file.name, { status: 'redrawing', displayStatus: '正在重绘图谱' });
      const { data } = await api.post(
        `/redraw-graph/${encodePathSegment(file.name)}`,
        null,
        {
          params: {
            renderer,
            community_min_size_mode: communityMinSizeMode,
            community_min_size: communityMinSize,
            community_auto_percent: communityAutoPercent,
          },
        },
      );
      await refresh({ quiet: true });
      patchFile(file.name, { graphRedrawnAt: Date.now() });
      toast(data?.message || `${renderer === 'sigma' ? 'Sigma' : 'PyVis'} 图谱已重绘`, 'success');
      return data;
    } catch (error) { toast(getApiErrorMessage(error, '重绘失败'), 'error'); refresh({ quiet: true }); }
  }, [communityAutoPercent, communityMinSize, communityMinSizeMode, patchFile, refresh, toast]);

  const applyDocument = useCallback(async (file) => {
    try {
      await api.post(`/update-document/${encodePathSegment(file.name)}`);
      patchFile(file.name, { status: 'updating', displayStatus: '增量更新中' });
      pollFile(file.name);
    } catch (error) { toast(getApiErrorMessage(error, '应用文档修改失败'), 'error'); }
  }, [patchFile, pollFile, toast]);

  return { files, setFiles, loading, uploading, refresh, upload, pause, resume, remove, clearHistory, redraw, applyDocument, patchFile };
}
