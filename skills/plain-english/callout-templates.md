# Callout Templates

Callout syntax for each output format offered in the plain-english interview (Question 6). Pass the matching template to each section agent.

## Obsidian Format (default)

**Tiered (audience = all):**
```markdown
> [!tip] 💡 What This Means
> <intuition-level explanation>

> [!example] 🔧 How To Apply This
> <operational guidance>

> [!important] ⚡ Why This Matters
> <executive-level implications>
```

**Single:**
```markdown
> [!note] 📖 Plain English
> <combined explanation at target reading level>
```

**Single with lead-ins:**
```markdown
> [!note] 📖 Plain English
> **In plain terms:** <intuition>
> **In practice:** <operational>
> **The takeaway:** <executive>
```

## Plain Blockquote Format

```markdown
> **💡 What This Means**
> <explanation>
```

## GitHub-Compatible Format

```markdown
> **💡 What This Means**
>
> <explanation>
```

## HTML Collapsible Format

```html
<details>
<summary>💡 What This Means</summary>
<p>explanation</p>
</details>
```
