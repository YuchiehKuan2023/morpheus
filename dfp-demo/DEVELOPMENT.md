# Development Guide

## Code Quality Tools

This project uses automated tools to maintain code quality and consistency.

### Pre-commit Hooks

Pre-commit hooks are configured at the repository root and automatically run when you commit changes from **any directory** (root, dfp-demo/, dfp-ecommerce/, etc.).

**Configured hooks:**

1. **Ruff** (Python) - Runs on all `.py` files in `dfp-*` directories
   - Linting with auto-fix
   - Code formatting checks

2. **ESLint** (TypeScript/React) - dfp-demo frontend
   - Runs on `dfp-demo/frontend/ui/**/*.{ts,tsx,js,jsx}` files
   - Auto-fixes issues when possible

3. **Prettier** (Formatting) - dfp-demo frontend
   - Runs on `dfp-demo/frontend/ui/**/*.{scss,css,json,md}` files
   - Ensures consistent formatting

4. **Biome** (TypeScript/React/CSS) - dfp-ecommerce frontend
   - Runs on `dfp-ecommerce/frontend/**/*.{ts,tsx,js,jsx,json,css}` files
   - Combined linting and formatting

**Setup:**

```bash
# Install pre-commit (once, from repository root)
pip install pre-commit

# Install hooks (once, from repository root)
pre-commit install

# Hooks will now run automatically on every commit
```

**Manual execution:**

```bash
# Run all hooks on staged files
pre-commit run

# Run all hooks on all files
pre-commit run --all-files

# Run specific hook
pre-commit run eslint-dfp-demo --all-files
```

## Frontend Development (dfp-demo)

### Styling with SCSS

The frontend uses **SCSS** (Sass) for styling, which provides:

- **Variables**: Define reusable color schemes, spacing, etc.
- **Nesting**: Write cleaner, more organized CSS
- **Mixins**: Reusable style blocks
- **Functions**: Dynamic style calculations
- **Import/Partials**: Split styles into logical files

**Main stylesheet:** [src/index.scss](src/index.scss)

**Example SCSS features:**

```scss
// Variables
$primary-color: #3b82f6;
$spacing-unit: 8px;

// Nesting
.card {
  padding: $spacing-unit * 2;
  
  &:hover {
    background: lighten($primary-color, 10%);
  }
  
  .card-title {
    font-size: 1.5rem;
  }
}

// Mixins
@mixin flex-center {
  display: flex;
  align-items: center;
  justify-content: center;
}

.button {
  @include flex-center;
}
```

**Note:** We still use Tailwind CSS v4 for utility classes. SCSS is for custom styles that can't be achieved with Tailwind alone.

### Code Formatting

**Format on save** (recommended):

Configure your editor to format on save:

**VSCode** - Add to `.vscode/settings.json`:

```json
{
  "editor.formatOnSave": true,
  "editor.defaultFormatter": "esbenp.prettier-vscode",
  "[typescript]": {
    "editor.defaultFormatter": "esbenp.prettier-vscode"
  },
  "[typescriptreact]": {
    "editor.defaultFormatter": "esbenp.prettier-vscode"
  },
  "[scss]": {
    "editor.defaultFormatter": "esbenp.prettier-vscode"
  }
}
```

**Manual formatting:**

```bash
cd frontend/ui

# Format all files
npm run format

# Check formatting without fixing
npm run format:check

# Lint TypeScript/React
npm run lint

# Build (includes type checking)
npm run build
```

### File Naming Conventions

- **Components**: PascalCase (e.g., `UserCard.tsx`)
- **Pages**: PascalCase (e.g., `Dashboard.tsx`)
- **Utilities**: camelCase (e.g., `formatDate.ts`)
- **Styles**: kebab-case (e.g., `user-card.scss`) or same as component
- **Types**: camelCase or PascalCase for interfaces (e.g., `types.ts`, `IUser`)

### Import Order

1. External libraries (React, Redux, etc.)
2. Internal modules (components, services, etc.)
3. Types
4. Styles

```tsx
// External
import { useState, useEffect } from 'react';
import { useDispatch } from 'react-redux';

// Internal
import { Layout } from '../components/Layout';
import { api } from '../services/api';

// Types
import type { User } from '../types';

// Styles
import './Dashboard.scss';
```

