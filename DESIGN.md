# Design

## Intent

Envman’s public surface is a late-night terminal control room: quiet instrument lights, dense but legible readings, and one intentional accent at a time. The physical scene is an operator reviewing machine state in a dim workspace, where glare and ornamental noise would make work harder.

## Color Tokens

- Background: `oklch(0.11 0 0)`
- Surface: `oklch(0.17 0.015 200)`
- Ink: `oklch(0.94 0.01 200)`
- Muted: `oklch(0.72 0.02 200)`
- Primary sky: `oklch(0.75 0.08 200)`
- Magenta accent: `oklch(0.68 0.18 330)`
- Success: `oklch(0.78 0.15 145)`
- Warning: `oklch(0.82 0.15 80)`
- Danger: `oklch(0.66 0.20 25)`

## Typography

Use the system UI sans-serif stack for prose and the system monospace stack for headings, values, and commands. No remote font or image dependency is permitted. Headings use clear weight and scale rather than compressed tracking; body measure remains below 75ch.

## Layout and Components

The landing page uses a bordered instrument-panel composition, strong semantic hierarchy, and deliberate asymmetry in the hero. Controls are solid, high-contrast actions with visible focus. Status labels include text and shape, never color alone. Motion is limited to a short, optional status sweep and is removed under `prefers-reduced-motion`.

## Accessibility

Text meets a 4.5:1 minimum contrast ratio, controls meet 44px targets, the skip link is visible on focus, and the 390px layout has no horizontal overflow.
