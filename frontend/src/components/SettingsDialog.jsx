import { useEffect, useMemo, useState } from 'react';
import { Bot, Check, FlaskConical, Network, Palette, RefreshCw, RotateCcw, SlidersHorizontal } from 'lucide-react';
import api, { getApiErrorMessage } from '../api/client.js';
import Modal from './ui/Modal.jsx';

const emptyAi = {
  baseUrl: '', apiKey: '', modelName: '', temperature: 0, enableThinking: false, stream: false,
  apiKeyConfigured: false, apiKeyHint: '', fallbackEnabled: false, fallbackBaseUrl: '',
  fallbackApiKey: '', fallbackModelName: '', fallbackStream: false, fallbackApiKeyConfigured: false, fallbackApiKeyHint: '',
  models: [], fallbackModels: [],
};

export default function SettingsDialog({ open, onClose, settings, onSettings, toast }) {
  const [tab, setTab] = useState('ai');
  const [ai, setAi] = useState(emptyAi);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [defaults, setDefaults] = useState(null);
  const [modelFetching, setModelFetching] = useState('');
  const [modelErrors, setModelErrors] = useState({});

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    api.get('/ai-settings').then(({ data }) => setAi({
      baseUrl: data.base_url || '', apiKey: '', modelName: data.model_name || '',
      temperature: Number(data.temperature ?? 0), enableThinking: Boolean(data.enable_thinking), stream: Boolean(data.stream),
      apiKeyConfigured: Boolean(data.api_key_configured), apiKeyHint: data.api_key_hint || '',
      fallbackEnabled: Boolean(data.fallback_enabled), fallbackBaseUrl: data.fallback_base_url || '',
      fallbackApiKey: '', fallbackModelName: data.fallback_model_name || '', fallbackStream: Boolean(data.fallback_stream),
      fallbackApiKeyConfigured: Boolean(data.fallback_api_key_configured), fallbackApiKeyHint: data.fallback_api_key_hint || '',
      models: [], fallbackModels: [],
    })).catch((error) => toast(getApiErrorMessage(error, '无法读取 AI 配置'), 'error')).finally(() => setLoading(false));
  }, [open, toast]);

  const loadDefaults = async (force = false) => {
    try {
      let values = defaults;
      if (!values) {
        const { data } = await api.get('/processing-prompts/defaults');
        values = { entityExtraction: data.entity_extraction || '', relationshipExtraction: data.relationship_extraction || '', knowledgeFusion: data.knowledge_fusion || '' };
        setDefaults(values);
      }
      onSettings({ customPrompts: force ? values : {
        entityExtraction: settings.customPrompts.entityExtraction || values.entityExtraction,
        relationshipExtraction: settings.customPrompts.relationshipExtraction || values.relationshipExtraction,
        knowledgeFusion: settings.customPrompts.knowledgeFusion || values.knowledgeFusion,
      } });
      if (force) toast('已恢复通用提示词', 'success');
    } catch (error) { toast(getApiErrorMessage(error, '获取默认提示词失败'), 'error'); }
  };

  useEffect(() => {
    if (open && settings.noteType === 'custom') loadDefaults();
    // Defaults are fetched only when custom processing is active.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, settings.noteType]);

  const payload = useMemo(() => ({
    base_url: ai.baseUrl.trim(), api_key: ai.apiKey.trim() || null, model_name: ai.modelName.trim(),
    temperature: Number(ai.temperature), enable_thinking: Boolean(ai.enableThinking), stream: Boolean(ai.stream),
    fallback_enabled: Boolean(ai.fallbackEnabled), fallback_base_url: ai.fallbackBaseUrl.trim() || null,
    fallback_api_key: ai.fallbackApiKey.trim() || null, fallback_model_name: ai.fallbackModelName.trim() || null,
    fallback_stream: Boolean(ai.fallbackStream),
  }), [ai]);

  const validate = () => {
    if (!payload.base_url || !payload.model_name || (!payload.api_key && !ai.apiKeyConfigured)) return '请完整填写主 AI 的 Base URL、模型名和 API Key';
    if (ai.fallbackEnabled && (!payload.fallback_base_url || !payload.fallback_model_name || (!payload.fallback_api_key && !ai.fallbackApiKeyConfigured))) return '启用备用 AI 后，请完整填写其连接信息';
    return '';
  };
  const test = async () => {
    const message = validate(); if (message) return toast(message, 'error');
    setTesting(true);
    try { const { data } = await api.post('/ai-settings/test', payload); toast(`${data.message || '连接正常'}${data.latency_ms ? ` · ${data.latency_ms} ms` : ''}`, 'success'); }
    catch (error) { toast(getApiErrorMessage(error, '连接测试失败'), 'error'); }
    finally { setTesting(false); }
  };
  const save = async () => {
    const message = validate(); if (message) return toast(message, 'error');
    setSaving(true);
    try { await api.put('/ai-settings', payload); toast('AI 配置已更新', 'success'); onClose(); }
    catch (error) { toast(getApiErrorMessage(error, '保存 AI 配置失败'), 'error'); }
    finally { setSaving(false); }
  };

  const fetchModels = async (kind) => {
    const isFallback = kind === 'fallback';
    const baseUrl = (isFallback ? ai.fallbackBaseUrl : ai.baseUrl).trim();
    const apiKey = (isFallback ? ai.fallbackApiKey : ai.apiKey).trim();
    if (!baseUrl) return toast('请先填写 Base URL', 'error');
    setModelFetching(kind);
    setModelErrors((current) => ({ ...current, [kind]: '' }));
    try {
      const { data } = await api.post('/ai-models', { base_url: baseUrl, api_key: apiKey || null });
      const models = Array.isArray(data.models) ? data.models : [];
      setAi((current) => ({ ...current, [isFallback ? 'fallbackModels' : 'models']: models }));
      if (!models.length) setModelErrors((current) => ({ ...current, [kind]: '服务未返回可用模型，请手动输入' }));
      else toast(`已获取 ${models.length} 个模型`, 'success');
    } catch (error) {
      setModelErrors((current) => ({ ...current, [kind]: getApiErrorMessage(error, '模型列表获取失败') }));
    } finally {
      setModelFetching('');
    }
  };

  const tabs = [{ id: 'ai', label: 'AI 模型', icon: Bot }, { id: 'graph', label: '图谱构建', icon: Network }, { id: 'rag', label: '问答与外观', icon: Palette }];
  return (
    <Modal open={open} onClose={onClose} title="工作台设置" eyebrow="PREFERENCES" wide footer={tab === 'ai' && <><button className="button secondary" onClick={test} disabled={testing || loading}><FlaskConical size={16} />{testing ? '正在测试' : '测试连接'}</button><button className="button primary" onClick={save} disabled={saving || loading}><Check size={16} />{saving ? '正在保存' : '保存 AI 配置'}</button></>}>
      <div className="settings-layout">
        <nav className="settings-nav">{tabs.map(({ id, label, icon: Icon }) => <button key={id} className={tab === id ? 'active' : ''} onClick={() => setTab(id)}><Icon size={17} />{label}</button>)}</nav>
        <div className="settings-content">
          {tab === 'ai' && <AiSettings ai={ai} setAi={setAi} loading={loading} fetchModels={fetchModels} modelFetching={modelFetching} modelErrors={modelErrors} />}
          {tab === 'graph' && <GraphSettings settings={settings} onSettings={onSettings} onDefaults={() => loadDefaults(true)} />}
          {tab === 'rag' && <RagAppearance settings={settings} onSettings={onSettings} />}
        </div>
      </div>
    </Modal>
  );
}

function AiSettings({ ai, setAi, loading, fetchModels, modelFetching, modelErrors }) {
  const change = (key, value) => setAi((current) => ({
    ...current,
    [key]: value,
    ...(key === 'baseUrl' || key === 'apiKey' ? { models: [] } : {}),
    ...(key === 'fallbackBaseUrl' || key === 'fallbackApiKey' ? { fallbackModels: [] } : {}),
  }));
  if (loading) return <div className="settings-loading">正在读取 AI 配置…</div>;
  return <>
    <SectionTitle icon={Bot} title="主 AI" copy="用于实体抽取、知识融合与 RAG 回答。" />
    <div className="form-grid"><Field label="Base URL"><input value={ai.baseUrl} onChange={(e) => change('baseUrl', e.target.value)} placeholder="https://api.openai.com/v1" /></Field><ModelField label="模型名称" value={ai.modelName} options={ai.models} onChange={(value) => change('modelName', value)} onFetch={() => fetchModels('primary')} fetching={modelFetching === 'primary'} error={modelErrors.primary} placeholder="gpt-4.1-mini" /><Field label="API Key" full><input type="password" value={ai.apiKey} onChange={(e) => change('apiKey', e.target.value)} placeholder={ai.apiKeyConfigured ? `已配置${ai.apiKeyHint ? `（${ai.apiKeyHint}）` : ''}，留空保持不变` : '请输入 API Key'} /></Field><Field label={`温度 ${Number(ai.temperature).toFixed(1)}`} full><input type="range" min="0" max="2" step="0.1" value={ai.temperature} onChange={(e) => change('temperature', Number(e.target.value))} /></Field></div>
    <div className="toggle-list"><Toggle checked={ai.enableThinking} onChange={(value) => change('enableThinking', value)} label="思考模式" copy="在模型支持时请求更完整的推理过程。" /><Toggle checked={ai.stream} onChange={(value) => change('stream', value)} label="流式 API" copy="文件处理中的实体、关系与融合请求使用流式响应。" /></div>
    <div className="settings-divider" />
    <SectionTitle icon={SlidersHorizontal} title="备用 AI" copy="主请求失败或输出格式异常时自动接管。" action={<Toggle compact checked={ai.fallbackEnabled} onChange={(value) => change('fallbackEnabled', value)} />} />
    {ai.fallbackEnabled && <><div className="form-grid"><Field label="备用 Base URL"><input value={ai.fallbackBaseUrl} onChange={(e) => change('fallbackBaseUrl', e.target.value)} /></Field><ModelField label="备用模型" value={ai.fallbackModelName} options={ai.fallbackModels} onChange={(value) => change('fallbackModelName', value)} onFetch={() => fetchModels('fallback')} fetching={modelFetching === 'fallback'} error={modelErrors.fallback} /><Field label="备用 API Key" full><input type="password" value={ai.fallbackApiKey} onChange={(e) => change('fallbackApiKey', e.target.value)} placeholder={ai.fallbackApiKeyConfigured ? '已配置，留空保持不变' : '请输入备用 API Key'} /></Field></div><Toggle checked={ai.fallbackStream} onChange={(value) => change('fallbackStream', value)} label="备用模型使用流式 API" copy="仅在请求切换到备用模型时生效。" /></>}
  </>;
}

function ModelField({ label, value, options, onChange, onFetch, fetching, error, placeholder }) {
  const choices = options.includes(value) || !value ? options : [value, ...options];
  return <label className="field model-field"><span>{label}</span><div className="model-picker">{options.length > 0 ? <select value={value} onChange={(event) => onChange(event.target.value)}><option value="">选择模型</option>{choices.map((model) => <option key={model} value={model}>{model}</option>)}</select> : <input value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} />}<button type="button" className="icon-button" onClick={onFetch} disabled={fetching} aria-label="获取模型列表" title="获取模型列表">{fetching ? <RefreshCw className="spin" size={14} /> : <RefreshCw size={14} />}</button></div>{error && <small className="model-picker-error">{error}</small>}</label>;
}

