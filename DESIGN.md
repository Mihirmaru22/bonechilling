# BoneChilling — design system

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
