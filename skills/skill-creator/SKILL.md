---
name: skill-creator
description: Create and customize specialized AEC engineering skills with domain-specific keywords and prompt instructions.
keywords: skill-creator, create skill, add skill, custom skill, aec skill, engineering skill
---

# AEC Skill Creator

Use this skill to author new, project-specific engineering skills for the local AI assistant.

## Skill Folder Structure
Each skill lives in `skills/<skill-name>/SKILL.md`:
```markdown
---
name: <unique-skill-name>
description: One-line concise summary of when this skill applies.
keywords: comma, separated, search, terms, that, trigger, this, skill
---

# <Title>
(Direct, actionable engineering instructions injected into the AI context)
```

## Best Practices for AEC Skills
1. Keep keywords tightly focused on engineering terminology (e.g., `setback`, `egress`, `shear wall`, `duct static pressure`).
2. Include concrete rules: formatting standards, required provenance citations, units of measurement, and error-handling steps.
3. Keep instructions completely offline and compatible with local models without third-party cloud APIs.