function GraphSettings({ settings, onSettings, onDefaults }) {
  const updatePrompt = (key, value) => onSettings({ customPrompts: { ...settings.customPrompts, [key]: value } });
  const updateChunkMax = (value) => {
    const nextMax = Math.max(128, Math.min(32768, Number(value) || 128));
    onSettings({ chunkMaxTokens: nextMax, chunkMinTokens: Math.min(settings.chunkMinTokens, nextMax - 1) });
  };
  const updateChunkMin = (value) => onSettings({ chunkMinTokens: Math.max(1, Math.min(settings.chunkMaxTokens - 1, Number(value) || 1)) });
  const updateCommunityMinSize = (value) => onSettings({ communityMinSize: Math.max(1, Math.min(1000000, Number(value) || 1)) });
  const updateCommunityAutoPercent = (value) => onSettings({ communityAutoPercent: Math.max(1, Math.min(100, Number(value) || 1)) });
  return <><SectionTitle icon={Network} title="图谱构建" copy="控制模型读取文档和抽取知识的方式。" />
    <Field label="图谱绘制方式"><div className="segmented graph-renderer-options">{[['pyvis', 'PyVis'], ['sigma', 'Sigma.js']].map(([value, label]) => <button type="button" key={value} className={settings.graphRenderer === value ? 'active' : ''} onClick={() => onSettings({ graphRenderer: value })}>{label}</button>)}</div></Field>
    {settings.graphRenderer === 'sigma' && <Field label="Sigma 默认视图"><div className="segmented graph-renderer-options">{[['full', '全量图'], ['communities', '社区总览']].map(([value, label]) => <button type="button" key={value} className={settings.sigmaViewMode === value ? 'active' : ''} onClick={() => onSettings({ sigmaViewMode: value })}>{label}</button>)}</div></Field>}
    <Field label="社区最小规模"><div className="segmented graph-renderer-options">{[['custom', '自定义'], ['auto', '自动计算']].map(([value, label]) => <button type="button" key={value} className={settings.communityMinSizeMode === value ? 'active' : ''} onClick={() => onSettings({ communityMinSizeMode: value })}>{label}</button>)}</div></Field>
    {settings.communityMinSizeMode === 'custom'
      ? <Field label="最小社区节点数"><IntegerInput min={1} max={1000000} step={1} value={settings.communityMinSize} onCommit={updateCommunityMinSize} /></Field>
      : <Field label="自动计算比例"><div className="number-with-unit"><IntegerInput min={1} max={100} step={1} value={settings.communityAutoPercent} onCommit={updateCommunityAutoPercent} /><span>%</span></div></Field>}
    <Field label="笔记类型"><div className="segmented">{[['general', '通用'], ['story', '故事'], ['custom', '自定义']].map(([value, label]) => <button key={value} className={settings.noteType === value ? 'active' : ''} onClick={() => onSettings({ noteType: value })}>{label}</button>)}</div></Field>
    {settings.noteType === 'custom' && <div className="prompt-fields"><div className="prompt-heading"><span>自定义提示词</span><button className="button text" onClick={onDefaults}><RotateCcw size={14} />恢复通用提示词</button></div><Field label="实体抽取"><textarea maxLength={30000} value={settings.customPrompts.entityExtraction} onChange={(e) => updatePrompt('entityExtraction', e.target.value)} /></Field><Field label="关系抽取"><textarea maxLength={30000} value={settings.customPrompts.relationshipExtraction} onChange={(e) => updatePrompt('relationshipExtraction', e.target.value)} /></Field><Field label="知识融合"><textarea maxLength={30000} value={settings.customPrompts.knowledgeFusion} onChange={(e) => updatePrompt('knowledgeFusion', e.target.value)} /></Field></div>}
    <div className="settings-divider" />
    <SectionTitle icon={SlidersHorizontal} title="文档分块" copy="新上传和增量处理会保存本次分块参数，断点恢复继续沿用。" />
    <div className="form-grid"><Field label="每块最大 Token"><IntegerInput min={128} max={32768} step={64} value={settings.chunkMaxTokens} onCommit={updateChunkMax} /></Field><Field label="每块最小 Token"><IntegerInput min={1} max={settings.chunkMaxTokens - 1} step={32} value={settings.chunkMinTokens} onCommit={updateChunkMin} /></Field></div>
    <Toggle checked={settings.useImg2txt} onChange={(value) => onSettings({ useImg2txt: value })} label="识别 PDF 中的图片内容" copy="适合扫描件或包含截图的 PDF，处理时间会增加。" />
  </>;
}

