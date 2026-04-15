// Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
// NOBA Command Center — Licensed under Apache 2.0.
import { onUnmounted } from 'vue'

export function useIntervals() {
  const intervals = new Map()

  function register(name, fn, ms) {
    clear(name)
    intervals.set(name, setInterval(fn, ms))
  }

  function clear(name) {
    const id = intervals.get(name)
    if (id) { clearInterval(id); intervals.delete(name) }
  }

  function clearAll() {
    for (const id of intervals.values()) clearInterval(id)
    intervals.clear()
  }

  onUnmounted(clearAll)

  return { register, clear, clearAll }
}
