import DefaultTheme from 'vitepress/theme'
import HomePage from './HomePage.vue'
import './style.css'

export default {
  extends: DefaultTheme,
  enhanceApp({ app }) {
    app.component('HomePage', HomePage)
  }
}
