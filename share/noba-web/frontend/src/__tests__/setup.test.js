// Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
// NOBA Command Center — Licensed under Apache 2.0.
import { describe, it, expect } from 'vitest'

describe('Test setup', () => {
  it('vitest runs', () => {
    expect(1 + 1).toBe(2)
  })

  it('jsdom provides document', () => {
    expect(typeof document).toBe('object')
    expect(typeof window).toBe('object')
  })

  it('localStorage is available', () => {
    localStorage.setItem('test', 'value')
    expect(localStorage.getItem('test')).toBe('value')
    localStorage.removeItem('test')
  })
})
