---
name: Nordic Wholesale Commerce
colors:
  surface: '#f9f9f9'
  surface-dim: '#dadada'
  surface-bright: '#f9f9f9'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f3f3f3'
  surface-container: '#eeeeee'
  surface-container-high: '#e8e8e8'
  surface-container-highest: '#e2e2e2'
  on-surface: '#1a1c1c'
  on-surface-variant: '#40484c'
  inverse-surface: '#2f3131'
  inverse-on-surface: '#f1f1f1'
  outline: '#70787d'
  outline-variant: '#c0c8cd'
  surface-tint: '#1f6580'
  primary: '#003d51'
  on-primary: '#ffffff'
  primary-container: '#005670'
  on-primary-container: '#8bcae8'
  inverse-primary: '#90cfed'
  secondary: '#44636f'
  on-secondary: '#ffffff'
  secondary-container: '#c7e8f6'
  on-secondary-container: '#4a6975'
  tertiary: '#363b00'
  on-tertiary: '#ffffff'
  tertiary-container: '#4c5300'
  on-tertiary-container: '#bbcb00'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#bee9ff'
  primary-fixed-dim: '#90cfed'
  on-primary-fixed: '#001f2a'
  on-primary-fixed-variant: '#004d65'
  secondary-fixed: '#c7e8f6'
  secondary-fixed-dim: '#accbd9'
  on-secondary-fixed: '#001f28'
  on-secondary-fixed-variant: '#2d4b56'
  tertiary-fixed: '#dded2a'
  tertiary-fixed-dim: '#c1d000'
  on-tertiary-fixed: '#1a1d00'
  on-tertiary-fixed-variant: '#454b00'
  background: '#f9f9f9'
  on-background: '#1a1c1c'
  surface-variant: '#e2e2e2'
  surface-pure: '#FFFFFF'
  status-fresh-green: '#C8D800'
  deep-ocean-navy: '#1E3D48'
  wholesale-teal: '#005670'
  border-subtle: '#E2E7E9'
  text-on-dark: '#FFFFFF'
typography:
  headline-xl:
    fontFamily: Hanken Grotesk
    fontSize: 48px
    fontWeight: '800'
    lineHeight: 56px
  headline-xl-mobile:
    fontFamily: Hanken Grotesk
    fontSize: 32px
    fontWeight: '800'
    lineHeight: 40px
  headline-lg:
    fontFamily: Hanken Grotesk
    fontSize: 36px
    fontWeight: '700'
    lineHeight: 44px
  headline-lg-mobile:
    fontFamily: Hanken Grotesk
    fontSize: 26px
    fontWeight: '700'
    lineHeight: 32px
  headline-md:
    fontFamily: Hanken Grotesk
    fontSize: 24px
    fontWeight: '700'
    lineHeight: 32px
  headline-sm:
    fontFamily: Hanken Grotesk
    fontSize: 20px
    fontWeight: '600'
    lineHeight: 28px
  body-lg:
    fontFamily: Hanken Grotesk
    fontSize: 18px
    fontWeight: '400'
    lineHeight: 28px
  body-md:
    fontFamily: Hanken Grotesk
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
  body-sm:
    fontFamily: Hanken Grotesk
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
  label-lg:
    fontFamily: Space Grotesk
    fontSize: 14px
    fontWeight: '700'
    lineHeight: 18px
  label-md:
    fontFamily: Space Grotesk
    fontSize: 12px
    fontWeight: '600'
    lineHeight: 16px
  label-sm:
    fontFamily: Space Grotesk
    fontSize: 11px
    fontWeight: '500'
    lineHeight: 14px
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  gutter: 1.5rem
  gutter-sm: 1rem
  margin: 2rem
  margin-sm: 1rem
  space-xs: 0.25rem
  space-sm: 0.5rem
  space-md: 1rem
  space-lg: 1.5rem
  space-xl: 2.5rem
---

## Brand & Style
The design system embodies the operational efficiency, fresh-food authority, and reliable service essential to modern B2B wholesale and foodservice distribution. Built to support professional chefs, restaurant operators, and retail merchants, the interface balances high-density utility with clean Nordic clarity.

Drawing inspiration from **Modern Nordic Minimalism** with industrial clarity, the visual language relies on crisp whitespace, deliberate structural alignment, high-contrast type hierarchies, and utilitarian data grouping. The emotional response is one of absolute reliability, prompt fulfillment, and culinary freshness—enabling users to rapidly scan inventory, monitor pricing tiers, calculate bulk logistics, and complete reorders under high-pressure commercial environments.

## Colors
The palette leverages a crisp, cool aquatic spectrum anchored by deep commercial blues and an energetic lime-chartreuse accent.

- **Primary Teal (`#005670`)**: The dominant brand tone used for primary actions, top-level navigation headers, prominent product categorization, and active state indicators.
- **Secondary Deep Navy (`#1E3D48`)**: Provides foundational weight, used primarily for high-contrast headers, dense typographic tables, footer anchors, and structural contrast.
- **Tertiary Lime Accent (`#C8D800`)**: A high-visibility, energetic marker denoting promotional wholesale discounts, flash deals, active badge highlights, and essential real-time updates. Because of its light chromatic value, it must be paired with `#1E3D48` for textual contrast.
- **Neutral Light Grey (`#F4F4F4`)**: Serves as the global backdrop tint, softening the starkness of pure white surfaces while organizing cards, specification sheets, and data grids into legible, compartmentalized sections.