## Backend Development (dfp-demo)

### Python Code Style

**Ruff** handles both linting and formatting:

```bash
cd frontend/backend

# Check code quality
ruff check .

# Auto-fix issues
ruff check --fix .

# Format code
ruff format .
```

**Configuration:** Ruff is configured at the repository root in `pyproject.toml` or `ruff.toml`.

### Type Hints

Always use type hints for function parameters and return values:

```python
from typing import List, Optional
from pydantic import BaseModel

def get_users(limit: int = 100) -> List[User]:
    """Get list of users."""
    pass

async def get_user(username: str) -> Optional[User]:
    """Get user by username."""
    pass
```

## Git Workflow

### Committing Changes

Pre-commit hooks run automatically when you commit:

```bash
# Stage changes
git add .

# Commit (hooks run automatically)
git commit -m "feat: add user profile page"

# If hooks fail, fix issues and re-commit
git add .
git commit -m "feat: add user profile page"
```

### Skip Hooks (Not Recommended)

Only skip hooks if absolutely necessary:

```bash
git commit --no-verify -m "WIP: work in progress"
```

### Commit Message Format

Follow conventional commits:

```html
<type>(<scope>): <subject>

<body>

<footer>
```

**Types:**

- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation only
- `style`: Code style changes (formatting, etc.)
- `refactor`: Code refactoring
- `test`: Adding tests
- `chore`: Maintenance tasks

**Examples:**

```bash
git commit -m "feat(frontend): add anomaly detail modal"
git commit -m "fix(api): resolve CORS issue"
git commit -m "docs: update installation instructions"
git commit -m "style(ui): format components with prettier"
```

## Troubleshooting

### Pre-commit hooks fail

**Issue:** Hooks fail even after fixing issues

**Solution:**

1. Make sure you're committing from the git root or any subdirectory (hooks work from anywhere)
2. Check that dependencies are installed (npm packages, Python packages)
3. Run hooks manually to see detailed errors: `pre-commit run --all-files`
4. If a hook consistently fails, you can temporarily disable it in `.pre-commit-config.yaml`

### SCSS not compiling

**Issue:** SCSS changes not reflected in browser

**Solution:**

1. Ensure `sass` package is installed: `npm install -D sass`
2. Restart Vite dev server: `npm run dev`
3. Clear browser cache
4. Check for SCSS syntax errors in terminal

### Prettier conflicts with ESLint

**Issue:** Prettier and ESLint give conflicting rules

**Solution:**

- This shouldn't happen as we're using compatible configs
- If it does, adjust `.prettierrc` to match ESLint rules
- Or disable the conflicting ESLint rule in `eslint.config.js`

### Import errors after moving files

**Issue:** TypeScript can't find imports after file moves

**Solution:**

1. Update import paths in affected files
2. Restart TypeScript server in editor (VSCode: Cmd+Shift+P → "TypeScript: Restart TS Server")
3. Check `tsconfig.json` path mappings if using aliases

## VS Code Setup (Recommended)

Install extensions:

- **ESLint** (`dbaeumer.vscode-eslint`)
- **Prettier** (`esbenp.prettier-vscode`)
- **Tailwind CSS IntelliSense** (`bradlc.vscode-tailwindcss`)
- **SCSS IntelliSense** (`mrmlnc.vscode-scss`)

Workspace settings:

```json
{
  "editor.formatOnSave": true,
  "editor.codeActionsOnSave": {
    "source.fixAll.eslint": "explicit"
  },
  "tailwindCSS.experimental.classRegex": [
    ["class:", "[\"'`]([^\"'`]*).*?[\"'`]"]
  ]
}
```

## Additional Resources

- [Tailwind CSS v4 Docs](https://tailwindcss.com/docs)
- [Sass/SCSS Documentation](https://sass-lang.com/documentation)
- [Prettier Configuration](https://prettier.io/docs/en/configuration.html)
- [ESLint Rules](https://eslint.org/docs/rules/)
- [Conventional Commits](https://www.conventionalcommits.org/)
