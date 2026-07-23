<script setup>
import {computed, ref, watch} from 'vue'
import SvgIcon from "@/components/SvgIcon/index.vue";
import api, { encodePathSegment, getApiErrorMessage } from "@/api/client";
import { Connection, RefreshLeft } from '@element-plus/icons-vue';
import { ElMessage } from 'element-plus';

const props = defineProps({
  fileListExpand: Boolean,
  enableStreamOutput: Boolean,
  enableHistoryContext: {
    type: Boolean,
    default: true
  },
  noteType: {
    type: String,
    default: "general"
  },
  customPrompts: {
    type: Object,
    default: () => ({
      entityExtraction: '',
      relationshipExtraction: '',
      knowledgeFusion: ''
    })
  },
  useImg2txt: {
    type: Boolean,
    default: false
  }
});
const emits = defineEmits([
  "update:fileListExpand", 
  "closeAll", 
  "update:enableStreamOutput", 
  "update:enableHistoryContext",
  "update:noteType",
  "update:customPrompts",
  "update:useImg2txt"
]);
const fileListExpand = computed({
  get() {
    return props.fileListExpand;
  },
  set(val) {
    emits("update:fileListExpand", val);
  }
});

const enableStreamOutput = computed({
  get() {
    return props.enableStreamOutput;
  },
  set(val) {
    emits("update:enableStreamOutput", val);
  }
});

const enableHistoryContext = computed({
  get() {
    return props.enableHistoryContext;
  },
  set(val) {
    emits("update:enableHistoryContext", val);
  }
});

const noteType = computed({
  get() {
    return props.noteType;
  },
  set(val) {
    emits("update:noteType", val);
  }
});

const useImg2txt = computed({
  get() {
    return props.useImg2txt;
  },
  set(val) {
    emits("update:useImg2txt", val);
  }
});

const menuRef = ref()
const activeIndex = ref("home")
const openSettings = ref(false)
const expandedFileId = ref(null)
const fileEntities = ref({})
const loadingEntities = ref({})
const aiSettingsLoading = ref(false)
const aiSettingsSaving = ref(false)
const aiSettingsTesting = ref(false)
const processingPromptsLoading = ref(false)
const defaultProcessingPrompts = ref(null)
const aiSettings = ref({
  baseUrl: '',
  apiKey: '',
  modelName: '',
  temperature: 0,
  enableThinking: false,
  apiKeyConfigured: false,
  apiKeyHint: ''
})

const apiKeyPlaceholder = computed(() => {
  if (!aiSettings.value.apiKeyConfigured) return '请输入 API Key';
  const hint = aiSettings.value.apiKeyHint ? `（${aiSettings.value.apiKeyHint}）` : '';
  return `已配置${hint}，留空则保持不变`;
});

const loadAiSettings = async () => {
  aiSettingsLoading.value = true;
  try {
    const { data } = await api.get('/ai-settings');
    aiSettings.value = {
      baseUrl: data.base_url || '',
      apiKey: '',
      modelName: data.model_name || '',
      temperature: Number(data.temperature ?? 0),
      enableThinking: Boolean(data.enable_thinking),
      apiKeyConfigured: Boolean(data.api_key_configured),
      apiKeyHint: data.api_key_hint || ''
    };
  } catch (error) {
    console.error('获取 AI 配置失败:', error);
    ElMessage.error(getApiErrorMessage(error, '获取 AI 配置失败'));
  } finally {
    aiSettingsLoading.value = false;
  }
};

const getAiSettingsPayload = () => {
  const baseUrl = aiSettings.value.baseUrl.trim();
  const modelName = aiSettings.value.modelName.trim();
  if (!baseUrl || !modelName) {
    ElMessage.warning('请填写 Base URL 和模型名称');
    return null;
  }
  if (!aiSettings.value.apiKey.trim() && !aiSettings.value.apiKeyConfigured) {
    ElMessage.warning('请填写 API Key');
    return null;
  }

  return {
    base_url: baseUrl,
    api_key: aiSettings.value.apiKey.trim() || null,
    model_name: modelName,
    temperature: aiSettings.value.temperature,
    enable_thinking: aiSettings.value.enableThinking
  };
};

