import {createApp} from 'vue';
import '@/style.css';
import ElementPlus from "element-plus";
/** element-plus 覆盖主题样式 */
import "@/styles/element/index.scss";
import {zhCn} from "element-plus/es/locale/index";
import App from "@/App.vue";
import router from '@/router'
import SvgIcon from '@/components/SvgIcon/index.vue'

const app = createApp(App)

// 注册全局svg组件
app.component('SvgIcon', SvgIcon)

app.use(ElementPlus, {locale: zhCn})
app.use(router)
app.mount('#app')
