// Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
// NOBA Command Center — Licensed under Apache 2.0.
import { defineConfig } from 'vitepress'

export default defineConfig({
  title: 'NOBA Command Center',
  description: 'Self-hosted infrastructure monitoring, automation, and predictive intelligence.',
  base: '/noba-ce/',
  head: [
    ['link', { rel: 'icon', type: 'image/svg+xml', href: '/noba/favicon.svg' }],
  ],
  themeConfig: {
    logo: '/favicon.svg',
    nav: [
      { text: 'Guide', link: '/guide/getting-started' },
      { text: 'Configuration', link: '/config/' },
      { text: 'API', link: '/api/' },
      { text: 'GitHub', link: 'https://github.com/raizenica/noba-ce' },
    ],
    sidebar: {
      '/guide/': [
        {
          text: 'Getting Started',
          items: [
            { text: 'Installation', link: '/guide/getting-started' },
            { text: 'Docker', link: '/guide/docker' },
            { text: 'First Login', link: '/guide/first-login' },
          ],
        },
        {
          text: 'Using NOBA',
          items: [
            { text: 'Dashboard', link: '/guide/dashboard' },
            { text: 'Remote Agents', link: '/guide/agents' },
            { text: 'Monitoring & SLA', link: '/guide/monitoring' },
            { text: 'Infrastructure', link: '/guide/infrastructure' },
            { text: 'Automations', link: '/guide/automations' },
            { text: 'Security Posture', link: '/guide/security' },
            { text: 'Remote Terminal', link: '/guide/terminal' },
          ],
        },
        {
          text: 'Advanced',
          items: [
            { text: 'Self-Healing', link: '/guide/healing' },
            { text: 'Workflow Builder', link: '/guide/workflows' },
            { text: 'Approval Queue', link: '/guide/approvals' },
            { text: 'Maintenance Windows', link: '/guide/maintenance' },
            { text: 'Predictions', link: '/guide/predictions' },
            { text: 'Plugins', link: '/guide/plugins' },
          ],
        },
      ],
      '/config/': [
        {
          text: 'Configuration',
          items: [
            { text: 'Overview', link: '/config/' },
            { text: 'Integrations', link: '/config/integrations' },
            { text: 'Agent Keys', link: '/config/agent-keys' },
            { text: 'Notifications', link: '/config/notifications' },
            { text: 'Themes', link: '/config/themes' },
          ],
        },
      ],
      '/api/': [
        {
          text: 'API Reference',
          items: [
            { text: 'Overview', link: '/api/' },
            { text: 'Authentication', link: '/api/authentication' },
            { text: 'Agents', link: '/api/agents' },
            { text: 'Automations', link: '/api/automations' },
            { text: 'Monitoring', link: '/api/monitoring' },
            { text: 'Healing', link: '/api/healing' },
          ],
        },
      ],
    },
    socialLinks: [
      { icon: 'github', link: 'https://github.com/raizenica/noba-ce' },
    ],
    footer: {
      message: 'Released under the MIT License.',
      copyright: 'Built by Raizen',
    },
    search: {
      provider: 'local',
    },
  },
})