const testAiSettings = async () => {
  const payload = getAiSettingsPayload();
  if (!payload) return;

  aiSettingsTesting.value = true;
  try {
    const { data } = await api.post('/ai-settings/test', payload);
    const latency = Number.isFinite(data.latency_ms) ? `（${data.latency_ms} ms）` : '';
    ElMessage.success(`${data.message || 'AI 连接测试成功'}${latency}`);
  } catch (error) {
    console.error('AI 连接测试失败:', error);
    ElMessage.error(getApiErrorMessage(error, 'AI 连接测试失败'));
  } finally {
    aiSettingsTesting.value = false;
  }
};

const saveAiSettings = async () => {
  const payload = getAiSettingsPayload();
  if (!payload) return;

  aiSettingsSaving.value = true;
  try {
    const { data } = await api.put('/ai-settings', payload);
    aiSettings.value.apiKey = '';
    aiSettings.value.apiKeyConfigured = Boolean(data.api_key_configured);
    aiSettings.value.apiKeyHint = data.api_key_hint || '';
    aiSettings.value.baseUrl = data.base_url;
    aiSettings.value.modelName = data.model_name;
    aiSettings.value.temperature = Number(data.temperature);
    aiSettings.value.enableThinking = Boolean(data.enable_thinking);
    ElMessage.success('AI 配置已更新');
    openSettings.value = false;
  } catch (error) {
    console.error('更新 AI 配置失败:', error);
    ElMessage.error(getApiErrorMessage(error, '更新 AI 配置失败'));
  } finally {
    aiSettingsSaving.value = false;
  }
};

const updateCustomPrompt = (field, value) => {
  emits('update:customPrompts', {
    ...props.customPrompts,
    [field]: value
  });
};

const loadDefaultProcessingPrompts = async (forceReset = false) => {
  if (processingPromptsLoading.value) return;
  processingPromptsLoading.value = true;
  try {
    if (!defaultProcessingPrompts.value) {
      const { data } = await api.get('/processing-prompts/defaults');
      defaultProcessingPrompts.value = {
        entityExtraction: data.entity_extraction || '',
        relationshipExtraction: data.relationship_extraction || '',
        knowledgeFusion: data.knowledge_fusion || ''
      };
    }

    const defaults = defaultProcessingPrompts.value;
    const current = props.customPrompts || {};
    emits('update:customPrompts', forceReset ? { ...defaults } : {
      entityExtraction: current.entityExtraction?.trim() ? current.entityExtraction : defaults.entityExtraction,
      relationshipExtraction: current.relationshipExtraction?.trim()
        ? current.relationshipExtraction
        : defaults.relationshipExtraction,
      knowledgeFusion: current.knowledgeFusion?.trim() ? current.knowledgeFusion : defaults.knowledgeFusion
    });
    if (forceReset) ElMessage.success('已恢复通用提示词');
  } catch (error) {
    console.error('获取通用提示词失败:', error);
    ElMessage.error(getApiErrorMessage(error, '获取通用提示词失败'));
  } finally {
    processingPromptsLoading.value = false;
  }
};

watch(noteType, value => {
  if (value === 'custom') loadDefaultProcessingPrompts();
});

watch(openSettings, isOpen => {
  if (isOpen) {
    loadAiSettings();
    if (noteType.value === 'custom') loadDefaultProcessingPrompts();
  }
});

const openMenuItem = (index) => {
  activeIndex.value = index;
}
const menuItemSelect = (index) => {
  activeIndex.value = index;
  if (index === "fileList") {
    fileListExpand.value = true;
  } else if (index === "home") {
    fileListExpand.value = false;
    emits("closeAll");
  }
}

const toggleFileExpand = async (file) => {
  if (!file || file.status !== 'completed') return;
  
  if (expandedFileId.value === file.name) {
    expandedFileId.value = null;
    return;
  }
  
  expandedFileId.value = file.name;
  
  if (!fileEntities.value[file.name] && !loadingEntities.value[file.name]) {
    try {
      loadingEntities.value[file.name] = true;
      const response = await api.get(`/file-entities/${encodePathSegment(file.name)}`);
      if (response.data && response.data.entities) {
        fileEntities.value[file.name] = {
          entities: response.data.entities,
          errorMessage: null
        };
      }
    } catch (error) {
      console.error('获取文件实体失败:', error);
      fileEntities.value[file.name] = {
        entities: [],
        errorMessage: error.response?.data?.error || '获取文件实体失败'
      };
    } finally {
      loadingEntities.value[file.name] = false;
    }
  }
}

// 笔记类型选项
const noteTypeOptions = [
  {
    value: 'general',
    label: '通用',
    color: '#409eff' // 蓝色，对应默认主题的主色调
  },
  {
    value: 'story',
    label: '故事',
    color: '#67c23a' // 绿色，使其与通用类型区分
  },
  {
    value: 'custom',
    label: '自定义',
    color: '#e6a23c'
  }
];

