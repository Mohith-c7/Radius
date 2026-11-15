# Radius — Design System Specification

## Brand Identity & Color System
Radius uses a disciplined developer tool aesthetic grounded in its signature green palette, paired with dark forest sidebar tones and crisp neutral content surfaces.

### Primary Palette
- **Primary Green**: `#19815C` — Main brand color, primary actions, confirmed verdicts
- **Accent Green**: `#64C89D` — Interactive highlights, active badges, copy success indicators
- **Sidebar Background**: `#13231E` — Dark forest green for navigation chrome
- **Sidebar Active/Hover**: `#1C3129` / `#223830`

### Neutral Surfaces
- **Canvas / App Background**: `#F8FAF8` — Subtle warm-tinted light canvas
- **Card / Panel Surface**: `#FFFFFF` — Primary content background
- **Border / Divider**: `#E7ECE8` — Crisp 1px structural boundaries
- **Border Subdued**: `#EDF0EE` — Internal row/item dividers
- **Ink (Primary Text)**: `#17211E` — High contrast text (14.5:1 ratio)
- **Muted (Secondary Text)**: `#56645E` — Readable metadata and descriptions (5.1:1 ratio, exceeds WCAG AA)

### Semantic State Colors
- **Positive (Verified / Healthy / Pass)**: Text `#167455`, Background `#E7F5EE`, Border `#B6DFC9`
- **Attention (Warning / Incomplete Evidence)**: Text `#9A580C`, Background `#FFF4E3`, Border `#F7D6A8`
- **Negative (Failed / Error)**: Text `#C53030`, Background `#FDF2F2`, Border `#F8B4B4`
- **Neutral (Running / Pending / Info)**: Text `#2563EB`, Background `#EFF6FF`, Border `#BFDBFE`

## Typography
- **UI Sans**: `Manrope`, system-ui, -apple-system, sans-serif
- **Code & Numbers**: `DM Mono`, monospace (used for commit SHAs, file paths, CLI snippets, and metric counters)
- **Hierarchy**:
  - Page Titles: 24px (1.5rem), font-weight 700, letter-spacing -0.02em
  - Section Headings (h2): 16px (1.0rem), font-weight 600, letter-spacing -0.01em
  - Card Titles (h3): 14px (0.875rem), font-weight 600
  - Body Text: 14px (0.875rem), line-height 1.5
  - Small / Metadata: 12px (0.75rem), line-height 1.4
  - Code / Monospace: 12px (0.75rem), DM Mono

### Anti-Pattern Bans (Impeccable Craft Floor)
- **No Eyebrows / Kickers**: Remove all `<p className="eyebrow">` labels.
- **No Gradient Text**: Use font weight and size for emphasis.
- **No 4px Colored Border-Left Callouts**: Use subtle tinted backgrounds with 1px border.
- **No Nested Cards**: Do not put cards inside cards.
- **No Fake / Purely Decorative Icons**: Only functional icons representing real entity types.

## Component Specifications

### 1. Navigation & App Shell
- **Desktop Sidebar**: 240px fixed width, dark forest background (`#13231E`).
- **Grouping**:
  - Verification: Overview, Repositories, Pull Requests, Analyses
  - Architecture & Tools: Dependency Graph, Compare Analyses, Search
  - Management: Settings, Organization, Profile
- **Mobile Support**: Under 950px, topbar includes a hamburger toggle opening an overlay drawer.

### 2. Metrics & KPI Presentation
- Clean, unboxed metric groups: label on top in muted small caps, large bold number with DM Mono alignment.
- When an overall confidence ring is present, do not repeat the same number in an adjacent card.

### 3. Tables & Data Display
- Table headers: 11px uppercase, letter-spacing 0.05em, muted color.
- Table rows: 12px 16px padding, subtle hover highlight (`#F4F7F5`).
- Monospace paths and SHAs with copy action.
- Status badges with icon + label, pill border-radius (9999px).

### 4. Interactive Test Selection & CLI Box
- Clear summary: "X of Y test files selected (Z% skipped)".
- Copyable terminal snippet with tabs (`pytest`, `vitest`, `jest`) and instant feedback toast/icon change.
- Progressive disclosure: Selected tests visible; skipped tests in a clean expandable section.
