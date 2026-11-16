---
name: KAIROS
description: 'Evidence Atlas: visible evidence, debated research and reviewed paper
  execution.'
colors:
  blue: '#294e96'
  blue-hover: '#203f7c'
  blue-soft: '#eef3fc'
  shell: '#192d53'
  shell-selected: '#324d7b'
  shell-hover: '#2b436c'
  shell-text: '#bbc9e0'
  ink: '#172945'
  muted: '#596b83'
  surface: '#fff'
  canvas: '#f3f6fb'
  line: '#e1e7f0'
  positive: '#167357'
  positive-soft: '#eaf5ef'
  negative: '#b43847'
  warning: '#94610f'
  focus: '#89aaf0'
  pill-neutral: '#f1f4f8'
  pill-ink: '#53657d'
  pill-green: '#e9f5ed'
  pill-green-ink: '#256143'
  pill-red: '#fbedef'
  pill-red-ink: '#9f3043'
  pill-amber: '#fff3db'
  pill-amber-ink: '#815616'
  pill-blue: '#edf2fe'
  pill-blue-ink: '#355c9d'
typography:
  headline:
    fontFamily: Manrope Variable, sans-serif
    fontSize: 30px
    fontWeight: 750
    lineHeight: 1.3
    letterSpacing: -0.03em
  title:
    fontFamily: Manrope Variable, sans-serif
    fontSize: 16px
    fontWeight: 750
    letterSpacing: -0.025em
  body:
    fontFamily: Manrope Variable, sans-serif
    fontSize: 13px
    lineHeight: 1.8
  intro:
    fontFamily: Manrope Variable, sans-serif
    fontSize: 14px
    fontWeight: 450
    lineHeight: 1.6
  label:
    fontFamily: Manrope Variable, sans-serif
    fontSize: 12px
    fontWeight: 700
  button:
    fontFamily: Manrope Variable, sans-serif
    fontSize: 11px
    fontWeight: 750
  price:
    fontFamily: Manrope Variable, sans-serif
    fontSize: 30px
    fontWeight: 760
    lineHeight: 1.3
    letterSpacing: -0.035em
rounded:
  chip: 5px
  icon: 6px
  field: 7px
  control: 8px
  node: 12px
  panel: 14px
  login: 16px
spacing:
  icon-gap: 8px
  control-gap: 12px
  control-inset: 16px
  grid-gap: 20px
  section: 24px
components:
  button-primary:
    backgroundColor: '{colors.blue}'
    textColor: '{colors.surface}'
    typography: '{typography.button}'
    rounded: '{rounded.control}'
    padding: 11px 16px
  button-primary-hover:
    backgroundColor: '{colors.blue-hover}'
  button-secondary:
    backgroundColor: '{colors.surface}'
    textColor: '#334966'
    typography: '{typography.button}'
    rounded: '{rounded.control}'
    padding: 11px 16px
  button-text:
    backgroundColor: transparent
    textColor: '{colors.blue}'
    typography: '{typography.button}'
    padding: 6px 0
  input-search:
    backgroundColor: '{colors.surface}'
    textColor: '{colors.ink}'
    rounded: '{rounded.control}'
    padding: 0 12px
  nav-item:
    backgroundColor: transparent
    textColor: '{colors.shell-text}'
    rounded: '{rounded.control}'
    padding: 13px 14px
  nav-item-selected:
    backgroundColor: '{colors.shell-selected}'
    textColor: '{colors.surface}'
  chip:
    backgroundColor: '{colors.pill-neutral}'
    textColor: '{colors.pill-ink}'
    rounded: '{rounded.chip}'
    padding: 5px 8px
  panel:
    backgroundColor: '{colors.surface}'
    textColor: '{colors.ink}'
    rounded: '{rounded.panel}'
  pipeline-node:
    backgroundColor: '#f8faff'
    textColor: '{colors.ink}'
    rounded: '{rounded.node}'
    padding: 16px
  evidence-tab:
    backgroundColor: transparent
    textColor: '{colors.muted}'
    padding: 16px 12px
  debate-turn:
    textColor: '{colors.ink}'
    padding: 23px 0
---

# Design System: KAIROS

## Overview

**Creative North Star: "Evidence Atlas"**

Evidence Atlas pairs a deep-blue navigation shell with cool light work areas and dark financial ink. Manrope keeps controls, evidence and tabular figures in one clear typographic voice. Emerald marks positive movement and completed evidence; amber and red expose warnings and failures.