// 获取当前选中的笔记类型显示文本和颜色
const selectedNoteTypeLabel = computed(() => {
  const selected = noteTypeOptions.find(item => item.value === noteType.value);
  return selected ? selected.label : '';
});

const selectedNoteTypeColor = computed(() => {
  const selected = noteTypeOptions.find(item => item.value === noteType.value);
  return selected ? selected.color : '';
});

defineExpose({
  openMenuItem,
  expandedFileId,
  fileEntities,
  loadingEntities,
  toggleFileExpand
})
</script>

<template>
  <el-menu class="menu" ref="menuRef" :default-active="activeIndex" @select="menuItemSelect">
    <div class="logo">
      <svg-icon icon-name="logo" size="32px"/>
    </div>
    <el-menu-item index="home">
      <div class="menu-item">
        <svg-icon icon-name="home" size="22px"/>
      </div>
    </el-menu-item>
    <el-menu-item index="fileList">
      <div class="menu-item">
        <svg-icon icon-name="file" size="22px"/>
      </div>
    </el-menu-item>
    <div class="flex-grow"/>
    <el-menu-item @click="openSettings=true">
      <div class="menu-item">
        <svg-icon icon-name="setting" size="24px"/>
      </div>
    </el-menu-item>
  </el-menu>

  <el-dialog 
    v-model="openSettings" 
    width="min(760px, calc(100vw - 24px))"
    top="5vh"
    :lock-scroll="false"
    :close-on-click-modal="false" 
    :show-close="false"
    style="border-radius: 8px"
    class="settings-dialog"
  >
    <template #header>
      <div class="settings-dialog-header">
        <div class="settings-title">设置</div>
        <svg-icon icon-name="close" icon-class="close-icon" size="18px" @click="openSettings=false"/>
      </div>
    </template>
    <template #default>
      <div v-loading="aiSettingsLoading" class="settings-content">
        <div class="settings-section">
          <div class="section-title">AI 模型设置</div>
          <el-form label-position="top" class="ai-settings-form">
            <el-form-item label="Base URL">
              <el-input
                v-model="aiSettings.baseUrl"
                placeholder="https://api.example.com/v1"
                autocomplete="off"
              />
            </el-form-item>
            <el-form-item label="API Key">
              <el-input
                v-model="aiSettings.apiKey"
                type="password"
                show-password
                :placeholder="apiKeyPlaceholder"
                autocomplete="new-password"
              />
            </el-form-item>
            <el-form-item label="模型名称">
              <el-input
                v-model="aiSettings.modelName"
                placeholder="例如：qwen-plus"
                autocomplete="off"
              />
            </el-form-item>
            <div class="ai-settings-row">
              <el-form-item label="温度">
                <el-input-number
                  v-model="aiSettings.temperature"
                  :min="0"
                  :max="2"
                  :step="0.1"
                  :precision="2"
                  controls-position="right"
                />
              </el-form-item>
              <el-form-item label="思考模式">
                <el-switch
                  v-model="aiSettings.enableThinking"
                  active-text="开启"
                  inactive-text="关闭"
                />
              </el-form-item>
            </div>
          </el-form>
        </div>

        <div class="settings-section">
          <div class="section-title">图谱构建设置</div>
          <div class="settings-item">
            <span class="item-label">笔记类型</span>
            <el-select 
              v-model="noteType" 
              placeholder="请选择笔记类型" 
              style="width: 140px"
              popper-class="note-type-dropdown"
            >
              <template #prefix>
                <span class="note-type-dot" :style="{ backgroundColor: selectedNoteTypeColor }"></span>
              </template>
              
              <el-option
                v-for="item in noteTypeOptions"
                :key="item.value"
                :value="item.value"
                :label="item.label"
              >
                <div class="note-type-option-content">
                  <span class="note-type-color-indicator" :style="{ backgroundColor: item.color }"></span>
                  <span class="note-type-label">{{ item.label }}</span>
                </div>
              </el-option>
            </el-select>
          </div>
          <div class="item-description">
            选择不同的笔记类型，AI将根据类型构建相应的知识图谱结构。
          </div>

          <div v-if="noteType === 'custom'" v-loading="processingPromptsLoading" class="custom-prompts-editor">
            <div class="custom-prompts-toolbar">
              <span class="item-label">处理提示词</span>
              <el-button
                text
                size="small"
                :icon="RefreshLeft"
                :disabled="processingPromptsLoading"
                @click="loadDefaultProcessingPrompts(true)"
              >
                恢复通用提示词
              </el-button>
            </div>
            <el-tabs type="card" class="processing-prompt-tabs">
              <el-tab-pane label="实体抽取">
                <el-input
                  :model-value="customPrompts.entityExtraction"
                  type="textarea"
                  :rows="10"
                  resize="vertical"
                  maxlength="30000"
                  show-word-limit
                  @update:model-value="updateCustomPrompt('entityExtraction', $event)"
                />
              </el-tab-pane>
              <el-tab-pane label="关系抽取">
                <el-input
                  :model-value="customPrompts.relationshipExtraction"
                  type="textarea"
                  :rows="10"
                  resize="vertical"
                  maxlength="30000"
                  show-word-limit
                  @update:model-value="updateCustomPrompt('relationshipExtraction', $event)"
                />
              </el-tab-pane>
              <el-tab-pane label="知识融合">
                <el-input
                  :model-value="customPrompts.knowledgeFusion"
                  type="textarea"
                  :rows="10"
                  resize="vertical"
                  maxlength="30000"
                  show-word-limit
                  @update:model-value="updateCustomPrompt('knowledgeFusion', $event)"
                />
              </el-tab-pane>
            </el-tabs>
          </div>
          
          <div class="settings-item">
            <span class="item-label">PDF图片内容识别</span>
            <el-switch 
              v-model="useImg2txt"
              active-text="开启"
              inactive-text="关闭"
            />
          </div>
          <div class="item-description">
            开启后，处理PDF文件时将使用QwenVL视觉模型对图片进行识别转为图片内容描述。
          </div>
        </div>
        
        <div class="settings-section">
          <div class="section-title">RAG问答设置</div>
          <div class="settings-item">
            <span class="item-label">启用流式输出</span>
            <el-switch 
              v-model="enableStreamOutput"
              active-text="开启"
              inactive-text="关闭"
            />
          </div>
          <div class="item-description">
            开启后，AI回答将实时流式输出，使对话更加自然流畅。
          </div>
          
          <div class="settings-item">
            <span class="item-label">携带历史上下文</span>
            <el-switch 
              v-model="enableHistoryContext"
              active-text="开启"
              inactive-text="关闭"
            />
          </div>
          <div class="item-description">
            开启后，AI回答会参考之前的对话历史，保持上下文连贯性。
          </div>
        </div>
      </div>
    </template>
    <template #footer>
      <div class="settings-dialog-footer">
        <el-button
          :icon="Connection"
          :loading="aiSettingsTesting"
          :disabled="aiSettingsSaving"
          @click="testAiSettings"
        >
          测试连接
        </el-button>
        <div class="settings-dialog-actions">
          <el-button @click="openSettings=false">取消</el-button>
          <el-button
            type="primary"
            :loading="aiSettingsSaving"
            :disabled="aiSettingsTesting"
            @click="saveAiSettings"
          >
            保存 AI 配置
          </el-button>
        </div>
      </div>
    </template>
  </el-dialog>
