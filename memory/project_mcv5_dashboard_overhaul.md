---
name: MCB Dashboard UX Overhaul
description: Autonomous UX overhaul of MCB dashboard — status, architecture, and remaining work
type: project
---

MCB dashboard UX overhaul was done autonomously across 2 sessions (12 commits total).

**Why:** Matthias wanted a polished, production-grade dashboard ("fertiges Hammerprojekt").

**How to apply:** When working on MCB dashboard, the architecture is:
- Vanilla JS IIFE in dashboard.js (~1756 lines), Plain CSS (~1778 lines)
- SSE event bus with REST fallback for initial load
- In-place DOM updates (kpiBuilt/resourcesBuilt flags) to avoid flicker
- IntersectionObserver for lazy peek loading and auto-mark-read
- Smart polling: pauses SSE + polling when tab hidden (visibilitychange API)
- Debounced SSE handlers to prevent rapid-fire DOM rebuilds
- Focus traps on drawer (role=dialog, aria-modal) and broadcast dialog
- MCB runs on port 8205 (NOT 8200 — that's MCV4)

**Completed features:**
- KPI row with flash animations, session cards with status dots/badges/typing dots
- Session groups by project with collapse persistence
- Toast notifications, keyboard shortcuts (?/r/n/b/Esc)
- Activity feed with typed icons, auto-mark-read on scroll
- Auto-Heal panel redesign, System resources with gradient bars
- Session detail drawer with token bars, terminal preview, quick actions
- Broadcast dialog with session selection
- PWA: overscroll-behavior, 44px touch targets, iOS zoom prevention
- Accessibility: focus-visible, tabindex, ARIA roles, reduced-motion
- Live timestamp ticker (30s), shimmer on working cards, hover lift

**Remaining ideas (from research):**
- iOS splash screen images for all resolutions
- Custom PWA install banner for iOS
- Sparkline charts in KPI cards for token trends
- "Yesterday's Notes" auto-summary feature
- Hot-swap LLM per agent UI
