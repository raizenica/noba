# Themes

NOBA includes 6 built-in colour themes. Select a theme from the dropdown in the header bar. Your choice is saved in `localStorage` and persists between sessions.

## Available Themes

### Default

A dark terminal aesthetic with green accents on a near-black background. Inspired by classic monochrome terminal displays.

- Background: `#0d0d0d`
- Accent: `#00ff88`
- Text: `#e0e0e0`

### Catppuccin Mocha

Soft pastel colours from the [Catppuccin](https://github.com/catppuccin/catppuccin) palette (Mocha flavour). Easy on the eyes for long sessions.

- Background: `#1e1e2e`
- Accent: `#cba6f7` (mauve)
- Text: `#cdd6f4`

### Tokyo Night

Deep blue palette from the [Tokyo Night](https://github.com/enkia/tokyo-night-vscode-theme) theme. Cool and focused.

- Background: `#1a1b26`
- Accent: `#7aa2f7`
- Text: `#c0caf5`

### Gruvbox

Warm retro colours from the [Gruvbox](https://github.com/morhetz/gruvbox) palette. High contrast, comfortable in dim environments.

- Background: `#282828`
- Accent: `#b8bb26`
- Text: `#ebdbb2`

### Dracula

The classic [Dracula](https://draculatheme.com) purple theme. Bold and distinctive.

- Background: `#282a36`
- Accent: `#bd93f9`
- Text: `#f8f8f2`

### Nord

Cool arctic colours from the [Nord](https://www.nordtheme.com) palette. Clean and professional.

- Background: `#2e3440`
- Accent: `#88c0d0`
- Text: `#eceff4`

## Applying a Theme

Click the theme name in the header dropdown. The theme is applied instantly without a page reload.

## Theme Persistence

Themes are stored in `localStorage` under the key `noba-theme`. To reset to the default theme, open the browser console and run:

```js
localStorage.removeItem('noba-theme')
location.reload()
```

## Custom Themes

Custom themes are not yet available through the UI. You can modify the CSS variables directly in `share/noba-web/static/style.css` to create a custom palette. The full set of CSS custom properties is documented at the top of that file.