function RagAppearance({ settings, onSettings }) {
  const themes = [{ id: 'default', label: '雾白', colors: ['#f3f7f5', '#4d7667', '#dca868'] }, { id: 'dark', label: '夜色', colors: ['#17201f', '#78a692', '#d8ac70'] }, { id: 'blue', label: '雨蓝', colors: ['#eff5f8', '#51778f', '#ce8d70'] }, { id: 'green', label: '苔绿', colors: ['#f1f6ed', '#618064', '#d2a06d'] }];
  return <><SectionTitle icon={Palette} title="RAG 与外观" copy="设置会保存在当前浏览器。" />
    <div className="toggle-list"><Toggle checked={settings.streamOutput} onChange={(value) => onSettings({ streamOutput: value })} label="流式输出" copy="边生成边展示回答。" /><Toggle checked={settings.historyContext} onChange={(value) => onSettings({ historyContext: value })} label="携带历史上下文" copy="让新问题继承当前文件的对话语境。" /><Toggle checked={settings.showAllEvidence} onChange={(value) => onSettings({ showAllEvidence: value })} label="展示全部证据高亮" copy="否则仅高亮当前定位对象。" /></div>
    <Field label="主题"><div className="theme-grid">{themes.map((theme) => <button key={theme.id} className={`theme-option ${settings.theme === theme.id ? 'active' : ''}`} onClick={() => onSettings({ theme: theme.id })}><span className="theme-swatches">{theme.colors.map((color) => <i key={color} style={{ background: color }} />)}</span><span>{theme.label}</span>{settings.theme === theme.id && <Check size={14} />}</button>)}</div></Field>
  </>;
}

