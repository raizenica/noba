# Self-Healing Validation Implementation Plan (Phase 6 of 6)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the validation and resilience layer: internal component health monitoring (watchdog), chaos testing framework for controlled fault injection, dry-run endpoint for safe pipeline simulation, and canary rollout mode for new heal rules.

**Architecture:** New `server/healing/watchdog.py` monitors subsystem heartbeats and triggers recovery. New `server/healing/chaos.py` defines chaos test scenarios and execution. Dry-run mode runs the full pipeline without executing actions. Canary adds `observation` and `dry-run` trust levels.

**Tech Stack:** Python 3.11+, SQLite WAL, threading, dataclasses, pytest

**Spec:** `docs/superpowers/specs/2026-03-22-full-self-healing-design.md` (Sections 9, 10)

---

## File Map

### New files
| File | Responsibility |
|------|---------------|
| `server/healing/watchdog.py` | Component heartbeat registry, health checking, recovery actions |
| `server/healing/chaos.py` | Chaos test scenario definitions, runner, result validation |
| `server/healing/dry_run.py` | Dry-run pipeline simulation without execution |
| `tests/test_watchdog.py` | Tests for component health monitoring |
| `tests/test_chaos.py` | Tests for chaos scenario runner |
| `tests/test_dry_run.py` | Tests for dry-run simulation |

### Modified files
| File | Change |
|------|--------|
| `server/routers/healing.py` | Add dry-run and chaos endpoints |
| `server/healing/__init__.py` | Heartbeat registration, canary mode support |

---

## Task 1: Component Watchdog

## Task 2: Dry-Run Pipeline Simulation

## Task 3: Chaos Testing Framework

## Task 4: Canary Rollout Mode

## Task 5: API Endpoints for Dry-Run + Chaos

## Task 6: Lint + Build + Final Integration