</template>

<style lang="scss" scoped>
.menu {
  display: flex;
  flex-direction: column;
  width: 64px;
  position: inherit;
  background-color: inherit;
  border: none;
  padding-top: 16px;
  padding-bottom: 12px;

  .logo {
    margin-bottom: 8px;
    text-align: center;
  }

  .el-menu-item {
    display: flex;
    justify-content: center;
    position: inherit;
  }

  .el-menu-item:hover {
    background-color: inherit;
  }

  .el-menu-item.is-active {
    background-color: inherit;

    .menu-item {
      background-color: var(--el-fill-color-darker);
    }
  }

  .menu-item {
    display: flex;
    justify-content: center;
    align-items: center;
    padding: 8px;
    border-radius: 8px;
  }

  .menu-item:hover {
    background-color: var(--el-fill-color-darker);
  }

  .flex-grow {
    flex: 1;
  }
}

.settings-dialog-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 18px;
  font-weight: 600;
  line-height: 28px;

  .settings-title {
    color: var(--el-color-primary);
    font-size: 20px;
  }

  .close-icon {
    cursor: pointer;
    padding: 4px;
    border-radius: 4px;
  }

  .close-icon:hover {
    background-color: var(--el-fill-color-light);
  }
}

.settings-content {
  padding: 0 16px;
  max-height: calc(90vh - 156px);
  overflow-y: auto;

  .settings-section {
    margin-bottom: 24px;

    .section-title {
      font-size: 16px;
      font-weight: 600;
      color: var(--el-color-primary) !important;
      margin-bottom: 16px;
      padding-bottom: 8px;
      border-bottom: 1px solid var(--el-border-color-light);
    }

    .settings-item {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 8px;

      .item-label {
        font-size: 14px;
        color: var(--el-text-color-primary);
        font-weight: 500;
      }
    }

    .item-description {
      font-size: 12px;
      color: var(--el-text-color-regular) !important;
      line-height: 1.5;
      margin-top: 4px;
      padding-left: 4px;
      margin-bottom: 16px;
    }
  }

  :deep(.el-select) {
    .el-input__wrapper {
      background-color: var(--el-fill-color-darker) !important;
      box-shadow: 0 0 0 1px var(--el-border-color) inset !important;
    }
    
    .el-input__inner {
      color: var(--el-text-color-primary) !important;
      font-weight: 500 !important;
    }
  }
  
  :deep(.el-select-dropdown__item) {
    color: var(--el-text-color-primary);
  }
  
  :deep(.el-select-dropdown__item.selected) {
    color: var(--el-color-primary);
  }
  
  :deep(.el-select-dropdown) {
    background-color: var(--el-fill-color-darker);
    border: 1px solid var(--el-border-color);
    
    .el-select-dropdown__item {
      color: var(--el-text-color-primary);
      
      &:hover, &.hover {
        background-color: var(--el-fill-color-light);
      }
      
      &.selected {
        color: var(--el-color-primary);
        font-weight: bold;
      }
    }
    
    .note-type-option {
      color: #ffffff;
      font-weight: 500;
      
      &:hover {
        color: var(--el-color-primary-light-3);
      }
      
      &.selected {
        color: var(--el-color-primary);
      }
    }
  }
}

