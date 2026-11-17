# BoneChilling — design system

## Concept card
```
Idea:        The app is a reading-room lightbox: films are clipped up, read, and signed off.
Metaphor:    Radiology reading room — lightbox glass, film base, film-label print, lead L/R markers.
Signature:   Opening a patient "clips" each film onto the lightbox — panels drop 6px into place in
             sequence while their dark film header backlights on. Films carry a lead-marker style
             L / R badge, taken from the markers techs place on real radiographs.
Emotion:     Calm, precise, clinical — nothing decorative competes with the findings.
Motion verb: "clip and settle" — short (160–320ms), decisive ease-out, no bounce.
Screenshot:  Patient page: big name, film-label meta line, row of dark film headers with L/R markers.
```

## Type
- **Host Grotesk** (variable 400–700, Google, self-hosted) — all text and display.
- **IBM Plex Mono** 400/500 — only for film-label data: IDs, dates, file paths, counters' units.
- Scale has deliberate jumps: page titles `clamp(2rem, 1.2rem + 2.2vw, 3.25rem)`, tracking −0.03em,
  leading 1.0; numerals `clamp(2.25rem, …, 3.5rem)` tabular; UI 12–14px; body 14–15px.
- Uppercase limited to the table header row; no eyebrow above every heading.

## Grid, shape, motion
- Content hangs from one left edge; panels are hairline-bordered, flat (no soft shadows).
- **One radius rule: 4px** for every control, panel and badge.
- Hovers move: index rows slide their content 6px and the arrow travels; buttons nudge their icon;
  nav items slide their label. Colour-only changes are kept for utility links.
- Page changes use a short cross-fade + 8px rise (View Transitions API, falls back to a CSS rise).
- `prefers-reduced-motion`: all movement removed, state changes kept (colour, fill, underline).

## Palette

Palette follows the art-direction rules of the `awwwards` skill (4–6 named roles taken from
the subject's own world, one accent used rarely, AA contrast everywhere). Tokens live in
`src/bonechiling/webui/styles.css`.

**Concept world:** a radiology reading room — film clipped to a lightbox, read in a dim room.

| Role | Light | Dark ("lightbox off") | Use |
|---|---|---|---|
| ground | `#edf0ef` lightbox glass | `#0a1013` | page background |
| surface | `#fafbfa` | `#10181c` | cards, tables |
| ink | `#0f1a1e` film base | `#e3eaeb` | primary text |
| muted | `#5e6d73` (4.7:1) | `#84959a` (6.2:1) | secondary text |
| line | `#d5dcdb` | `#24333a` | hairlines, borders |
| accent | `#0b6870` film-base teal | `#5cb8c0` | primary action, focus, selection, active nav only |
| curtain | `#0d1719` darkroom | `#060b0d` | sidebar |

Status hues (`ok #2f6b3a`, `warn #8a5a00`, `err #a3262a`) are semantic only — badges, film
status edges, the name-conflict warning — never decoration.

**Avoided defaults:** multi-hue stat tiles and rainbow avatars (now one neutral), blue→purple
gradients, soft-shadow card kit (flat surfaces separated by hairlines instead).
