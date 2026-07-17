# Agent Workspace AI Design System

> Generated with `ui-ux-pro-max`, then adapted to the supplied enterprise SaaS references and this product's operational workflows.

## Product Direction

- Product: enterprise AI Agent project collaboration platform.
- Audience: product, engineering, project, quality and operations teams.
- Style: quiet, utilitarian, content-dense SaaS administration.
- Design dials: variance 4/10, motion 3/10, density 8/10.
- Primary surfaces are unframed page layouts. Cards are reserved for repeated entities, metrics and framed work tools.

## Color Tokens

| Role | Value | Token |
| --- | --- | --- |
| Primary action | `#2563EB` | `--color-primary` |
| Primary hover | `#1D4ED8` | `--color-primary-hover` |
| Primary soft | `#EFF6FF` | `--color-primary-soft` |
| Foreground | `#111827` | `--color-foreground` |
| Secondary text | `#4B5563` | `--color-secondary-text` |
| Muted text | `#6B7280` | `--color-muted-text` |
| Page background | `#F7F8FA` | `--color-background` |
| Surface | `#FFFFFF` | `--color-surface` |
| Border | `#E5E7EB` | `--color-border` |
| Success | `#15803D` | `--color-success` |
| Warning | `#B45309` | `--color-warning` |
| Destructive | `#B91C1C` | `--color-danger` |

Color is never the only state signal. Status text, icons or labels accompany semantic colors.

## Typography

- Font stack: `Inter`, `PingFang SC`, `Microsoft YaHei`, `Noto Sans CJK SC`, sans-serif.
- Page title: 28px / 750 weight, 24px on phones.
- Section title: 17px / 700 weight.
- Body: 15px with 1.5 or greater line-height.
- Data labels: 12px; eyebrow and compact metadata may use 11px.
- Numbers use tabular figures. Letter spacing remains `0`.

## Spacing And Shape

- Spacing rhythm: 4, 8, 12, 16, 20, 24 and 32px.
- Control height: 40px desktop, at least 44px for login and mobile-critical fields.
- Radius: 4px compact tags, 6px controls, 8px cards and dialogs.
- Shadows are subtle and never replace borders.
- Fixed-format controls use stable dimensions to prevent layout shift.

## Navigation

- Desktop and tablet landscape: persistent 236px sidebar plus 64px top bar.
- Under 900px: off-canvas navigation with a full-screen scrim.
- Navigation uses one outline icon family and visible text labels.
- Active location uses background, weight and a blue indicator, not color alone.
- Destructive logout stays in the user menu, separated from primary navigation.

## Components

- Primary buttons use solid blue; secondary commands use neutral borders.
- Icon-only buttons require `aria-label` and tooltip/title.
- Forms always have visible labels, loading/disabled states and actionable errors.
- Tables use neutral headers and internal overflow rather than widening the page.
- Agent cards expose role, model, approval, memory and tool permissions without hover-only content.
- Dashboard charts include a text legend and an accessible summary.

## Responsive Rules

- Verify 375, 390, 768, 1024 and 1440px widths.
- No page-level horizontal scrolling.
- Business pages use a 1480px maximum content width; compact pages use 1440px so wide screens do not create excessive empty gutters.
- Desktop content gutters are 28px before max-width centering; prose remains locally constrained instead of narrowing the entire operational page.
- 3-column Agent cards become 2 columns below 1180px and 1 column below 640px.
- Dashboard sections stack below 900px; tables remain usable inside their own surface.
- Top-bar secondary commands hide before they can compress search or account controls.

## Motion And Accessibility

- Interaction transitions: 150-200ms, color/elevation only; no layout-shifting transforms.
- Honor `prefers-reduced-motion` globally.
- Normal text targets WCAG 4.5:1 contrast.
- Keyboard focus uses a visible 3px blue ring.
- A skip link and route-change main-content focus support keyboard and screen-reader navigation.
- Clickable controls use semantic buttons/links and a minimum 40px desktop target.

## Delivery Checklist

- [ ] No emoji structural icons.
- [ ] No console errors.
- [ ] No horizontal page overflow at supported widths.
- [ ] Loading, empty, disabled and error states are visible.
- [ ] Focus order follows visual order.
- [ ] Long names and tool identifiers do not overlap adjacent content.
- [ ] Reduced motion remains functional.