.ai-settings-form {
  :deep(.el-form-item) {
    margin-bottom: 14px;
  }

  :deep(.el-form-item__label) {
    color: var(--el-text-color-primary);
    font-weight: 500;
  }

  .ai-settings-row {
    display: grid;
    grid-template-columns: minmax(160px, 1fr) minmax(160px, 1fr);
    gap: 20px;

    :deep(.el-input-number) {
      width: 100%;
    }
  }
}

.settings-dialog-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;

  .settings-dialog-actions {
    display: flex;
    gap: 8px;
  }
}

.custom-prompts-editor {
  margin: 12px 0 20px;
  padding-top: 12px;
  border-top: 1px solid var(--el-border-color-light);

  .custom-prompts-toolbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    margin-bottom: 8px;
  }

  .processing-prompt-tabs {
    :deep(.el-tabs__content) {
      overflow: visible;
    }

    :deep(.el-textarea__inner) {
      min-height: 180px !important;
      line-height: 1.5;
      font-family: inherit;
    }
  }
}

@media (max-width: 520px) {
  .settings-content {
    padding: 0 4px;
  }

  .ai-settings-form .ai-settings-row {
    grid-template-columns: 1fr;
    gap: 0;
  }

  .settings-dialog-footer {
    align-items: stretch;
    flex-direction: column;

    .settings-dialog-actions {
      justify-content: flex-end;
    }
  }
}

.note-type-option-content {
  display: flex;
  align-items: center;
  
  .note-type-color-indicator {
    width: 12px;
    height: 12px;
    border-radius: 50%;
    margin-right: 8px;
    flex-shrink: 0;
    border: 1px solid rgba(255, 255, 255, 0.2);
  }
  
  .note-type-label {
    color: var(--el-text-color-primary);
    font-weight: 500;
  }
}

.note-type-dot {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  margin-right: 6px;
  border: 1px solid rgba(255, 255, 255, 0.2);
}

:deep(.el-select .el-input__wrapper) {
  padding-left: 8px;
}

:deep(.el-select .el-input__inner) {
  padding-left: 4px;
  font-weight: 500;
  color: #ffffff;
}

:deep(.el-select .el-select__tags) {
  background-color: transparent;
}

/* 增强设置dialog和项目的对比度 */
:deep(.settings-dialog) {
  max-height: 90vh;
  display: flex;
  flex-direction: column;

  .el-dialog__header, .el-dialog__body {
    padding: 16px;
  }

  .el-dialog__body {
    min-height: 0;
    overflow: hidden;
  }
}