function SectionTitle({ icon: Icon, title, copy, action }) { return <div className="section-title"><div className="section-icon"><Icon size={18} /></div><div><h3>{title}</h3><p>{copy}</p></div>{action && <div className="section-action">{action}</div>}</div>; }
function Field({ label, children, full = false }) { return <label className={`field ${full ? 'full' : ''}`}><span>{label}</span>{children}</label>; }
function IntegerInput({ value, min, max, step, onCommit }) {
  const [draft, setDraft] = useState(String(value));
  useEffect(() => setDraft(String(value)), [value]);
  const commit = () => {
    const parsed = Number(draft);
    if (!Number.isInteger(parsed)) {
      setDraft(String(value));
      return;
    }
    const normalized = Math.max(min, Math.min(max, parsed));
    setDraft(String(normalized));
    onCommit(normalized);
  };
  return <input type="number" min={min} max={max} step={step} value={draft} onChange={(event) => setDraft(event.target.value)} onBlur={commit} onKeyDown={(event) => { if (event.key === 'Enter') event.currentTarget.blur(); }} />;
}
function Toggle({ checked, onChange, label, copy, compact = false }) { return <label className={`toggle-row ${compact ? 'compact' : ''}`}><span>{label && <strong>{label}</strong>}{copy && <small>{copy}</small>}</span><input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} /><i /></label>; }
