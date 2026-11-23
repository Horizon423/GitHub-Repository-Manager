# GitHub Repository Manager & Bulk Folder Uploader

A beginner-friendly, full-screen terminal app for **Android Termux** that lets you browse your GitHub repositories and **bulk-upload folders from your phone's internal storage** using real `git add`, `git commit` and `git push`.

It never overwrites what is already in your repository unless you explicitly tell it to.

- **One script** (`github.py`) — Python standard library only, nothing to `pip install`
- **White & green** interface with a startup animation, spinners and progress bars
- **Green** SUCCESS, **red** FAILED, **yellow** WARNING messages
- Licensed under the **BSD 3-Clause License** (full text at the bottom of this file)

---

## Table of contents

1. [Features](#features)
2. [Requirements](#requirements)
3. [Installation](#installation)
4. [Creating a GitHub token](#creating-a-github-token)
5. [Usage](#usage)
6. [How uploads work (and keep your data safe)](#how-uploads-work-and-keep-your-data-safe)
7. [Permissions](#permissions)
8. [Security](#security)
9. [Troubleshooting](#troubleshooting)
10. [Command-line options](#command-line-options)
11. [Project files](#project-files)
12. [License](#license)

---

## Features

| Area | What you get |
|------|--------------|
| Main menu | Numbered, interactive menu with login status |
| First launch | Automatic permission and dependency check — **asks before installing anything** |
| Authentication | Secure token login (hidden input), optional saved token with owner-only permissions |
| Repositories | Live list of your **public and private** repositories, with paging, search (`/text`) and a Public/Private filter |
| Upload | Enter any internal-storage path, recursive folder scan, numbered selection with **SELECT ALL**, folder browsing, destination folder, branch choice, commit message |
| Safety | Y/N confirmation, existing repository content preserved, conflict policy (skip / keep both / overwrite), automatic rebase if the remote changed, files over 100 MB skipped with a warning |
| Git | Real `git clone`, `add`, `commit`, `push` — your history stays intact |
| Management | Create a new repository (public/private, optional README) and delete a repository (typed confirmation) |
| Feedback | Spinners, live git progress, progress bars, full-success and full-error notification boxes |

---

## Requirements

- Android phone with the **Termux** app (F-Droid or GitHub release recommended)
- Internet connection
- A GitHub account and a [Personal Access Token](#creating-a-github-token)
- Packages: `python` (3.8+) and `git` — the installer takes care of them

---

## Installation

Open Termux and run the commands below one by one.

### 1. Install Git (needed to clone this project)

```bash
pkg update -y && pkg install -y git
```

### 2. Clone the repository

Replace `<your-username>` with the GitHub account that hosts this project:

```bash
git clone https://github.com/Horizon423/GitHub-Repository-Manager.git
cd GitHub-Repository-Manager
```

### 3. Run the installer

```bash
bash install.sh
```

The installer will:

1. Check for Python 3.8+, Git, CA certificates and Termux storage access
2. **Ask you before installing** anything that is missing
3. Offer to run `termux-setup-storage` (Android shows a permission dialog — tap **Allow**)
4. Verify `github.py`
5. Optionally create a `github-manager` shortcut command

Use `bash install.sh -y` to answer "yes" to every question automatically.

### 4. Start the app

```bash
python github.py
```

or, if you created the shortcut:

```bash
github-manager
```

On the very first launch the app also runs its own dependency and permission check.

### Updating

```bash
cd github-repo-manager
git pull
```

---

## Creating a GitHub token

The app talks to GitHub with a Personal Access Token (it never asks for your password).

**Classic token (simplest)**

1. Open <https://github.com/settings/tokens> and choose **Generate new token (classic)**
2. Tick the **`repo`** scope (full control of private and public repositories)
3. Optional: also tick **`delete_repo`** if you want to delete repositories from the app
4. Generate the token and **copy it immediately** (GitHub shows it only once)

**Fine-grained token**

1. Open <https://github.com/settings/personal-access-tokens>
2. Choose the repositories you want to manage
3. Permissions → **Contents: Read and write** (add **Administration: Read and write** to create or delete repositories)

Tip: paste the token in Termux by long-pressing the screen. Input is hidden, so you will not see it — that is normal.

---

## Usage

```
 MAIN MENU
  [1] Login / Switch account
  [2] Browse my repositories (public & private)
  [3] Upload folder to a repository
  [4] Create a new repository
  [5] Delete a repository
  [6] System & dependency check
  [7] Log out & remove saved token
  [0] Exit
```

### Log in (option 1)

Paste your token (hidden). The app verifies it with GitHub and shows your username. You can choose to save the token on the device so the next launch logs you in automatically. If the environment variable `GITHUB_TOKEN` is set, the app offers to use it.

### Browse repositories (option 2)

Repositories are fetched live and tagged `[PUBLIC]` or `[PRIVATE]`.

| Key | Action |
|-----|--------|
| a number | open that repository's details |
| `N` / `P` | next / previous page |
| `/text` | search by name (use `/` alone to clear) |
| `F` | cycle filter: All → Public → Private |
| `R` | refresh from GitHub |
| `Q` | cancel |

### Upload a folder (option 3)

1. **Choose the repository** from the live list.
2. **Enter the folder path** on your phone, for example:
   - `~/storage/shared/Download`
   - `/sdcard/MyProject`
   - `~/my-termux-folder`
3. **Select what to upload.** Items are listed with their recursive file count and size.

   | Input | Meaning |
   |-------|---------|
   | `1,3,5-8` | toggle those items |
   | `A` | **SELECT ALL** items in the current folder |
   | `O 2` | open folder number 2 and pick files inside it |
   | `B` | go back to the parent folder |
   | `C` | clear the selection |
   | `N` / `P` | next / previous page |
   | `D` | done — continue |
   | `Q` | cancel |

   Your selection is remembered while you move between folders, and paths are kept relative to the folder you first entered.
4. **Destination folder** inside the repository (press Enter for the repository root).
5. **Branch** (defaults to the repository's default branch; a new branch is created if it does not exist).
6. **Commit message** (a sensible default is offered).
7. Review the **summary box** and answer **`y`** to upload or **`n`** to cancel.

The app then clones, copies, stages, commits and pushes while showing progress, and finishes with a green **UPLOAD COMPLETE** box — or a red **UPLOAD FAILED** box that explains what went wrong.

> **Tip:** To keep a folder's own name in the repository, enter its *parent* path and select the folder. To upload only what is *inside* a folder, enter that folder's path and press `A`.

### Create a repository (option 4)

Choose a name, description, visibility (private by default) and whether to add a README. You can upload a folder to the new repository immediately.

### Delete a repository (option 5)

Permanent. You must type the full `owner/name` to confirm. Requires the `delete_repo` permission.

### System check (option 6)

Re-runs the dependency, network, storage-permission and config-folder checks.

### Log out (option 7)

Clears the session and deletes the saved token file from the device.

---

## How uploads work (and keep your data safe)

1. The repository is **cloned into a temporary folder** (shallow clone for speed). Existing files and history are kept.
2. Your selected files are copied into that clone. Your original files are **never modified or deleted**.
3. If a file already exists in the repository:
   - **identical content** → skipped silently
   - **different content** → you choose: **[S]kip** (default, safest), **[R]ename** (keep both, new file gets a `_1` suffix) or **[O]verwrite**, or **[C]ancel** the whole upload
4. `git add -A`, `git commit` and `git push` run for real. Commits use your GitHub noreply address, so your private email is never exposed.
5. If someone pushed to the branch while you were uploading, the app **rebases** your commit on top of theirs and retries instead of forcing anything. It never uses `--force`.
6. The temporary folder is deleted afterwards, even if something fails or you press `Ctrl+C`.

Limits and notes:

- Files **100 MB or larger** are skipped (GitHub rejects them). Files over 50 MB trigger a warning.
- `.git` folders inside your selection are ignored.
- Files excluded by the repository's own `.gitignore` are reported and not uploaded.
- Symbolic-link folders are not followed.
- New files are committed as normal files (mode 100644), which avoids accidental "executable" flags from Android storage.

---

## Permissions

| Permission | Why it is needed | How to grant |
|------------|------------------|--------------|
| Termux storage access | Read folders on internal storage (`~/storage/shared`, `/sdcard`) | `termux-setup-storage` (installer and first-launch check offer to run it) |
| Internet | Talk to GitHub | Normal Android network access |
| GitHub token: `repo` scope | Read repositories and push commits | See [Creating a GitHub token](#creating-a-github-token) |
| GitHub token: `delete_repo` scope | Only for deleting repositories | Optional |

Packages are **only installed after you say yes**. The app never installs anything silently.

The app writes only to its config folder `~/.config/github-manager/` (a settings file and, if you choose to save it, the token) and to a temporary working folder that it removes after each upload.

---

## Security

- Tokens are typed with **hidden input** and verified against GitHub before use.
- Saving the token is **optional**. If saved, it lives in `~/.config/github-manager/token` with **owner-only permissions** (`chmod 600`) inside a `700` folder. Option 7 deletes it.
- The token is **never printed, never written to a log** and is scrubbed from any error text.
- For `git push`/`clone` the token is passed through **environment variables scoped to the GitHub host**. It is never put in the remote URL, command line or the repository's `.git/config`.
- The GitHub API is only contacted over **HTTPS** (a local HTTP address is accepted only for testing).
- Prefer tokens with an **expiration date** and only the scopes you need. Revoke a token anytime at <https://github.com/settings/tokens>.

GitHub Enterprise users can set `GHM_API_URL` (HTTPS only), for example `export GHM_API_URL=https://github.example.com/api/v3`.

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `git: command not found` | Run `pkg install git` or `bash install.sh` |
| `Authentication failed: the token is invalid...` | The token is wrong, expired or revoked. Create a new one and use option 1 |
| Private repositories are missing | The token needs the `repo` scope (classic) or access to those repositories (fine-grained) |
| `Path does not exist` / folder is empty | Run `termux-setup-storage`, then use `~/storage/shared/...` or `/sdcard/...` paths. Check spelling and capitalization |
| `No permission to read` | Storage permission not granted. Use menu option 6, or run `termux-setup-storage` and tap **Allow** |
| `Network error` / `Could not resolve host` | Check Wi-Fi or mobile data, then retry |
| `CERTIFICATE_VERIFY_FAILED` | Run `pkg install ca-certificates` (the app also offers this) |
| `The branch is protected` | Push to a different branch name and open a pull request on GitHub |
| `No write access to this repository` | The token's owner is not a collaborator, or the token lacks write permission |
| `A file is too large for GitHub` | Remove files of 100 MB or more, or use Git LFS outside this app |
| Upload says "Nothing new to upload" | Every selected file already exists in the repository unchanged, or was excluded by `.gitignore` |
| Push dropped / `RPC failed` | Unstable connection or a very large upload. Retry on Wi-Fi, or upload fewer files at once |
| Colors look broken | Use a terminal that supports ANSI colors, or run with `NO_COLOR=1 python github.py` |
| Delete says "Not found" or "forbidden" | Add the `delete_repo` scope (classic) or Administration permission (fine-grained) |
| Something else | Run `python github.py --check`, then re-run the failing step. Set `GHM_DEBUG=1` to see a full error trace |

---

## Command-line options

```text
python github.py              start the interactive menu
python github.py --no-anim    skip the startup animation
python github.py --check      run the system check and exit
python github.py --version    print the version
python github.py --help       show help
```

---

## Project files

This project intentionally contains exactly three files:

| File | Purpose |
|------|---------|
| `github.py` | The complete application |
| `install.sh` | Dependency checker and installer |
| `README.md` | This documentation, including the license text |

---

## License

This project is released under the **BSD 3-Clause License**, a permissive open-source license. You may use, modify and redistribute it, including commercially, as long as the copyright notice and disclaimer are kept.

```text
BSD 3-Clause License

Copyright (c) 2026, GitHub Repository Manager Authors
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this
   list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

3. Neither the name of the copyright holder nor the names of its
   contributors may be used to endorse or promote products derived from
   this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

---

*Made for Termux. Contributions and bug reports are welcome.*
