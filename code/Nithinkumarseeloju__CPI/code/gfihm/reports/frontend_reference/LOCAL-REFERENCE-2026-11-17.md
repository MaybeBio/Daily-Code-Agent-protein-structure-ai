# Local reference verification - 17 November 2026

Reference and live result: http://127.0.0.1:5173/
Project: H:\siddu\frontend

The requested reference is served by this existing frontend. It was inspected in a real headless Chrome browser at desktop and mobile sizes, including each content section, navigation, filters, dataset dialogs, and the prediction form. The existing layout, colors, Arial/Georgia typography, spacing, procedural Three.js scene, and GSAP transitions were retained.

## Change

Only `src/style.css` changed: the fullscreen `.menu` now uses `overflow-y: auto` and `overscroll-behavior: contain`. Before the fix, the menu content exceeded the viewport at 320 x 568 and 844 x 390, while the underlying page was locked. The final navigation link could be offscreen and unreachable by scrolling. After the fix, the menu itself scrolls and every link remains accessible. No visual redesign or model/API/source-scene replacement was made.

The production `dist/` was rebuilt with `npm run build` (Vite 7.3.8). This document, the JSON result, and the screenshots record this verification separately from earlier reference-analysis notes.

## Checks

- HTTP 200, loader completes, original Three.js canvas present
- Menu navigation, all dataset filters, detail dialog, forward/back history and Escape work
- No horizontal overflow at 320,390,768,1024,1440px and 844px landscape; formerly clipped menu links now scroll into view and navigate
- CSV download and invalid protein validation work
- Real KIBA and Metz model responses displayed through the original prediction endpoint; no request mocks
- Reduced-motion navigation and WebGL-unavailable fallback work
- Production build passed.
- No uncaught browser page errors.
- Desktop and mobile screenshots were visually inspected against the original local page.
- Davis returned HTTP 200 in the pre-change baseline; KIBA and Metz returned HTTP 200 after the CSS fix. The actual model endpoint was used throughout; no mocked scores. These were software smoke tests using the existing illustrative example, not a biological validation of that pair.

## Limits

Tests exercised the Vite development site at port 5173 and Chrome viewport emulation. Physical phones, Safari, Firefox, and production-preview inference were not tested. No measured frame-rate guarantee or pixel-perfect comparison of moving Three.js frames is claimed. The independent GF IHM CPI/BioEmu application was not modified by this frontend task.

Artifacts: `LOCAL-REFERENCE-2026-11-17.json`, `local-reference-desktop.png`, `local-reference-mobile.png`.
