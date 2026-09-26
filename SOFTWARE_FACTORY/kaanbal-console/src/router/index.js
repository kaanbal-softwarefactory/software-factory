import { createRouter, createWebHistory } from 'vue-router'
import { authState, checkAuth } from '../store/auth'

const router = createRouter({
    history: createWebHistory(import.meta.env.BASE_URL),
    routes: [
        {
            path: '/login',
            name: 'login',
            component: () => import('../views/Login.vue'),
            meta: { public: true }
        },
        {
            path: '/setup',
            redirect: '/login',
            meta: { public: true }
        },
        {
            path: '/wizard',
            name: 'wizard',
            component: () => import('../views/Wizard.vue'),
        },
        {
            path: '/',
            redirect: '/dashboard'
        },
        {
            path: '/dashboard',
            name: 'dashboard',
            component: () => import('../views/Dashboard.vue')
        },
        {
            path: '/apps',
            name: 'apps',
            component: () => import('../views/Apps.vue')
        },
        {
            path: '/templates',
            name: 'templates',
            component: () => import('../views/Templates.vue')
        },
        {
            path: '/stacks',
            name: 'stacks',
            component: () => import('../views/Stacks.vue')
        },
        {
            path: '/domains',
            name: 'domains',
            component: () => import('../views/Domains.vue')
        },
        {
            path: '/security',
            name: 'security',
            component: () => import('../views/Security.vue')
        },
        {
            path: '/updates',
            name: 'updates',
            component: () => import('../views/Updates.vue')
        },
        {
            path: '/settings',
            name: 'settings',
            component: () => import('../views/Settings.vue')
        },
        {
            path: '/logs',
            name: 'logs',
            component: () => import('../views/Logs.vue')
        }
    ]
})

router.beforeEach(async (to, from, next) => {
    // Public routes don't need auth
    if (to.meta.public) {
        return next();
    }

    // Check token exists AND is not expired
    if (!checkAuth()) {
        return next('/login');
    }

    next();
})

export default router
