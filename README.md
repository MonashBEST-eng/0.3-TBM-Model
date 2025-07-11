## Monash BEST Code Repository

## Overview
Welcome to the code repository of  Monash BEST! This repository contains the source code, scripts, and tools developed by our team.

## Directory Structure
This repository is organized into different folders, each dedicated to a specific sub-team within Monash BEST. Please ensure that codes, scripts, 
or tools are uploaded to the correct folders based on the sub-team that you belong to. 

# 🧠 Git Conventions for This Repository

To maintain a clean, consistent, and automation-friendly Git history, this project uses enforced conventions for **branch names** and **commit messages**.

---

##  Branch Naming Convention

Branches must follow this structure:


Where:
- `<type>` is one of: `feature`, `bug`, `docs`, `chore`, `hotfix`
- `<short-description>` is lowercase and uses hyphens (no spaces)

### ✅ Examples

- `feature/login-page`
- `bug/fix-header-overlap`
- `docs/readme-update`
- `chore/cleanup-eslint`
- `hotfix/payment-crash`

### ❌ Invalid Examples

- `login-page` → (missing type prefix)
- `Bug/fix` → (type must be lowercase)
- `feature_Login_Page` → (no underscores or uppercase)

> ⚠️ Branch name rules are enforced via GitHub Actions and local pre-push Git hooks.

---

## ✏️ Commit Message Convention

All commits must follow the [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) format:


Where:
- `<type>` is one of: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`
- `<scope>` is optional (e.g., a folder or module name)
- The description should be written in **present tense**, without a period

### ✅ Examples

- `feat(auth): add login functionality`
- `fix(api): handle 500 error on user fetch`
- `docs(readme): add usage instructions`
- `chore: update dependencies`

### ❌ Invalid Examples

- `added login page` → (missing type and format)
- `Fix login` → (type not lowercase)
- `feat: ` → (missing description)

> 🚨 Commit messages are enforced by a local `commit-msg` Git hook.

---

## ⚙️ Setup (for Local Enforcement)

To enable local enforcement of these rules:

1. Clone the repository
2. Run the setup script:
   ```bash
   bash setup.sh


## Task Formatting Procedures
If you are starting a new project, please refer to the formatting/naming conventions provided in the respective sub-team folders.
It includes a template to help you get started and correctly format the files.

## Code Organisation
For projects with numerous files, please establish a dedicated folder containing all essential code files. 
This guarantees organized code structuring and mitigates the risk of code malfunction due to missing files.

E.g. For matlab files, please ensure functions files and its scripts files are uploaded into a dedicated folder
