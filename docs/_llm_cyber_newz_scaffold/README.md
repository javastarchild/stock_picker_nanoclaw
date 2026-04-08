# LLM Cyber Newz

Curated daily intelligence across AI/ML, Cybersecurity, and Miscellaneous topics.

**Curated by:** javastarchild (weekdays, from a trusted associate)
**Cataloged by:** Andy (NanoClaw agent)

## Structure

```
editions/
  YYYY/
    MM/
      YYYY-MM-DD.md   ← one file per edition
README.md
```

## Categories

- 🤖 **LLMz** — AI, LLMs, agents, synthetic media
- 🔒 **Cyberz** — Security, ransomware, nation-state, vulnerabilities
- 🌐 **MISCz** — Everything else worth knowing

## Format

Each edition file follows this template:

```markdown
# LLM Cyber Newz — YYYY-MM-DD

## 🤖 LLMz
### Title
- **URL:** [link](url)
- **Summary:** One sentence.
- **Tags:** `tag1` `tag2`

## 🔒 Cyberz
...

## 🌐 MISCz
...
```

## Cross-Project Use

- **SMW Wiki:** Each edition published at `News:YYYY-MM-DD`
- **Logic Tools:** News tags seeded as FOL facts (`isAbout`, `mentions`, `category`)
- **Stock Picker:** Breach/vulnerability news fed as sentiment signal for affected public companies
