import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import DashboardCard from '../../components/cards/DashboardCard.vue'

describe('DashboardCard', () => {
  it('renders title text', () => {
    const wrapper = mount(DashboardCard, {
      props: { title: 'CPU', icon: 'fa-microchip', cardId: 'cpu' },
    })
    expect(wrapper.find('.card-title').text()).toBe('CPU')
  })

  it('renders icon class', () => {
    const wrapper = mount(DashboardCard, {
      props: { title: 'CPU', icon: 'fa-microchip', cardId: 'cpu' },
    })
    const icon = wrapper.find('.card-icon')
    expect(icon.classes()).toContain('fa-microchip')
  })

  it('card-body is visible by default (not collapsed)', () => {
    const wrapper = mount(DashboardCard, {
      props: { title: 'CPU', icon: 'fa-microchip', cardId: 'cpu' },
    })
    // v-show keeps the element in DOM; check it is visible (display !== none)
    const body = wrapper.find('.card-body')
    expect(body.exists()).toBe(true)
    expect(body.isVisible()).toBe(true)
  })

  it('clicking collapse button hides card-body', async () => {
    const wrapper = mount(DashboardCard, {
      props: { title: 'CPU', icon: 'fa-microchip', cardId: 'cpu' },
    })
    await wrapper.find('.collapse-btn').trigger('click')
    expect(wrapper.find('.card-body').isVisible()).toBe(false)
  })

  it('clicking collapse button a second time shows card-body again', async () => {
    const wrapper = mount(DashboardCard, {
      props: { title: 'CPU', icon: 'fa-microchip', cardId: 'cpu' },
    })
    const btn = wrapper.find('.collapse-btn')
    await btn.trigger('click')
    await btn.trigger('click')
    expect(wrapper.find('.card-body').isVisible()).toBe(true)
  })

  it('renders slot content inside card-body', () => {
    const wrapper = mount(DashboardCard, {
      props: { title: 'CPU', icon: 'fa-microchip', cardId: 'cpu' },
      slots: { default: '<div class="test-content">Content</div>' },
    })
    expect(wrapper.find('.test-content').exists()).toBe(true)
    expect(wrapper.find('.test-content').text()).toBe('Content')
  })

  it('applies data-health attribute when health prop is provided', () => {
    const wrapper = mount(DashboardCard, {
      props: { title: 'CPU', icon: 'fa-microchip', cardId: 'cpu', health: 'ok' },
    })
    expect(wrapper.find('.card').attributes('data-health')).toBe('ok')
  })

  it('does not set data-health attribute when health prop is empty', () => {
    const wrapper = mount(DashboardCard, {
      props: { title: 'CPU', icon: 'fa-microchip', cardId: 'cpu', health: '' },
    })
    expect(wrapper.find('.card').attributes('data-health')).toBeUndefined()
  })

  it('sets data-id attribute from cardId prop', () => {
    const wrapper = mount(DashboardCard, {
      props: { title: 'CPU', icon: 'fa-microchip', cardId: 'cpu' },
    })
    expect(wrapper.find('.card').attributes('data-id')).toBe('card-cpu')
  })

  it('collapse button has aria-expanded=true by default', () => {
    const wrapper = mount(DashboardCard, {
      props: { title: 'CPU', icon: 'fa-microchip', cardId: 'cpu' },
    })
    expect(wrapper.find('.collapse-btn').attributes('aria-expanded')).toBe('true')
  })

  it('collapse button has aria-expanded=false after collapsing', async () => {
    const wrapper = mount(DashboardCard, {
      props: { title: 'CPU', icon: 'fa-microchip', cardId: 'cpu' },
    })
    await wrapper.find('.collapse-btn').trigger('click')
    expect(wrapper.find('.collapse-btn').attributes('aria-expanded')).toBe('false')
  })

  it('collapse button has correct aria-controls attribute', () => {
    const wrapper = mount(DashboardCard, {
      props: { title: 'CPU', icon: 'fa-microchip', cardId: 'cpu' },
    })
    expect(wrapper.find('.collapse-btn').attributes('aria-controls')).toBe('body-cpu')
  })

  it('does not render collapse button when collapsible=false', () => {
    const wrapper = mount(DashboardCard, {
      props: { title: 'CPU', icon: 'fa-microchip', cardId: 'cpu', collapsible: false },
    })
    expect(wrapper.find('.collapse-btn').exists()).toBe(false)
  })

  it('collapse button gains is-collapsed class after click', async () => {
    const wrapper = mount(DashboardCard, {
      props: { title: 'CPU', icon: 'fa-microchip', cardId: 'cpu' },
    })
    const btn = wrapper.find('.collapse-btn')
    expect(btn.classes()).not.toContain('is-collapsed')
    await btn.trigger('click')
    expect(btn.classes()).toContain('is-collapsed')
  })
})
