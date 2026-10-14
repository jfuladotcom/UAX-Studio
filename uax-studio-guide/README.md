# UAX Studio: the complete guide

A 34-slide presentation and end-to-end tutorial made with plain HTML, CSS, and JavaScript. It follows the current UAX Studio workspace v0.4.0.

## Open it

1. Unzip the package.
2. Keep the `uax-studio-guide` folder together.
3. Open `index.html` in a modern browser.

No installation, server, build step, API key, or account is needed for the presentation. The live UAX app has separate access requirements. Relative assets, local scripts, and the examples work from the folder. Your browser may require manual copying for example text opened from a local file. The guide provides a selectable-text fallback.

## Controls

| Control | Purpose |
| --- | --- |
| Next / Previous, or arrow keys | Move through the slides |
| Contents / C | Search and jump to a topic |
| Notes / N | Read presenter notes and extra instructions |
| Read all | Show the whole tutorial as a continuous document |
| Full screen / F | Enter presentation mode, if the browser supports it |
| Home / End | Go to the first / last slide |
| ? | Open the controls guide and print command |
| Print / Save as PDF | Use the browser print dialog, one page per slide |

The illustrations include a clickable workspace menu, setup tabs, agent tabs, and a guidance switch. They teach the interface and do not edit a real UAX project. Keyboard shortcuts pause in text inputs and open dialogs. Reduced-motion preferences are respected.

For printing, select landscape and enable background graphics if your browser requires it. The print stylesheet displays all slides. Interactive tabs print the panel currently selected. Presenter notes stay in the on-screen Notes dialog.

## Add it to your existing GitHub repository

Repository: https://github.com/jfuladotcom/UAX-Studio

Copy the complete folder into a new directory in your repository, such as `docs/guide/`. Keep its internal paths unchanged. This package does not overwrite the application or require a change to its backend.

For example, after copying the folder contents to `docs/guide/` in your local checkout:

```bash
git add docs/guide
git commit -m "Add UAX Studio presentation and tutorial"
git push
```

These commands are instructions for you to run in your own checkout. Nothing in this package automatically commits, pushes, or publishes.

### Serve it as a website

If your GitHub Pages site already publishes the `docs` directory, placing the guide in `docs/guide/` makes its entry point `guide/index.html` relative to that site. Add a link to it from your existing documentation homepage. Preserve your existing publishing configuration and homepage.

If Pages is not configured, choose a publishing source using the [GitHub Pages setup guide](https://docs.github.com/en/pages/getting-started-with-github-pages/creating-a-github-pages-site). Its source needs an entry file at the source root. You can place this guide directly at that root for a dedicated presentation site, or keep it in a subfolder beneath an existing homepage. Use the actual URL GitHub provides after publishing.

GitHub's repository file viewer displays HTML source rather than running the presentation. Open the local file or a deployed static-site URL to use the interactive guide. No deployment workflow is added here, so this folder cannot replace an existing site by itself.

The same files also work on any host that serves static HTML, CSS, JavaScript, and images. Publishing this guide does not publish the UAX application or enable its ChatGPT connection.

## Files

| File | Purpose |
| --- | --- |
| `index.html` | Page shell, controls, dialogs, metadata |
| `styles.css` | UAX black/mint theme, responsive and print layouts |
| `slides.js` | All 34 slides, presenter notes, and example UI content |
| `app.js` | Navigation, outline search, copying, keyboard controls, reading mode |
| `assets/cover.png` | Original AI-generated abstract cover artwork |
| `assets/favicon.svg` | Small UAX-style favicon |
| `examples/practice-notes.md` | Fictional source material for the tutorial |
| `examples/research-brief.uax.json` | Completed example that opens in UAX |
| `examples/research-brief-package.zip` | Full UAX export for the example |
| `CONTENT_SOURCES.md` | Version basis, source attribution, and scope |

## Follow the example

For the full lesson, begin with a blank UAX project and follow slides 6–30. Import `practice-notes.md` after creating the brief.

For a quick orientation, download your current UAX project, then use **Open project** to select `examples/research-brief.uax.json`. Inspect its four agents and five connections. The example contains fictional material and records untested ideas.

To practice the AI handoff, unzip `research-brief-package.zip` and read `00_START_HERE.md`. It contains instructions for work an AI could perform. It does not contain completed research outputs.

## Edit the presentation

- Edit slide content and notes in `slides.js`.
- Preserve unique slide IDs so links and browser hashes remain valid.
- Change colors, typography, or responsive behavior in `styles.css`.
- Change runtime interactions in `app.js`.
- Update the live app URL in both `index.html` and `slides.js` if your deployment changes.
- Update the app version and instructions when the product changes.
- Check desktop and mobile views after editing longer slide text.

The presentation makes no model calls, uses no analytics, sets no cookies, and stores no state in localStorage or a database. Slide position appears in the URL hash. User notes and preferences are not saved. Links to UAX, GitHub, or the setup documentation open external services only when followed.

## Scope

The current guide covers the UAX workspace developed in this conversation, not a guarantee that every historical version of the GitHub project has the same interface. It separates implemented instruction-authoring features from the future discovery vision. It also discloses that live verification of the connected ChatGPT path remains pending.

The example JSON and ZIP use the actual v0.4.0 project normalization and export functions. A public app launch, account permissions, a live model connection, and research quality are separate concerns from this presentation.
