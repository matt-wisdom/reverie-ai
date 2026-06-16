import { createRouter, createWebHistory } from 'vue-router'
import HomeView from '../views/HomeView.vue'
import ProjectDetail from '../views/ProjectDetail.vue'
import ReportView from '../views/ReportView.vue'
import SettingsView from '../views/SettingsView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: HomeView },
    { path: '/project/:tag', component: ProjectDetail },
    { path: '/project/:tag/report/:id', component: ReportView },
    { path: '/settings', component: SettingsView }
  ]
})

export default router
