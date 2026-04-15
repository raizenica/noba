// Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
// NOBA Command Center — Licensed under Apache 2.0.
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import AppModal from '../../components/ui/AppModal.vue'

describe('AppModal', () => {
  it('renders nothing when show=false', () => {
    const wrapper = mount(AppModal, {
      props: { show: false },
      global: { stubs: { Teleport: true, Transition: true } },
    })
    expect(wrapper.find('.modal-overlay').exists()).toBe(false)
  })

  it('renders modal-overlay and modal-box when show=true', () => {
    const wrapper = mount(AppModal, {
      props: { show: true, title: 'Hello' },
      global: { stubs: { Teleport: true, Transition: true } },
    })
    expect(wrapper.find('.modal-overlay').exists()).toBe(true)
    expect(wrapper.find('.modal-box').exists()).toBe(true)
  })

  it('displays title text', () => {
    const wrapper = mount(AppModal, {
      props: { show: true, title: 'My Title' },
      global: { stubs: { Teleport: true, Transition: true } },
    })
    expect(wrapper.find('.modal-title').text()).toContain('My Title')
  })

  it('does not render modal-title when title is empty', () => {
    const wrapper = mount(AppModal, {
      props: { show: true, title: '' },
      global: { stubs: { Teleport: true, Transition: true } },
    })
    expect(wrapper.find('.modal-title').exists()).toBe(false)
  })

  it('emits close when backdrop (modal-overlay) is clicked', async () => {
    const wrapper = mount(AppModal, {
      props: { show: true, title: 'Test' },
      global: { stubs: { Teleport: true, Transition: true } },
    })
    await wrapper.find('.modal-overlay').trigger('click')
    expect(wrapper.emitted('close')).toBeTruthy()
    expect(wrapper.emitted('close').length).toBe(1)
  })

  it('emits close when close button is clicked', async () => {
    const wrapper = mount(AppModal, {
      props: { show: true, title: 'Test' },
      global: { stubs: { Teleport: true, Transition: true } },
    })
    await wrapper.find('.modal-close').trigger('click')
    expect(wrapper.emitted('close')).toBeTruthy()
  })

  it('renders default slot content', () => {
    const wrapper = mount(AppModal, {
      props: { show: true, title: 'Test' },
      slots: { default: '<p class="slot-content">Slot body</p>' },
      global: { stubs: { Teleport: true, Transition: true } },
    })
    expect(wrapper.find('.slot-content').exists()).toBe(true)
    expect(wrapper.find('.slot-content').text()).toBe('Slot body')
  })

  it('renders footer slot when provided', () => {
    const wrapper = mount(AppModal, {
      props: { show: true, title: 'Test' },
      slots: { footer: '<button class="footer-btn">OK</button>' },
      global: { stubs: { Teleport: true, Transition: true } },
    })
    expect(wrapper.find('.modal-footer').exists()).toBe(true)
    expect(wrapper.find('.footer-btn').exists()).toBe(true)
  })

  it('does not render footer when footer slot is not provided', () => {
    const wrapper = mount(AppModal, {
      props: { show: true, title: 'Test' },
      global: { stubs: { Teleport: true, Transition: true } },
    })
    expect(wrapper.find('.modal-footer').exists()).toBe(false)
  })

  it('applies custom width style to modal-box', () => {
    const wrapper = mount(AppModal, {
      props: { show: true, title: 'Test', width: '800px' },
      global: { stubs: { Teleport: true, Transition: true } },
    })
    const box = wrapper.find('.modal-box')
    expect(box.attributes('style')).toContain('800px')
  })

  it('uses default width of 540px when width prop is not provided', () => {
    const wrapper = mount(AppModal, {
      props: { show: true, title: 'Test' },
      global: { stubs: { Teleport: true, Transition: true } },
    })
    const box = wrapper.find('.modal-box')
    expect(box.attributes('style')).toContain('540px')
  })
})