The system is professional, compact and inspectable. Bordered surfaces organize dense research without turning every block into a floating card. Authored SVG diagrams and animated evidence connections explain actual workflow events; readable reports and debate arguments carry the substance.

**Key Characteristics:**
- Deep-blue shell around cool light research surfaces.
- Manrope typography with tabular financial numerals.
- Bounded semantic color and explicit status labels.
- Authored SVG evidence geometry and event-driven handoffs.
- Readable evidence first, structured details on demand.

## Colors

Deep blue provides orientation and action; cool whites and blue-gray ink make dense evidence legible. The frontmatter is the normative color record; names below describe its use.

### Primary

- **Atlas Blue** (`blue`): primary research actions, selected report tabs, line charts and live handoffs. Its darker hover and pale wash support state changes.
- **Deep Navigation Blue** (`shell`): persistent desktop navigation and the mobile drawer. Selected and hover tones retain the shell's character.

### Secondary

- **Evidence Emerald** (`positive`): positive chart movement, completed steps and source-fetch status. Pale emerald supports restrained success states.

### Tertiary

- **Risk Red** (`negative`): negative candles, Bear arguments and failed execution.
- **Caution Amber** (`warning`): warning semantics; amber chips use the separate observed chip tones.

### Neutral

- **Research Ink** (`ink`): headings, measurements and readable report content.
- **Slate Annotation** (`muted`): dates, provider notes, secondary descriptions and metadata.
- **Cool Workspace** (`canvas`), **White Surface** (`surface`) and **Quiet Divider** (`line`): the background, bounded work areas and separators.
- **Focus Blue** (`focus`): keyboard outline. Status chip colors are separate from the stronger chart and text colors.

**The Evidence Color Rule.** Semantic color follows evidence or execution state and is accompanied by a label or icon.

## Typography

**Display and Body Font:** Manrope Variable, with sans-serif fallback. The font is self-hosted through `@fontsource-variable/manrope`. Financial numerals use tabular figures; structured payloads retain the browser's monospace treatment.

The hierarchy is compact and practical. There is no oversized marketing display role and no rigid ratio across sizes.

- **Headline:** workspace heading (30px, weight 750, line-height 1.3), reduced on mobile (25px).
- **Title:** section headings (16px, weight 750); report headings use the same size.
- **Body:** report and debate arguments (13px, line-height 1.8; report lists 1.9). Text measures range from 65ch for proposal prose to 78–80ch for debate and report narratives.
- **Intro:** supporting workspace copy (14px, line-height 1.6), reduced on mobile (13px).
- **Label:** common field and pipeline labels (12px). Metadata remains smaller (9–11px); paper-order labels are larger (13px).
- **Button:** compact action labels (11px, weight 750).
- **Price:** research chart value (30px, weight 760); paper-market quote uses a nearby size (29px).

## Layout

The desktop shell uses a fixed sidebar (224px), a white top bar (73px) and a centered content area capped at 1600px. Main gutters are 34px, increasing to 48px on wide screens. At 1200px the sidebar narrows to 195px and gutters to 24px. At 700px the sidebar becomes a hidden drawer, the top bar is 64px and content gutters are 17px.

Paired work areas use an asymmetric grid (1.4fr / 1fr, gap 20px), collapsing at 960px. Wider screens use 1.5fr / 1fr. Pipeline nodes use four columns, then two at 700px. Typical section spacing is 24px; compact controls use 8–16px gaps and insets. Report measurements collapse from two columns to one on mobile. Tables and report tabs scroll horizontally where needed.

The research workspace's composition is recorded in `.impeccable/surfaces/research-workspace.md`: chart and proposal precede the expanded pipeline, with a compact activity summary linking to it. This is a surface arrangement, not a required layout for every page. Mobile stock controls retain a separate selected-symbol and exchange line above the search field.

## Elevation & Depth

Depth comes mainly from the dark shell, light canvas, white bounded surfaces and thin dividers. Resting research panels have no shadow. Elevation is reserved for overlays, the login surface and an actively working pipeline node.

### Shadow Vocabulary

- **Search results:** (`0 12px 30px #17294520`) separates the result list from work beneath it.
- **Working node:** (`0 5px 14px #315a9e13`) gives the live step a slight lift.
- **Mobile drawer:** (`10px 0 40px #192d531c`) separates navigation from the workspace.
- **Login:** (`0 14px 44px #192d5310`) supports the isolated authentication surface.