## Typography
The typography strategy prioritizes rapid legibility, dense SKU scanning, and clear price hierarchy. 

- **Primary Headings & Body (`Hanken Grotesk`)**: Chosen to mirror the structural geometry, low distortion, and contemporary Nordic air of Matter. It provides clear open apertures and robust weights that hold up cleanly in high-density product cards, unit quantities, and delivery schedules.
- **Labels, Metrics & Data (`Space Grotesk`)**: Provides subtle technical rhythm for batch codes, GTINs, weight ratios, pallet counts, and monetary figures. Its geometric, slightly mechanical figures deliver unambiguous reading in high-speed picking scenarios.

## Layout & Spacing
The layout model employs a flexible 12-column responsive grid on desktop and tablet, scaling down to a structured 4-column layout on mobile viewports.

- **Desktop (1024px and up)**: 12-column fluid grid, 2rem margins, 1.5rem gutters. Product listings display in 4-column or 6-column matrices to maximize visual inventory density without compromising unit details.
- **Tablet (768px – 1023px)**: 8-column fluid grid, 1.5rem margins, 1rem gutters. Filter panels collapse into an off-canvas drawer to safeguard catalog scanability.
- **Mobile (Below 768px)**: 4-column fluid grid with 1rem margins and 0.5rem gutters. Horizontal scrolling lists are utilized for rapid category pivots and instant reordering drawers.

## Elevation & Depth
This design system avoids excessive drop shadows in favor of crisp **low-contrast outlines** and structured **tonal layering**. This keeps data dense, fresh, and uncluttered.

- **Base Level (Canvas)**: Background tint set to `#F4F4F4`.
- **Level 1 (Cards, Lists, Panels)**: `#FFFFFF` flat containers encapsulated by a hairline `1px solid #E2E7E9` border. No drop shadow.
- **Level 2 (Interactive Floating & Hover States)**: On hover or active focus, cards transition with an ambient shadow: `box-shadow: 0 4px 16px -2px rgba(30, 61, 72, 0.08)`. Border shifts slightly darker to `#005670`.
- **Level 3 (Modals, Overlays, Dropdowns)**: Surfaces sit on `#FFFFFF` with a diffused ambient shadow: `box-shadow: 0 12px 32px -4px rgba(30, 61, 72, 0.16)`, framed by a solid `1px solid #005670`.

## Shapes
A restrained, low-radius shape system (`roundedness: 1`) reflects Nordic utility and industrial logistics. 

- Interactive buttons, form inputs, and SKU cards use tight `0.25rem` corners.
- Large modal dialogue boxes, filter panels, and product imagery cards expand slightly to `rounded-lg` (`0.5rem`).
- Pills and full circles are reserved exclusively for status tags (e.g., in-stock indicators, temperature control badges) and promotional unit highlights.

## Components

### Buttons
- **Primary**: Solid `#005670` fill with `#FFFFFF` text. Flat finish, 0.25rem border-radius, font weight 600. On hover, background deepens to `#1E3D48`.
- **Secondary / Action Accent**: Solid `#C8D800` fill with `#1E3D48` text. Strictly applied to high-conversion actions like "Add to Reorder List" or "Confirm Shipment."
- **Tertiary / Outline**: Transparent fill, 1.5px solid `#005670`, text `#005670`. On hover, fills with rgba(0, 86, 112, 0.06).
- **Ghost**: Transparent fill, text `#1E3D48`, underline accent visible only on hover.

### Product & SKU Cards
- Pure white (`#FFFFFF`) background enclosed by a 1px `#E2E7E9` border.
- Visual hierarchy: High-resolution product visual centered, followed by SKU code (`label-md` in `#1E3D48`), commercial item title (`headline-sm`), quantity-per-crate breakdown, and wholesale pricing.
- Hover state: Border shifts to `#005670` with subtle elevation tint.

### Chips & Badges
- **Status Tags**: Rounded pill containers. Temperature markers (Cold Storage, Frozen, Ambient) use subtle tinted backgrounds with a solid dot indicator.
- **Campaign Tags**: Background in `#C8D800` with bold text in `#1E3D48`, uppercase `label-sm`.

### Input Fields & Selectors
- Standard text input uses a `#FFFFFF` fill, 1px solid `#E2E7E9` border, and 0.25rem border radius.
- Height standardized to 44px on desktop to accommodate fast barcode reader entries and touch interfaces.
- Focus state: Border transitions to 2px solid `#005670` with no external glow.

### Checkboxes & Radio Buttons
- Crisp 18px square (checkbox) and circle (radio) with 1.5px solid `#1E3D48`.
- Checked state: Filled with `#005670`, exhibiting a white checkmark or center pip.

### Lists & Data Grids
- Alternating row zebra-striping using `#FFFFFF` and `#F4F4F4`.
- Column headers set in `Space Grotesk` uppercase (`label-md`), accompanied by sort toggles.
- Hairline horizontal dividers using `#E2E7E9`.