:deep(.settings-section) {
  .section-title {
    font-size: 16px;
    font-weight: 600;
    color: var(--el-color-primary) !important;
  }
  
  .item-label {
    font-weight: 500;
  }
  
  .item-description {
    color: var(--el-text-color-regular) !important;
  }
}
</style>

<style lang="scss">
/* 全局样式，确保能够应用到弹出的下拉框 */
body[data-theme="dark"] {
  .el-popper.is-light {
    background-color: var(--el-select-dropdown-bg-color, #2a2a2a) !important;
    border-color: var(--el-border-color, #4c4d4f) !important;
  }
  
  .el-select-dropdown__item {
    color: #e5eaf3 !important; /* 使用更亮的颜色，提高未选中项的可读性 */
    font-weight: 500 !important;
    
    &:hover, &.hover {
      background-color: var(--el-select-dropdown-item-hover-bg, #3a3a3a) !important;
      color: #ffffff !important; /* 悬停时使用白色 */
    }
    
    &.selected {
      color: var(--el-select-dropdown-item-selected-color, #67c23a) !important;
      font-weight: bold !important;
      background-color: rgba(103, 194, 58, 0.15) !important;
    }
  }
  
  /* 特别针对笔记类型选项增加样式 */
  .note-type-option {
    color: #ffffff !important; /* 直接使用白色，最大对比度 */
    text-shadow: 0 0 1px rgba(255, 255, 255, 0.3); /* 添加轻微文字阴影增强可读性 */
  }
  
  .el-popper__arrow::before {
    background-color: var(--el-select-dropdown-bg-color, #2a2a2a) !important;
    border-color: var(--el-border-color, #4c4d4f) !important;
  }
  
  /* 自定义笔记类型选项样式 */
  .el-select-dropdown__item .note-type-option-content {
    .note-type-label {
      color: #ffffff !important;
      font-weight: 500;
    }
  }
  
  .el-select-dropdown__item.selected .note-type-option-content {
    .note-type-label {
      color: var(--el-color-primary) !important;
      font-weight: bold;
    }
  }

  /* 自定义下拉菜单背景 */
  .note-type-dropdown {
    background-color: #2a2a2a !important;
    border: 1px solid #4c4d4f !important;
    
    .el-select-dropdown__item {
      height: auto;
      padding: 8px 12px;
      
      &:hover, &.hover {
        background-color: #3a3a3a !important;
      }
      
      &.selected {
        background-color: #424242 !important;
      }
      
      .note-type-option-content {
        .note-type-label {
          color: #ffffff !important;
          font-weight: 500;
          text-shadow: 0 0 1px rgba(0, 0, 0, 0.5);
        }
      }
    }
  }
  
  /* 选择器内部样式 */
  .el-select .el-input__wrapper {
    background-color: rgba(54, 54, 55, 0.8) !important;
    box-shadow: 0 0 0 1px #4c4d4f inset !important;
  }
  
  .el-select .el-input__inner {
    color: #ffffff !important;
  }
  
  /* Popper箭头样式 */
  .el-popper.note-type-dropdown .el-popper__arrow::before {
    background-color: #2a2a2a !important;
    border-color: #4c4d4f !important;
  }

  /* 设置对话框样式优化 */
  .settings-dialog {
    .el-dialog {
      background-color: #2c2c2c !important; /* 更亮一点的背景色 */
      border: 1px solid #4c4d4f !important;
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.4) !important;
    }
  }

  /* 选项标签样式 */
  .settings-content {
    .settings-section {
      .section-title {
        color: #409eff !important;
        border-bottom-color: #4c4d4f !important;
      }
      
      .settings-item {
        .item-label {
          color: #d16161;
          font-weight: 600;
          text-shadow: 0 0 1px rgba(255, 255, 255, 0.2);
        }
      }
      
      .item-description {
        color: #b8b8b8 !important;
      }
    }
  }
  
  /* 增强选择器样式 */
  .el-select-dropdown__item {
    color: #e6e6e6 !important;
    font-weight: 500 !important;
    font-size: 14px !important;
    
    &:hover, &.hover {
      background-color: #3a3a3a !important;
    }
    
    &.selected {
      background-color: rgba(64, 158, 255, 0.2) !important;
      color: #67c23a !important;
      font-weight: bold !important;
    }
  }
  
  /* 开关组件增强 */
  .el-switch__label {
    color: #e6e6e6 !important;
    
    &.is-active {
      color: #67c23a !important;
    }
  }
}
</style>
