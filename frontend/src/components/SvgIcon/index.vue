<template>
  <component
    :is="iconComponent"
    v-if="iconComponent"
    aria-hidden="true"
    :class="svgClass"
    :style="svgStyle"
  />
</template>

<script setup lang="ts">
import {computed} from 'vue';
import ClearIcon from '@/assets/icons/svg/clear.svg?component';
import CloseIcon from '@/assets/icons/svg/close.svg?component';
import DeleteIcon from '@/assets/icons/svg/delete.svg?component';
import FileIcon from '@/assets/icons/svg/file.svg?component';
import FilterIcon from '@/assets/icons/svg/filter.svg?component';
import HistoryIcon from '@/assets/icons/svg/history.svg?component';
import HomeIcon from '@/assets/icons/svg/home.svg?component';
import LogoIcon from '@/assets/icons/svg/logo.svg?component';
import SearchIcon from '@/assets/icons/svg/search.svg?component';
import SettingIcon from '@/assets/icons/svg/setting.svg?component';
import UploadIcon from '@/assets/icons/svg/upload.svg?component';

const icons = {
  clear: ClearIcon,
  close: CloseIcon,
  delete: DeleteIcon,
  file: FileIcon,
  filter: FilterIcon,
  history: HistoryIcon,
  home: HomeIcon,
  logo: LogoIcon,
  search: SearchIcon,
  setting: SettingIcon,
  upload: UploadIcon
};

const props = defineProps({
  prefix: {
    type: String,
    default: 'icon'
  },
  iconClass: {
    type: String,
  },
  iconName: {
    type: String,
    required: false
  },
  color: {
    type: String
  },
  size: {
    type: String,
    default: '1em'
  }
});

const iconComponent = computed(() => icons[props.iconName]);
const svgClass = computed(() => {
  if (props.iconClass) {
    return `svg-icon ${props.iconClass}`
  }
  return 'svg-icon'
});
const svgStyle = computed(() => ({
  width: props.size,
  height: props.size,
  color: props.color
}));
</script>

<style scoped>
.svg-icon {
  display: inline-block;
  flex-shrink: 0;
  overflow: hidden;
}

.svg-icon:not([fill="none"]) {
  fill: currentColor;
}
</style>