**The Bounded Surface Rule.** Research panels establish hierarchy with borders and tonal layering; lift is reserved for overlays or active work.

## Shapes

Cards use gently curved corners (14px), with slightly tighter pipeline nodes and draft containers (12px). Controls and navigation use compact corners (8px); conventional input fields use 7px. Small status pills use 5px, while avatars and phase markers are circular. Thin one-pixel borders organize panels and state changes. Blocked pipeline nodes use dashed borders.

Charts, evidence paths and empty-state diagrams are authored SVG geometry. Reuse the thin connected-path language, small nodes and restrained blue linework; avoid adding photographic decoration to research views. Icons use small outlined SVGs.

## Components

### Buttons

Compact, explicit actions. Primary buttons use Atlas Blue with white text and a darker hover; secondary actions use white surfaces with a quiet border. Both use control corners and padding (11px 16px), normally a minimum height of 42px. Text actions keep blue ink, minimal horizontal padding and a minimum height of 36px. Disabled controls reduce opacity and change the cursor. Focus uses a visible outline (3px, offset 3px). Background and border transitions take 180ms with ease timing.

### Chips

Small rectangular status markers with compact rounding, padding (5px 8px), bold text (9px) and no border. Neutral, green, red, amber and blue variants use their dedicated pale background and darker text pairs. They describe state rather than act as oversized calls to action.

### Cards / Containers

White panels with a quiet border and shared panel radius. Headers use generous horizontal insets (normally 22px, with 17px on smaller desktop widths); report bodies use 24px, then 18px on mobile. Quiet provenance notes and verdicts use tonal washes. Raw payloads live in scrollable, wrapping code blocks behind explicit disclosure controls.

### Inputs / Fields

Conventional fields use white backgrounds, subtle borders, compact corners and clear labels. Search adds an inline magnifier in a bordered rounded wrapper, with results in an elevated list. Each stock-search instance uses unique combobox/listbox/option IDs, keyboard navigation and exchange labels. Search text becomes 16px on mobile; selected instrument text remains separately visible. Errors are inline and readable; disabled fields retain their labels and use muted surfaces.

### Navigation

A deep-blue vertical shell contains outlined icons, left-aligned text and rounded selected backgrounds. Navigation labels use 14px; selected items use white ink. Hover uses a distinct shell tone. On mobile, a menu control opens the drawer; the closed drawer is hidden from view and focus. Report tabs use a blue underline and a pale selected wash, with horizontal overflow preserved.

### Agent pipeline

The signature is a connected trail of inspectable agent nodes. Gather, Debate and Propose phase markers summarize progress. Nodes show role, framework and text status; Ready, Waiting, Working, Complete, Failed and Not reached remain distinguishable. Selecting a node exposes its job and available output. A failed workflow marks unreached nodes as blocked rather than complete.

Working nodes receive blue emphasis and a small lift. Connections animate only when an actual completed node hands off to a working node; the active icon softly breathes. Handoff motion takes 1s; breathing takes 2s. Reduced-motion styles remove animation and transitions while preserving state, and the activity-summary link uses immediate scrolling.

### Evidence reports and live debate

Report tabs expose specialist narratives, source articles, provider dates and measurements before optional structured data. Bull and Bear contributions use restrained emerald and red icon treatments; the manager uses blue. Streamed text sits in a bounded pale-blue draft area with an explicit unvalidated label. Completed contributions and verdicts remain visually distinct from drafts. Empty states use authored evidence-path SVGs and explain what a real run will produce.

## Do's and Don'ts

### Do:

- **Do** use the shared ink, muted, surface, canvas and blue primitives for new surfaces.
- **Do** pair status color with a readable label or icon.
- **Do** keep source dates, provider identity, missing data and draft validation status visible.
- **Do** preserve the selected symbol and exchange on narrow screens.
- **Do** make reduced-motion state changes immediate and keep keyboard focus visible.

### Don't:

- **Don't** animate progress independently of actual execution events.
- **Don't** imply a generated report timestamp is the source publication time.
- **Don't** use positive green or warning amber as decorative backgrounds for unrelated actions.
- **Don't** replace authored evidence geometry with generic stock imagery.
- **Don't** hide primary research content behind raw structured output.
